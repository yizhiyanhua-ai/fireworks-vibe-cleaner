"""Exact-closure native Codex archival. No direct database or transcript writes."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import time
import uuid

from . import history
from .codex_rpc import CodexRPC, executable_record
from .common import Json, Refused, candidate_fd, file_hash, sync_dir
from .engine import idle_check, journal_save, locked_state, read_run as read_journal, run_path, seal

ACTION = "codex-native-history-archive"
RISK = ("Native archival moves history out of the default list and includes spawned descendants. "
        "It retains transcript bytes and promises zero disk reclaim. Recovery unarchives each changed thread "
        "individually and updates file/index timestamps; this is not a guarantee of conversation continuation. "
        "The native program reads this Codex home configuration and maintains its index. The OS sandbox denies "
        "network, other executable paths and writes outside this Codex home and the private runtime home. "
        "Stop every writer first.")
MAX_RECORDS = 20000
ROW_FIELDS = ("id", "root", "relative", "identity", "updated_at", "archived", "pinned", "source")


def audit_again(inventory: Json) -> Json:
    return history.audit(Path(inventory["root"]), **inventory["thresholds"],
                         **inventory["policy"], max_records=MAX_RECORDS)


def closure(inventory: Json, roots: list[str]) -> tuple[dict[str, Json], dict[str, list[str]], list[Json]]:
    if inventory.get("schema") != 1 or inventory.get("kind") != "codex-history-audit":
        raise Refused("Expected a native Codex history audit")
    if inventory.get("complete") is not True:
        raise Refused("Native archival requires a complete index, file and lineage audit; inspect unresolved records")
    rows = {r["id"]: r for r in inventory["threads"]}
    if not rows or len(rows) != len(inventory["threads"]) or len(rows) > MAX_RECORDS:
        raise Refused("Native history has duplicate or excessive indexed threads")
    if not roots or len(roots) != len(set(roots)) or any(r not in rows for r in roots):
        raise Refused("Select existing, unique native root IDs")
    children: dict[str, list[str]] = {}
    parents: dict[str, str] = {}
    for edge in inventory["edges"]:
        parent, child = edge["parent"], edge["child"]
        if child in parents:
            raise Refused("Duplicate or conflicting native lineage edges")
        parents[child] = parent
        children.setdefault(parent, []).append(child)
    groups: dict[str, list[str]] = {}
    reached: set[str] = set()
    for root in roots:
        if root in parents or rows[root]["source"] not in history.MAIN_SOURCES:
            raise Refused("Select a top-level native thread, never a linked child")
        group: set[str] = set()
        pending = [root]
        while pending:
            value = pending.pop()
            if value not in rows or value in group or value in reached:
                raise Refused("Unresolved, cyclic, or overlapping native mutation closure")
            group.add(value)
            pending.extend(children.get(value, []))
        reached.update(group)
        groups[root] = sorted(group)
    edges = sorted((dict(e) for e in inventory["edges"] if e["parent"] in reached or e["child"] in reached),
                   key=lambda e: (e["parent"], e["child"], e["status"]))
    return {i: rows[i] for i in sorted(reached)}, groups, edges


def structural_item(item: Json, root: str) -> None:
    if (item["root"] != root or not item.get("identity") or item["identity"]["nlink"] != 1
            or type(item["archived"]) is not bool or type(item["pinned"]) is not bool):
        raise Refused("Unsupported source identity, archive state, or pin state")
    relative = Path(item["relative"])
    match = re.fullmatch(r"rollout-(\d{4})-(\d{2})-(\d{2})T[0-9-]+-" + re.escape(item["id"]) + r"\.jsonl", relative.name)
    if not match or relative.is_absolute() or ".." in relative.parts:
        raise Refused("Unrecognized native transcript path")
    expected = (Path("archived_sessions") / relative.name if item["archived"] else
                Path("sessions") / match[1] / match[2] / match[3] / relative.name)
    if relative != expected:
        raise Refused("Native unarchive cannot prove restoration to this original path")


def hash_source(item: Json, *, header: bool = False) -> str:
    with candidate_fd(item) as fd:
        if os.fstat(fd).st_uid != os.getuid():
            raise Refused("Unowned native transcript")
        if header:
            with os.fdopen(os.dup(fd), "rb") as stream:
                line = stream.readline(2 * 1024**2 + 1)
            if len(line) > 2 * 1024**2:
                raise Refused("Native transcript header is too large")
            try:
                row = json.loads(line)
                payload = row["payload"]
                source = item["source"]
                source = json.loads(source) if source.startswith("{") else source
                valid = row["type"] == "session_meta" and payload["id"] == item["id"] and payload["source"] == source
            except (ValueError, KeyError, TypeError, AttributeError):
                valid = False
            if not valid:
                raise Refused("Transcript header identity/source disagrees with native index")
        return file_hash(fd)


def projection(rows: dict[str, Json]) -> Json:
    return {ident: {key: row[key] for key in ROW_FIELDS} for ident, row in rows.items()}


def make_plan(inventory: Json, ids: list[str], state: Path, *, codex: Path | str = "codex", ttl: int = 3600) -> Json:
    if not 1 <= ttl <= 86400:
        raise Refused("Native plan TTL must be between 1 and 86400 seconds")
    root = Path(inventory["root"])
    state = state.expanduser().absolute()
    if root.resolve(strict=True) != root or state.resolve() != state or state.is_relative_to(root):
        raise Refused("Use canonical Codex and state paths, with state outside the Codex home")
    old, old_groups, old_edges = closure(inventory, ids)
    fresh = audit_again(inventory)
    rows, groups, edges = closure(fresh, ids)
    if projection(rows) != projection(old) or groups != old_groups or edges != old_edges:
        raise Refused("Native history changed since the supplied audit; review a fresh audit")
    if any(row["protection_reasons"] for row in rows.values()) or any(rows[i]["archived"] for i in ids):
        raise Refused("The entire native closure must be unprotected, with unarchived selected roots")
    items = []
    for row in rows.values():
        structural_item(row, str(root))
        item = {key: row[key] for key in ROW_FIELDS}
        item["sha256"] = hash_source(row, header=True)
        item["archive_relative"] = str(Path("archived_sessions") / Path(row["relative"]).name)
        if not row["archived"] and os.path.lexists(root / item["archive_relative"]):
            raise Refused("Native archive destination already exists")
        items.append(item)
    idle_check(items)
    with locked_state(state):
        home = state / ("native-home-" + uuid.uuid4().hex)
        runtime = executable_record(codex, root, home)
    now = time.time()
    plan = {"schema": 1, "action": ACTION, "risk": RISK, "root": str(root),
            "created_at": now, "expires_at": now + ttl, "state_dir": str(state),
            "thresholds": fresh["thresholds"], "policy": fresh["policy"], "selected_roots": ids,
            "groups": groups, "edges": edges, "items": items, "runtime": runtime,
            "changed_ids": sorted(i["id"] for i in items if not i["archived"]),
            "expected_immediate_reclaimed_bytes": 0, "harness_resume_verified": False}
    plan["hash"] = seal(plan)
    check_plan(plan, plan["hash"])
    return plan


def check_plan(plan: Json, approval: str, *, expired_ok: bool = False) -> None:
    if (plan.get("schema") != 1 or plan.get("action") != ACTION or plan.get("risk") != RISK
            or plan.get("expected_immediate_reclaimed_bytes") != 0 or plan.get("harness_resume_verified") is not False):
        raise Refused("Unsupported native history plan")
    if plan.get("hash") != seal(plan) or approval != plan["hash"]:
        raise Refused("Approval must equal the exact reviewed native history plan hash")
    if not expired_ok and time.time() > plan["expires_at"]:
        raise Refused("Native history plan expired; audit and review again")
    if len(json.dumps(plan).encode()) > 16 * 1024**2:
        raise Refused("Native plan exceeds journal size bound")
    if (not plan["items"] or len(plan["items"]) > MAX_RECORDS
            or len({i["id"] for i in plan["items"]}) != len(plan["items"])):
        raise Refused("Invalid native closure item set")
    if plan["runtime"]["codex_home"] != plan["root"]:
        raise Refused("Native runtime is bound to a different home")
    state, home = Path(plan["state_dir"]), Path(plan["runtime"]["home"])
    if not home.is_relative_to(state) or state.is_relative_to(Path(plan["root"])):
        raise Refused("Unsafe native runtime state placement")
    expected = sorted(i["id"] for i in plan["items"] if not i["archived"])
    if not expected or plan["changed_ids"] != expected:
        raise Refused("Invalid native changed-thread set")
    for item in plan["items"]:
        structural_item(item, plan["root"])


def current_rows(plan: Json) -> dict[str, Json]:
    fresh = audit_again(plan)
    rows, groups, edges = closure(fresh, plan["selected_roots"])
    if groups != plan["groups"] or edges != plan["edges"] or set(rows) != {i["id"] for i in plan["items"]}:
        raise Refused("Native descendant closure changed since review")
    return rows


def verify_rows(plan: Json, *, desired: dict[str, bool] | None = None,
                require_unprotected: bool = False, journal: Json | None = None) -> list[Json]:
    rows = current_rows(plan)
    intents = {e["id"] for e in (journal or {}).get("events", [])
               if e["status"] in {"unarchive-intent", "unarchived"}}
    restored = (journal or {}).get("restored_metadata", {})
    observed = {**(journal or {}).get("archived_metadata", {}), **restored}
    archived_intents = {i for e in (journal or {}).get("events", [])
                        if e["status"] in {"archive-intent", "archived"} for i in e["ids"]}
    results = []
    for item in plan["items"]:
        row = rows[item["id"]]
        structural_item(row, plan["root"])
        if any(row[k] != item[k] for k in ("id", "root", "pinned", "source")):
            raise Refused("Native transcript metadata or identity changed since review")
        baseline = observed.get(item["id"], item)
        if item["id"] in intents and not row["archived"] and item["id"] not in restored:
            # Codex unarchive deliberately touches mtime, then repairs updated_at.
            # Only a durable intent permits this transition. Bytes and inode stay bound.
            if (any(row["identity"][k] != item["identity"][k] for k in item["identity"] if k != "mtime_ns")
                    or not item["identity"]["mtime_ns"] <= row["identity"]["mtime_ns"] <= time.time_ns() + 5 * 10**9
                    or not item["updated_at"] <= row["updated_at"] <= time.time() + 5):
                raise Refused("Unexpected native recovery metadata transition")
        elif item["id"] in archived_intents and row["archived"] and item["id"] not in observed:
            # Native archive internally repairs same-second DB ordering fractions.
            # A recorded archive intent permits that fraction only; file identity stays exact.
            if (row["identity"] != item["identity"]
                    or math.floor(row["updated_at"]) != math.floor(item["updated_at"])):
                raise Refused("Unexpected metadata change during native archival")
        elif row["identity"] != baseline["identity"] or row["updated_at"] != baseline["updated_at"]:
            raise Refused("Native transcript metadata or identity changed since review")
        if require_unprotected and row["protection_reasons"]:
            raise Refused("A thread in the native closure is now protected")
        archived = row["archived"]
        if item["archived"] and not archived:
            raise Refused("An originally archived descendant changed outside this run")
        expected_path = item["archive_relative"] if archived else item["relative"]
        if row["relative"] != expected_path or hash_source(row, header=True) != item["sha256"]:
            raise Refused("Native path or transcript bytes differ from the reviewed plan")
        if not item["archived"]:
            other = item["relative"] if archived else item["archive_relative"]
            if os.path.lexists(Path(plan["root"]) / other):
                raise Refused("Both original and native archive paths exist; inspect the conflict")
        if desired is not None and archived != desired[item["id"]]:
            raise Refused("Native archive membership differs from the expected stage")
        results.append({"id": item["id"], "archived": archived, "relative": row["relative"],
                        "identity": row["identity"], "updated_at": row["updated_at"], "bytes_verified": True})
    return results


def rpc_preflight(rpc: CodexRPC, plan: Json, roots: list[str]) -> None:
    rows = current_rows(plan)
    for root in roots:
        expected = set(plan["groups"][root]) - {root}
        active = rpc.descendants(root, archived=False, cap=MAX_RECORDS)
        archived = rpc.descendants(root, archived=True, cap=MAX_RECORDS)
        if active & archived or active | archived != expected:
            raise Refused("Native API descendant listing does not prove the full indexed closure")
        if active != {i for i in expected if not rows[i]["archived"]}:
            raise Refused("Native API and indexed archive membership disagree")
        for ident in plan["groups"][root]:
            result = rpc.request("thread/read", {"threadId": ident, "includeTurns": False})["thread"]
            if result.get("id") != ident or result.get("status", {}).get("type") != "notLoaded":
                raise Refused("Native thread is loaded, active, or has unknown runtime state")
            if result.get("path") != str(Path(plan["root"]) / rows[ident]["relative"]):
                raise Refused("Native API path differs from the indexed path")
    # notLoaded describes only this server; the caller must separately stop every writer.


def apply(plan: Json, approval: str, *, quiescent: bool) -> Json:
    check_plan(plan, approval)
    if not quiescent:
        raise Refused("Stop every relevant writer and acknowledge --writers-stopped")
    state = Path(plan["state_dir"])
    with locked_state(state):
        directory = run_path(state, plan["hash"])
        if directory.exists():
            raise Refused("Native run already exists; verify or restore, never replay archive")
        desired = {i["id"]: i["archived"] for i in plan["items"]}
        verify_rows(plan, desired=desired, require_unprotected=True)
        idle_check(plan["items"])
        with CodexRPC(plan["runtime"]) as rpc:
            rpc_preflight(rpc, plan, plan["selected_roots"])
            verify_rows(plan, desired=desired, require_unprotected=True)
            directory.mkdir(mode=0o700)
            sync_dir(state)
            journal: Json = {"schema": 1, "plan": plan, "status": "archiving", "events": []}
            journal_save(directory, journal)
            try:
                for root in plan["selected_roots"]:
                    verify_rows(plan, desired=desired, journal=journal)
                    rpc_preflight(rpc, plan, [root])
                    rows = current_rows(plan)
                    if any(rows[i]["protection_reasons"] for i in plan["groups"][root]):
                        raise Refused("Native closure protection changed immediately before archive")
                    idle_check([rows[i] for i in plan["groups"][root]])
                    event = {"root": root, "status": "archive-intent", "ids": plan["groups"][root]}
                    journal["events"].append(event)
                    journal_save(directory, journal)
                    rpc.request("thread/archive", {"threadId": root})
                    for ident in plan["groups"][root]:
                        desired[ident] = True
                    verify_rows(plan, desired=desired, journal=journal)
                    event["status"] = "archived"
                    journal_save(directory, journal)
            except BaseException:
                journal["status"] = "interrupted"
                journal_save(directory, journal)
                raise
        try:
            observed = verify_rows(plan, desired=desired, journal=journal)
            journal["archived_metadata"] = {r["id"]: {"identity": r["identity"], "updated_at": r["updated_at"]}
                                            for r in observed}
            journal["status"] = "archived"
            journal_save(directory, journal)
        except BaseException:
            journal["status"] = "interrupted"
            journal_save(directory, journal)
            raise
        return {"run": plan["hash"], "status": "archived", "files": len(plan["changed_ids"]),
                "reclaimed_bytes": 0, "harness_resume_verified": False}


def read_run(state: Path, run: str) -> tuple[Path, Json]:
    directory, journal = read_journal(state, run)
    check_plan(journal["plan"], run, expired_ok=True)
    return directory, journal


def verify(state: Path, run: str) -> Json:
    with locked_state(state):
        _, journal = read_run(state, run)
        plan = journal["plan"]
        rows = verify_rows(plan, journal=journal)
        intended = {i for e in journal["events"] if e["status"] in {"archive-intent", "archived"} for i in e["ids"]}
        if any(r["archived"] and r["id"] in plan["changed_ids"] and r["id"] not in intended for r in rows):
            raise Refused("A thread was archived without this run recording intent")
        desired = ({i["id"]: True for i in plan["items"]} if journal["status"] == "archived" else
                   {i["id"]: i["archived"] for i in plan["items"]} if journal["status"] == "restored" else None)
        ok = desired is not None and all(r["archived"] == desired[r["id"]] for r in rows)
        return {"run": run, "status": journal["status"], "ok": ok, "items": rows,
                "bytes_verified": True, "reclaimed_bytes": 0, "harness_resume_verified": False}


def restore(state: Path, run: str, approval: str, *, quiescent: bool) -> Json:
    if approval != "unarchive:" + run or not quiescent:
        raise Refused("Native recovery requires unarchive:<run> approval and stopped writers")
    with locked_state(state):
        directory, journal = read_run(state, run)
        plan = journal["plan"]
        rows = verify_rows(plan, journal=journal)
        intended = {i for e in journal["events"] if e["status"] in {"archive-intent", "archived"} for i in e["ids"]}
        pending = [r["id"] for r in rows if r["id"] in plan["changed_ids"] and r["archived"]]
        if not set(pending) <= intended:
            raise Refused("Recovery cannot unarchive a thread without recorded archive intent")
        with CodexRPC(plan["runtime"]) as rpc:
            rpc_preflight(rpc, plan, plan["selected_roots"])
            journal["status"] = "restoring"
            journal_save(directory, journal)
            try:
                for ident in pending:
                    verify_rows(plan, journal=journal)
                    current = current_rows(plan)[ident]
                    idle_check([current])
                    rpc_preflight(rpc, plan, plan["selected_roots"])
                    event = {"id": ident, "status": "unarchive-intent"}
                    journal["events"].append(event)
                    journal_save(directory, journal)
                    result = rpc.request("thread/unarchive", {"threadId": ident})
                    original = next(i for i in plan["items"] if i["id"] == ident)
                    if result.get("thread", {}).get("id") != ident:
                        raise Refused("Unexpected native unarchive response")
                    verified = {r["id"]: r for r in verify_rows(plan, journal=journal)}[ident]
                    if verified["archived"] or verified["relative"] != original["relative"]:
                        raise Refused("Native unarchive did not restore the reviewed path")
                    event["status"] = "unarchived"
                    journal_save(directory, journal)
                verify_rows(plan, desired={i["id"]: i["archived"] for i in plan["items"]}, journal=journal)
            except BaseException:
                journal["status"] = "interrupted"
                journal_save(directory, journal)
                raise
        # Observe after the private server exits so its metadata repair has settled.
        try:
            observed = verify_rows(plan, desired={i["id"]: i["archived"] for i in plan["items"]}, journal=journal)
            journal["restored_metadata"] = {r["id"]: {"identity": r["identity"], "updated_at": r["updated_at"]}
                                            for r in observed if r["id"] in plan["changed_ids"]}
            journal["status"] = "restored"
            journal_save(directory, journal)
        except BaseException:
            journal["status"] = "interrupted"
            journal_save(directory, journal)
            raise
        return {"run": run, "status": "restored", "files": len(pending),
                "reclaimed_bytes": 0, "harness_resume_verified": False}
