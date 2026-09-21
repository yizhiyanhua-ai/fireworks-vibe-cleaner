"""Synthetic indexed fixtures; native transport is replaced except in the separate canary."""
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from vibe_cleaner import history, native_history as native
from vibe_cleaner.codex_rpc import CodexRPC, environment, executable_record
from vibe_cleaner.common import Refused


class NativeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vibe-native-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "codex"
        self.root.mkdir()
        self.state = self.base / "state"
        self.ids = [f"01940000-0000-7000-8000-{n:012d}" for n in range(1, 5)]
        self.db = self.root / "state_5.sqlite"
        self.original = {}
        with contextlib.closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TABLE threads(id TEXT PRIMARY KEY,rollout_path TEXT,updated_at INTEGER,"
                       "updated_at_ms INTEGER,archived INTEGER,is_pinned INTEGER,source TEXT)")
            db.execute("CREATE TABLE thread_spawn_edges(parent_thread_id TEXT,child_thread_id TEXT,status TEXT)")
            for n, ident in enumerate(self.ids):
                source = ({"subagent": {"thread_spawn": {"parent_thread_id": self.ids[n-1], "depth": n,
                           "agent_path": None, "agent_nickname": None, "agent_role": None}}} if n in (1, 2) else "cli")
                path = self.root / "sessions/2025/01/01" / f"rollout-2025-01-01T00-00-00-{ident}.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                raw = (json.dumps({"type": "session_meta", "payload": {"id": ident, "source": source}}) + "\n").encode()
                path.write_bytes(raw)
                path.chmod(0o600)
                old = int(time.time()) - 90 * 86400
                os.utime(path, (old, old))
                self.original[ident] = (path, raw)
                db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?)",
                           (ident, str(path), old, old * 1000, 0, 0, source if isinstance(source, str) else json.dumps(source)))
                if n in (1, 2):
                    db.execute("INSERT INTO thread_spawn_edges VALUES (?,?,?)", (self.ids[n-1], ident, "open"))
        self.calls = []
        self.fail_after_archive = False
        test = self

        class FakeRPC:
            def __init__(self, runtime):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def descendants(self, ident, *, archived, cap):
                inv = test.audit()
                wanted = history.descendants(ident, inv["edges"]) - {ident}
                return {r["id"] for r in inv["threads"] if r["id"] in wanted and r["archived"] == archived}

            def request(self, method, params):
                ident = params["threadId"]
                inv = test.audit()
                rows = {r["id"]: r for r in inv["threads"]}
                if method == "thread/read":
                    return {"thread": {"id": ident, "status": {"type": "notLoaded"},
                            "path": str(test.root / rows[ident]["relative"])}}
                journal_paths = list(test.state.glob("*/journal.json"))
                test.assertEqual(len(journal_paths), 1)
                journal = json.loads(journal_paths[0].read_text())
                test.assertEqual(journal["events"][-1]["status"],
                                 "archive-intent" if method == "thread/archive" else "unarchive-intent")
                test.calls.append((method, ident))
                affected = history.descendants(ident, inv["edges"]) if method == "thread/archive" else {ident}
                with contextlib.closing(sqlite3.connect(test.db)) as db, db:
                    for value in affected:
                        before = test.root / rows[value]["relative"]
                        archived = method == "thread/archive"
                        if rows[value]["archived"] == archived:
                            continue
                        after = test.root / "archived_sessions" / before.name if archived else test.original[value][0]
                        after.parent.mkdir(parents=True, exist_ok=True)
                        before.rename(after)
                        db.execute("UPDATE threads SET archived=?,rollout_path=? WHERE id=?", (int(archived), str(after), value))
                        if archived:
                            db.execute("UPDATE threads SET updated_at_ms=updated_at_ms+1 WHERE id=?", (value,))
                        else:
                            now = time.time()
                            os.utime(after, (now, now))
                            db.execute("UPDATE threads SET updated_at=?,updated_at_ms=? WHERE id=?",
                                       (int(now), int(now * 1000), value))
                if method == "thread/archive" and test.fail_after_archive:
                    raise Refused("Synthetic lost response after completed archival")
                return {} if method == "thread/archive" else {"thread": {"id": ident}}

        self.addCleanup(patch.stopall)
        patch.object(native, "CodexRPC", FakeRPC).start()
        patch.object(native, "idle_check", lambda items: None).start()
        patch.object(native, "executable_record", lambda codex, root, home: {
            "path": "/synthetic/codex", "version": "codex-cli 0.154.0",
            "codex_home": str(root), "home": str(home),
        }).start()

    def audit(self):
        return history.audit(self.root, keep_recent=0)

    def plan(self):
        return native.make_plan(self.audit(), [self.ids[0]], self.state)

    def test_exact_closure_journal_roundtrip_and_replay(self):
        plan = self.plan()
        self.assertEqual(plan["changed_ids"], self.ids[:3])
        self.assertEqual(len(plan["edges"]), 2)
        for approval, stopped in (("wrong", True), (plan["hash"], False)):
            with self.assertRaises(Refused):
                native.apply(plan, approval, quiescent=stopped)
        native.apply(plan, plan["hash"], quiescent=True)
        self.assertTrue(native.verify(self.state, plan["hash"])["ok"])
        self.assertEqual(self.calls, [("thread/archive", self.ids[0])])
        self.assertFalse(self.original[self.ids[0]][0].exists())
        self.assertEqual(self.original[self.ids[3]][0].read_bytes(), self.original[self.ids[3]][1])
        with self.assertRaises(Refused):
            native.apply(plan, plan["hash"], quiescent=True)
        with self.assertRaises(Refused):
            native.restore(self.state, plan["hash"], plan["hash"], quiescent=True)
        native.restore(self.state, plan["hash"], "unarchive:" + plan["hash"], quiescent=True)
        self.assertEqual(self.calls[1:], [("thread/unarchive", i) for i in self.ids[:3]])
        self.assertTrue(native.verify(self.state, plan["hash"])["ok"])
        for path, raw in self.original.values():
            self.assertEqual(path.read_bytes(), raw)

    def test_pinned_descendant_and_changed_lineage_fail_closed(self):
        plan = self.plan()
        with contextlib.closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE threads SET is_pinned=1 WHERE id=?", (self.ids[1],))
        with self.assertRaises(Refused):
            self.plan()
        with self.assertRaises(Refused):
            native.apply(plan, plan["hash"], quiescent=True)
        with contextlib.closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE threads SET is_pinned=0")
            db.execute("INSERT INTO thread_spawn_edges VALUES (?,?,?)", (self.ids[2], self.ids[3], "closed"))
        with self.assertRaises(Refused):
            native.apply(plan, plan["hash"], quiescent=True)
        self.assertEqual(self.calls, [])
        for path, raw in self.original.values():
            self.assertEqual(path.read_bytes(), raw)

    def test_lost_archive_response_requires_verified_explicit_recovery(self):
        plan = self.plan()
        self.fail_after_archive = True
        with self.assertRaises(Refused):
            native.apply(plan, plan["hash"], quiescent=True)
        result = native.verify(self.state, plan["hash"])
        self.assertEqual(result["status"], "interrupted")
        self.assertFalse(result["ok"])
        self.assertTrue(all(r["archived"] for r in result["items"]))
        native.restore(self.state, plan["hash"], "unarchive:" + plan["hash"], quiescent=True)
        self.assertTrue(native.verify(self.state, plan["hash"])["ok"])

    def test_incomplete_unrelated_record_blocks_plan_and_apply(self):
        plan = self.plan()
        self.original[self.ids[3]][0].unlink()
        self.assertFalse(self.audit()["complete"])
        with self.assertRaises(Refused):
            self.plan()
        with self.assertRaises(Refused):
            native.apply(plan, plan["hash"], quiescent=True)
        self.assertEqual(self.calls, [])

    def test_dangling_destination_link_blocks_archive_and_recovery(self):
        original = self.original[self.ids[0]][0]
        archived = self.root / "archived_sessions" / original.name
        archived.parent.mkdir()
        archived.symlink_to(self.base / "absent-target")
        with self.assertRaises(Refused):
            self.plan()
        archived.unlink()
        plan = self.plan()
        archived.symlink_to(self.base / "absent-target")
        with self.assertRaises(Refused):
            native.apply(plan, plan["hash"], quiescent=True)
        self.assertEqual(self.calls, [])
        archived.unlink()
        native.apply(plan, plan["hash"], quiescent=True)
        original.symlink_to(self.base / "absent-target")
        with self.assertRaises(Refused):
            native.restore(self.state, plan["hash"], "unarchive:" + plan["hash"], quiescent=True)
        self.assertEqual(self.calls, [("thread/archive", self.ids[0])])
        self.assertTrue(original.is_symlink())

    def test_transport_cannot_start_turns_or_inherit_provider_environment(self):
        with self.assertRaises(Refused):
            CodexRPC({}).request("turn/start", {})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-secret", "CODEX_THREAD_ID": "unrelated"}):
            env = environment(self.root, self.base / "private-home")
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CODEX_THREAD_ID", env)

    def test_unrecognized_launcher_is_never_bound_as_native_binary(self):
        (self.base / "bin").mkdir()
        launcher = self.base / "bin/codex"
        launcher.write_text("#!/bin/sh\necho codex-cli 0.154.0\n")
        launcher.chmod(0o700)
        with self.assertRaisesRegex(Refused, "native Mach-O"):
            executable_record(launcher, self.root, self.base / "private-home")

    def test_safe_archived_descendant_stays_archived_and_pinned_one_blocks(self):
        ident = self.ids[2]
        original, raw = self.original[ident]
        archived = self.root / "archived_sessions" / original.name
        archived.parent.mkdir()
        original.rename(archived)
        with contextlib.closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE threads SET archived=1,is_pinned=1,rollout_path=? WHERE id=?", (str(archived), ident))
        with self.assertRaises(Refused):
            self.plan()
        with contextlib.closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE threads SET is_pinned=0 WHERE id=?", (ident,))
        plan = self.plan()
        self.assertEqual(plan["changed_ids"], self.ids[:2])
        native.apply(plan, plan["hash"], quiescent=True)
        native.restore(self.state, plan["hash"], "unarchive:" + plan["hash"], quiescent=True)
        self.assertTrue(native.verify(self.state, plan["hash"])["ok"])
        self.assertEqual(archived.read_bytes(), raw)
        self.assertNotIn(("thread/unarchive", ident), self.calls)


if __name__ == "__main__":
    unittest.main()
