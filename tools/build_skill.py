#!/usr/bin/env python3
"""Reproducible Skill mirror and release archive from one source tree."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vibe_cleaner import __version__  # noqa: E402

FILES = ["SKILL.md", "README.md", "README.zh.md", "LICENSE", "CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md"]
DIRS = ["vibe_cleaner", "scripts", "agents", "schemas", "docs"]


def sources() -> list[Path]:
    result = [ROOT / f for f in FILES]
    for directory in DIRS:
        result.extend(p for p in (ROOT / directory).rglob("*") if p.is_file()
                      and "__pycache__" not in p.parts and not p.name.startswith("."))
    return sorted(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    mirror = ROOT / "skills/fireworks-vibe-cleaner"
    expected = {str(p.relative_to(ROOT)): p.read_bytes() for p in sources()}
    if args.check:
        actual = {str(p.relative_to(mirror)): p.read_bytes() for p in mirror.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts}
        if actual != expected:
            raise SystemExit("Skill mirror is stale; run python3 tools/build_skill.py")
    else:
        # Only the generated mirror, never user data.
        if mirror.exists():
            shutil.rmtree(mirror)
        for name, content in expected.items():
            target = mirror / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    if args.release:
        out = ROOT / "dist"
        out.mkdir(exist_ok=True)
        target = out / f"fireworks-vibe-cleaner-{__version__}.zip"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(expected.items()):
                info = zipfile.ZipInfo("fireworks-vibe-cleaner/" + name, (2026, 1, 1, 0, 0, 0))
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content)
        (out / "SHA256SUMS").write_text(hashlib.sha256(target.read_bytes()).hexdigest() + "  " + target.name + "\n")
    print(f"Skill distribution verified: {len(expected)} files; version {__version__}")


if __name__ == "__main__":
    main()
