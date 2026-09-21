"""Synthetic, isolated native-index pressure and protection regressions."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from vibe_cleaner.common import Refused
from vibe_cleaner.history import audit


class HistoryAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vibe-history-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = sqlite3.connect(self.root / "state_5.sqlite")
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE threads(id TEXT PRIMARY KEY, rollout_path TEXT, updated_at INTEGER,
                updated_at_ms INTEGER, archived INTEGER, is_pinned INTEGER, source TEXT);
            CREATE TABLE thread_spawn_edges(parent_thread_id TEXT, child_thread_id TEXT, status TEXT);
        """)
        self.old = int(time.time()) - 60 * 86400

    def add(self, number, *, parent=None, pinned=False, archived=False, header_id=None):
        uid = f"10000000-0000-0000-0000-{number:012x}"
        source = {"subAgent": {"thread_spawn": {"parent_thread_id": parent}}} if parent else "cli"
        path = self.root / ("archived_sessions" if archived else "sessions/2025/01/01") / (
            "rollout-2025-01-01T00-00-00-" + uid + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": header_id or uid, "source": source}}) + "\n")
        os.utime(path, (self.old, self.old))
        self.db.execute("INSERT INTO threads VALUES(?,?,?,?,?,?,?)", (
            uid, str(path), self.old, self.old * 1000, int(archived), int(pinned),
            json.dumps(source) if isinstance(source, dict) else source))
        if parent:
            self.db.execute("INSERT INTO thread_spawn_edges VALUES(?,?,?)", (parent, uid, "open"))
        self.db.commit()
        return uid, path

    def report(self, **kwargs):
        return audit(self.root, keep_recent=kwargs.pop("keep_recent", 0), **kwargs)

    def test_thresholds_count_and_archive_does_not_reclaim(self):
        one, path = self.add(1)
        self.add(2, archived=True)
        original = path.read_bytes()
        r = self.report(total_bytes=1, single_bytes=1, count_limit=1)
        self.assertTrue(r["complete"])
        self.assertEqual(r["summary"]["unarchived_threads"], 1)
        self.assertEqual(r["summary"]["archived_threads"], 1)
        self.assertEqual(r["summary"]["triggers"], {
            "total_bytes_exceeded": True, "single_session_exceeded": True,
            "unarchived_count_exceeded": False})
        self.assertEqual(r["native_candidates"], [one])
        self.assertEqual(r["summary"]["native_archive_reclaim_bytes"], 0)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.db.execute("SELECT sum(archived) FROM threads").fetchone()[0], 1)

    def test_pinned_archived_child_blocks_parent(self):
        parent, _ = self.add(1)
        self.add(2, parent=parent, archived=True, pinned=True)
        self.assertEqual(self.report()["native_candidates"], [])

    def test_pinned_shared_descendant_blocks_other_parent(self):
        pinned, _ = self.add(1, pinned=True)
        other, _ = self.add(2)
        child, _ = self.add(3, parent=pinned)
        self.db.execute("INSERT INTO thread_spawn_edges VALUES(?,?,?)", (other, child, "closed"))
        self.db.commit()
        r = self.report()
        self.assertFalse(r["complete"])
        self.assertEqual(r["native_candidates"], [])

    def test_recent_conflicting_timestamp_and_keep_rules(self):
        uid, _ = self.add(1)
        self.assertEqual(self.report(keep_ids=[uid])["native_candidates"], [])
        self.assertEqual(self.report(keep_recent=1)["native_candidates"], [])
        self.db.execute("UPDATE threads SET updated_at=?", (int(time.time()),))
        self.db.commit()
        r = self.report()
        self.assertEqual(r["native_candidates"], [])
        self.assertIn("inconsistent-native-update-times", r["threads"][0]["protection_reasons"])

    def test_header_mismatch_is_not_an_archive_candidate(self):
        self.add(1, header_id="20000000-0000-0000-0000-000000000099")
        r = self.report()
        self.assertFalse(r["complete"])
        self.assertEqual(r["native_candidates"], [])
        self.assertEqual(r["summary"]["measured_files"], 1)
        self.assertGreater(r["summary"]["known_logical_bytes"], 0)

    def test_cycle_and_unknown_edge_status_are_protected(self):
        first, _ = self.add(1)
        second, _ = self.add(2, parent=first)
        self.db.execute("INSERT INTO thread_spawn_edges VALUES(?,?,?)", (second, first, "future-value"))
        self.db.commit()
        r = self.report()
        self.assertFalse(r["complete"])
        self.assertGreater(r["summary"]["lineage_issues"], 0)
        self.assertEqual(r["native_candidates"], [])

    def test_missing_file_and_symlink_do_not_silently_reduce_index_count(self):
        self.add(1)
        _, path = self.add(2)
        path.unlink()
        r = self.report(count_limit=1)
        self.assertEqual(r["summary"]["unarchived_threads"], 2)
        self.assertTrue(r["summary"]["triggers"]["unarchived_count_exceeded"])
        self.assertFalse(r["complete"])
        external = self.root / "external.jsonl"
        external.write_text("private fixture")
        path.symlink_to(external)
        r = self.report()
        self.assertEqual(r["summary"]["missing_or_unsafe_files"], 1)

    def test_unknown_schema_and_bounds_refuse(self):
        with self.assertRaises(Refused):
            self.report(count_limit=0)
        self.db.execute("ALTER TABLE threads RENAME COLUMN is_pinned TO unknown_pin")
        self.db.commit()
        with self.assertRaises(Refused):
            self.report()


if __name__ == "__main__":
    unittest.main()
