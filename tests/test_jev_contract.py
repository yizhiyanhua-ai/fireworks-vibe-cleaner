import copy
import os
import unittest
from unittest.mock import patch

from vibe_cleaner import jev
from vibe_cleaner.common import Refused


class JevContract(unittest.TestCase):
    def setUp(self):
        self.items = [{"identity": {"size": 100}, "age_days": 60, "category": "log", "eligible": True}]
        self.request = jev.packet(self.items)
        self.response = {"model": "jev-preview", "answers": {"c0": {"type": "choice", "choice": "keep",
                         "probabilities": {"keep": 1.0, "review": 0.0}, "confidence": 1.0}},
                         "usage": {"input_tokens": 1, "output_tokens": 1}}

    def test_invalid_distributions(self):
        for value in [float("nan"), float("inf"), -0.1, 1.1, True, "1"]:
            data = copy.deepcopy(self.response)
            data["answers"]["c0"]["confidence"] = value
            with self.assertRaises(Refused):
                jev.validate_response(data, self.request)
        self.response["answers"]["c0"]["probabilities"]["review"] = 0.5
        with self.assertRaises(Refused):
            jev.validate_response(self.response, self.request)

    def test_two_decimal_rounding_is_bounded_disclosed_and_not_normalized(self):
        request = copy.deepcopy(self.request)
        request["questions"]["c0"]["criteria"] = {"a": "first", "b": "second", "c": "third"}
        data = copy.deepcopy(self.response)
        data["answers"]["c0"].update(choice="a", probabilities={"a": 0.33, "b": 0.33, "c": 0.33})
        result = jev.validate_response(data, request)["answers"]["c0"]
        self.assertTrue(result["probability_rounding_tolerated"])
        self.assertEqual(result["probabilities"], data["answers"]["c0"]["probabilities"])
        self.assertAlmostEqual(result["probability_sum"], 0.99)
        for values in [(0.3, 0.3, 0.3), (0.34, 0.335, 0.32), (0.34, 0.32, 0.32)]:
            data["answers"]["c0"]["probabilities"] = dict(zip(("a", "b", "c"), values))
            with self.assertRaises(Refused):
                jev.validate_response(data, request)

    def test_unknown_ids_forbidden_choice_and_bad_usage(self):
        mutations = [lambda d: d["answers"].update({"private-path": {}}),
                     lambda d: d["answers"]["c0"].update({"choice": "purge"}),
                     lambda d: d["usage"].update({"input_tokens": -1})]
        for mutate in mutations:
            data = copy.deepcopy(self.response)
            mutate(data)
            with self.assertRaises(Refused):
                jev.validate_response(data, self.request)

    def test_timeout_and_key_absence_no_retry(self):
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-only"}):
            with patch("urllib.request.OpenerDirector.open", side_effect=TimeoutError) as mocked:
                result = jev.advise(self.items, enabled=True)
                self.assertEqual(result["mode"], "rules-only")
                self.assertEqual(mocked.call_count, 1)
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            self.assertEqual(jev.advise(self.items, enabled=True)["calls"], 0)

    def test_invalid_response_has_fixed_diagnostic_without_exception_text(self):
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-only"}):
            result = jev.request_advice(self.request, enabled=True, transport=lambda *a: {})
            self.assertEqual(result["error_code"], "model")
            with patch("urllib.request.OpenerDirector.open", side_effect=OSError("private secret")):
                result = jev.request_advice(self.request, enabled=True)
                self.assertEqual(result["error_code"], "transport")
                self.assertNotIn("secret", str(result))

    def test_batch_boundaries_and_no_state_mutation(self):
        before = copy.deepcopy(self.items)
        p = jev.packet(self.items * 2)
        self.assertIn("state.candidates[1]", p["questions"]["c1"]["instructions"])
        self.assertEqual(self.items, before)
        with self.assertRaises(Refused):
            jev.packet(self.items * 21)
        with self.assertRaises(Refused):
            jev.packet([])

    def test_delete_requires_local_policy_retention_and_activity_evidence(self):
        item = self.items[0]
        self.assertNotIn("delete", self.request["questions"]["c0"]["criteria"])
        eligible = dict(item, local_policy_checked=True, retention_met=True, active_state="no_open_handles")
        request = jev.packet([eligible])
        self.assertIn("delete", request["questions"]["c0"]["criteria"])
        for delta in [{"active_state": "unknown"}, {"active_state": "open_or_unknown"},
                      {"retention_met": False}, {"local_policy_checked": False}, {"category": "protected"},
                      {"category": "worktree"}, {"category": "session"}]:
            p = jev.packet([{**eligible, **delta}])
            self.assertNotIn("delete", p["questions"]["c0"]["criteria"])

    def test_protected_or_open_objects_never_receive_backup_or_delete(self):
        for item in [dict(self.items[0], category="protected"),
                     dict(self.items[0], category="session", active_state="open_or_unknown"),
                     dict(self.items[0], category="session", backup_eligible=False)]:
            self.assertEqual(set(jev.packet([item])["questions"]["c0"]["criteria"]), {"keep", "review"})

    def test_cross_candidate_actions_rejected(self):
        request = jev.packet([self.items[0], dict(self.items[0], category="session", backup_eligible=True,
                                                local_policy_checked=True)])
        data = copy.deepcopy(self.response)
        data["answers"]["c1"] = {"type": "choice", "choice": "backup", "confidence": 1.0,
                                   "probabilities": {"keep": 0.0, "review": 0.0, "backup": 1.0}}
        jev.validate_response(data, request)
        data["answers"]["c0"], data["answers"]["c1"] = data["answers"]["c1"], data["answers"]["c0"]
        with self.assertRaises(Refused):
            jev.validate_response(data, request)

    def test_choice_is_max_probability_and_extra_text_is_dropped(self):
        data = copy.deepcopy(self.response)
        data["answers"]["c0"]["explanation"] = "untrusted private output"
        data["extra"] = "must not persist"
        result = jev.validate_response(data, self.request)
        self.assertNotIn("extra", result)
        self.assertNotIn("explanation", result["answers"]["c0"])
        data["answers"]["c0"]["choice"] = "review"
        with self.assertRaises(Refused):
            jev.validate_response(data, self.request)

    def test_delete_is_only_advice_and_never_calls_executor(self):
        item = dict(self.items[0], local_policy_checked=True, retention_met=True, active_state="no_open_handles")
        response = {"model": "jev-test", "answers": {"c0": {"type": "choice", "choice": "delete",
                    "probabilities": {"keep": 0.0, "review": 0.0, "delete": 1.0}, "confidence": 1.0}},
                    "usage": {"input_tokens": 1, "output_tokens": 1}}
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-only"}), patch("vibe_cleaner.engine.apply") as execute:
            result = jev.advise([item], enabled=True, transport=lambda *a: response)
        self.assertEqual(result["answers"]["c0"]["choice"], "delete")
        execute.assert_not_called()
