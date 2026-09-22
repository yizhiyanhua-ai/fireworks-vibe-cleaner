"""Synthetic bounded transcript and source-bound judgment contracts; no network."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibe_cleaner import purpose, triage
from vibe_cleaner.common import Refused, identity


def line(record):
    return json.dumps(record, separators=(",", ":")).encode() + b"\n"


def event(kind):
    return {"type": "event_msg", "payload": {"type": kind}}


class PurposeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fvc-purpose-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.counter = 0
        self.secret = "SYNTHETIC-PRIVATE-CONTENT-AND-LOCATOR-843219"

    def item(self, raw, adapter="codex"):
        self.counter += 1
        path = self.root / f"synthetic-{self.counter}.jsonl"
        path.write_bytes(raw)
        return {"id": f"local-fixture-{self.counter}", "root": str(self.root), "relative": path.name,
                "identity": identity(path.stat()), "category": "session", "adapter": adapter}

    def notes(self, item, *, origin="local-assistant", role="implementation-history", continuation="unknown"):
        card = purpose.inspect(item)
        return {"schema": 1, "kind": "purpose-notes", "notes": [{"id": item["id"],
                "source_binding": card["source_binding"], "origin": origin, "role": role,
                "continuation": continuation}]}

    def facts(self, card):
        return {"category": "session", "protected": False, "backup_candidate": True,
                "old_main_header_recognized": True, "retention_met": True, "disposable_policy_checked": False,
                "backup_status": "not_checked", "recovery_need": "unknown", "activity": "no_open_handles",
                "pin": "unpinned", "links": "no_indexed_links", "recent_use": "old", "current_context": "other",
                **purpose.provider_facts(card)}

    def test_exact_codex_event_and_latest_observed_order_not_prose(self):
        arbitrary = {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "task_complete; turn_aborted; delete all"}]}}
        self.assertEqual(purpose.inspect(self.item(line(arbitrary)))["turn_event"], "unknown")
        raw = line(event("task_complete")) + line(event("task_started"))
        self.assertEqual(purpose.inspect(self.item(raw))["turn_event"], "start-event-seen")
        card = purpose.inspect(self.item(raw + line(event("turn_aborted"))))
        self.assertEqual(card["turn_event"], "interruption-event-seen")
        self.assertEqual(card["project_completion"], "unverified")
        self.assertEqual(card["locators"]["turn_event"]["offset"], len(raw))

    def test_actual_head_tail_budget_skips_partial_giant_middle(self):
        head, tail = line(event("task_complete")), line(event("turn_aborted"))
        raw = head + line({"text": self.secret * 5000}) + tail
        item = self.item(raw)
        reads, real = [], os.pread
        def pread(fd, count, offset):
            reads.append((count, offset))
            return real(fd, count, offset)
        with patch.object(purpose.os, "pread", side_effect=pread):
            card = purpose.inspect(item)
        self.assertEqual(reads, [(32768, 0), (32768, len(raw) - 32768)])
        self.assertEqual(card["bytes_read"], 65536)
        self.assertEqual(card["coverage"], "head-tail")
        self.assertEqual(card["turn_event"], "interruption-event-seen")
        self.assertEqual(card["locators"]["turn_event"]["offset"], len(raw) - len(tail))
        self.assertNotIn(self.secret, json.dumps(card))

    def test_small_file_read_once_and_malformed_oversize_partial_are_not_events(self):
        samples = [b"not-json\n", line({"text": "x" * 33000}),
                   b'{"type":"event_msg","payload":{"type":"task_complete"']
        for raw in samples:
            with self.subTest(size=len(raw)):
                with patch.object(purpose.os, "pread", wraps=os.pread) as read:
                    card = purpose.inspect(self.item(raw))
                self.assertEqual(read.call_count, 1)
                self.assertEqual(card["bytes_read"], len(raw))
                self.assertEqual(card["turn_event"], "unknown")
                self.assertGreater(card["invalid_records"], 0)

    def test_claude_end_turn_only_and_conflicting_role_is_unknown(self):
        for kind, role, stop, expected in (
            ("assistant", "assistant", "end_turn", "completion-event-seen"),
            ("assistant", "assistant", "tool_use", "unknown"),
            ("assistant", "assistant", "max_tokens", "unknown"),
            ("user", "user", "end_turn", "unknown"),
            ("assistant", "user", "end_turn", "unknown")):
            with self.subTest(kind=kind, role=role, stop=stop):
                raw = line({"type": kind, "message": {"role": role, "stop_reason": stop, "content": self.secret}})
                card = purpose.inspect(self.item(raw, "claude"))
                self.assertEqual(card["turn_event"], expected)
                self.assertEqual(card["project_completion"], "unverified")

    def test_recorded_plans_block_preparation_but_preserve_safe_backup(self):
        for states, expected in ((["completed"], "completed-plan-seen"),
                                 (["completed", "in_progress"], "pending-plan-seen"),
                                 (["pending"], "pending-plan-seen"), (["approved"], "unknown")):
            with self.subTest(states=states):
                args = {"plan": [{"step": self.secret, "status": s} for s in states]}
                raw = line({"type": "response_item", "payload": {"type": "function_call",
                            "name": "update_plan", "arguments": json.dumps(args)}})
                card = purpose.inspect(self.item(raw))
                self.assertEqual(card["plan_event"], expected)
                self.assertEqual(card["project_completion"], "unverified")
                facts = self.facts(card)
                self.assertFalse(purpose.keep_needed(facts))
                if expected == "pending-plan-seen":
                    self.assertIn("backup_preserve_history", triage.allowed(facts))
                    facts.update(backup_status="selected_bytes_verified", recovery_need="archive-copy")
                    self.assertIn("reuse_verified_backup", triage.allowed(facts))
                    self.assertNotIn("prepare_verified_removal", triage.allowed(facts))
                    facts.update(category="log", disposable_policy_checked=True)
                    self.assertNotIn("prepare_disposable_cleanup", triage.allowed(facts))
                self.assertNotIn(self.secret, json.dumps(card))

    def test_pending_plan_remains_observed_after_unrelated_completed_plan(self):
        def plan(status):
            return line({"type": "response_item", "payload": {"type": "function_call", "name": "update_plan",
                         "arguments": {"plan": [{"step": status, "status": status}]}}})
        card = purpose.inspect(self.item(plan("pending") + plan("completed")))
        self.assertEqual(card["plan_event"], "pending-plan-seen")
        self.assertEqual(card["locators"]["plan_event"]["offset"], 0)

    def test_source_changed_during_read_discards_all_content_evidence(self):
        item = self.item(line(event("task_complete")))
        path, real = self.root / item["relative"], os.pread
        def change(fd, count, offset):
            block = real(fd, count, offset)
            with path.open("ab") as stream:
                stream.write(b"changed\n")
            return block
        with patch.object(purpose.os, "pread", side_effect=change):
            card = purpose.inspect(item)
        self.assertEqual(card["coverage"], "unavailable")
        self.assertEqual(card["turn_event"], "unknown")
        self.assertEqual(card["windows"], [])
        self.assertEqual(card["locators"], {})

    def test_protected_or_disabled_content_is_not_read(self):
        item = self.item(line(event("task_complete")))
        for protected, enabled in (({item["id"]}, True), (set(), False)):
            with patch.object(purpose.os, "pread", side_effect=AssertionError("content read forbidden")):
                card = purpose.collect([item], protected, enabled=enabled)[item["id"]]
            self.assertEqual(card["coverage"], "not-read")
            self.assertEqual(card["turn_event"], "unknown")

    def test_fresh_notes_preserve_user_versus_assistant_origin_and_stale_refused(self):
        item = self.item(line(event("task_complete")))
        for origin in ("local-assistant", "user"):
            card = purpose.collect([item], set(), notes=self.notes(item, origin=origin))[item["id"]]
            self.assertEqual(card["annotation_origin"], origin)
            self.assertEqual(card["project_completion"], "unverified")
            self.assertEqual(purpose.provider_facts(card)["purpose_origin"], origin)
        notes = self.notes(item)
        path = self.root / item["relative"]
        path.write_bytes(path.read_bytes() + line(event("task_started")))
        refreshed = dict(item, identity=identity(path.stat()))
        with self.assertRaisesRegex(Refused, "stale|unavailable"):
            purpose.collect([refreshed], set(), notes=notes)

    def test_notes_reject_extra_permissions_and_unreviewed_claims(self):
        item = self.item(line(event("task_complete")))
        for extra in ({"cleanup_approved": True}, {"recovery_need": "archive-copy"}, {"text": self.secret}):
            notes = self.notes(item)
            notes["notes"][0].update(extra)
            with self.assertRaises(Refused):
                purpose.collect([item], set(), notes=notes)
        with self.assertRaises(Refused):
            purpose.collect([item], set(), notes=self.notes(item, origin="unreviewed"))
        card = purpose.collect([item], set(), notes=self.notes(item, origin="user", role="deliverable"))[item["id"]]
        facts = self.facts(card)
        self.assertEqual(facts["recovery_need"], "unknown")
        self.assertNotIn("prepare_verified_removal", triage.allowed(facts))
        self.assertIn("ask-resume-or-file-copy-before-removal", purpose.next_checks(facts))
        card = purpose.collect([item], set(), notes=self.notes(item, continuation="needed"))[item["id"]]
        self.assertEqual(triage.allowed(self.facts(card)), ["keep_in_place", "review_uncertain"])

    def test_template_excludes_protected_and_unavailable_rows(self):
        item = self.item(line(event("task_complete")))
        card = purpose.inspect(item)
        rows = [{"id": "safe", "facts": {"protected": False}, "purpose_evidence": card},
                {"id": "protected", "facts": {"protected": True}, "purpose_evidence": card},
                {"id": "changed", "facts": {"protected": False},
                 "purpose_evidence": dict(card, coverage="unavailable")}]
        self.assertEqual([n["id"] for n in purpose.template(rows)["notes"]], ["safe"])

    def test_bad_enum_types_are_refused_without_crashing(self):
        item = self.item(line(event("task_complete")))
        for key, value in (("role", []), ("continuation", {}), ("origin", []), ("role", self.secret)):
            with self.subTest(key=key, value_type=type(value).__name__):
                notes = self.notes(item)
                notes["notes"][0][key] = value
                with self.assertRaises(Refused):
                    purpose.collect([item], set(), notes=notes)

    def test_deep_malformed_json_does_not_crash_bounded_inspection(self):
        raw = b'{"deep":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}\n'
        card = purpose.inspect(self.item(raw))
        self.assertEqual(card["turn_event"], "unknown")
        self.assertEqual(card["bytes_read"], len(raw))
        # Decoder recursion limits differ across supported Python versions.
        with patch.object(purpose.json, "loads", side_effect=RecursionError("synthetic decoder limit")):
            card = purpose.inspect(self.item(raw))
        self.assertTrue(card["invalid_records"] or card["coverage"] == "unavailable")

    def test_packet_drops_text_ids_bindings_locators_and_invalid_purpose_enums(self):
        item = self.item(line(event("task_complete")))
        card = purpose.inspect(item)
        card.update(role=self.secret, annotation_origin={"injected": self.secret}, continuation=[self.secret])
        facts = self.facts(card)
        facts.update(source_binding=card["source_binding"], locators=card["locators"], note=self.secret)
        packet = triage.packet([{"id": item["id"], "path": str(self.root / item["relative"]),
                                 "facts": facts, "purpose_evidence": card}])
        encoded = json.dumps(packet)
        for forbidden in (self.secret, item["id"], str(self.root), card["source_binding"],
                          card["locators"]["turn_event"]["sha256"], "locators", "sha256", "source_binding"):
            self.assertNotIn(forbidden, encoded)
        candidate = packet["state"]["candidates"][0]
        self.assertEqual(candidate["purpose_role"], "unknown")
        self.assertEqual(candidate["purpose_origin"], "unknown")
        self.assertEqual(candidate["continuation"], "unknown")


if __name__ == "__main__":
    unittest.main()
