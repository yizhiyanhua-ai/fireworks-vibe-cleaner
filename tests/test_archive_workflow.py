"""Canary-gated archive cleanup tests using disposable synthetic transcripts."""

import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from vibe_cleaner import archive_workflow, backup, sessions
from vibe_cleaner.common import Refused
from vibe_cleaner.engine import seal
from vibe_cleaner.scan import scan


class ArchiveWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "codex"
        self.root.mkdir()
        self.state = self.base / "state"
        self.backups = self.base / "backups"
        self.backups.mkdir(mode=0o700)
        self.archive = self.backups / "sessions.zip"
        self.paths = []
        for n in range(3):
            uid = f"22222222-2222-2222-2222-{n:012d}"
            path = self.root / f"sessions/2025/01/01/rollout-2025-01-01T00-00-00-{uid}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"type": "session_meta", "payload": {"id": uid, "source": "cli"}}) + "\n")
            path.chmod(0o600)
            old = time.time_ns() - 60 * 86400 * 10**9
            os.utime(path, ns=(old, old))
            self.paths.append(path)
        self.inventory = scan([("codex", self.root)])
        self.ids = [row["id"] for row in self.inventory["items"]]
        backup.backup(self.inventory, self.ids, self.archive, max_bytes=100000)
        self.idle = patch("vibe_cleaner.sessions.idle_check", return_value=None)
        self.idle.start()
        self.addCleanup(self.idle.stop)

    def plans(self):
        canary = sessions.make_plan(self.inventory, self.ids[:1], [self.archive], self.state, max_bytes=100000)
        cleanup = sessions.make_plan(self.inventory, self.ids[1:], [self.archive], self.state, max_bytes=100000)
        return canary, cleanup

    def test_refresh_preserves_exact_scope_and_requires_new_hash(self):
        canary, _ = self.plans()
        expired = copy.deepcopy(canary)
        expired["expires_at"] = 0
        expired["hash"] = seal(expired)
        refreshed = sessions.refresh_plan(expired, ttl=7200)
        self.assertNotEqual(refreshed["hash"], expired["hash"])
        self.assertEqual(refreshed["refresh"]["supersedes_hash"], expired["hash"])
        self.assertTrue(refreshed["refresh"]["scope_unchanged"])
        for key in ("items", "archives", "state_dir", "risk", "max_bytes", "keep"):
            self.assertEqual(refreshed[key], expired[key])
        with self.assertRaises(Refused):
            sessions.apply(refreshed, expired["hash"], quiescent=True, acknowledge_risk=True)

    def test_refresh_refuses_changed_source_or_archive(self):
        canary, _ = self.plans()
        self.paths[0].write_bytes(self.paths[0].read_bytes() + b"changed\n")
        with self.assertRaises(Refused):
            sessions.refresh_plan(canary)
        self.paths[0].write_bytes(b"unrelated")
        with self.archive.open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaises(Refused):
            sessions.refresh_plan(canary)

    def test_workflow_requires_canary_restore_before_cleanup(self):
        canary, cleanup = self.plans()
        workflow = archive_workflow.make_plan(canary, cleanup)
        with self.assertRaises(Refused):
            archive_workflow.apply(workflow, "wrong", quiescent=True, acknowledge_risk=True)
        result = archive_workflow.apply(workflow, workflow["hash"], quiescent=True, acknowledge_risk=True)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["canary"]["locations"], {"source": 1})
        self.assertEqual(result["cleanup"]["locations"], {"archive-only": 2})
        self.assertTrue(self.paths[0].exists())
        self.assertTrue(all(not path.exists() for path in self.paths[1:]))
        self.assertTrue(self.archive.exists())
        receipt = archive_workflow.verify(self.state, workflow["hash"])
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["stage"], "verified")

    def test_failed_canary_restore_blocks_cleanup(self):
        canary, cleanup = self.plans()
        workflow = archive_workflow.make_plan(canary, cleanup)
        with patch("vibe_cleaner.archive_workflow.sessions.restore", return_value={"status": "restored"}):
            with self.assertRaises(Refused):
                archive_workflow.apply(workflow, workflow["hash"], quiescent=True, acknowledge_risk=True)
        self.assertFalse(self.paths[0].exists())
        self.assertTrue(all(path.exists() for path in self.paths[1:]))
        receipt = archive_workflow.verify(self.state, workflow["hash"])
        self.assertFalse(receipt["ok"])
        self.assertEqual(receipt["stage"], "interrupted")
        sessions.restore(self.state, canary["hash"], quiescent=True)

    def test_workflow_refuses_overlapping_or_rebound_scope(self):
        canary, cleanup = self.plans()
        overlap = copy.deepcopy(cleanup)
        overlap["items"][0] = copy.deepcopy(canary["items"][0])
        overlap["source_logical_bytes"] = sum(row["identity"]["size"] for row in overlap["items"])
        overlap["hash"] = seal(overlap)
        with self.assertRaises(Refused):
            archive_workflow.make_plan(canary, overlap)
        workflow = archive_workflow.make_plan(canary, cleanup)
        forged = copy.deepcopy(workflow)
        forged["cleanup_files"] += 1
        forged["hash"] = seal(forged)
        with self.assertRaises(Refused):
            archive_workflow.check_plan(forged, forged["hash"])


if __name__ == "__main__":
    unittest.main()
