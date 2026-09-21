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
    if report["data"] != "real-live-jev":
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
    elif report["data"] == "real-local-large":
        assert report["source_bytes"] >= 10 * 1024**3
        assert report["final_all_source_hashes_unchanged"]
        assert report["source_bytes_deleted"] == report["cleanup_bytes_reclaimed"] == 0
        assert report["cleanup_requires_human_confirmation"]
        for row in report["rows"]:
            assert row["source_bytes"] == row["full_stream_restored_bytes"]
            assert row["all_restore_hashes_match"] and row["strict_jsonl_valid"]
    elif report["data"] == "real-live-jev":
        assert report["transport_mocked"] is False
        assert report["network_calls"] == report["successful_calls"] == len(report["runs"])
        assert report["deletion_actions"] == 0
        for run in report["runs"]:
            assert run["status"] == "ok"
            assert all(a["choice"] in {"keep", "review", "backup"} for a in run["answers"].values())
    elif report["data"] == "real-session-preflight":
        assert report["source_mutations_authorized"] is False
        assert report["source_mutations_executed"] is False
        assert report["real_source_files_deleted"] == report["verified_reclaimed_bytes"] == 0
        assert report["phase"] == "read-only-preflight-complete-awaiting-exact-cleanup-approval"
        preflight = report["preflight"]
        assert preflight["real_original_files"] > 0 and preflight["source_logical_bytes"] > 0
        assert preflight["unique_archives"] > 0 and preflight["retained_archive_bytes"] > 0
        assert preflight["full_source_hashes_match"]
        assert preflight["full_archives_and_selected_members_verified"]
        assert preflight["open_handle_checks_passed"]
        assert len(report["actual_cli_refusal_checks"]) == 3
        assert all(row["exit_code"] == 2 and not row["run_created"]
                   for row in report["actual_cli_refusal_checks"])
    elif report["data"] == "real-native-history":
        # A failed native recovery check is a finding, never rewritten as success.
        assert report["continuation_verified"] is False
        codex_ok = all(row["ok"] for row in report["codex"]["samples"])
        claude_ok = all(row["ok"] for row in report["claude"]["exact_source_file_copy_samples"])
        assert report["all_native_checks_passed"] == (codex_ok and claude_ok)
        assert report["codex"]["nonempty_history_read_verified"] == codex_ok
        assert report["claude"]["exact_file_read_verified"] == claude_ok
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
