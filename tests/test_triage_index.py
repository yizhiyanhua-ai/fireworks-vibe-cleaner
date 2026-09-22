"""Selected Codex index facts; all homes and transcripts are synthetic and local."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from vibe_cleaner import triage_evidence
from vibe_cleaner.common import Refused
from vibe_cleaner.scan import scan, transcript_id


class IndexFixture:
    """Minimal supported native schema, with nullable legacy millisecond timestamps."""
    def __init__(self, root):
        self.root = root.resolve()
        self.root.mkdir(parents=True)
        self.database = self.root / "state_5.sqlite"
        self.db = sqlite3.connect(self.database)
        self.db.executescript("""
            CREATE TABLE threads(id TEXT PRIMARY KEY, rollout_path TEXT, updated_at INTEGER,
                updated_at_ms INTEGER, archived INTEGER, is_pinned INTEGER, source TEXT);
            CREATE TABLE thread_spawn_edges(parent_thread_id TEXT, child_thread_id TEXT PRIMARY KEY,
                status TEXT);
            CREATE INDEX idx_thread_spawn_edges_parent_status
                ON thread_spawn_edges(parent_thread_id, status);
        """)
        self.old = int(time.time()) - 60 * 86400

    def add(self, number, *, pinned=False, archived=False, parent=None, edge=False):
        uid = f"10000000-0000-0000-0000-{number:012x}"
        source = {"subAgent": {"thread_spawn": {"parent_thread_id": parent}}} if parent else "cli"
        path = self.root / ("archived_sessions" if archived else "sessions/2025/01/01") / (
            "rollout-2025-01-01T00-00-00-" + uid + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "session_meta", "payload": {"id": uid, "source": source}}) + "\n")
        os.utime(path, (self.old, self.old))
        self.db.execute("INSERT INTO threads VALUES(?,?,?,?,?,?,?)", (
            uid, str(path), self.old, self.old * 1000, int(archived), int(pinned),
            json.dumps(source) if isinstance(source, dict) else source))
        if edge:
            self.db.execute("INSERT INTO thread_spawn_edges VALUES(?,?,?)", (parent, uid, "open"))
        self.db.commit()
        return self.item(path)

    def item(self, path):
        return next(i for i in scan([("codex", self.root)])["items"]
                    if i["relative"] == str(path.relative_to(self.root)))

    def update(self, item, column, value):
        assert column in {"is_pinned", "archived", "rollout_path", "source", "updated_at", "updated_at_ms"}
        self.db.execute(f"UPDATE threads SET {column}=? WHERE id=?", (value, self.uid(item)))
        self.db.commit()

    @staticmethod
    def uid(item):
        return transcript_id(item["relative"], "codex")


class TriageIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fvc-triage-index-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.fixture = self.home("first")
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.fixture.root), "CODEX_THREAD_ID": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def home(self, name):
        fixture = IndexFixture(self.base / name)
        self.addCleanup(fixture.db.close)
        return fixture

    def facts(self, item):
        return triage_evidence.index_facts([item], 30)[item["id"]]

    def unknown(self, row):
        self.assertEqual(row["pin"], "unknown")
        self.assertEqual(row["archived"], "unknown")
        self.assertEqual(row["recent_use"], "unknown")
        self.assertNotEqual(row["links"], "no_indexed_links")

    def test_fresh_pin_and_closed_edges_override_earlier_snapshot(self):
        item = self.fixture.add(1)
        child = self.fixture.add(2, parent=self.fixture.uid(item))
        first = self.facts(item)
        self.assertEqual((first["pin"], first["links"], first["recent_use"]),
                         ("unpinned", "no_indexed_links", "old"))
        self.fixture.update(item, "is_pinned", 1)
        self.fixture.db.execute("INSERT INTO thread_spawn_edges VALUES(?,?,?)", (
            self.fixture.uid(item), self.fixture.uid(child), "closed"))
        self.fixture.db.commit()
        rows = triage_evidence.index_facts([item, child], 30)
        self.assertEqual(rows[item["id"]]["pin"], "pinned")
        self.assertEqual(rows[item["id"]]["links"], "linked")
        self.assertEqual(rows[child["id"]]["links"], "linked")
        self.assertEqual(first["pin"], "unpinned")

    def test_header_parent_without_index_edge_remains_linked(self):
        parent = self.fixture.add(1)
        child = self.fixture.add(2, parent=self.fixture.uid(parent))
        self.assertEqual(self.facts(child)["links"], "linked")

    def test_missing_row_schema_and_invalid_pin_never_become_unpinned(self):
        for case in ("missing-row", "missing-pin", "missing-edge-status", "invalid-pin"):
            with self.subTest(case=case):
                fixture = self.home(case)
                item = fixture.add(1)
                if case == "missing-row":
                    fixture.db.execute("DELETE FROM threads")
                elif case == "missing-pin":
                    fixture.db.execute("ALTER TABLE threads RENAME COLUMN is_pinned TO unknown_pin")
                elif case == "missing-edge-status":
                    fixture.db.execute("ALTER TABLE thread_spawn_edges RENAME COLUMN status TO unknown_status")
                else:
                    fixture.update(item, "is_pinned", 2)
                fixture.db.commit()
                self.unknown(self.facts(item))

    def test_path_source_and_header_identity_mismatches_fail_closed(self):
        for case in ("path", "source", "header-id", "replaced-file", "archive-path-state"):
            with self.subTest(case=case):
                fixture = self.home(case)
                item = fixture.add(1)
                path = Path(item["root"]) / item["relative"]
                if case == "path":
                    fixture.update(item, "rollout_path", str(path.with_name("different.jsonl")))
                elif case == "source":
                    fixture.update(item, "source", "vscode")
                elif case == "archive-path-state":
                    fixture.update(item, "archived", 1)
                elif case == "header-id":
                    payload = {"id": "20000000-0000-0000-0000-000000000001", "source": "cli"}
                    path.write_text(json.dumps({"type": "session_meta", "payload": payload}) + "\n")
                    os.utime(path, (fixture.old, fixture.old))
                    item = fixture.item(path)
                else:
                    path.unlink()
                    path.write_text("synthetic replacement with different bytes\n")
                self.unknown(self.facts(item))

    def test_nullable_milliseconds_use_seconds_but_invalid_times_are_unknown(self):
        item = self.fixture.add(1)
        self.fixture.update(item, "updated_at_ms", None)
        self.assertEqual(self.facts(item)["recent_use"], "old")
        now = int(time.time())
        self.fixture.update(item, "updated_at", now)
        self.assertEqual(self.facts(item)["recent_use"], "recent")
        for seconds, millis in ((0, 0), (-1, None), (None, None),
                               (self.fixture.old, 0), (self.fixture.old, "bad"),
                               (self.fixture.old, (self.fixture.old + 2) * 1000),
                               (now + 3600, (now + 3600) * 1000)):
            with self.subTest(seconds=seconds, millis=millis):
                self.fixture.update(item, "updated_at", seconds)
                self.fixture.update(item, "updated_at_ms", millis)
                self.unknown(self.facts(item))

    def test_current_context_is_scoped_to_the_matching_root(self):
        item = self.fixture.add(1)
        other = self.home("other-home")
        same_uuid = other.add(1, pinned=True)
        self.assertNotEqual(item["id"], same_uuid["id"])
        with patch.dict(os.environ, {"CODEX_THREAD_ID": self.fixture.uid(item)}):
            rows = triage_evidence.index_facts([item, same_uuid], 30)
        self.assertEqual(rows[item["id"]]["current_context"], "current")
        self.assertEqual(rows[same_uuid["id"]]["current_context"], "unknown")
        self.assertEqual(rows[item["id"]]["pin"], "unpinned")
        self.assertEqual(rows[same_uuid["id"]]["pin"], "pinned")
        self.assertEqual(self.facts(item)["current_context"], "unknown")

    def test_selected_only_read_only_query_and_transcript_access(self):
        item = self.fixture.add(1)
        unrelated = self.fixture.add(2)
        path = Path(item["root"]) / item["relative"]
        (Path(unrelated["root"]) / unrelated["relative"]).unlink()
        baseline = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.fixture.database, path)}
        statements, opened, connections = [], [], []
        real_connect, real_candidate_fd = sqlite3.connect, triage_evidence.candidate_fd

        def connect(database, *args, **kwargs):
            connections.append((database, kwargs))
            db = real_connect(database, *args, **kwargs)
            db.set_trace_callback(statements.append)
            return db

        def candidate_fd(selected, *args, **kwargs):
            opened.append(selected["id"])
            self.assertEqual(selected["id"], item["id"])
            return real_candidate_fd(selected, *args, **kwargs)

        with patch.object(triage_evidence.sqlite3, "connect", side_effect=connect), \
                patch.object(triage_evidence, "candidate_fd", side_effect=candidate_fd), \
                patch("os.walk", side_effect=AssertionError("whole-home filesystem traversal")):
            self.assertEqual(self.facts(item)["pin"], "unpinned")
        self.assertEqual(opened, [item["id"]])
        self.assertEqual(len(connections), 1)
        self.assertTrue(connections[0][0].endswith("?mode=ro"))
        self.assertTrue(connections[0][1]["uri"])
        self.assertIn("PRAGMA query_only=ON", statements)
        selects = [s.upper() for s in statements if s.lstrip().upper().startswith("SELECT")]
        self.assertTrue(selects)
        self.assertTrue(all(" WHERE " in s for s in selects))
        self.assertFalse(any(s.lstrip().upper().startswith(("UPDATE ", "INSERT ", "DELETE ",
                             "CREATE ", "ALTER ", "DROP ", "REPLACE ")) for s in statements))
        self.assertEqual(baseline, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in baseline})

    def test_unsupported_edge_status_is_never_reported_as_no_links(self):
        parent = self.fixture.add(1)
        child = self.fixture.add(2, parent=self.fixture.uid(parent), edge=True)
        self.fixture.db.execute("UPDATE thread_spawn_edges SET status='future-unknown-status'")
        self.fixture.db.commit()
        rows = triage_evidence.index_facts([parent, child], 30)
        self.assertTrue(all(r["links"] in {"linked", "unknown"} for r in rows.values()))

    def test_valid_archived_record_is_observation_not_current_or_idle_proof(self):
        item = self.fixture.add(1, archived=True)
        row = self.facts(item)
        self.assertEqual(row["archived"], "yes")
        self.assertEqual(row["current_context"], "unknown")
        self.assertEqual(row["scope"], "selected-index-snapshot")
        self.assertNotIn("executable", row)
        self.assertNotIn("idle", row.values())

    def test_bounded_input(self):
        item = self.fixture.add(1)
        with self.assertRaises(Refused):
            triage_evidence.index_facts([item] * 101, 30)
        with self.assertRaises(Refused):
            triage_evidence.index_facts([item], 0)


if __name__ == "__main__":
    unittest.main()
