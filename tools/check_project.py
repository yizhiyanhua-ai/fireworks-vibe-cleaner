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
    for src in re.findall(r'<img[^>]+src="([^"]+)"', content):
        assert (ROOT / src).is_file(), src
for path in (ROOT / "schemas").glob("*.json"):
    json.loads(path.read_text())
assert "name: fireworks-vibe-cleaner" in (ROOT / "SKILL.md").read_text()
for path in (ROOT / "docs/experiments").glob("*.json"):
    report = json.loads(path.read_text())
    assert report["real_user_data_modified"] is False
    assert report["network_calls"] == 0
    if report["data"] == "synthetic-only":
        assert report["passed"] and len(report["experiments"]) == 7
        assert all(row["passed"] for row in report["experiments"])
    elif report["data"] == "real-local":
        assert report["cleanup_bytes_reclaimed"] == 0
        assert report["inventory_after_fix_same_snapshot"]["eligible_files"] == 0
        assert len(report["backups"]) == 2
        for row in report["backups"]:
            assert row["status"] == "bytes-verified"
            assert row["source_hashes_unchanged"] and row["extracted_hashes_match"]
            assert row["source_bytes_deleted"] == row["cleanup_bytes_reclaimed"] == 0
            assert row["source_bytes_before"] == row["source_bytes_after"]
    else:
        raise AssertionError("Unknown public evidence type")
    forbidden_keys = {"path", "root", "relative", "username", "hostname", "session_id", "api_key", "token"}
    def inspect(value):
        if isinstance(value, dict):
            assert not (set(value) & forbidden_keys), "Private field in public evidence"
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
        elif isinstance(value, str):
            assert not any(prefix in value for prefix in ["/Users/", "/home/", "/Volumes/", "Bearer "])
    inspect(report)
print(f"Version, documentation links, schemas and Skill identity verified: {version}")
