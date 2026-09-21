"""Plan-bound, regular-file-only quarantine, recovery, and purge."""

from __future__ import annotations

import contextlib
import fcntl
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time
from typing import Iterator

from .common import (Json, Refused, candidate_fd, digest, file_hash, identity, load,
                     parent_fd, sync_dir, write)
from .scan import POLICY, bytecode_git_check, classify


def seal(plan: Json) -> str:
    return digest({k: v for k, v in plan.items() if k != "hash"})


def make_plan(inventory: Json, ids: list[str], state: Path, *, max_bytes: int,
              ttl: int = 3600) -> Json:
    if not ids or len(ids) != len(set(ids)) or not 1 <= ttl <= 86400 or max_bytes < 1:
        raise Refused("Select unique candidate IDs, positive cap, TTL <= 24 hours")
    selected = [dict(i) for i in inventory["items"] if i["id"] in ids]
    if len(selected) != len(ids):
        raise Refused("Unknown candidate ID")
    if inventory.get("policy") != POLICY:
        raise Refused("Unknown inventory policy")
    for item in selected:
        validate_candidate(item, inventory["min_age_days"], inventory.get("keep", []))
        with candidate_fd(item) as fd:
            item["sha256"] = file_hash(fd)
    total = sum(i["identity"]["size"] for i in selected)
    if total > max_bytes:
        raise Refused("Selected bytes exceed cap")
    plan = {"schema": 1, "policy": POLICY, "action": "quarantine", "created_at": time.time(),
            "expires_at": time.time() + ttl, "max_bytes": max_bytes,
            "state_dir": str(state.expanduser().resolve()), "items": selected,
            "min_age_days": inventory["min_age_days"], "keep": inventory.get("keep", []),
            "expected_immediate_reclaimed_bytes": 0}
    plan["hash"] = seal(plan)
    return plan


def validate_candidate(item: Json, min_age: int, keep: list[str]) -> None:
    root = Path(item["root"])
    path = root / item["relative"]
    category, _ = classify(root, item["relative"], item["adapter"])
    if not item.get("eligible") or category not in {"log", "bytecode"} or category != item["category"]:
        raise Refused("Protected object cannot enter executor")
    if min_age < 1 or (time.time_ns() - item["identity"]["mtime_ns"]) / 86400e9 < min_age:
        raise Refused("Retention period not met")
    if item["identity"]["nlink"] != 1 or any(path.match(p) for p in keep):
        raise Refused("Hardlink or keep rule")
    bytecode_git_check(item)


def idle_check(items: list[Json]) -> None:
    """Fail closed on uncertain lsof output. Operator must also quiesce writers."""
    if not shutil.which("lsof"):
        raise Refused("lsof is required for writes")
    for item in items:
        path = str(Path(item["root"]) / item["relative"])
        result = subprocess.run(["lsof", "-nP", "-F", "p", "--", path],
                                capture_output=True, timeout=10)
        if result.returncode != 1 or result.stdout or result.stderr:
            raise Refused("File is open, or open-handle inspection is inconclusive")


@contextlib.contextmanager
def locked_state(state: Path) -> Iterator[None]:
    if os.name != "posix":
        raise Refused("Write operations require POSIX")
    if state.is_symlink() or state.resolve() != state.absolute():
        raise Refused("State path changed or contains a symlink")
    missing = []
    ancestor = state
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    for path in reversed(missing):
        path.mkdir(mode=0o700)
        sync_dir(path.parent)
    s = state.stat()
    if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) & 0o077:
        raise Refused("State directory must be owned by you and mode 0700")
    fd = os.open(state / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError as exc:
        raise Refused("Another executor is using this state directory") from exc
    finally:
        os.close(fd)


def state_usage(state: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(state, followlinks=False):
        if any((Path(root) / d).is_symlink() for d in dirs):
            raise Refused("Unexpected state symlink")
        for name in files:
            s = (Path(root) / name).lstat()
            if not stat.S_ISREG(s.st_mode):
                raise Refused("Unexpected state object")
            total += s.st_size
    return total


def run_path(state: Path, run: str) -> Path:
    if len(run) != 64 or any(c not in "0123456789abcdef" for c in run):
        raise Refused("Invalid run identifier")
    return state / run


def check_plan(plan: Json, approval: str) -> None:
    if plan.get("schema") != 1 or plan.get("policy") != POLICY or plan.get("action") != "quarantine":
        raise Refused("Unsupported plan")
    if plan.get("hash") != seal(plan) or approval != plan["hash"]:
        raise Refused("Approval must equal the exact reviewed plan hash")
    if time.time() > plan["expires_at"]:
        raise Refused("Plan expired; rescan and review")
    if not plan["items"] or len({(i["root"], i["relative"]) for i in plan["items"]}) != len(plan["items"]):
        raise Refused("Empty or duplicated plan")
    if sum(i["identity"]["size"] for i in plan["items"]) > plan["max_bytes"]:
        raise Refused("Plan exceeds cap")


def journal_save(directory: Path, journal: Json) -> None:
    write(directory / "journal.json", journal, overwrite=True)


def apply(plan: Json, approval: str, *, quiescent: bool, state_cap: int = 1024**3) -> Json:
    check_plan(plan, approval)
    if not quiescent:
        raise Refused("Stop writers and acknowledge --writers-stopped before apply")
    state = Path(plan["state_dir"])
    with locked_state(state):
        directory = run_path(state, plan["hash"])
        if directory.exists():
            raise Refused("Run already exists; verify/restore it, never replay apply")
        if state_usage(state) + sum(i["identity"]["size"] for i in plan["items"]) > state_cap:
            raise Refused("Quarantine capacity exceeded")
        for item in plan["items"]:
            if (Path(item["root"]) / item["relative"]).is_relative_to(state):
                raise Refused("Cannot clean the state directory")
            if item["identity"]["dev"] != state.stat().st_dev:
                raise Refused("Cross-volume quarantine disabled; choose state on source volume")
            validate_candidate(item, plan["min_age_days"], plan.get("keep", []))
            with candidate_fd(item) as fd:
                if file_hash(fd) != item["sha256"]:
                    raise Refused("Content changed since plan")
        idle_check(plan["items"])
        directory.mkdir(mode=0o700)
        sync_dir(state)
        journal: Json = {"schema": 1, "plan": plan, "status": "running", "events": [],
                   "free_before": shutil.disk_usage(state).free}
        journal_save(directory, journal)
        try:
            for index, item in enumerate(plan["items"]):
                target = directory / str(index)
                event = {"index": index, "status": "prepared"}
                journal["events"].append(event)
                journal_save(directory, journal)
                with candidate_fd(item) as fd:
                    if file_hash(fd) != item["sha256"]:
                        raise Refused("Content changed immediately before operation")
                    with parent_fd(item["root"], item["relative"]) as (parent, name):
                        if identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != item["identity"]:
                            raise Refused("Path changed immediately before rename")
                        os.rename(name, target, src_dir_fd=parent)
                        os.fsync(parent)
                    sync_dir(directory)
                    event["status"] = "quarantined"
                    journal_save(directory, journal)
                    if identity(target.lstat()) != item["identity"] or file_hash(fd) != item["sha256"]:
                        raise Refused("Concurrent writer detected; preserve quarantine and inspect")
                idle_check([{**item, "root": str(directory), "relative": str(index)}])
            journal["status"] = "quarantined"
        except BaseException:
            journal["status"] = "interrupted"
            journal_save(directory, journal)
            raise
        journal["free_after"] = shutil.disk_usage(state).free
        journal["immediate_reclaimed_bytes"] = 0
        journal_save(directory, journal)
        return {"run": plan["hash"], "status": journal["status"], "state_dir": str(state),
                "files": len(plan["items"]), "immediate_reclaimed_bytes": 0}


def read_run(state: Path, run: str) -> tuple[Path, Json]:
    directory = run_path(state, run)
    if directory.is_symlink() or directory.resolve() != directory:
        raise Refused("Changed run directory")
    journal = load(directory / "journal.json")
    plan = journal["plan"]
    if plan["hash"] != run or seal(plan) != run or plan["state_dir"] != str(state):
        raise Refused("Journal plan integrity mismatch")
    return directory, journal


def quarantine_item(directory: Path, index: int, item: Json) -> Json:
    return {**item, "root": str(directory), "relative": str(index)}


def verify(state: Path, run: str) -> Json:
    with locked_state(state):
        directory, journal = read_run(state, run)
        rows = []
        for index, item in enumerate(journal["plan"]["items"]):
            target = directory / str(index)
            source = Path(item["root"]) / item["relative"]
            location = "missing"
            valid = False
            try:
                if target.exists() or target.is_symlink():
                    with candidate_fd(quarantine_item(directory, index, item)) as fd:
                        valid = file_hash(fd) == item["sha256"]
                    location = "conflict" if source.exists() or source.is_symlink() else "quarantine"
                elif source.exists() or source.is_symlink():
                    with candidate_fd(item) as fd:
                        valid = file_hash(fd) == item["sha256"]
                    location = "source"
                elif journal["status"] == "purged":
                    location, valid = "purged", True
            except (OSError, Refused):
                location, valid = "changed", False
            rows.append({"index": index, "location": location, "valid": valid})
        return {"run": run, "status": journal["status"], "items": rows,
                "ok": all(x["valid"] and x["location"] != "conflict" for x in rows)}


def restore(state: Path, run: str, *, quiescent: bool) -> Json:
    if not quiescent:
        raise Refused("Stop writers before restore")
    with locked_state(state):
        directory, journal = read_run(state, run)
        if journal["status"] == "purged":
            raise Refused("Permanently purged; cannot restore")
        # Preflight every object before restoring any; never overwrite a new source.
        pending = []
        for index, item in enumerate(journal["plan"]["items"]):
            target = directory / str(index)
            source = Path(item["root"]) / item["relative"]
            if target.exists() or target.is_symlink():
                if source.exists() or source.is_symlink():
                    # Recovery for interruption between link and unlink below.
                    a, b = target.lstat(), source.lstat()
                    if (journal["status"] == "restoring" and a.st_ino == b.st_ino
                            and a.st_dev == b.st_dev and a.st_nlink == 2):
                        expected = dict(item["identity"], nlink=2)
                        with candidate_fd({**quarantine_item(directory, index, item),
                                           "identity": expected}) as fd:
                            if file_hash(fd) != item["sha256"]:
                                raise Refused("Interrupted restore content changed")
                        with parent_fd(item["root"], item["relative"]) as (parent, name):
                            if identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected:
                                raise Refused("Interrupted restore source changed")
                            os.fsync(parent)
                        target.unlink()
                        sync_dir(directory)
                        continue
                    raise Refused("Restore conflict; original path is occupied")
                with candidate_fd(quarantine_item(directory, index, item)) as fd:
                    if file_hash(fd) != item["sha256"]:
                        raise Refused("Quarantine content changed")
                pending.append((index, item))
            else:
                with candidate_fd(item) as fd:
                    if file_hash(fd) != item["sha256"]:
                        raise Refused("Neither a valid original nor quarantine exists")
        idle_check([quarantine_item(directory, index, item) for index, item in pending])
        journal["status"] = "restoring"
        journal_save(directory, journal)
        for index, item in pending:
            target = directory / str(index)
            with candidate_fd(quarantine_item(directory, index, item)) as fd:
                if file_hash(fd) != item["sha256"]:
                    raise Refused("Quarantine changed before restore")
                with parent_fd(item["root"], item["relative"]) as (parent, name):
                    # link is atomic no-clobber; a crash may leave two identical links.
                    os.link(target, name, dst_dir_fd=parent, follow_symlinks=False)
                    expected = dict(item["identity"], nlink=2)
                    if identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected:
                        raise Refused("Restore source changed; preserve both copies")
                    if file_hash(fd) != item["sha256"]:
                        raise Refused("Concurrent writer during restore; preserve both copies")
                    os.fsync(parent)
                    target.unlink()
                    sync_dir(directory)
        journal["status"] = "restored"
        journal_save(directory, journal)
        return {"run": run, "status": "restored", "files": len(pending)}


def purge(state: Path, run: str, approval: str, *, quiescent: bool) -> Json:
    if approval != "purge:" + run or not quiescent:
        raise Refused("Permanent deletion requires --approve purge:<run> and stopped writers")
    with locked_state(state):
        directory, journal = read_run(state, run)
        if journal["status"] not in {"quarantined", "purging"}:
            raise Refused("Only a completed quarantine can be purged")
        targets = []
        for index, item in enumerate(journal["plan"]["items"]):
            target = directory / str(index)
            if not target.exists() and not target.is_symlink() and journal["status"] == "purging":
                continue
            qitem = quarantine_item(directory, index, item)
            with candidate_fd(qitem) as fd:
                if file_hash(fd) != item["sha256"]:
                    raise Refused("Quarantine content changed")
            targets.append(qitem)
        idle_check(targets)
        before = shutil.disk_usage(state).free
        journal["status"] = "purging"
        journal.setdefault("purge_attempts", [])
        attempt: Json = {"free_before": before, "planned_indices": [int(i["relative"]) for i in targets],
                         "completed_indices": []}
        journal["purge_attempts"].append(attempt)
        journal_save(directory, journal)
        for item in targets:
            with candidate_fd(item, allow_unlinked=True) as fd:
                if file_hash(fd) != item["sha256"]:
                    raise Refused("Content changed before purge")
                with parent_fd(item["root"], item["relative"]) as (parent, name):
                    if identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != item["identity"]:
                        raise Refused("Quarantine changed before unlink")
                    os.unlink(name, dir_fd=parent)
                    os.fsync(parent)
            attempt["completed_indices"].append(int(item["relative"]))
            journal_save(directory, journal)
        after = shutil.disk_usage(state).free
        journal["status"] = "purged"
        journal["purge"] = {"observed_free_delta": after - before,
                            "deleted_logical_bytes": sum(i["identity"]["size"] for i in journal["plan"]["items"]),
                            "this_attempt_logical_bytes": sum(i["identity"]["size"] for i in targets),
                            "note": "Volume delta includes unrelated writes and filesystem accounting."}
        journal_save(directory, journal)
        return {"run": run, "status": "purged", **journal["purge"]}
