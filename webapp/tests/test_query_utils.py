"""Tests for webapp.query_utils (TD-06 + TD-07 unit tests).

Pure stdlib, no pytest dep. Run via:
    cd webapp && python -m unittest tests.test_query_utils
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Allow running this file from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from webapp.query_utils import (
    _safe_int,
    fts_query,
    limit_from,
    page_from,
    row_to_dict,
)


class TestSafeInt(unittest.TestCase):
    def test_basic_int(self):
        self.assertEqual(_safe_int("42"), 42)
        self.assertEqual(_safe_int(42), 42)

    def test_invalid_returns_default(self):
        self.assertEqual(_safe_int("abc"), 0)
        self.assertEqual(_safe_int(None), 0)
        self.assertEqual(_safe_int(""), 0)
        self.assertEqual(_safe_int([]), 0)
        self.assertEqual(_safe_int(None, default=5), 5)

    def test_min_clamp(self):
        self.assertEqual(_safe_int("-5", default=1, min_=1), 1)
        self.assertEqual(_safe_int("0", default=1, min_=1), 1)
        self.assertEqual(_safe_int("10", default=1, min_=1), 10)

    def test_max_clamp(self):
        self.assertEqual(_safe_int("999", default=10, max_=100), 100)
        self.assertEqual(_safe_int("50", default=10, max_=100), 50)

    def test_min_and_max_clamp(self):
        self.assertEqual(_safe_int("-5", default=10, min_=0, max_=100), 0)
        self.assertEqual(_safe_int("999", default=10, min_=0, max_=100), 100)


class TestFtsQuery(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(fts_query(""), "")
        self.assertEqual(fts_query(None), "")

    def test_ascii_gets_prefix(self):
        self.assertEqual(fts_query("abc"), "abc*")
        self.assertEqual(fts_query("afngw"), "afngw*")
        self.assertEqual(fts_query("AB12"), "AB12*")

    def test_chinese_2plus_chars(self):
        self.assertEqual(fts_query("医药"), '"医药"*')
        self.assertEqual(fts_query("医保药品"), '"医保"*')

    def test_single_chinese_char(self):
        self.assertEqual(fts_query("医"), '"医"*')

    def test_sanitize(self):
        # sanitize keeps internal whitespace, then prefix match on first 2 chars
        self.assertEqual(fts_query("医 保 药", sanitize=True), '"医 "*')
        self.assertEqual(fts_query("!!!", sanitize=True), "")
        self.assertEqual(fts_query("  ab  ", sanitize=True), "ab*")


class TestRowToDict(unittest.TestCase):
    def test_none_returns_empty(self):
        self.assertEqual(row_to_dict(None), {})

    def test_explicit_keys(self):
        row = ("a", "b", "c")
        d = row_to_dict(row, ["x", "y", "z"])
        self.assertEqual(d, {"x": "a", "y": "b", "z": "c"})

    def test_explicit_keys_short_row(self):
        row = ("a", "b")
        d = row_to_dict(row, ["x", "y", "z"])
        self.assertEqual(d, {"x": "a", "y": "b"})

    def test_plain_tuple_no_keys(self):
        row = ("a", "b")
        d = row_to_dict(row)
        self.assertIn(0, d)
        self.assertEqual(d[0], "a")


class _Args:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class TestPageFrom(unittest.TestCase):
    def test_default_when_missing(self):
        self.assertEqual(page_from(_Args({})), 1)

    def test_explicit_value(self):
        self.assertEqual(page_from(_Args({"page": "5"})), 5)

    def test_invalid_value_uses_default(self):
        self.assertEqual(page_from(_Args({"page": "abc"})), 1)

    def test_negative_clamped_to_min(self):
        self.assertEqual(page_from(_Args({"page": "-3"})), 1)

    def test_large_clamped_to_max(self):
        self.assertEqual(page_from(_Args({"page": "999999"})), 10000)


class TestLimitFrom(unittest.TestCase):
    def test_default_50(self):
        self.assertEqual(limit_from(_Args({})), 50)

    def test_explicit(self):
        self.assertEqual(limit_from(_Args({"limit": "20"})), 20)

    def test_max_clamped(self):
        self.assertEqual(limit_from(_Args({"limit": "9999"})), 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)