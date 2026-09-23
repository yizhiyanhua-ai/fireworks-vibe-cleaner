"""Black-box archive CLI checks using isolated, disposable harness data only."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest


class ArchiveCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vibe-cleaner-cli-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "codex"
        self.root.mkdir()
        self.home = self.base / "home"
        self.home.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        # Preserve actual open-handle checks without invoking installed harnesses.
        lsof = shutil.which("lsof")
        if lsof:
            (self.bin / "lsof").symlink_to(Path(lsof).resolve())
        self.lsof_available = bool(lsof)
        self.guard = self.base / "python-guard"
        self.guard.mkdir()
        self.network_marker = self.base / "network-attempted"
        (self.guard / "sitecustomize.py").write_text(
            "import os, sys\n"
            "def guard(event, args):\n"
            "    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:\n"
            "        with open(os.environ['VIBE_TEST_NETWORK_MARKER'], 'w') as out:\n"
            "            out.write(event)\n"
            "        raise RuntimeError('Network forbidden in synthetic CLI tests')\n"
            "sys.addaudithook(guard)\n"
        )
        package = importlib.util.find_spec("vibe_cleaner")
        self.assertIsNotNone(package)
        repo = Path(package.origin).resolve().parent.parent
        self.secret = "synthetic-typesafe-key-MUST-NOT-APPEAR-745e962c"
        # Do not inherit real credentials, harness roots, or provider settings.
        self.env = {
            "HOME": str(self.home),
            "CODEX_HOME": str(self.root),
            "CLAUDE_CONFIG_DIR": str(self.base / "claude"),
            "PATH": str(self.bin),
            "PYTHONPATH": os.pathsep.join((str(self.guard), str(repo))),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TYPESAFE_API_KEY": self.secret,
            "VIBE_TEST_NETWORK_MARKER": str(self.network_marker),
        }
        uid = "12345678-1234-4321-abcd-123456789abc"
        self.source = self.root / (
            "sessions/2025/01/01/rollout-2025-01-01T00-00-00-" + uid + ".jsonl"
        )
        self.source.parent.mkdir(parents=True)
        self.original = (
            json.dumps({"type": "session_meta", "payload": {"id": uid, "source": "cli"}})
            + '\n{"type":"event_msg","payload":{"message":"synthetic only"}}\n'
        ).encode()
        self.source.write_bytes(self.original)
        self.source.chmod(0o600)
        old = time.time_ns() - 60 * 86400 * 10**9
        os.utime(self.source, ns=(old, old))
        self.original_stat = self.source.stat()
        self.inventory_path = self.base / "scan.json"

    def cli(self, *args, expected=0, json_output=True, with_key=True):
        env = dict(self.env)
        if not with_key:
            env.pop("TYPESAFE_API_KEY")
        result = subprocess.run(
            [sys.executable, "-m", "vibe_cleaner.cli", *map(str, args)],
            cwd=self.base, env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertFalse(self.network_marker.exists(), "CLI attempted a network operation")
        self.assertNotIn(self.secret, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        if not json_output:
            return result
        if expected == 0:
            self.assertEqual(result.stderr, "")
            output = result.stdout
        else:
            self.assertEqual(result.stdout, "")
            output = result.stderr
        parsed = json.loads(output)
        self.assertIsInstance(parsed, dict)
        return parsed

    def scan(self):
        result = self.cli(
            "scan", "--root", "codex=" + str(self.root), "--min-age-days", 30,
            "--output", self.inventory_path,
        )
        self.assertTrue(result["complete"])
        self.assertEqual(result["archive_candidate_files"], 1)
        inventory = json.loads(self.inventory_path.read_text())
        self.assertEqual(inventory["errors"], [])
        self.assertEqual(len(inventory["items"]), 1)
        item = inventory["items"][0]
        self.assertEqual(item["category"], "session")
        self.assertTrue(item["archive_eligible"])
        return item["id"]

    def test_archive_cli_roundtrip_and_explicit_confirmation(self):
        if not self.lsof_available:
            self.skipTest("Actual archive mutations require local lsof")
        candidate = self.scan()
        backup_dir = self.base / "backups"
        backup_dir.mkdir(mode=0o700)
        archive = backup_dir / "sessions.zip"
        backed_up = self.cli(
            "backup", "--scan", self.inventory_path, "--id", candidate,
            "--output", archive, "--max-bytes", 100000,
        )
        self.assertEqual(backed_up["status"], "bytes-verified")
        self.assertFalse(backed_up["source_removed"])
        self.assertEqual(self.source.read_bytes(), self.original)
        archive_bytes = archive.read_bytes()
        manifest = archive.with_suffix(".zip.manifest.json")
        manifest_bytes = manifest.read_bytes()
        state = self.base / "state"
        plan_path = self.base / "archive-plan.json"
        plan = self.cli(
            "archive-plan", "--scan", self.inventory_path, "--id", candidate,
            "--archive", archive, "--state-dir", state, "--max-bytes", 100000,
            "--output", plan_path,
        )
        self.assertEqual(plan, json.loads(plan_path.read_text()))
        self.assertEqual(plan["action"], "remove-archived-transcripts")
        self.assertEqual(plan["source_logical_bytes"], len(self.original))
        self.assertFalse(plan["harness_resume_verified"])
        self.assertEqual(plan["items"][0]["id"], candidate)
        refreshed_path = self.base / "archive-plan-refreshed.json"
        refreshed = self.cli(
            "archive-refresh", "--plan", plan_path, "--ttl-seconds", 7200,
            "--output", refreshed_path,
        )
        self.assertTrue(refreshed["refresh"]["scope_unchanged"])
        self.assertEqual(refreshed["refresh"]["supersedes_hash"], plan["hash"])
        self.assertEqual(refreshed["items"], plan["items"])
        self.assertNotEqual(refreshed["hash"], plan["hash"])
        approval = plan["hash"]
        apply_args = ("archive-apply", "--plan", plan_path)
        missing = self.cli(*apply_args, expected=2, json_output=False)
        self.assertIn("--approve", missing.stderr)
        self.assertEqual(missing.stdout, "")
        for options in (
            ("--approve", "0" * 64, "--writers-stopped", "--acknowledge-history-risk"),
            ("--approve", approval, "--acknowledge-history-risk"),
            ("--approve", approval, "--writers-stopped"),
        ):
            with self.subTest(options=options):
                refusal = self.cli(*apply_args, *options, expected=2)
                self.assertEqual(refusal["error"], "Refused")
                self.assertEqual(self.source.read_bytes(), self.original)
                self.assertFalse(state.exists())
        applied = self.cli(
            *apply_args, "--approve", approval, "--writers-stopped",
            "--acknowledge-history-risk",
        )
        self.assertEqual(applied["run"], approval)
        self.assertEqual(applied["status"], "removed")
        self.assertEqual(applied["files"], 1)
        self.assertEqual(applied["deleted_logical_bytes"], len(self.original))
        self.assertTrue(applied["archive_retained"])
        self.assertFalse(applied["harness_resume_verified"])
        self.assertFalse(self.source.exists())
        run_args = ("--state-dir", state, "--run", approval)
        removed = self.cli("archive-verify", *run_args)
        self.assertTrue(removed["ok"])
        self.assertTrue(removed["archives_verified"])
        self.assertEqual(removed["items"], [{"index": 0, "location": "archive-only", "valid": True}])
        self.assertEqual(removed["removed_logical_bytes"], len(self.original))
        summary = self.cli("archive-verify", *run_args, "--summary")
        self.assertEqual(summary["items"], 1)
        self.assertEqual(summary["locations"], {"archive-only": 1})
        self.assertEqual(summary["invalid_items"], 0)
        restored = self.cli("archive-restore", *run_args, "--writers-stopped")
        self.assertEqual(restored["status"], "restored")
        self.assertEqual(restored["files"], 1)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.source.stat().st_mtime_ns, self.original_stat.st_mtime_ns)
        self.assertEqual(stat.S_IMODE(self.source.stat().st_mode), 0o600)
        verified = self.cli("archive-verify", *run_args)
        self.assertTrue(verified["ok"])
        self.assertTrue(verified["archives_verified"])
        self.assertEqual(verified["status"], "restored")
        self.assertEqual(verified["items"], [{"index": 0, "location": "source", "valid": True}])
        self.assertEqual(verified["removed_logical_bytes"], 0)
        self.assertEqual(archive.read_bytes(), archive_bytes)
        self.assertEqual(manifest.read_bytes(), manifest_bytes)

    def test_archive_workflow_cli_binds_canary_to_cleanup(self):
        if not self.lsof_available:
            self.skipTest("Actual archive mutations require local lsof")
        second_uid = "87654321-4321-1234-abcd-123456789abc"
        second = self.source.with_name(
            "rollout-2025-01-01T00-00-01-" + second_uid + ".jsonl"
        )
        second.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": second_uid, "source": "cli"}}) + "\n")
        second.chmod(0o600)
        old = time.time_ns() - 60 * 86400 * 10**9
        os.utime(second, ns=(old, old))
        inventory_path = self.base / "workflow-scan.json"
        self.cli("scan", "--root", "codex=" + str(self.root), "--min-age-days", 30,
                 "--output", inventory_path)
        inventory = json.loads(inventory_path.read_text())
        by_relative = {row["relative"]: row["id"] for row in inventory["items"]}
        canary_id = by_relative[str(self.source.relative_to(self.root))]
        cleanup_id = by_relative[str(second.relative_to(self.root))]
        backup_dir = self.base / "workflow-backups"
        backup_dir.mkdir(mode=0o700)
        archive = backup_dir / "sessions.zip"
        self.cli("backup", "--scan", inventory_path, "--id", canary_id, "--id", cleanup_id,
                 "--output", archive, "--max-bytes", 100000)
        state = self.base / "workflow-state"
        canary_path = self.base / "canary-plan.json"
        cleanup_path = self.base / "cleanup-plan.json"
        self.cli("archive-plan", "--scan", inventory_path, "--id", canary_id,
                 "--archive", archive, "--state-dir", state, "--max-bytes", 100000,
                 "--output", canary_path)
        self.cli("archive-plan", "--scan", inventory_path, "--id", cleanup_id,
                 "--archive", archive, "--state-dir", state, "--max-bytes", 100000,
                 "--output", cleanup_path)
        workflow_path = self.base / "workflow-plan.json"
        workflow = self.cli("archive-workflow-plan", "--canary-plan", canary_path,
                            "--cleanup-plan", cleanup_path, "--output", workflow_path)
        refused = self.cli("archive-workflow-apply", "--plan", workflow_path,
                           "--approve", "0" * 64, "--writers-stopped",
                           "--acknowledge-history-risk", expected=2)
        self.assertEqual(refused["error"], "Refused")
        result = self.cli("archive-workflow-apply", "--plan", workflow_path,
                          "--approve", workflow["hash"], "--writers-stopped",
                          "--acknowledge-history-risk")
        self.assertEqual(result["status"], "verified")
        self.assertTrue(self.source.exists())
        self.assertFalse(second.exists())
        receipt = self.cli("archive-workflow-verify", "--state-dir", state,
                           "--run", workflow["hash"])
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["canary"]["locations"], {"source": 1})
        self.assertEqual(receipt["cleanup"]["locations"], {"archive-only": 1})

    def test_doctor_and_advice_are_offline_and_secret_safe(self):
        doctor = self.cli("doctor")
        self.assertEqual(doctor["harness_versions"], {"codex": "unavailable", "claude": "unavailable"})
        self.assertTrue(doctor["jev_recommended"])
        self.assertTrue(doctor["jev_key_present"])
        self.assertFalse(doctor["network_tested"])
        self.assertFalse(doctor["harness_resume_verified"])
        self.assertEqual(doctor["session_deletion"], "verified-archive-and-exact-human-approval-required")
        self.assertEqual({r["kind"]: r["path"] for r in doctor["roots"]}, {
            "codex": str(self.root), "claude": str(self.base / "claude"),
        })
        candidate = self.scan()
        output = self.base / "advice.json"
        args = ("advise", "--scan", self.inventory_path, "--id", candidate)
        offline = self.cli(*args, "--output", output)
        self.assertEqual((offline["status"], offline["mode"], offline["calls"]), ("disabled", "rules-only", 0))
        self.assertEqual(offline, json.loads(output.read_text()))
        no_key_output = self.base / "advice-without-key.json"
        no_key = self.cli(*args, "--output", no_key_output, "--enable-network", with_key=False)
        self.assertEqual((no_key["status"], no_key["mode"], no_key["calls"]), ("missing-key", "rules-only", 0))
        self.assertEqual(no_key, json.loads(no_key_output.read_text()))
        self.assertNotIn(self.secret, output.read_text())
        self.assertEqual(self.source.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
