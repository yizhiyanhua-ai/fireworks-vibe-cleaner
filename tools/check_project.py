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
    data = report["data"]
    if data == "real-approved-cleanup":
        assert report["real_user_data_modified"] is True
    else:
        assert report["real_user_data_modified"] is False
    if data not in {"real-live-jev", "real-jev-triage", "real-jev-evidence", "real-purpose-comparison",
                    "real-approved-cleanup"}:
        assert report["network_calls"] == 0
    if data == "synthetic-only":
        assert report["passed"] and len(report["experiments"]) == 7
        assert all(row["passed"] for row in report["experiments"])
    elif data == "real-local":
        assert report["cleanup_bytes_reclaimed"] == 0
        assert report["inventory_after_fix_same_snapshot"]["eligible_files"] == 0
        assert len(report["backups"]) == 2
        for row in report["backups"]:
            assert row["status"] == "bytes-verified"
            assert row["source_hashes_unchanged"] and row["extracted_hashes_match"]
            assert row["source_bytes_deleted"] == row["cleanup_bytes_reclaimed"] == 0
            assert row["source_bytes_before"] == row["source_bytes_after"]
    elif data == "real-local-large":
        assert report["source_bytes"] >= 10 * 1024**3
        assert report["final_all_source_hashes_unchanged"]
        assert report["source_bytes_deleted"] == report["cleanup_bytes_reclaimed"] == 0
        assert report["cleanup_requires_human_confirmation"]
        for row in report["rows"]:
            assert row["source_bytes"] == row["full_stream_restored_bytes"]
            assert row["all_restore_hashes_match"] and row["strict_jsonl_valid"]
    elif data == "real-live-jev":
        assert report["transport_mocked"] is False
        assert report["network_calls"] == report["successful_calls"] == len(report["runs"])
        assert report["deletion_actions"] == 0
        for run in report["runs"]:
            assert run["status"] == "ok"
            assert all(a["choice"] in {"keep", "review", "backup"} for a in run["answers"].values())
    elif data == "real-jev-triage":
        assert report["transport_mocked"] is False and report["source_hashes_unchanged"]
        assert report["source_mutations_executed"] is False and report["actual_reclaimed_bytes"] == 0
        assert report["no_accuracy_claim"] and report["no_cleanup_authorization"]
        assert report["network_calls"] == sum(r["provider"]["calls"] for r in report["runs"])
        for run in report["runs"]:
            assert len(run["decisions"]) == report["source_files"]
            assert sum(run["action_counts"].values()) == report["source_files"]
            assert all(d["action"] in {"keep", "review", "backup", "prepare_removal", "prepare_cache_cleanup"}
                       for d in run["decisions"])
    elif data == "real-jev-evidence":
        assert not report["transport_mocked"] and not report["source_mutations_executed"]
        assert report["actual_reclaimed_bytes"] == 0 and report["no_accuracy_claim"]
        assert report["all_hash_checked_sources_unchanged"]
        assert report["hash_checked_files"] + report["protected_or_dynamic_files_not_hashed"] == report["source_files"]
        assert report["network_calls"] == sum(r["provider"]["calls"] for r in report["runs"])
        assert report["no_cleanup_authorization"] and report["recovery_need"] == "unknown"
        assert report["total_validation_calls"] == report["network_calls"] + report["earlier_attempt"]["network_calls"] + report["diagnostic_call"]["calls"]
        for run in report["runs"]:
            assert len(run["decisions"]) == report["source_files"]
            assert sum(run["action_counts"].values()) == report["source_files"]
        for run in report["runs"][1:]:
            assert "prepare_removal" not in run["action_counts"]
            assert all(not d["facts"]["protected"] or d["source"] == "local-protection" for d in run["decisions"])
    elif data == "real-purpose-comparison":
        assert not report["transport_mocked"] and not report["source_mutations_executed"]
        assert report["actual_reclaimed_bytes"] == 0 and report["no_cleanup_authorization"]
        assert report["all_hash_checked_sources_unchanged"] and report["no_accuracy_claim"]
        assert not report["human_labels_available"] and report["recovery_need"] == "unknown"
        assert report["network_calls"] == sum(r["provider"]["calls"] for r in report["runs"])
        assert report["runs"][0]["provider"]["calls"] == 0
        assert report["hash_checked_files"] + report["protected_or_dynamic_files_not_hashed"] == report["source_files"]
        assert report["same_requests_before_and_after_final_local_gate"]
        for run in report["runs"]:
            assert len(run["decisions"]) == report["source_files"]
            assert sum(run["actions"].values()) == report["source_files"]
            assert "prepare_removal" not in run["actions"]
            assert all(d["action"] != "backup" or d["facts"]["purpose_role"] != "unknown" for d in run["decisions"])
    elif data == "real-session-preflight":
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
    elif data == "real-codex-history-audit":
        assert report["real_threads_archived"] == report["verified_reclaimed_bytes"] == 0
        metrics = report["metrics"]
        assert metrics["indexed_threads"] == metrics["archived_threads"] + metrics["unarchived_threads"]
        assert metrics["known_logical_bytes"] > 0 and metrics["native_archive_reclaim_bytes"] == 0
        assert report["audit_complete"] is False
        assert report["native_plan_refusal"] == {
            "exit_code": 2, "reason": "incomplete-index-file-lineage-coverage",
            "plan_created": False, "run_created": False}
    elif data == "synthetic-native-archive":
        assert report["transport_mocked"] is False and report["network_denied"]
        assert report["other_executables_denied"] and report["writes_limited_to_fixture_and_runtime_home"]
        assert report["synthetic_threads"] == 4
        assert report["archived_threads"] == report["restored_threads"] == 3
        assert report["archive_verify_passed"] and report["restore_verify_passed"]
        assert report["all_original_paths_and_content_hashes_match"]
        assert report["unrelated_thread_preserved_after_roundtrip"]
        assert report["verified_reclaimed_bytes"] == 0 and not report["harness_resume_verified"]
        assert len(report["refused_cases"]) == 4
        assert all(r["exit_code"] == 2 for r in report["refused_cases"])
    elif data == "real-native-history":
        # A failed native recovery check is a finding, never rewritten as success.
        assert report["continuation_verified"] is False
        codex_ok = all(row["ok"] for row in report["codex"]["samples"])
        claude_ok = all(row["ok"] for row in report["claude"]["exact_source_file_copy_samples"])
        assert report["all_native_checks_passed"] == (codex_ok and claude_ok)
        assert report["codex"]["nonempty_history_read_verified"] == codex_ok
        assert report["claude"]["exact_file_read_verified"] == claude_ok
    elif data == "real-approved-cleanup":
        assert report["source_mutations_authorized"]
        assert report["cleanup"]["originals_removed"] == report["cleanup"]["valid_archive_only_items"]
        assert report["cleanup"]["invalid_items"] == 0 and report["cleanup"]["archives_verified"]
        assert report["canary"]["restored_byte_verification"] == "passed"
        assert report["canary"]["retained_at_end"]
        assert report["jev_acceptance"]["paths_or_content_sent"] is False
        assert report["network_calls"] == (report["jev_acceptance"]["real_calls"]
                                           + report["jev_acceptance"]["synthetic_calls"])
        assert report["not_verified"]
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
