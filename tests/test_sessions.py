"""Synthetic fault-injection tests, never operate on a real harness root."""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from vibe_cleaner import backup, engine, sessions
from vibe_cleaner.common import Refused, load
from vibe_cleaner.scan import scan


class ArchiveRemovalTests(unittest.TestCase):
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
        for n in range(2):
            uid = f"11111111-1111-1111-1111-{n:012d}"
            path = self.root / f"sessions/2025/01/01/rollout-2025-01-01T00-00-00-{uid}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"type": "session_meta", "payload": {"id": uid, "source": "cli"}}) + '\n')
            path.chmod(0o600)
            old = time.time_ns() - 60 * 86400 * 10**9
            os.utime(path, ns=(old, old))
            self.paths.append(path)
        self.inv = scan([("codex", self.root)])
        self.ids = [i["id"] for i in self.inv["items"]]
        backup.backup(self.inv, self.ids, self.archive, max_bytes=100000)

    def plan(self, inv=None):
        return sessions.make_plan(inv or self.inv, self.ids, [self.archive], self.state, max_bytes=100000)

    def apply(self, plan=None):
        plan = plan or self.plan()
        return plan, sessions.apply(plan, plan["hash"], quiescent=True, acknowledge_risk=True)

    def test_actual_unlink_restore_paths_bytes_mode_and_mtime(self):
        before = [(p.read_bytes(), p.stat()) for p in self.paths]
        plan, result = self.apply()
        self.assertTrue(all(not p.exists() for p in self.paths))
        self.assertEqual(result["deleted_logical_bytes"], sum(len(b) for b, _ in before))
        self.assertEqual(len(result["observed_free_delta_by_volume"]), 1)
        observation = next(iter(result["observed_free_delta_by_volume"].values()))
        self.assertEqual(observation["method"], "shutil.disk_usage")
        self.assertEqual(observation["observed_free_delta_bytes"],
                         observation["free_after_bytes"] - observation["free_before_bytes"])
        self.assertTrue(self.archive.exists())
        self.assertTrue(sessions.verify(self.state, plan["hash"])["ok"])
        sessions.restore(self.state, plan["hash"], quiescent=True)
        for p, (data, old) in zip(self.paths, before):
            self.assertEqual(p.read_bytes(), data)
            self.assertEqual(p.stat().st_mode, old.st_mode)
            self.assertEqual(p.stat().st_mtime_ns, old.st_mtime_ns)
        self.assertTrue(sessions.verify(self.state, plan["hash"])["ok"])
        self.assertEqual(sessions.verify(self.state, plan["hash"])["removed_logical_bytes"], 0)
        with self.assertRaises(Refused):
            sessions.apply(plan, plan["hash"], quiescent=True, acknowledge_risk=True)

    def test_volume_snapshot_deduplicates_roots_on_one_device(self):
        other = self.base / "other-root"
        other.mkdir()
        items = [{"root": str(self.root)}, {"root": str(other)}, {"root": str(self.root)}]
        snapshot = sessions.volume_snapshot(items)
        self.assertEqual(len(snapshot), 1)
        row = next(iter(snapshot.values()))
        self.assertIn(row["representative_root"], {str(self.root), str(other)})
        self.assertEqual(row["method"], "shutil.disk_usage")

    def test_exact_approval_risk_ack_stopped_writers_and_expiry(self):
        plan = self.plan()
        for approval, stopped, risk in [("wrong", True, True), (plan["hash"], False, True),
                                         (plan["hash"], True, False)]:
            with self.assertRaises(Refused):
                sessions.apply(plan, approval, quiescent=stopped, acknowledge_risk=risk)
        expired = dict(plan, expires_at=0)
        expired["hash"] = engine.seal(expired)
        with self.assertRaises(Refused):
            self.apply(expired)
        self.assertTrue(all(p.exists() for p in self.paths))

    def test_old_executor_cannot_bypass_backup(self):
        with self.assertRaises(Refused):
            engine.make_plan(self.inv, self.ids, self.state, max_bytes=100000)
        plan = self.plan()
        forged = copy.deepcopy(plan)
        forged["action"] = "quarantine"
        forged["hash"] = engine.seal(forged)
        with self.assertRaises(Refused):
            engine.apply(forged, forged["hash"], quiescent=True)

    def test_forged_manifest_success_is_not_evidence(self):
        with zipfile.ZipFile(self.archive, "w") as z:
            for n, p in enumerate(self.paths):
                z.writestr(str(n), b"x" * p.stat().st_size)
        with self.assertRaises(Refused):
            self.plan()
        self.assertTrue(all(p.exists() for p in self.paths))

    def test_archive_tamper_after_plan_and_missing_archive(self):
        plan = self.plan()
        with self.archive.open("ab") as out:
            out.write(b"tampered")
        with self.assertRaises(Refused):
            self.apply(plan)
        self.archive.unlink()
        with self.assertRaises((Refused, OSError)):
            self.apply(plan)
        self.assertTrue(all(p.exists() for p in self.paths))

    def test_manifest_mapping_ambiguity(self):
        path = self.archive.with_suffix(".zip.manifest.json")
        data = load(path)
        data["files"].append(copy.deepcopy(data["files"][0]))
        path.write_text(json.dumps(data))
        with self.assertRaises(Refused):
            self.plan()

    def test_missing_and_duplicate_members(self):
        with zipfile.ZipFile(self.archive, "w") as z:
            z.writestr("unrelated", b"content")
        with self.assertRaises(Refused):
            self.plan()

    def test_source_changed_or_hardlinked_after_review(self):
        plan = self.plan()
        self.paths[0].write_text("changed")
        with self.assertRaises(Refused):
            self.apply(plan)
        self.assertTrue(self.paths[1].exists())

    def test_keep_retention_and_nonregular_rejected(self):
        kept = scan([("codex", self.root)], keep=["*.jsonl"])
        with self.assertRaises(Refused):
            self.plan(kept)
        os.utime(self.paths[0], None)
        with self.assertRaises(Refused):
            self.plan(scan([("codex", self.root)]))
        os.link(self.paths[1], self.base / "hardlink")
        fresh = scan([("codex", self.root)])
        self.assertFalse(any(i["archive_eligible"] for i in fresh["items"]))

    def test_open_source_or_archive_refuses_without_changes(self):
        plan = self.plan()
        for path in [self.paths[0], self.archive]:
            with path.open("rb"), self.assertRaises(Refused):
                self.apply(plan)
        self.assertTrue(all(p.exists() for p in self.paths))

    def test_unknown_header_refused(self):
        self.paths[0].write_text('{"unknown":true}\n')
        os.utime(self.paths[0], (0, 0))
        inv = scan([("codex", self.root)])
        with self.assertRaises(Refused):
            self.plan(inv)

    def test_top_level_codex_subagent_and_unknown_source_refused(self):
        for source in [{"subagent": {"thread_spawn": {}}}, "unknown", None]:
            data = json.loads(self.paths[0].read_text())
            data["payload"]["source"] = source
            self.paths[0].write_text(json.dumps(data)+'\n')
            os.utime(self.paths[0], (0, 0))
            with self.assertRaises(Refused):
                self.plan(scan([("codex", self.root)]))

    def test_ancestor_durability_before_any_source_unlink(self):
        plan = self.plan()
        recorded = []
        sync = sessions.sync_dir
        unlink = os.unlink

        def synced(path):
            recorded.append(Path(path))
            return sync(path)

        def removed(path, *args, **kwargs):
            if str(path) in {p.name for p in self.paths}:
                self.assertIn(self.backups, recorded)
                self.assertIn(self.base, recorded)
            return unlink(path, *args, **kwargs)

        with patch("vibe_cleaner.sessions.sync_dir", side_effect=synced), patch("vibe_cleaner.sessions.os.unlink", side_effect=removed):
            self.apply(plan)

    def test_restore_reuses_temp_after_failure_before_link(self):
        for p in self.paths:
            p.chmod(0o444)
        self.inv = scan([("codex", self.root)])
        plan, _ = self.apply()
        link = os.link

        def interrupted(src, dst, *args, **kwargs):
            if str(src).startswith(".fireworks-restore-"):
                raise OSError("synthetic interruption before installing restored file")
            return link(src, dst, *args, **kwargs)

        with patch("vibe_cleaner.sessions.os.link", side_effect=interrupted), self.assertRaises(OSError):
            sessions.restore(self.state, plan["hash"], quiescent=True)
        self.assertEqual(len(list(self.paths[0].parent.glob('.fireworks-restore-*'))), 1)
        sessions.restore(self.state, plan["hash"], quiescent=True)
        self.assertEqual(list(self.paths[0].parent.glob('.fireworks-restore-*')), [])
        self.assertTrue(sessions.verify(self.state, plan["hash"])["ok"])

    def test_changed_ancestor_symlink_refused(self):
        plan = self.plan()
        old = self.root / "sessions"
        moved = self.root / "moved"
        old.rename(moved)
        old.symlink_to(moved, target_is_directory=True)
        with self.assertRaises((Refused, OSError)):
            self.apply(plan)

    def test_interrupted_after_unlink_restores_partial_run(self):
        plan = self.plan()
        unlink = os.unlink
        fired = False

        def interrupted(path, *args, **kwargs):
            nonlocal fired
            result = unlink(path, *args, **kwargs)
            if str(path) == self.paths[0].name and not fired:
                fired = True
                raise OSError("synthetic crash immediately after source unlink")
            return result

        with patch("vibe_cleaner.sessions.os.unlink", side_effect=interrupted), self.assertRaises(OSError):
            self.apply(plan)
        self.assertFalse(self.paths[0].exists())
        self.assertTrue(self.paths[1].exists())
        report = sessions.verify(self.state, plan["hash"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "interrupted")
        sessions.restore(self.state, plan["hash"], quiescent=True)
        self.assertTrue(sessions.verify(self.state, plan["hash"])["ok"])

    def test_restore_conflict_and_missing_backup(self):
        plan, _ = self.apply()
        self.paths[0].write_text("new work")
        with self.assertRaises(Refused):
            sessions.restore(self.state, plan["hash"], quiescent=True)
        self.assertEqual(self.paths[0].read_text(), "new work")
        self.assertFalse(self.paths[1].exists())
        self.assertFalse(sessions.verify(self.state, plan["hash"])["ok"])

    def test_restore_race_never_overwrites_new_file(self):
        plan, _ = self.apply()
        original_link = os.link

        def racing(src, dst, *args, **kwargs):
            if str(src).startswith(".fireworks-restore-"):
                self.paths[0].write_text("new work during restore")
            return original_link(src, dst, *args, **kwargs)

        with patch("vibe_cleaner.sessions.os.link", side_effect=racing), self.assertRaises(FileExistsError):
            sessions.restore(self.state, plan["hash"], quiescent=True)
        self.assertEqual(self.paths[0].read_text(), "new work during restore")

    def test_claude_top_level_only_and_exact_path_identity(self):
        root = self.base / "claude"
        uid = "22222222-2222-2222-2222-222222222222"
        path = root / f"projects/project-a/{uid}.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"type": "user", "sessionId": uid, "message": {"content": "synthetic"}})+'\n')
        os.utime(path, (0, 0))
        child = path.parent / "subagents" / f"{uid}.jsonl"
        child.parent.mkdir()
        child.write_bytes(path.read_bytes())
        os.utime(child, (0, 0))
        inv = scan([("claude", root)])
        item = next(i for i in inv["items"] if i["archive_eligible"])
        self.assertEqual(sum(i["archive_eligible"] for i in inv["items"]), 1)
        archive = self.backups / "claude.zip"
        backup.backup(inv, [item["id"]], archive, max_bytes=10000)
        plan = sessions.make_plan(inv, [item["id"]], [archive], self.state, max_bytes=10000)
        self.apply(plan)
        self.assertTrue(child.exists())
        sessions.restore(self.state, plan["hash"], quiescent=True)
        self.assertEqual(path.read_bytes(), child.read_bytes())
        data = json.loads(path.read_text())
        data["isSidechain"] = True
        path.write_text(json.dumps(data)+'\n')
        os.utime(path, (0, 0))
        inv = scan([("claude", root)])
        with self.assertRaisesRegex(Refused, "sidechain"):
            sessions.make_plan(inv, [item["id"]], [archive], self.state, max_bytes=10000)
