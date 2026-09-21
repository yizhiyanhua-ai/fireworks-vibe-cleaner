"""Explicitly approved removal of archived transcripts, with byte/path recovery.

This does not edit harness indexes or claim conversation continuation support.
The log/cache executor deliberately remains a separate, narrower path.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time
from typing import Iterator
import uuid
import zipfile

from .common import (Json, Refused, candidate_fd, file_hash, identity, parent_fd,
                     sync_dir)
from .engine import idle_check, journal_save, locked_state, run_path, seal
from .scan import POLICY, classify, transcript_id

ACTION = "remove-archived-transcripts"
RISK = ("Removes only the selected transcript files. Related files and harness indexes stay unchanged; "
        "history entries may become unavailable. Recovery restores original file bytes and paths, "
        "not application state or verified conversation continuation. Keep archives and this journal.")


def durable_directory_chain(path: Path) -> None:
    """Persist directory entries up to this filesystem's mount point."""
    device = path.stat().st_dev
    while path.stat().st_dev == device:
        sync_dir(path)
        if path.parent == path:
            break
        path = path.parent


def file_ref(path: Path) -> Json:
    path = path.expanduser().absolute()
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_uid != os.getuid():
        raise Refused("Archive/manifest must be an owned regular file, without hardlinks")
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise Refused("Archive directory must be private (0700)")
    return {"root": str(path.parent), "relative": path.name, "identity": identity(s)}


def validate_source(item: Json, min_age: int, keep: list[str]) -> None:
    category, _ = classify(Path(item["root"]), item["relative"], item["adapter"])
    if (category != "session" or item["category"] != "session"
            or not transcript_id(item["relative"], item["adapter"])
            or not item.get("archive_eligible")):
        raise Refused("Only recognized top-level transcripts can use archive removal")
    if min_age < 1 or (time.time_ns() - item["identity"]["mtime_ns"]) / 86400e9 < min_age:
        raise Refused("Transcript retention period not met")
    if item["identity"]["nlink"] != 1 or any((Path(item["root"]) / item["relative"]).match(p) for p in keep):
        raise Refused("Hardlink or user keep rule")


def check_header(fd: int, item: Json) -> None:
    """Recognize source identity; refuse unknown formats without reading unbounded lines."""
    wanted = transcript_id(item["relative"], item["adapter"])
    os.lseek(fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(fd), "rb") as stream:
        consumed = 0
        for _ in range(100):
            line = stream.readline(2 * 1024**2 + 1)
            consumed += len(line)
            if not line or len(line) > 2 * 1024**2 or consumed > 16 * 1024**2:
                break
            try:
                data = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                raise Refused("Unrecognized transcript format") from None
            if not isinstance(data, dict):
                break
            if item["adapter"] == "codex":
                payload = data.get("payload")
                if (data.get("type") == "session_meta" and isinstance(payload, dict)
                        and payload.get("id") == wanted):
                    if (payload.get("source") not in ("cli", "vscode", "exec")
                            or any(payload.get(k) for k in ("parent_thread_id", "parent_session_id",
                                                           "forked_from_id", "subagent", "agent_role"))):
                        raise Refused("Linked, subagent or unknown-origin transcript stays backup-only")
                    return
            elif data.get("type") in {"user", "assistant"} and data.get("sessionId") == wanted:
                if (data.get("isSidechain") not in (False, None) or data.get("agentId")
                        or data.get("parentSessionId")):
                    raise Refused("Claude sidechain or subagent transcript stays backup-only")
                return
    raise Refused("Transcript identity/schema not recognized; keep or back up only")


@contextlib.contextmanager
def checked_archives(plan: Json) -> Iterator[dict[int, zipfile.ZipFile]]:
    """Hash each complete archive and stream-check selected members against source hashes."""
    with contextlib.ExitStack() as stack:
        archives = {}
        try:
            for n, binding in enumerate(plan["archives"]):
                fd = stack.enter_context(candidate_fd(binding))
                if file_hash(fd) != binding["sha256"]:
                    raise Refused("Archive bytes changed since review")
                stream = stack.enter_context(os.fdopen(os.dup(fd), "rb"))
                archive = stack.enter_context(zipfile.ZipFile(stream))
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise Refused("Duplicate archive members")
                archives[n] = archive
            for item in plan["items"]:
                binding = item["backup"]
                archive = archives[binding["archive_index"]]
                member = binding["member"]
                size = item["identity"]["size"]
                if archive.getinfo(member).file_size != size:
                    raise Refused("Archive member size mismatch")
                h = hashlib.sha256()
                count = 0
                with archive.open(member) as member_stream:
                    while block := member_stream.read(1024**2):
                        count += len(block)
                        if count > size:
                            raise Refused("Archive expansion exceeded approved size")
                        h.update(block)
                if count != size or h.hexdigest() != item["sha256"]:
                    raise Refused("Archive does not contain the exact approved source bytes")
            yield archives
        except (zipfile.BadZipFile, KeyError, EOFError) as exc:
            raise Refused("Missing or damaged archive member") from exc


def make_plan(inventory: Json, ids: list[str], archives: list[Path], state: Path,
              *, max_bytes: int, ttl: int = 3600) -> Json:
    if (inventory.get("policy") != POLICY or not ids or len(set(ids)) != len(ids)
            or not 1 <= len(ids) <= 10000 or not 1 <= ttl <= 86400 or max_bytes < 1 or not 1 <= len(archives) <= 64):
        raise Refused("Select unique transcripts, 1..64 archives, a byte cap and a valid TTL")
    selected = [dict(i) for i in inventory["items"] if i["id"] in ids]
    if len(selected) != len(ids):
        raise Refused("Unknown transcript ID")
    if sum(i["identity"]["size"] for i in selected) > max_bytes:
        raise Refused("Selected transcripts exceed byte cap")
    for item in selected:
        validate_source(item, inventory["min_age_days"], inventory.get("keep", []))
        with candidate_fd(item) as fd:
            check_header(fd, item)
            item["sha256"] = file_hash(fd)
    idle_check(selected)
    bindings = []
    for n, path in enumerate(archives):
        binding = file_ref(path)
        with candidate_fd(binding) as fd:
            binding["sha256"] = file_hash(fd)
            os.fsync(fd)
        manifest_ref = file_ref(path.with_suffix(path.suffix + ".manifest.json"))
        if manifest_ref["identity"]["size"] > 64 * 1024**2:
            raise Refused("Manifest too large")
        with candidate_fd(manifest_ref) as fd, os.fdopen(os.dup(fd), "rb") as stream:
            manifest = json.load(stream)
        # Never trust manifest.status; match a source and verify the actual ZIP bytes below.
        for item in selected:
            matches = [row for row in manifest["files"]
                       if (row["item"]["root"], row["item"]["relative"]) == (item["root"], item["relative"])]
            if matches:
                if len(matches) != 1 or "backup" in item:
                    raise Refused("Ambiguous source-to-archive mapping")
                row = matches[0]
                if (row["sha256"] != item["sha256"] or row["item"]["identity"]["size"] != item["identity"]["size"]
                        or not isinstance(row["member"], str) or not row["member"].isascii()
                        or not row["member"].isdecimal()):
                    raise Refused("Archive manifest does not match current source")
                if binding["identity"]["dev"] != item["identity"]["dev"]:
                    raise Refused("Keep the private archive on the source volume")
                item["backup"] = {"archive_index": n, "member": row["member"]}
        sync_dir(path.parent)
        bindings.append(binding)
    if any("backup" not in item for item in selected):
        raise Refused("Every selected source needs an exact verified backup")
    if len({(a["root"], a["relative"]) for a in bindings}) != len(bindings):
        raise Refused("Duplicate archives")
    now = time.time()
    plan: Json = {"schema": 1, "policy": POLICY, "action": ACTION, "created_at": now,
                  "expires_at": now + ttl, "max_bytes": max_bytes,
                  "min_age_days": inventory["min_age_days"], "keep": inventory.get("keep", []),
                  "state_dir": str(state.expanduser().resolve()), "items": selected, "archives": bindings,
                  "risk": RISK, "harness_resume_verified": False,
                  "source_logical_bytes": sum(i["identity"]["size"] for i in selected),
                  "retained_archive_bytes": sum(a["identity"]["size"] for a in bindings)}
    plan["hash"] = seal(plan)
    check_plan(plan, plan["hash"])
    with checked_archives(plan):
        pass
    return plan


def check_plan(plan: Json, approval: str, *, expired_ok: bool = False) -> None:
    if (plan.get("schema") != 1 or plan.get("policy") != POLICY or plan.get("action") != ACTION
            or plan.get("risk") != RISK or plan.get("harness_resume_verified") is not False):
        raise Refused("Unsupported archive removal plan")
    if plan.get("hash") != seal(plan) or approval != plan["hash"]:
        raise Refused("Approval must match the complete reviewed archive removal plan")
    if not expired_ok and time.time() > plan["expires_at"]:
        raise Refused("Archive removal plan expired; prepare and review again")
    items = plan["items"]
    if not 1 <= len(items) <= 10000 or len({(i["root"], i["relative"]) for i in items}) != len(items):
        raise Refused("Empty or duplicate source selection")
    if len(json.dumps(plan, ensure_ascii=False, indent=2).encode()) > 16 * 1024**2:
        raise Refused("Plan too large; leave journal headroom and split the selection")
    if sum(i["identity"]["size"] for i in items) > plan["max_bytes"]:
        raise Refused("Plan exceeds cap")
    if not 1 <= len(plan["archives"]) <= 64:
        raise Refused("Invalid archive count")
    for item in items:
        validate_source(item, plan["min_age_days"], plan.get("keep", []))


def read_run(state: Path, run: str) -> tuple[Path, Json]:
    from .engine import read_run as read_journal
    directory, journal = read_journal(state, run)
    check_plan(journal["plan"], run, expired_ok=True)
    return directory, journal


def apply(plan: Json, approval: str, *, quiescent: bool, acknowledge_risk: bool) -> Json:
    check_plan(plan, approval)
    if not quiescent or not acknowledge_risk:
        raise Refused("Stop writers and explicitly acknowledge the reviewed history/continuation risk")
    state = Path(plan["state_dir"])
    idle_check(plan["archives"])
    with locked_state(state), checked_archives(plan):
        directory = run_path(state, plan["hash"])
        if directory.exists():
            raise Refused("Run already exists; verify/restore it instead of replaying deletion")
        for item in plan["items"]:
            if (Path(item["root"]) / item["relative"]).is_relative_to(state):
                raise Refused("Cannot remove a file inside the state directory")
            with candidate_fd(item) as fd:
                check_header(fd, item)
                if file_hash(fd) != item["sha256"]:
                    raise Refused("Source changed after review")
        idle_check(plan["items"])
        directory.mkdir(mode=0o700)
        sync_dir(state)
        durable_directory_chain(directory)
        for binding in plan["archives"]:
            with candidate_fd(binding) as fd:
                os.fsync(fd)
            durable_directory_chain(Path(binding["root"]))
        devices = {str(Path(i["root"])) for i in plan["items"]}
        before = {root: shutil.disk_usage(root).free for root in devices}
        journal: Json = {"schema": 1, "plan": plan, "status": "removing", "events": [], "free_before": before}
        journal_save(directory, journal)
        try:
            for index, item in enumerate(plan["items"]):
                event = {"index": index, "status": "intent"}
                journal["events"].append(event)
                journal_save(directory, journal)
                # Archive descriptors stay open; verify path identity again immediately before unlink.
                binding = plan["archives"][item["backup"]["archive_index"]]
                with candidate_fd(binding), candidate_fd(item, allow_unlinked=True) as fd:
                    if file_hash(fd) != item["sha256"]:
                        raise Refused("Source changed immediately before removal")
                    with parent_fd(item["root"], item["relative"]) as (parent, name):
                        if identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != item["identity"]:
                            raise Refused("Source path changed before unlink")
                        os.unlink(name, dir_fd=parent)
                        os.fsync(parent)
                event["status"] = "removed"
                journal_save(directory, journal)
            journal["status"] = "removed"
        except BaseException:
            journal["status"] = "interrupted"
            journal_save(directory, journal)
            raise
        journal["deleted_logical_bytes"] = sum(i["identity"]["size"] for i in plan["items"])
        journal["observed_free_delta_by_root"] = {root: shutil.disk_usage(root).free - free for root, free in before.items()}
        journal_save(directory, journal)
        return {"run": plan["hash"], "status": "removed", "files": len(plan["items"]),
                "deleted_logical_bytes": journal["deleted_logical_bytes"],
                "observed_free_delta_by_root": journal["observed_free_delta_by_root"],
                "archive_retained": True, "harness_resume_verified": False,
                "note": "Free-space changes include unrelated writes and filesystem accounting; do not sum roots on one volume."}


def source_matches(item: Json) -> bool:
    """Restored files have a new inode; require bytes, mode and mtime, not the old inode."""
    with parent_fd(item["root"], item["relative"]) as (parent, name):
        s = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_size != item["identity"]["size"]
                or s.st_mtime_ns != item["identity"]["mtime_ns"]
                or stat.S_IMODE(s.st_mode) != (stat.S_IMODE(item["identity"]["mode"]) & 0o777)):
            return False
        current = {**item, "identity": identity(s)}
        with candidate_fd(current) as fd:
            return file_hash(fd) == item["sha256"]


def verify(state: Path, run: str) -> Json:
    with locked_state(state):
        _, journal = read_run(state, run)
        plan = journal["plan"]
        with checked_archives(plan):
            rows = []
            intents = {e["index"] for e in journal["events"]}
            for n, item in enumerate(plan["items"]):
                try:
                    valid = source_matches(item)
                    location = "source" if valid else "conflict"
                except FileNotFoundError:
                    valid, location = n in intents, "archive-only"
                except (Refused, OSError):
                    valid, location = False, "changed"
                rows.append({"index": n, "location": location, "valid": valid})
        return {"run": run, "status": journal["status"], "items": rows,
                "ok": all(r["valid"] for r in rows), "archives_verified": True,
                "harness_resume_verified": False,
                "removed_logical_bytes": sum(plan["items"][r["index"]]["identity"]["size"]
                                             for r in rows if r["valid"] and r["location"] == "archive-only")}


def restore(state: Path, run: str, *, quiescent: bool) -> Json:
    if not quiescent:
        raise Refused("Stop relevant writers before restoring original paths")
    with locked_state(state):
        directory, journal = read_run(state, run)
        plan = journal["plan"]
        idle_check(plan["archives"])
        with checked_archives(plan) as archives:
            pending = []
            intents = {e["index"]: e for e in journal["events"]}
            for n, item in enumerate(plan["items"]):
                event = intents.get(n, {})
                # Recover a crash after no-clobber installation but before temp unlink.
                temp = event.get("restore_temp")
                if temp:
                    if not temp.startswith(".fireworks-restore-") or Path(temp).name != temp:
                        raise Refused("Invalid restore temporary name")
                    with parent_fd(item["root"], item["relative"]) as (parent, name):
                        try:
                            a = os.stat(temp, dir_fd=parent, follow_symlinks=False)
                        except FileNotFoundError:
                            a = None
                        if a is not None:
                            recorded = event.get("restore_temp_identity", {})
                            if (not stat.S_ISREG(a.st_mode) or a.st_uid != os.getuid()
                                    or (a.st_dev, a.st_ino) != (recorded.get("dev"), recorded.get("ino"))):
                                raise Refused("Unrecognized restore temp; preserve it and inspect the journal")
                            try:
                                b = os.stat(name, dir_fd=parent, follow_symlinks=False)
                            except FileNotFoundError:
                                b = None
                            if b is not None:
                                if a.st_ino != b.st_ino or a.st_dev != b.st_dev or a.st_nlink != 2:
                                    raise Refused("Restore temp conflicts with occupied source")
                                current = {**item, "identity": identity(b)}
                                with candidate_fd(current) as fd:
                                    if file_hash(fd) != item["sha256"]:
                                        raise Refused("Interrupted restore bytes changed")
                                os.unlink(temp, dir_fd=parent)
                                os.fsync(parent)
                            elif a.st_nlink != 1:
                                raise Refused("Hardlinked restore temp; preserve it")
                try:
                    if not source_matches(item):
                        raise Refused("Restore conflict; existing source differs, never overwrite")
                except FileNotFoundError:
                    if n not in intents:
                        raise Refused("Source disappeared without a recorded removal intent")
                    pending.append((n, item))
            needed: dict[int, int] = {}
            reusable: dict[int, int] = {}
            for n, item in pending:
                device = Path(item["root"]).stat().st_dev
                needed[device] = needed.get(device, 0) + item["identity"]["size"]
                temp = intents[n].get("restore_temp")
                if temp:
                    with parent_fd(item["root"], item["relative"]) as (parent, _):
                        try:
                            allocated = getattr(os.stat(temp, dir_fd=parent, follow_symlinks=False), "st_blocks", 0) * 512
                            reusable[device] = reusable.get(device, 0) + allocated
                        except FileNotFoundError:
                            pass
            for _, item in pending:
                device = Path(item["root"]).stat().st_dev
                if shutil.disk_usage(item["root"]).free < max(0, needed[device] - reusable.get(device, 0)) + 16 * 1024**2:
                    raise Refused("Insufficient conservative restore headroom")
            journal["status"] = "restoring"
            journal_save(directory, journal)
            for n, item in pending:
                event = intents[n]
                with parent_fd(item["root"], item["relative"]) as (parent, name):
                    temp = event.get("restore_temp")
                    try:
                        s = os.stat(temp, dir_fd=parent, follow_symlinks=False) if temp else None
                    except FileNotFoundError:
                        s = None
                    if s is None:
                        temp = ".fireworks-restore-" + uuid.uuid4().hex
                        event["restore_temp"] = temp
                        journal_save(directory, journal)
                        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                        event["restore_temp_identity"] = {k: identity(os.fstat(fd))[k] for k in ("dev", "ino")}
                    else:
                        fd = os.open(temp, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                    try:
                        recorded = event["restore_temp_identity"]
                        opened = os.fstat(fd)
                        if (opened.st_dev, opened.st_ino, opened.st_nlink) != (recorded["dev"], recorded["ino"], 1):
                            raise Refused("Restore temp changed before reuse")
                        journal_save(directory, journal)
                        complete = opened.st_size == item["identity"]["size"] and file_hash(fd) == item["sha256"]
                        if not complete:
                            # A previous attempt may already have restored read-only permissions.
                            # Change only our recorded temp inode, never an occupied source path.
                            os.fchmod(fd, 0o600)
                            writable = os.open(temp, os.O_WRONLY | os.O_NOFOLLOW, dir_fd=parent)
                            os.close(fd)
                            fd = writable
                            reopened = os.fstat(fd)
                            if (reopened.st_dev, reopened.st_ino, reopened.st_nlink) != (recorded["dev"], recorded["ino"], 1):
                                raise Refused("Restore temp changed before writing")
                            os.ftruncate(fd, 0)
                            binding = item["backup"]
                            h = hashlib.sha256()
                            count = 0
                            with os.fdopen(fd, "wb", closefd=False) as out, archives[binding["archive_index"]].open(binding["member"]) as src:
                                while block := src.read(1024**2):
                                    count += len(block)
                                    if count > item["identity"]["size"]:
                                        raise Refused("Restore exceeded approved size")
                                    h.update(block)
                                    out.write(block)
                            if count != item["identity"]["size"] or h.hexdigest() != item["sha256"]:
                                raise Refused("Restored content mismatch; preserve archive")
                        os.fchmod(fd, stat.S_IMODE(item["identity"]["mode"]) & 0o777)
                        ns = item["identity"]["mtime_ns"]
                        os.utime(fd, ns=(ns, ns))
                        os.fsync(fd)
                        os.link(temp, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                        os.fsync(parent)
                        os.unlink(temp, dir_fd=parent)
                        os.fsync(parent)
                    finally:
                        os.close(fd)
                event["status"] = "restored"
                journal_save(directory, journal)
            journal["status"] = "restored"
            journal_save(directory, journal)
        return {"run": run, "status": "restored", "files": len(pending), "harness_resume_verified": False}
