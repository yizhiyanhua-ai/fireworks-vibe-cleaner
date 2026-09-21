"""Read-only Codex history pressure and conservative native-archive candidates.

SQLite is opened in read-only mode. Native mutations belong to a separate,
explicitly approved adapter; no database updates or filesystem moves occur here.
"""
from __future__ import annotations

from collections import Counter, deque
import contextlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

from .common import Json, Refused, candidate_fd, identity

GIB = 1024**3
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
MAIN_SOURCES = {"cli", "vscode", "exec", "appServer"}


def header_parent(fd: int, thread_id: str, source: str) -> str | None:
    """Inspect only bounded metadata; never return instructions or transcript text."""
    with os.fdopen(os.dup(fd), "rb") as stream:
        line = stream.readline(2 * 1024**2 + 1)
    if len(line) > 2 * 1024**2:
        raise Refused("Oversize native transcript metadata")
    try:
        record = json.loads(line)
        payload = record.get("payload", {})
        expected_source = json.loads(source) if source.startswith("{") else source
        if (record.get("type") != "session_meta" or payload.get("id") != thread_id
                or payload.get("source") != expected_source):
            raise Refused("Native index and transcript metadata disagree")
        origin = payload.get("source")
        parent = payload.get("parent_thread_id")
        if isinstance(origin, dict):
            agent = origin.get("subAgent", origin.get("subagent", {}))
            spawn = agent.get("thread_spawn", {}) if isinstance(agent, dict) else {}
            parent = spawn.get("parent_thread_id", parent) if isinstance(spawn, dict) else parent
        if parent is not None and (not isinstance(parent, str) or not UUID.fullmatch(parent)):
            raise Refused("Unknown native parent identifier")
        return parent
    except (ValueError, TypeError, AttributeError):
        raise Refused("Unrecognized native transcript metadata") from None


def descendants(root_id: str, edges: list[Json]) -> set[str]:
    children: dict[str, set[str]] = {}
    for edge in edges:
        children.setdefault(edge["parent"], set()).add(edge["child"])
    reached: set[str] = set()
    visiting: set[str] = set()

    def visit(thread: str) -> None:
        if thread in visiting:
            raise Refused("Cycle in native thread lineage; review manually")
        if thread in reached:
            return
        visiting.add(thread)
        for child in children.get(thread, set()):
            visit(child)
        visiting.remove(thread)
        reached.add(thread)

    try:
        visit(root_id)
    except RecursionError:
        raise Refused("Native thread lineage is too deep") from None
    return reached


def audit(root: Path, *, total_bytes: int = 3 * GIB, single_bytes: int = 3 * GIB,
          count_limit: int = 200, min_age_days: int = 30, keep_recent: int = 100,
          keep_ids: list[str] | None = None, max_records: int = 20000) -> Json:
    if (min(total_bytes, single_bytes, count_limit, min_age_days, max_records) < 1
            or keep_recent < 0 or max_records > 20000):
        raise Refused("Positive thresholds/retention required; at most 20000 indexed threads")
    root = root.expanduser().resolve(strict=True)
    if root == Path("/") or root == Path.home().resolve():
        raise Refused("Choose the Codex home, not HOME or /")
    databases = list(root.glob("state_*.sqlite"))
    if len(databases) != 1 or databases[0].name != "state_5.sqlite":
        raise Refused("Native history audit requires one supported state_5.sqlite; never guess or edit an index")
    database = databases[0]
    s = database.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_uid != os.getuid():
        raise Refused("Native index must be an owned regular file without symlinks/hardlinks")
    required = {"id", "rollout_path", "updated_at", "updated_at_ms", "archived", "is_pinned", "source"}
    try:
        with contextlib.closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            columns = {r[1] for r in db.execute("PRAGMA table_info(threads)")}
            edge_columns = {r[1] for r in db.execute("PRAGMA table_info(thread_spawn_edges)")}
            if not required <= columns or not {"parent_thread_id", "child_thread_id", "status"} <= edge_columns:
                raise Refused("Unsupported native index/pin/lineage schema; keep sessions unchanged")
            count = db.execute("SELECT count(*) FROM threads").fetchone()[0]
            if count > max_records:
                raise Refused("Native history exceeds the bounded inventory limit; review in a native client")
            records = db.execute(
                "SELECT id,rollout_path,updated_at,updated_at_ms,archived,is_pinned,source FROM threads"
            ).fetchall()
            edge_rows = db.execute(
                "SELECT parent_thread_id,child_thread_id,status FROM thread_spawn_edges LIMIT ?",
                (max_records * 4 + 1,),
            ).fetchall()
            if len(edge_rows) > max_records * 4:
                raise Refused("Native lineage exceeds the bounded inventory limit")
    except sqlite3.Error:
        raise Refused("Native index could not be read consistently; no fallback writes are allowed") from None
    edges = [{"parent": r[0], "child": r[1], "status": r[2]} for r in edge_rows]
    if any(not isinstance(e[k], str) or not UUID.fullmatch(e[k]) for e in edges for k in ("parent", "child")):
        raise Refused("Unrecognized native lineage identifiers")
    keep = set(keep_ids or [])
    current = os.getenv("CODEX_THREAD_ID")
    if current:
        keep.add(current)
    now = time.time()
    rows: list[Json] = []
    seen_ids: set[str] = set()
    seen_paths: dict[str, Json] = {}
    seen_inodes: set[tuple[int, int]] = set()
    logical = allocated = 0
    missing = 0
    for thread_id, path_text, seconds, millis, archived, pinned, source in records:
        if not isinstance(thread_id, str) or not UUID.fullmatch(thread_id) or thread_id in seen_ids:
            raise Refused("Unknown or duplicated native thread identifier")
        seen_ids.add(thread_id)
        if archived not in (0, 1) or pinned not in (0, 1):
            raise Refused("Unknown native archive/pin state")
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise Refused("Unknown native update time")
        valid_millis = type(millis) in (int, float) and math.isfinite(millis) and millis > 0
        updated = max(seconds, millis / 1000) if valid_millis else seconds
        reasons = []
        if valid_millis and abs(millis / 1000 - seconds) >= 1:
            reasons.append("inconsistent-native-update-times")
        if millis is not None and not valid_millis:
            reasons.append("invalid-native-millisecond-time")
        if pinned:
            reasons.append("pinned")
        if thread_id in keep:
            reasons.append("explicit-keep-or-current-thread")
        if now - updated < min_age_days * 86400:
            reasons.append("recent-or-future-update")
        row: Json = {"id": thread_id, "root": str(root), "relative": None, "identity": None, "measured_size": None,
                     "updated_at": updated, "archived": bool(archived), "pinned": bool(pinned),
                     "source": source, "protection_reasons": reasons}
        try:
            path = Path(path_text)
            relative = path.relative_to(root)
            if (not relative.parts or relative.parts[0] not in {"sessions", "archived_sessions"}
                    or path.suffix != ".jsonl" or not path.stem.endswith(thread_id)):
                raise Refused("Unknown transcript path")
            s = path.lstat()
            if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_uid != os.getuid():
                raise Refused("Nonregular, linked or unowned transcript")
            row.update(relative=str(relative), identity=identity(s))
            with candidate_fd(row) as fd:
                row["measured_size"] = s.st_size
                key = (s.st_dev, s.st_ino)
                if key not in seen_inodes:
                    logical += s.st_size
                    allocated += getattr(s, "st_blocks", 0) * 512
                    seen_inodes.add(key)
                row["header_parent"] = header_parent(fd, thread_id, source)
            if bool(archived) != (relative.parts[0] == "archived_sessions"):
                reasons.append("index-path-state-mismatch")
            if now - s.st_mtime < min_age_days * 86400:
                reasons.append("recent-or-future-file-write")
            if str(path) in seen_paths:
                reasons.append("duplicated-rollout-path")
                seen_paths[str(path)]["protection_reasons"].append("duplicated-rollout-path")
            seen_paths[str(path)] = row
        except (OSError, ValueError, TypeError, Refused):
            reasons.append("missing-unsafe-or-unreadable-transcript")
            row["identity"] = None
            missing += 1
        rows.append(row)
    recent = sorted((r for r in rows if not r["archived"]), key=lambda r: (-r["updated_at"], r["id"]))
    for row in recent[:keep_recent]:
        row["protection_reasons"].append("keep-most-recent")
    by_id = {r["id"]: r for r in rows}
    lineage_issues = 0
    parents: dict[str, set[str]] = {}
    for edge in edges:
        parents.setdefault(edge["child"], set()).add(edge["parent"])
        # open/closed are persisted spawn-edge lifecycle values, not proof of idle writers.
        if edge["status"] not in {"open", "closed"}:
            lineage_issues += 1
            for thread in (edge["parent"], edge["child"]):
                if thread in by_id:
                    by_id[thread]["protection_reasons"].append("unknown-spawn-edge-status")
    for child, ancestor_ids in parents.items():
        if len(ancestor_ids) > 1:
            lineage_issues += 1
            for thread in ancestor_ids | {child}:
                if thread in by_id:
                    by_id[thread]["protection_reasons"].append("multiple-spawn-parents")
    for row in rows:
        parent = row.get("header_parent")
        if (parent or parents.get(row["id"])) and parents.get(row["id"]) != ({parent} if parent else set()):
            lineage_issues += 1
            row["protection_reasons"].append("header-index-lineage-mismatch")
            if parent in by_id:
                by_id[parent]["protection_reasons"].append("header-index-lineage-mismatch")
    children_by_parent: dict[str, set[str]] = {}
    indegree: dict[str, int] = {}
    for edge in edges:
        children_by_parent.setdefault(edge["parent"], set()).add(edge["child"])
        indegree.setdefault(edge["parent"], 0)
        indegree.setdefault(edge["child"], 0)
    for children_set in children_by_parent.values():
        for child in children_set:
            indegree[child] += 1
    queue = deque(t for t, n in indegree.items() if n == 0)
    while queue:
        for child in children_by_parent.get(queue.popleft(), set()):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    for thread, degree in indegree.items():
        if degree:
            lineage_issues += 1
            if thread in by_id:
                by_id[thread]["protection_reasons"].append("cyclic-or-deep-lineage")
    unknown_edges = sum(e["parent"] not in by_id or e["child"] not in by_id for e in edges)
    children = {e["child"] for e in edges}
    candidates = []
    for row in sorted(rows, key=lambda r: (r["updated_at"], r["id"])):
        if row["archived"] or row["protection_reasons"] or row["source"] not in MAIN_SOURCES or row["id"] in children:
            continue
        try:
            closure = descendants(row["id"], edges)
        except Refused:
            row["protection_reasons"].append("cyclic-or-deep-lineage")
            continue
        if all(t in by_id and not by_id[t]["protection_reasons"] for t in closure):
            candidates.append(row["id"])
    oversized = [r["id"] for r in rows if r["measured_size"] is not None and r["measured_size"] > single_bytes]
    unarchived = sum(not r["archived"] for r in rows)
    triggers = {"total_bytes_exceeded": logical > total_bytes, "single_session_exceeded": bool(oversized),
                "unarchived_count_exceeded": unarchived > count_limit}
    return {"schema": 1, "kind": "codex-history-audit", "root": str(root), "created_at": now,
            "thresholds": {"total_bytes": total_bytes, "single_bytes": single_bytes, "count_limit": count_limit},
            "policy": {"min_age_days": min_age_days, "keep_recent": keep_recent, "keep_ids": sorted(keep)},
            "complete": missing == 0 and unknown_edges == 0 and lineage_issues == 0,
            "threads": rows, "edges": edges, "native_candidates": candidates,
            "summary": {"indexed_threads": len(rows), "unarchived_threads": unarchived,
                        "archived_threads": len(rows) - unarchived, "known_logical_bytes": logical,
                        "known_allocated_bytes": allocated, "missing_or_unsafe_files": missing,
                        "measured_files": len(seen_inodes),
                        "largest_known_session_bytes": max((r["measured_size"] or 0 for r in rows), default=0),
                        "unresolved_edges": unknown_edges, "lineage_issues": lineage_issues,
                        "native_candidate_roots": len(candidates),
                        "protected_threads": sum(bool(t["protection_reasons"]) for t in rows),
                        "oversized_thread_ids": oversized, "triggers": triggers,
                        "protected_reasons": dict(Counter(r for t in rows for r in t["protection_reasons"])),
                        "native_archive_reclaim_bytes": 0,
                        "note": "Index-wide counts, not a UI/project-filtered list. Bytes cover readable indexed files only; "
                                "unindexed files are excluded. Native archive reduces list clutter, not disk usage. "
                                "Candidates are preliminary; full descendant scope and human approval are required."}}
