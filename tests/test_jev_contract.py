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
                         "probabilities": {"keep": 1.0, "review": 0.0, "backup": 0.0}, "confidence": 1.0}},
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

    def test_batch_boundaries_and_no_state_mutation(self):
        before = copy.deepcopy(self.items)
        p = jev.packet(self.items * 2)
        self.assertIn("state.candidates[1]", p["questions"]["c1"]["instructions"])
        self.assertEqual(self.items, before)
        with self.assertRaises(Refused):
            jev.packet(self.items * 21)
        with self.assertRaises(Refused):
            jev.packet([])
