from __future__ import annotations

import os
from pathlib import Path
import py_compile
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

from vibe_cleaner import backup, engine, jev
from vibe_cleaner.common import Refused, load, write
from vibe_cleaner.scan import scan


class CleanerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "codex"
        self.root.mkdir()
        self.state = self.base / "state"
        self.log = self.root / "logs" / "codex-tui.log"
        self.log.parent.mkdir()
        self.log.write_bytes(b"synthetic diagnostic\n" * 100)
        old = time.time() - 60 * 86400
        os.utime(self.log, (old, old))

    def inventory(self):
        return scan([("codex", self.root)])

    def plan(self):
        inv = self.inventory()
        ids = [i["id"] for i in inv["items"] if i["eligible"]]
        return engine.make_plan(inv, ids, self.state, max_bytes=100000)

    def apply(self):
        plan = self.plan()
        result = engine.apply(plan, plan["hash"], quiescent=True)
        return plan, result

    def test_scan_does_not_read_or_modify_contents(self):
        before = self.log.stat()
        with patch("vibe_cleaner.common.candidate_fd", side_effect=AssertionError("content read")):
            result = self.inventory()
        self.assertEqual(result["summary"]["eligible_files"], 1)
        self.assertEqual(before.st_mtime_ns, self.log.stat().st_mtime_ns)

    def test_idle_checks_batch_paths_without_weakening_failure_gate(self):
        items = [{"root": str(self.root), "relative": f"logs/{n}.log"} for n in range(33)]
        clean = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"")
        with patch("vibe_cleaner.engine.subprocess.run", return_value=clean) as run:
            engine.idle_check(items)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(len(run.call_args_list[0].args[0]), 37)
        opened = subprocess.CompletedProcess([], 0, stdout=b"p123\n", stderr=b"")
        with patch("vibe_cleaner.engine.subprocess.run", side_effect=[clean, opened]), self.assertRaises(Refused):
            engine.idle_check(items)

    def test_protected_sessions_memory_database_assets_worktree(self):
        for rel in ["sessions/active.jsonl", "archived_sessions/old.jsonl", "memories/x.log",
                    "state.sqlite-wal", "skills/cache.log", "generated_images/only.png", "worktrees/x/a.py"]:
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("unique")
            os.utime(p, (0, 0))
        inv = self.inventory()
        self.assertEqual(inv["summary"]["eligible_files"], 1)
        for item in inv["items"]:
            if item["category"] != "log":
                with self.assertRaises(Refused):
                    engine.make_plan(inv, [item["id"]], self.state, max_bytes=100000)

    def test_symlink_hardlink_keep_and_retention(self):
        (self.log.parent / "alias.log").symlink_to(self.log)
        os.link(self.log, self.log.parent / "hard.log")
        self.assertEqual(self.inventory()["summary"]["eligible_files"], 0)
        (self.log.parent / "hard.log").unlink()
        self.assertEqual(scan([("codex", self.root)], keep=["*.log"])["summary"]["eligible_files"], 0)
        os.utime(self.log, None)
        self.assertEqual(self.inventory()["summary"]["eligible_files"], 0)

    def test_custom_service_logs_cannot_enter_cleanup(self):
        for relative in ("logs/custom-service.err.log", "log/unrelated.log", "logs/nested/codex-tui.log"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("private service diagnostic")
            os.utime(path, (0, 0))
        inv = self.inventory()
        self.assertEqual(inv["summary"]["eligible_files"], 1)
        for item in inv["items"]:
            if item["relative"] != "logs/codex-tui.log":
                self.assertEqual(item["category"], "protected")
                with self.assertRaises(Refused):
                    engine.make_plan(inv, [item["id"]], self.state, max_bytes=100000)
    def test_plan_tamper_expiry_cap_and_wrong_approval(self):
        plan = self.plan()
        with self.assertRaises(Refused):
            engine.apply(plan, "wrong", quiescent=True)
        plan["max_bytes"] += 1
        with self.assertRaises(Refused):
            engine.apply(plan, plan["hash"], quiescent=True)
        plan = self.plan()
        plan["expires_at"] = 0
        plan["hash"] = engine.seal(plan)
        with self.assertRaises(Refused):
            engine.apply(plan, plan["hash"], quiescent=True)
        inv = self.inventory()
        with self.assertRaises(Refused):
            engine.make_plan(inv, [inv["items"][0]["id"]], self.state, max_bytes=1)

    def test_changed_content_blocks_apply(self):
        plan = self.plan()
        original = self.log.stat()
        self.log.write_bytes(b"X" * original.st_size)
        os.utime(self.log, ns=(original.st_atime_ns, original.st_mtime_ns))
        with self.assertRaises(Refused):
            engine.apply(plan, plan["hash"], quiescent=True)
        self.assertTrue(self.log.exists())

    def test_parent_symlink_swap_blocked(self):
        plan = self.plan()
        moved = self.root / "moved"
        self.log.parent.rename(moved)
        self.log.parent.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(OSError):
            engine.apply(plan, plan["hash"], quiescent=True)
        self.assertTrue((moved / "codex-tui.log").exists())

    def test_quarantine_restore_and_replay(self):
        original = self.log.read_bytes()
        plan, result = self.apply()
        self.assertFalse(self.log.exists())
        self.assertEqual(result["immediate_reclaimed_bytes"], 0)
        self.assertTrue(engine.verify(self.state, plan["hash"])["ok"])
        with self.assertRaises(Refused):
            engine.apply(plan, plan["hash"], quiescent=True)
        engine.restore(self.state, plan["hash"], quiescent=True)
        self.assertEqual(self.log.read_bytes(), original)
        self.assertTrue(engine.verify(self.state, plan["hash"])["ok"])
        self.assertEqual(engine.restore(self.state, plan["hash"], quiescent=True)["files"], 0)

    def test_restore_no_clobber(self):
        plan, _ = self.apply()
        self.log.write_text("new work")
        with self.assertRaises(Refused):
            engine.restore(self.state, plan["hash"], quiescent=True)
        self.assertEqual(self.log.read_text(), "new work")

    def test_purge_requires_separate_approval(self):
        plan, _ = self.apply()
        with self.assertRaises(Refused):
            engine.purge(self.state, plan["hash"], plan["hash"], quiescent=True)
        result = engine.purge(self.state, plan["hash"], "purge:" + plan["hash"], quiescent=True)
        self.assertGreater(result["deleted_logical_bytes"], 0)
        self.assertTrue(engine.verify(self.state, plan["hash"])["ok"])
        with self.assertRaises(Refused):
            engine.restore(self.state, plan["hash"], quiescent=True)

    def test_open_file_prevents_apply(self):
        plan = self.plan()
        with self.log.open():
            with self.assertRaises(Refused):
                engine.apply(plan, plan["hash"], quiescent=True)
        self.assertTrue(self.log.exists())

    def test_missing_lsof_fail_closed(self):
        plan = self.plan()
        with patch("vibe_cleaner.engine.shutil.which", return_value=None):
            with self.assertRaises(Refused):
                engine.apply(plan, plan["hash"], quiescent=True)

    def test_capacity_and_stopped_writer_gate(self):
        plan = self.plan()
        for kwargs in ({"quiescent": False}, {"quiescent": True, "state_cap": 1}):
            with self.assertRaises(Refused):
                engine.apply(plan, plan["hash"], **kwargs)
        self.assertTrue(self.log.exists())

    def test_interrupted_rename_recoverable(self):
        plan = self.plan()
        real_rename = os.rename
        def crash(*args, **kwargs):
            real_rename(*args, **kwargs)
            raise OSError("injected crash after rename")
        with patch("vibe_cleaner.engine.os.rename", side_effect=crash):
            with self.assertRaises(OSError):
                engine.apply(plan, plan["hash"], quiescent=True)
        self.assertTrue(engine.verify(self.state, plan["hash"])["ok"])
        engine.restore(self.state, plan["hash"], quiescent=True)
        self.assertTrue(self.log.exists())

    def test_interrupted_restore_link_recoverable(self):
        plan, _ = self.apply()
        real_link = os.link
        def crash(src, dst, **kwargs):
            real_link(src, dst, **kwargs)
            if isinstance(dst, str) and dst == "codex-tui.log":
                raise OSError("injected after restore link")
        with patch("vibe_cleaner.engine.os.link", side_effect=crash):
            with self.assertRaises(OSError):
                engine.restore(self.state, plan["hash"], quiescent=True)
        engine.restore(self.state, plan["hash"], quiescent=True)
        self.assertTrue(engine.verify(self.state, plan["hash"])["ok"])

    def test_bytecode_requires_tracked_source_and_ignored_cache(self):
        import py_compile
        root = self.base / "project"
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        source = root / "main.py"
        source.write_text("x = 1\n")
        cache = Path(py_compile.compile(str(source)))
        os.utime(cache, (0, 0))
        inv = scan([("project", root)])
        item = next(i for i in inv["items"] if i["category"] == "bytecode")
        with self.assertRaises(Refused):
            engine.make_plan(inv, [item["id"]], self.state, max_bytes=10000)
        (root / ".gitignore").write_text("__pycache__/\n")
        subprocess.run(["git", "-C", str(root), "add", "main.py"], check=True)
        plan = engine.make_plan(inv, [item["id"]], self.state, max_bytes=10000)
        self.assertEqual(plan["items"][0]["category"], "bytecode")

    def test_backup_extract_and_preserve_original(self):
        session = self.root / "sessions" / "a.jsonl"
        session.parent.mkdir()
        session.write_text('{"synthetic":true}\n')
        inv = self.inventory()
        item = next(i for i in inv["items"] if i["category"] == "session")
        archive = self.base / "snapshot.zip"
        result = backup.backup(inv, [item["id"]], archive, max_bytes=10000)
        self.assertFalse(result["harness_resume_verified"])
        backup.extract(archive, self.base / "extracted")
        self.assertEqual((self.base / "extracted/0").read_bytes(), session.read_bytes())
        self.assertTrue(session.exists())
        with self.assertRaises(Refused):
            backup.extract(archive, self.base / "extracted")

    def test_zip_path_traversal_rejected(self):
        archive = self.base / "evil.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("../outside", "bad")
        write(archive.with_suffix(".zip.manifest.json"), {"files": [{"member": "../outside"}]})
        with self.assertRaises(Refused):
            backup.extract(archive, self.base / "out")
        self.assertFalse((self.base / "outside").exists())

    def test_incomplete_scan_is_disclosed(self):
        (self.root / "other").write_text("x")
        self.assertFalse(scan([("codex", self.root)], max_files=1)["complete"])

    def test_destination_synced_before_first_rename(self):
        plan = self.plan()
        events = []
        real_sync, real_rename = engine.sync_dir, os.rename
        def synced(path):
            events.append(("sync", path))
            return real_sync(path)
        def renamed(*args, **kwargs):
            self.assertIn(("sync", self.state), events)
            self.assertIn(("sync", self.state.parent), events)
            return real_rename(*args, **kwargs)
        with patch("vibe_cleaner.engine.sync_dir", side_effect=synced), patch("vibe_cleaner.engine.os.rename", side_effect=renamed):
            engine.apply(plan, plan["hash"], quiescent=True)

    def test_purge_resume_preserves_cumulative_accounting(self):
        plan, _ = self.apply()
        real_unlink = os.unlink
        def crash(path, *args, **kwargs):
            real_unlink(path, *args, **kwargs)
            if str(path) == "0":
                raise OSError("injected after unlink")
        with patch("vibe_cleaner.engine.os.unlink", side_effect=crash):
            with self.assertRaises(OSError):
                engine.purge(self.state, plan["hash"], "purge:" + plan["hash"], quiescent=True)
        result = engine.purge(self.state, plan["hash"], "purge:" + plan["hash"], quiescent=True)
        self.assertEqual(result["deleted_logical_bytes"], plan["items"][0]["identity"]["size"])
        self.assertEqual(result["this_attempt_logical_bytes"], 0)

    def test_resumed_purge_rejects_broken_symlink(self):
        plan, _ = self.apply()
        directory = self.state / plan["hash"]
        journal = load(directory / "journal.json")
        journal["status"] = "purging"
        write(directory / "journal.json", journal, overwrite=True)
        (directory / "0").unlink()
        (directory / "0").symlink_to(directory / "missing")
        with self.assertRaises(OSError):
            engine.purge(self.state, plan["hash"], "purge:" + plan["hash"], quiescent=True)

    def test_restore_revalidates_after_preflight(self):
        plan, _ = self.apply()
        target = self.state / plan["hash"] / "0"
        original = target.read_bytes()
        def replace(_items):
            target.unlink()
            target.write_bytes(b"replacement")
        with patch("vibe_cleaner.engine.idle_check", side_effect=replace):
            with self.assertRaises(Refused):
                engine.restore(self.state, plan["hash"], quiescent=True)
        self.assertFalse(self.log.exists())
        self.assertNotEqual(target.read_bytes(), original)

    def test_extract_capacity_before_writing(self):
        archive = self.base / "large.zip"
        write(archive.with_suffix(".zip.manifest.json"), {"files": [{"member": "0", "item": {"identity": {"size": 100}}}]})
        with self.assertRaises(Refused):
            backup.extract(archive, self.base / "too-big", max_bytes=10)
        self.assertFalse((self.base / "too-big").exists())

    def test_scan_does_not_follow_directory_link(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "unique.log").write_text("keep")
        (self.root / "logs/linked").symlink_to(outside, target_is_directory=True)
        inv = self.inventory()
        self.assertFalse(inv["complete"])
        self.assertEqual(len(inv["items"]), 1)

    def test_duplicate_ids_and_root_traversal_refused(self):
        inv = self.inventory()
        item = inv["items"][0]
        with self.assertRaises(Refused):
            engine.make_plan(inv, [item["id"], item["id"]], self.state, max_bytes=10000)
        item["relative"] = "logs/../../outside.log"
        with self.assertRaises(Refused):
            engine.make_plan(inv, [item["id"]], self.state, max_bytes=10000)

    def test_jev_metadata_no_path_or_content_and_valid_response(self):
        items = self.inventory()["items"]
        def transport(request, timeout):
            raw = request.data.decode()
            self.assertNotIn(str(self.root), raw)
            self.assertNotIn("codex-tui.log", raw)
            self.assertNotIn("synthetic diagnostic", raw)
            return {"model": "jev-test", "answers": {"c0": {"type": "choice", "choice": "review",
                    "probabilities": {"keep": 0.1, "review": 0.9}, "confidence": 0.7}},
                    "usage": {"input_tokens": 100, "output_tokens": 10}}
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-only"}):
            result = jev.advise(items, enabled=True, transport=transport)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["mode"], "advisory-only")

    def test_jev_local_evidence_rechecks_real_files_and_open_handles(self):
        inv = self.inventory()
        rows = jev.local_evidence(inv["items"], inv, inspect_activity=True)
        self.assertIn("delete", jev.packet(rows)["questions"]["c0"]["criteria"])
        with self.log.open("rb"):
            rows = jev.local_evidence(inv["items"], inv, inspect_activity=True)
            self.assertNotIn("delete", jev.packet(rows)["questions"]["c0"]["criteria"])
        self.log.write_text("changed after scan")
        rows = jev.local_evidence(inv["items"], inv, inspect_activity=True)
        self.assertNotIn("delete", jev.packet(rows)["questions"]["c0"]["criteria"])

    def test_jev_local_keep_credentials_and_lsof_failure(self):
        kept = scan([("codex", self.root)], keep=["*.log"])
        rows = jev.local_evidence(kept["items"], kept, inspect_activity=True)
        self.assertNotIn("delete", jev.packet(rows)["questions"]["c0"]["criteria"])
        inv = self.inventory()
        for failure in [Refused("inconclusive"), subprocess.TimeoutExpired("lsof", 10)]:
            with patch("vibe_cleaner.jev.idle_check", side_effect=failure):
                rows = jev.local_evidence(inv["items"], inv, inspect_activity=True)
            self.assertNotIn("delete", jev.packet(rows)["questions"]["c0"]["criteria"])
        credential = self.root / "auth.json"
        credential.write_text("synthetic credential placeholder")
        inv = self.inventory()
        item = next(i for i in inv["items"] if i["relative"] == "auth.json")
        item["eligible"] = True
        rows = jev.local_evidence([item], inv, inspect_activity=True)
        self.assertEqual(set(jev.packet(rows)["questions"]["c0"]["criteria"]), {"keep", "review"})

    def test_jev_untracked_bytecode_source_cannot_get_delete_advice(self):
        source = self.root / "example.py"
        source.write_text("print('synthetic')\n")
        compiled = Path(py_compile.compile(str(source), doraise=True))
        os.utime(compiled, (0, 0))
        inv = scan([("project", self.root)])
        item = next(i for i in inv["items"] if i["category"] == "bytecode")
        rows = jev.local_evidence([item], inv, inspect_activity=True)
        self.assertNotIn("delete", jev.packet(rows)["questions"]["c0"]["criteria"])

    def test_jev_service_failure_and_malformed_answer_fail_closed(self):
        items = self.inventory()["items"]
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-only"}):
            for code in [401, 403, 429, 503]:
                def transport(*args):
                    raise urllib.error.HTTPError("https://example.invalid", code, "failure", {}, None)
                self.assertEqual(jev.advise(items, enabled=True, transport=transport)["mode"], "rules-only")
            for response in [{}, {"model": "wrong"}, {"model": "jev-test", "answers": {}},
                             {"model": "jev-test", "answers": {"c0": {"choice": "delete"}}}]:
                self.assertEqual(jev.advise(items, enabled=True, transport=lambda *a: response)["mode"], "rules-only")
        self.assertEqual(jev.advise(items)["calls"], 0)

    def test_private_atomic_json_no_clobber(self):
        path = self.base / "result.json"
        write(path, {"ok": True})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            write(path, {"ok": False})
        self.assertTrue(load(path)["ok"])


if __name__ == "__main__":
    unittest.main()
