"""Synthetic contracts for fast triage; never call a real provider or executor.

Decisions expose a short action and a fixed joint ``reason_code``. Transport
responses are derived from each packet's allowed criteria; provider text never
becomes a local instruction or an explanation displayed to the user.
"""

import contextlib
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from vibe_cleaner import triage
from vibe_cleaner.common import Refused
from vibe_cleaner.scan import scan


ACTIONS = {
    "keep_in_place", "review_uncertain", "backup_preserve_history",
    "prepare_verified_removal", "prepare_disposable_cleanup",
}
SAFE = {"keep_in_place", "review_uncertain"}


class TriageContract(unittest.TestCase):
    def test_interrupt_cancels_queued_calls(self):
        for n in range(100):
            self.transcript(n)
        inventory = self.inventory()
        release = threading.Event()
        lock = threading.Lock()
        calls = []
        cancellations = []

        class ObservedPool(ThreadPoolExecutor):
            def shutdown(self, wait=True, *, cancel_futures=False):
                cancellations.append(cancel_futures)
                # run() cancels queued futures before releasing these active calls.
                release.set()
                return super().shutdown(wait=wait, cancel_futures=cancel_futures)

        def interrupted(request, timeout):
            with lock:
                first = not calls
                calls.append(1)
            if first:
                raise KeyboardInterrupt()
            if not release.wait(3):
                raise TimeoutError()
            return self.answer(json.loads(request.data))

        with patch.object(triage, "ThreadPoolExecutor", ObservedPool):
            with self.assertRaises(KeyboardInterrupt):
                triage.run(inventory, limit=100, enabled=True, transport=interrupted)
        self.assertEqual(cancellations, [True])
        self.assertLessEqual(len(calls), 1 + triage.MAX_WORKERS)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fvc-triage-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "codex-private-fixture"
        self.root.mkdir()
        self.secret = "PRIVATE-TRANSCRIPT-CONTENT-NOT-FOR-PROVIDER-69371"
        self.key = "synthetic-typesafe-test-key-never-output"
        self.paths = []
        self.original = {}
        self.calls = []
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"TYPESAFE_API_KEY": self.key}).start()
        # A missed transport injection must fail locally before any request.
        patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("real network forbidden")).start()

    def transcript(self, n=0, *, source="cli", linked=False, age_days=90):
        uid = f"12345678-1234-4321-abcd-{n:012d}"
        path = self.root / f"sessions/2025/01/01/rollout-2025-01-01T00-00-00-{uid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {"id": uid, "source": source, "originator": self.secret}
        if linked:
            metadata["parent_thread_id"] = "private-parent-identity"
        raw = (json.dumps({"type": "session_meta", "payload": metadata}) + "\n" +
               json.dumps({"type": "event_msg", "payload": {"message": self.secret}}) + "\n").encode()
        path.write_bytes(raw)
        path.chmod(0o600)
        old = time.time_ns() - age_days * 86400 * 10**9
        os.utime(path, ns=(old, old))
        self.paths.append(path)
        self.original[path] = raw
        return path

    def inventory(self):
        return scan([("codex", self.root)], min_age_days=30)

    def protected(self):
        path = self.root / "auth.json"
        raw = json.dumps({"api_key": self.secret}).encode()
        path.write_bytes(raw)
        path.chmod(0o600)
        self.original[path] = raw
        return path

    def rows(self, inventory):
        return triage.evidence(inventory["items"], inventory)

    def action(self, choice):
        matches = [a for a in ACTIONS if choice.startswith(a)]
        self.assertEqual(len(matches), 1, f"Unknown or ambiguous joint choice key: {choice}")
        return matches[0]

    def actions(self, question):
        self.assertEqual(question["type"], "choice")
        return {self.action(key) for key in question["criteria"]}

    def answer(self, request, preferred="review_uncertain", confidence=1.0):
        answers = {}
        for ident, question in request["questions"].items():
            choices = list(question["criteria"])
            matching = [key for key in choices if self.action(key) == preferred]
            self.assertTrue(matching, f"Expected preparatory choice {preferred} to be allowed")
            choice = matching[0]
            answers[ident] = {"type": "choice", "choice": choice, "confidence": confidence,
                              "probabilities": {key: float(key == choice) for key in choices}}
        return {"model": "jev-test", "answers": answers,
                "usage": {"input_tokens": 7, "output_tokens": 3}}

    def transport(self, preferred="review_uncertain", confidence=1.0):
        def respond(request, timeout):
            body = request.data.decode()
            for value in (str(self.root), self.secret, self.key, "rollout-", "auth.json"):
                self.assertNotIn(value, body)
            self.assertLessEqual(len(request.data), 16384)
            parsed = json.loads(body)
            self.assertLessEqual(len(parsed["questions"]), 20)
            self.calls.append(parsed)
            return self.answer(parsed, preferred, confidence)
        return respond

    @contextlib.contextmanager
    def no_hash_or_mutation(self):
        with contextlib.ExitStack() as stack:
            for target in (
                "vibe_cleaner.common.file_hash", "vibe_cleaner.sessions.file_hash",
                "vibe_cleaner.engine.file_hash", "hashlib.file_digest",
                "vibe_cleaner.backup.backup", "vibe_cleaner.backup.extract",
                "vibe_cleaner.engine.make_plan", "vibe_cleaner.engine.apply", "vibe_cleaner.engine.purge",
                "vibe_cleaner.sessions.make_plan", "vibe_cleaner.sessions.apply", "vibe_cleaner.sessions.restore",
                "vibe_cleaner.native_history.make_plan", "vibe_cleaner.native_history.apply",
            ):
                stack.enter_context(patch(target, side_effect=AssertionError("fast triage cannot hash or execute")))
            yield

    def nonexecuting(self, result):
        self.assertIs(result["executable"], False)
        self.assertEqual(result["actual_reclaimed_bytes"], 0)
        self.assertEqual(result["provider"]["calls"], len(self.calls))

    def test_packet_whitelist_joint_choice_and_no_input_mutation(self):
        self.transcript()
        inv = self.inventory()
        rows = self.rows(inv)
        rows[0]["facts"].update({"private_path": str(self.root), "prompt": self.secret,
                                 "nested": {"credentials": self.key}})
        before = copy.deepcopy(rows)
        request = triage.packet(rows, goal="balanced")
        raw = json.dumps(request)
        for value in (str(self.root), self.secret, self.key, inv["items"][0]["id"], "rollout-"):
            self.assertNotIn(value, raw)
        self.assertEqual(rows, before)
        self.assertEqual(len(request["questions"]), len(rows))
        self.assertTrue(self.actions(request["questions"]["c0"]) <= ACTIONS)
        # A single fixed Choice binds action and reason; there is no separate free-text question.
        self.assertEqual(set(request["questions"]), {"c0"})
        self.assertNotIn("reason", request["questions"])

    def test_protected_rows_cannot_receive_backup_or_preparation_actions(self):
        self.protected()
        inv = self.inventory()
        inv["items"][0].update(eligible=True, archive_eligible=True, backup_verified=True)
        packet = triage.packet(self.rows(inv))
        self.assertLessEqual(self.actions(packet["questions"]["c0"]), SAFE)

    def test_unknown_packet_category_cannot_be_promoted_by_conflicting_flags(self):
        self.transcript()
        rows = self.rows(self.inventory())
        rows[0]["facts"].update(category="new-unrecognized-scope", protected=False,
                                backup_candidate=True, old_main_header_recognized=True,
                                retention_met=True, disposable_policy_checked=True)
        request = triage.packet(rows)
        self.assertLessEqual(self.actions(request["questions"]["c0"]), SAFE)

    def test_changed_missing_and_symlink_sources_lose_preparatory_actions(self):
        for n in range(3):
            self.transcript(n)
        inv = self.inventory()
        self.paths[0].write_text("changed after scan")
        self.paths[1].unlink()
        self.paths[2].unlink()
        outside = self.base / "outside-synthetic.jsonl"
        outside.write_text(self.secret)
        self.paths[2].symlink_to(outside)
        request = triage.packet(self.rows(inv))
        for question in request["questions"].values():
            self.assertLessEqual(self.actions(question), SAFE)

    def test_only_old_recognized_main_can_offer_verified_removal_preparation(self):
        self.transcript(0)
        self.transcript(1, linked=True)
        self.transcript(2, source="unknown")
        self.transcript(3, age_days=1)
        inv = self.inventory()
        for item in inv["items"]:
            row = self.rows({**inv, "items": [item]})
            actions = self.actions(triage.packet(row)["questions"]["c0"])
            if item["relative"].endswith("000000000000.jsonl"):
                self.assertIn("prepare_verified_removal", actions)
            else:
                self.assertNotIn("prepare_verified_removal", actions)

    def test_preparatory_removal_is_not_execution_and_never_hashes(self):
        self.transcript()
        inv = self.inventory()
        with self.no_hash_or_mutation():
            result = triage.run(inv, enabled=True, transport=self.transport("prepare_verified_removal"))
        self.nonexecuting(result)
        self.assertEqual(result["decisions"][0]["action"], "prepare_removal")
        self.assertEqual(result["decisions"][0]["reason_code"], "prepare_verified_removal")
        self.assertEqual(self.paths[0].read_bytes(), self.original[self.paths[0]])
        rendered = triage.render(result, language="zh")
        self.assertIsInstance(rendered, str)
        self.assertNotIn(self.secret, rendered)
        self.assertNotIn(self.key, rendered)

    def test_unverified_backup_and_forged_activity_are_unknown(self):
        self.transcript()
        inv = self.inventory()
        inv["items"][0].update(backup_state="verified", backup_verified=True,
                                active_state="no_open_handles", writers_stopped=True)
        facts = self.rows(inv)[0]["facts"]
        self.assertEqual(facts["backup_status"], "not_checked")
        self.assertEqual(facts["activity"], "not_checked")
        self.assertEqual(facts["index_pin_and_lineage"], "not_checked")

    def test_forty_decisions_are_batched_without_duplicates_or_scope_loss(self):
        for n in range(40):
            self.transcript(n)
        inv = self.inventory()
        with self.no_hash_or_mutation():
            result = triage.run(inv, limit=40, enabled=True, transport=self.transport("backup_preserve_history"))
        self.nonexecuting(result)
        ids = [d["id"] for d in result["decisions"]]
        self.assertEqual(set(ids), {i["id"] for i in inv["items"]})
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sum(len(call["questions"]) for call in self.calls), 40)
        self.assertGreater(len(self.calls), 1)
        self.assertLess(len(self.calls), 40)

    def test_low_confidence_degrades_to_review_and_provider_text_is_discarded(self):
        self.transcript()
        def transport(request, timeout):
            parsed = json.loads(request.data)
            self.calls.append(parsed)
            result = self.answer(parsed, "prepare_verified_removal", confidence=0.01)
            result["extra"] = self.secret
            for answer in result["answers"].values():
                answer["explanation"] = self.secret
            return result
        result = triage.run(self.inventory(), enabled=True, transport=transport)
        self.nonexecuting(result)
        self.assertEqual(result["decisions"][0]["action"], "review")
        self.assertEqual(result["decisions"][0]["reason_code"], "review_uncertain")
        self.assertNotIn(self.secret, json.dumps(result))
        self.assertNotIn(self.secret, triage.render(result, language="zh"))

    def test_disabled_or_missing_key_does_not_call_transport(self):
        self.transcript()
        inv = self.inventory()
        def forbidden(*args):
            self.fail("network-disabled triage must not call transport")
        for enabled, key in ((False, self.key), (True, "")):
            with self.subTest(enabled=enabled, key_present=bool(key)), patch.dict(os.environ, {"TYPESAFE_API_KEY": key}):
                result = triage.run(inv, enabled=enabled, transport=forbidden)
                self.nonexecuting(result)
                self.assertEqual(len(result["decisions"]), 1)

    def test_bad_provider_answers_or_timeout_fall_back_once_without_leaking_text(self):
        self.transcript()
        inv = self.inventory()
        for case in ("timeout", "forbidden-choice", "missing-answer", "invalid-confidence"):
            with self.subTest(case=case):
                self.calls.clear()
                def transport(request, timeout):
                    parsed = json.loads(request.data)
                    self.calls.append(parsed)
                    if case == "timeout":
                        raise TimeoutError(self.secret)
                    response = self.answer(parsed, "prepare_verified_removal")
                    answer = response["answers"]["c0"]
                    if case == "forbidden-choice":
                        answer["choice"] = "purge_now_without_approval"
                    elif case == "missing-answer":
                        response["answers"].pop("c0")
                    else:
                        answer["confidence"] = float("nan")
                    return response
                result = triage.run(inv, enabled=True, transport=transport)
                self.nonexecuting(result)
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(result["decisions"][0]["action"], "review")
                self.assertEqual(result["decisions"][0]["source"], "local-fallback")
                self.assertNotIn(self.secret, json.dumps(result))

    def test_bad_scope_rejected_before_any_provider_call(self):
        self.transcript()
        inv = self.inventory()
        ident = inv["items"][0]["id"]
        for ids in ([ident, ident], ["not-in-scan"]):
            with self.subTest(ids=ids), self.assertRaises(Refused):
                triage.run(inv, ids=ids, enabled=True, transport=self.transport())
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
