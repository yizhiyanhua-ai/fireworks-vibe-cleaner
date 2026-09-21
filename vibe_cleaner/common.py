"""Small POSIX primitives. Never follow a candidate's symbolic links."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Iterator

Json = dict[str, Any]


class Refused(RuntimeError):
    """A safety precondition was not established."""


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def load(path: Path) -> Json:
    if path.stat().st_size > 64 * 1024 * 1024:
        raise Refused("JSON exceeds 64 MiB limit")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise Refused("Expected a JSON object")
    return value


def write(path: Path, value: Json, *, overwrite: bool = False) -> None:
    """Private JSON, durable atomic installation; refuse accidental overwrite."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".vibe-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(name, path)
        else:
            os.link(name, path, follow_symlinks=False)
        sync_dir(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def identity(s: os.stat_result) -> Json:
    return {"dev": s.st_dev, "ino": s.st_ino, "size": s.st_size,
            "mtime_ns": s.st_mtime_ns, "mode": s.st_mode, "nlink": s.st_nlink}


def file_hash(fd: int) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    h = hashlib.sha256()
    while block := os.read(fd, 1024 * 1024):
        h.update(block)
    return h.hexdigest()


@contextlib.contextmanager
def parent_fd(root: str, relative: str) -> Iterator[tuple[int, str]]:
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in (".", "..") for p in parts):
        raise Refused("Unsafe relative path")
    # Walk absolute ancestors too: a changed root symlink is not silently resolved.
    if not Path(root).is_absolute():
        raise Refused("Root must be absolute")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in (*Path(root).parts[1:], *parts[:-1]):
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd, parts[-1]
    finally:
        os.close(fd)


@contextlib.contextmanager
def candidate_fd(item: Json, *, allow_unlinked: bool = False) -> Iterator[int]:
    with parent_fd(item["root"], item["relative"]) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            s = os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or identity(s) != item["identity"]:
                raise Refused("Candidate changed or is not a regular file")
            yield fd
            after = identity(os.fstat(fd))
            expected = item["identity"]
            if allow_unlinked and after["nlink"] == 0:
                expected = dict(expected, nlink=0)
            if after != expected:
                raise Refused("Candidate changed during read")
        finally:
            os.close(fd)
