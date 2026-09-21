"""Read-only discovery. Unknown objects stay protected."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import time
from typing import Any

from .common import Json, Refused, digest, identity

POLICY = "conservative-files-v1"
KINDS = ("codex", "claude", "project")
PROTECTED = {"memory", "memories", "agent-memory", "skills", "plugins", ".git",
             "node_modules", ".venv", "venv"}


def classify(root: Path, rel: str, kind: str) -> tuple[str, str]:
    p = Path(rel)
    if any(x in PROTECTED for x in p.parts):
        return "protected", "source/configuration/memory/dependency store"
    if p.name.startswith(".env") or p.suffix in {".sqlite", ".db"} or p.name.endswith(("-wal", "-shm")):
        return "protected", "credentials or application state"
    if kind == "codex":
        if p.parts[0] in {"sessions", "archived_sessions"} and p.suffix == ".jsonl":
            return "session", "transcript backup only; resume dependencies unverified"
        if p.parts[0] in {"log", "logs"} and p.suffix == ".log":
            return "log", "known harness diagnostic log"
        if p.parts[0] == "worktrees":
            return "worktree", "use harness/Git lifecycle; never remove automatically"
    if kind == "claude":
        if p.parts[0] == "projects" and (p.suffix == ".jsonl" or "tool-results" in p.parts):
            return "session", "session/tool result backup only; resume dependencies unverified"
        if p.parts[0] == "debug" and p.suffix in {".txt", ".log"}:
            return "log", "known harness diagnostic log"
        if p.parts[0] == "file-history":
            return "checkpoint", "checkpoint restore data"
    if kind == "project" and p.suffix == ".pyc" and "__pycache__" in p.parts:
        try:
            source = Path(importlib.util.source_from_cache(str(root / p)))
            if source.is_file() and not source.is_symlink():
                return "bytecode", "Python bytecode with existing source; Git checked at plan/apply"
        except ValueError:
            pass
    if p.suffix.lower() in {".png", ".jpg", ".webp", ".mp4", ".pdf", ".svg"}:
        return "asset", "may be the only deliverable; retain"
    return "protected", "unknown ownership or recovery requirements"


def roots_default() -> list[tuple[str, Path]]:
    return [("codex", Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex")))),
            ("claude", Path(os.getenv("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))))]


def scan(roots: list[tuple[str, Path]], *, min_age_days: int = 30,
         max_files: int = 200000, keep: list[str] | None = None) -> Json:
    if min_age_days < 1 or max_files < 1:
        raise Refused("Age and file limit must be positive")
    now = time.time()
    items: list[Json] = []
    errors: list[Json] = []
    root_rows: list[Json] = []
    seen: set[tuple[int, int]] = set()
    complete = True
    for kind, supplied in roots:
        if kind not in KINDS:
            raise Refused("Unknown adapter")
        root = supplied.expanduser().resolve(strict=True)
        if root == Path("/") or root == Path.home().resolve():
            raise Refused("Choose a harness or project root, not / or HOME")
        rs = root.stat()
        if not root.is_dir():
            raise Refused("Root must be a directory")
        root_rows.append({"path": str(root), "kind": kind, "dev": rs.st_dev, "ino": rs.st_ino})

        def onerror(error: OSError) -> None:
            errors.append({"root": str(root), "error": type(error).__name__})

        for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
            parent = Path(directory)
            dirs.sort()
            files.sort()
            # Keep third-party dependencies bounded; aggregate pruning is disclosed.
            for d in list(dirs):
                child = parent / d
                try:
                    if child.is_symlink() or child.stat().st_dev != rs.st_dev or d in {
                        ".git", "node_modules", ".venv", "venv", ".fireworks-vibe-cleaner"
                    }:
                        dirs.remove(d)
                        errors.append({"path": str(child), "error": "skipped_boundary_or_dependency"})
                except OSError:
                    dirs.remove(d)
                    errors.append({"path": str(child), "error": "unreadable_directory"})
            for name in files:
                if len(items) >= max_files:
                    complete = False
                    break
                path = parent / name
                try:
                    s = path.lstat()
                    rel = str(path.relative_to(root))
                    category, reason = classify(root, rel, kind)
                    age = max(0.0, (now - s.st_mtime) / 86400)
                    allowed = category in {"log", "bytecode"} and age >= min_age_days
                    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_dev != rs.st_dev:
                        allowed, reason = False, "nonregular, hardlinked or different volume"
                    if any(path.match(pattern) for pattern in (keep or [])):
                        allowed, reason = False, "user keep rule"
                    key = (s.st_dev, s.st_ino)
                    allocated = getattr(s, "st_blocks", 0) * 512 if key not in seen else 0
                    seen.add(key)
                    items.append({"id": digest([str(root), rel])[:20], "root": str(root),
                                  "relative": rel, "adapter": kind, "category": category,
                                  "identity": identity(s), "allocated_bytes": allocated,
                                  "age_days": round(age, 2), "eligible": allowed,
                                  "reason": reason, "active_state": "unknown"})
                except OSError:
                    errors.append({"path": str(path), "error": "unreadable_file"})
            if not complete:
                break
        if not complete:
            break
    return {"schema": 1, "policy": POLICY, "created_at": now, "roots": root_rows,
            "min_age_days": min_age_days, "keep": keep or [], "complete": complete and not errors,
            "errors": errors, "items": items, "summary": summarize(items)}


def summarize(items: list[Json]) -> Json:
    categories: dict[str, Any] = {}
    for item in items:
        row = categories.setdefault(item["category"], {"files": 0, "logical_bytes": 0,
                                                       "allocated_bytes": 0})
        row["files"] += 1
        row["logical_bytes"] += item["identity"]["size"]
        row["allocated_bytes"] += item["allocated_bytes"]
    return {"files": len(items), "categories": categories,
            "eligible_files": sum(bool(i["eligible"]) for i in items),
            "eligible_allocated_bytes": sum(i["allocated_bytes"] for i in items if i["eligible"]),
            "note": "Eligible is preliminary; not authorization or verified reclaimable space."}


def bytecode_git_check(item: Json) -> None:
    """Require a real repository, a tracked source, and an ignored untracked cache."""
    if item["category"] != "bytecode":
        return
    root = Path(item["root"])
    source = Path(importlib.util.source_from_cache(str(root / item["relative"])))
    commands = [(["ls-files", "--error-unmatch", "--", str(source)], 0),
                (["ls-files", "--error-unmatch", "--", item["relative"]], 1),
                (["check-ignore", "--quiet", "--", item["relative"]], 0)]
    for args, expected in commands:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=10)
        if result.returncode != expected:
            raise Refused("Bytecode must be Git-ignored, untracked, with tracked source")
