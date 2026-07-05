"""Tests for webapp.helpers (SOURCE_LABEL + parse_kp_partner).

Pure stdlib, no pytest dep.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from webapp.helpers import PAGE_SIZE, SOURCE_LABEL, parse_kp_partner


class TestSourceLabel(unittest.TestCase):
    def test_known_sources(self):
        self.assertIn("nhsa_batch", SOURCE_LABEL)
        self.assertIn("pdf_2025", SOURCE_LABEL)
        self.assertIn("pdf_old", SOURCE_LABEL)

    def test_values_are_strings(self):
        for k, v in SOURCE_LABEL.items():
            self.assertIsInstance(v, str)
            self.assertGreater(len(v), 0, f"empty label for {k}")


class TestPageSize(unittest.TestCase):
    def test_value(self):
        self.assertEqual(PAGE_SIZE, 20)


class TestParseKpPartner(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(parse_kp_partner(None, "pair"))
        self.assertIsNone(parse_kp_partner(None, "service"))
        self.assertIsNone(parse_kp_partner("", "pair"))

    def test_invalid_json_returns_none(self):
        self.assertIsNone(parse_kp_partner("not json", "pair"))
        self.assertIsNone(parse_kp_partner("{invalid}", "pair"))

    def test_pair_type(self):
        row = json.dumps({"subject_name_b": "对照药 X", "codes_b": "Z0001"})
        result = parse_kp_partner(row, "pair")
        self.assertEqual(result, {
            "name": "对照药 X",
            "code": "Z0001",
            "label": "配对项目",
        })

    def test_pair_empty_both_returns_none(self):
        row = json.dumps({"subject_name_b": "", "codes_b": ""})
        self.assertIsNone(parse_kp_partner(row, "pair"))

    def test_pair_only_name(self):
        row = json.dumps({"subject_name_b": "对照药", "codes_b": ""})
        result = parse_kp_partner(row, "pair")
        self.assertEqual(result["name"], "对照药")
        self.assertEqual(result["code"], "")
        self.assertEqual(result["label"], "配对项目")

    def test_service_type(self):
        row = json.dumps({"row": ["", "OP001", "配对手术", "x"]})
        result = parse_kp_partner(row, "service")
        self.assertEqual(result, {
            "name": "配对手术",
            "code": "OP001",
            "label": "配对手术",
        })

    def test_service_short_row_returns_none(self):
        row = json.dumps({"row": ["a", "b"]})
        self.assertIsNone(parse_kp_partner(row, "service"))

    def test_unknown_type_returns_none(self):
        row = json.dumps({"subject_name_b": "对照药", "codes_b": "Z1"})
        self.assertIsNone(parse_kp_partner(row, "drug"))


if __name__ == "__main__":
    unittest.main(verbosity=2)