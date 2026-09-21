"""Verified file snapshots; never remove source or claim harness resume support."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile
import zipfile

from .common import Json, Refused, candidate_fd, load, write


def backup(inventory: Json, ids: list[str], output: Path, *, max_bytes: int) -> Json:
    items = [i for i in inventory["items"] if i["id"] in ids]
    if not ids or len(items) != len(ids) or len(set(ids)) != len(ids):
        raise Refused("Select existing unique IDs")
    if any(i["category"] not in {"session", "checkpoint", "asset"} for i in items):
        raise Refused("Backup supports transcripts, checkpoints and assets only")
    total = sum(i["identity"]["size"] for i in items)
    if max_bytes < 1 or total > max_bytes:
        raise Refused("Backup exceeds explicit byte cap")
    output = output.absolute()
    if output.exists() or output.is_symlink() or output.with_suffix(output.suffix + ".manifest.json").exists():
        raise Refused("Backup destination exists")
    if not output.parent.exists():
        raise Refused("Create a private local backup directory first")
    parent = output.parent.stat()
    if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077:
        raise Refused("Backup directory must be private (0700)")
    if any(i["identity"]["dev"] != parent.st_dev for i in items):
        raise Refused("Cross-volume backup requires encryption; not supported in v0.1")
    if shutil.disk_usage(output.parent).free < total + 16 * 1024**2:
        raise Refused("Insufficient conservative backup headroom")
    fd, tmp = tempfile.mkstemp(prefix=".vibe-backup-", dir=output.parent)
    os.close(fd)
    rows = []
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for n, item in enumerate(items):
                h = hashlib.sha256()
                member = str(n)
                with candidate_fd(item) as source, archive.open(member, "w", force_zip64=True) as dest:
                    while block := os.read(source, 1024 * 1024):
                        dest.write(block)
                        h.update(block)
                rows.append({"member": member, "sha256": h.hexdigest(), "item": item})
        with zipfile.ZipFile(tmp) as archive:
            for row in rows:
                h = hashlib.sha256()
                with archive.open(row["member"]) as source:
                    while block := source.read(1024 * 1024):
                        h.update(block)
                if h.hexdigest() != row["sha256"]:
                    raise Refused("Backup readback mismatch")
        with open(tmp, "rb") as stream:
            os.fsync(stream.fileno())
        os.link(tmp, output)
        manifest = {"schema": 1, "archive": output.name, "files": rows,
                    "status": "bytes-verified", "source_removed": False, "harness_resume_verified": False}
        write(output.with_suffix(output.suffix + ".manifest.json"), manifest)
        return {"status": "bytes-verified", "files": len(items), "archive": str(output),
                "source_removed": False, "harness_resume_verified": False}
    finally:
        os.unlink(tmp)


def extract(output: Path, destination: Path, *, max_bytes: int = 1024**3) -> Json:
    manifest = load(output.with_suffix(output.suffix + ".manifest.json"))
    if destination.exists() or destination.is_symlink():
        raise Refused("Extraction destination must not exist")
    rows = manifest["files"]
    if len({r["member"] for r in rows}) != len(rows):
        raise Refused("Duplicate backup members")
    total = 0
    for row in rows:
        member = row["member"]
        if not isinstance(member, str) or not member.isascii() or not member.isdecimal():
            raise Refused("Unsafe archive member")
        size = row["item"]["identity"]["size"]
        if type(size) is not int or size < 0:
            raise Refused("Invalid archive member size")
        total += size
    if max_bytes < 1 or total > max_bytes:
        raise Refused("Extraction exceeds output cap")
    if shutil.disk_usage(destination.parent).free < total + 16 * 1024**2:
        raise Refused("Insufficient extraction headroom")
    destination.mkdir(mode=0o700)
    with zipfile.ZipFile(output) as archive:
        if sorted(archive.namelist()) != sorted(r["member"] for r in rows):
            raise Refused("Archive member mismatch")
        for row in rows:
            member = row["member"]
            if not isinstance(member, str) or not member.isascii() or not member.isdecimal():
                raise Refused("Unsafe archive member")
            expected = row["item"]["identity"]["size"]
            if archive.getinfo(member).file_size != expected:
                raise Refused("Archive size mismatch")
            h = hashlib.sha256()
            target = destination / member
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as dest, archive.open(member) as src:
                count = 0
                while block := src.read(1024 * 1024):
                    count += len(block)
                    if count > expected:
                        raise Refused("Archive expansion limit exceeded")
                    h.update(block)
                    dest.write(block)
            if h.hexdigest() != row["sha256"]:
                raise Refused("Extracted hash mismatch; output retained for inspection")
    return {"status": "extracted-and-verified", "files": len(rows),
            "harness_resume_verified": False, "note": "Numbered copies only; no live harness state modified."}
