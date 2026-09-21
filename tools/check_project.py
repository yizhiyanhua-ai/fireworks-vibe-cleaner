#!/usr/bin/env python3
"""Cheap consistency checks for the public distribution."""
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
meta = tomllib.loads((ROOT / "pyproject.toml").read_text())
version = meta["project"]["version"]
assert f'__version__ = "{version}"' in (ROOT / "vibe_cleaner/__init__.py").read_text()
assert (ROOT / f"docs/releases/v{version}.md").exists()
for name in ("README.md", "README.zh.md"):
    content = (ROOT / name).read_text()
    assert "README.md" in content and "README.zh.md" in content
    for link in re.findall(r"\]\(([^)]+)\)", content):
        if not link.startswith(("https:", "http:", "#")):
            assert (ROOT / link.split("#")[0]).exists(), link
for path in (ROOT / "schemas").glob("*.json"):
    json.loads(path.read_text())
assert "name: fireworks-vibe-cleaner" in (ROOT / "SKILL.md").read_text()
print(f"Version, documentation links, schemas and Skill identity verified: {version}")
