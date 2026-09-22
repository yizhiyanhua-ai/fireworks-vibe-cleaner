"""Bounded local evidence for advice. Never modifies source files or harness state."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import time
import zipfile
import zlib

from .common import Json, Refused, candidate_fd
from .history import UUID, header_parent
from .scan import transcript_id
from .sessions import file_ref

RECOVERY_NEEDS = {"unknown", "archive-copy", "native-resume"}


def index_facts(items: list[Json], min_age_days: int) -> dict[str, Json]:
    """Selected IDs and incident edges in one fresh read-only snapshot per root.

    No-indexed-links is a scoped observation, not proof of complete lineage.
    Unrelated transcript files are never opened. Unsupported adapters stay unknown.
    """
    if len(items) > 100 or min_age_days < 1:
        raise Refused("Selected index lookup accepts at most 100 files and positive retention")
    result: dict[str, Json] = {i["id"]: {"pin": "unknown", "links": "unknown", "archived": "unknown",
                         "recent_use": "unknown", "current_context": "unknown"} for i in items}
    groups: dict[str, list[Json]] = {}
    for item in items:
        if item["adapter"] == "codex" and item["category"] == "session":
            groups.setdefault(item["root"], []).append(item)
    now = time.time()
    current = os.getenv("CODEX_THREAD_ID", "")
    current_root = Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
    for root_string, selected in groups.items():
        root = Path(root_string)
        thread_items = {transcript_id(i["relative"], "codex"): i for i in selected}
        if None in thread_items or len(thread_items) != len(selected):
            continue
        ids = list(thread_items)
        placeholders = ",".join("?" for _ in ids)
        database = root / "state_5.sqlite"
        db = None
        try:
            databases = list(root.glob("state_*.sqlite"))
            if len(databases) != 1 or databases[0] != database:
                continue
            before = database.lstat()
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid()
                    or root.resolve() != root):
                continue
            db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2)
            db.row_factory = sqlite3.Row
            deadline = time.monotonic() + 2
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            columns = {r[1] for r in db.execute("PRAGMA table_info(threads)")}
            edge_columns = {r[1] for r in db.execute("PRAGMA table_info(thread_spawn_edges)")}
            required = {"id", "rollout_path", "updated_at", "updated_at_ms", "archived", "is_pinned", "source"}
            if not required <= columns or not {"parent_thread_id", "child_thread_id", "status"} <= edge_columns:
                continue
            records = list(db.execute(f"SELECT id, rollout_path, updated_at, updated_at_ms, archived, is_pinned, source "
                                      f"FROM threads WHERE id IN ({placeholders}) LIMIT 101", ids))
            if len({r["id"] for r in records}) != len(records):
                continue
            edges = list(db.execute(f"SELECT parent_thread_id, child_thread_id, status FROM thread_spawn_edges "
                                    f"WHERE parent_thread_id IN ({placeholders}) OR child_thread_id IN ({placeholders}) LIMIT 1001", ids + ids))
            if len(edges) > 1000:
                continue
            after = database.lstat()
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                continue
            related = {v for edge in edges for v in (edge["parent_thread_id"], edge["child_thread_id"])}
            for row in records:
                item = thread_items[row["id"]]
                assert item is not None
                observed = result[item["id"]]
                known_current = bool(UUID.fullmatch(current) and root == current_root)
                observed["current_context"] = "current" if known_current and row["id"] == current else "other" if known_current else "unknown"
                # Keep positive protection evidence even if other fields are bad.
                if row["is_pinned"] == 1:
                    observed["pin"] = "pinned"
                if row["id"] in related:
                    observed["links"] = "linked"
                if row["is_pinned"] not in (0, 1) or row["archived"] not in (0, 1):
                    continue
                if row["rollout_path"] != str(Path(item["root"]) / item["relative"]):
                    continue
                if Path(item["relative"]).parts[0] != ("archived_sessions" if row["archived"] else "sessions"):
                    continue
                if not isinstance(row["source"], str):
                    continue
                try:
                    with candidate_fd(item) as fd:
                        parent = header_parent(fd, row["id"], row["source"])
                    seconds, millis = row["updated_at"], row["updated_at_ms"]
                    if type(seconds) is not int or seconds <= 0:
                        continue
                    if millis is not None and (type(millis) is not int or millis <= 0 or abs(seconds - millis / 1000) >= 1):
                        continue
                    updated = seconds if millis is None else max(seconds, millis / 1000)
                    if updated > now + 60:
                        continue
                    observed.update(pin="pinned" if row["is_pinned"] else "unpinned",
                                    links="linked" if parent or row["id"] in related else "no_indexed_links",
                                    archived="yes" if row["archived"] else "no",
                                    recent_use="recent" if now - updated < min_age_days * 86400 else "old",
                                    observed_at=now, scope="selected-index-snapshot")
                except (Refused, OSError, ValueError, KeyError):
                    continue
        except (OSError, ValueError, sqlite3.Error):
            continue
        finally:
            if db is not None:
                db.close()
    return result


def activity(items: list[Json]) -> dict[str, str]:
    """One lsof per 32 files; unknown output never means idle."""
    if len(items) > 100:
        raise Refused("Selected activity lookup accepts at most 100 files")
    result = {i["id"]: "unknown" for i in items}
    if not shutil.which("lsof"):
        return result
    for start in range(0, len(items), 32):
        batch = items[start:start + 32]
        paths: dict[str, str] = {}
        try:
            for item in batch:
                with candidate_fd(item):
                    pass
                path = str(Path(item["root"]) / item["relative"])
                if any(c in path for c in "\n\r\x00"):
                    raise Refused("Ambiguous lsof path")
                if path in paths:
                    raise Refused("Duplicate activity path")
                paths[path] = item["id"]
            response = subprocess.run(["lsof", "-nP", "-F", "pn", "--", *paths],
                                      capture_output=True, timeout=10)
            if response.stderr or len(response.stdout) > 1024**2:
                continue
            opened: set[str] = set()
            if response.returncode == 1 and not response.stdout:
                pass
            elif response.returncode == 0 and response.stdout:
                for line in response.stdout.decode("utf-8", errors="strict").splitlines():
                    if re.fullmatch(r"p[0-9]+", line):
                        continue
                    if not line.startswith("n") or line[1:] not in paths:
                        raise Refused("Unmapped lsof output")
                    opened.add(paths[line[1:]])
                if not opened:
                    continue
            else:
                continue
            # Identity must remain unchanged across the entire observation.
            for item in batch:
                with candidate_fd(item):
                    pass
            result.update({i["id"]: "open" if i["id"] in opened else "no_open_handles" for i in batch})
        except (Refused, OSError, ValueError, subprocess.TimeoutExpired):
            continue
    return result


def _hash_stream(stream, expected: int) -> str:
    digest = hashlib.sha256()
    count = 0
    while block := stream.read(min(1024**2, expected - count + 1)):
        count += len(block)
        if count > expected:
            raise Refused("Selected backup expansion exceeds its byte budget")
        digest.update(block)
    if count != expected:
        raise Refused("Selected backup has incomplete bytes")
    return digest.hexdigest()


def backups(items: list[Json], archives: list[Path], *, max_verify_bytes: int = 0) -> Json:
    """References are not proof. Optional budget counts source + expanded member bytes.

    Verifies selected members only, never claims the whole ZIP or native resume.
    Evidence is made fresh in this call, never loaded from caller-supplied flags.
    """
    if not 0 <= max_verify_bytes <= 32 * 1024**3 or len(archives) > 64 or len(items) > 100:
        raise Refused("At most 64 archives and 0..32 GiB verification read budget")
    paths = [p.expanduser().absolute() for p in archives]
    if len(set(paths)) != len(paths):
        raise Refused("Duplicate supplied archive")
    rows: dict[str, Json] = {i["id"]: {"status": "no_match_supplied" if paths else "not_checked"} for i in items}
    lookup = {(i["root"], i["relative"]): i for i in items}
    matches: dict[str, list[Json]] = {i["id"]: [] for i in items}
    references: list[Json] = []
    ambiguous_ids: set[str] = set()
    manifest_bytes = 0
    errors = 0
    for path in paths:
        try:
            binding = file_ref(path)
            manifest_ref = file_ref(path.with_suffix(path.suffix + ".manifest.json"))
            manifest_bytes += manifest_ref["identity"]["size"]
            if manifest_bytes > 16 * 1024**2:
                raise Refused("Supplied manifests exceed 16 MiB total")
            with candidate_fd(binding):
                pass
            with candidate_fd(manifest_ref) as fd, os.fdopen(os.dup(fd), "rb") as stream:
                manifest = json.load(stream)
            if (manifest.get("schema") != 1 or manifest.get("archive") != path.name
                    or not isinstance(manifest.get("files"), list) or len(manifest["files"]) > 10000):
                raise Refused("Unknown backup manifest schema")
            members = [r["member"] for r in manifest["files"]]
            if any(not isinstance(m, str) or not m.isascii() or not m.isdecimal() for m in members):
                raise Refused("Unknown backup member format")
            if len(members) != len(set(members)):
                raise Refused("Ambiguous backup members")
            item_keys = [(r["item"]["root"], r["item"]["relative"]) for r in manifest["files"]]
            if any(not isinstance(root, str) or not isinstance(relative, str) for root, relative in item_keys):
                raise Refused("Unknown manifest source mapping")
            seen_keys: set[tuple[str, str]] = set()
            for key in item_keys:
                if key in seen_keys and key in lookup:
                    ambiguous_ids.add(lookup[key]["id"])
                seen_keys.add(key)
            archive_index = len(references)
            references.append({"binding": binding, "manifest": manifest_ref})
            for row in manifest["files"]:
                original = row["item"]
                item = lookup.get((original["root"], original["relative"]))
                if item is None:
                    continue
                if (not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
                        or original["identity"]["size"] != item["identity"]["size"]
                        or item["identity"]["dev"] != binding["identity"]["dev"]):
                    rows[item["id"]] = {"status": "invalid"}
                    continue
                matches[item["id"]].append({"archive_index": archive_index, "member": row["member"],
                                             "declared_sha256": row["sha256"]})
        except (Refused, OSError, ValueError, KeyError, TypeError, AttributeError):
            errors += 1
    bytes_read = 0
    verified_at = time.time()
    for item in items:
        ident = item["id"]
        found = matches[ident]
        if len(found) > 1 or ident in ambiguous_ids:
            rows[ident] = {"status": "ambiguous"}
            continue
        if not found:
            if errors and rows[ident]["status"] == "no_match_supplied":
                rows[ident] = {"status": "unknown"}
            continue
        match = found[0]
        ref = references[match["archive_index"]]
        binding = ref["binding"]
        # These references stay local. The provider sees only the status enum.
        rows[ident] = {"status": "manifest_only", "archive": str(Path(binding["root"]) / binding["relative"]),
                       "member": match["member"]}
        expected = item["identity"]["size"]
        if 2 * expected > max_verify_bytes - bytes_read:
            rows[ident]["verification_deferred"] = "byte_budget"
            continue
        # Reserve the whole selected budget even on failure; never retry silently.
        bytes_read += 2 * expected
        try:
            with candidate_fd(ref["manifest"]), candidate_fd(binding) as archive_fd, candidate_fd(item) as source_fd:
                with os.fdopen(os.dup(source_fd), "rb") as stream:
                    source_sha = _hash_stream(stream, expected)
                with os.fdopen(os.dup(archive_fd), "rb") as stream, zipfile.ZipFile(stream) as archive:
                    names = archive.namelist()
                    if len(names) > 10000 or len(names) != len(set(names)):
                        raise Refused("Ambiguous ZIP members")
                    info = archive.getinfo(match["member"])
                    if (info.is_dir() or info.file_size != expected or info.flag_bits & 1
                            or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)):
                        raise Refused("Unsupported selected ZIP member")
                    with archive.open(info) as member_stream:
                        backup_sha = _hash_stream(member_stream, expected)
                if source_sha != backup_sha or source_sha != match["declared_sha256"]:
                    raise Refused("Current source and backup bytes differ")
            with candidate_fd(item), candidate_fd(binding):
                pass
            rows[ident].update(status="selected_bytes_verified", sha256=source_sha, verified_at=verified_at,
                               source_identity=item["identity"], archive_identity=binding["identity"],
                               verification_budget_bytes=2 * expected)
        except (Refused, OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile, RuntimeError, zlib.error):
            rows[ident]["status"] = "invalid"
    return {"items": rows, "archives_supplied": len(paths), "manifest_errors": errors,
            "verification_budget_used_bytes": bytes_read, "max_verify_bytes": max_verify_bytes,
            "whole_archives_verified": False, "native_resume_verified": False}
