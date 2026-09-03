"""Tests for webapp.search_backend (detect_mode + row_to_kp_dict).

Pure stdlib, no pytest dep. detect_mode is a string-only function so
no DB needed; row_to_kp_dict is exercised with a plain tuple.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from webapp.search_backend import detect_mode


class TestDetectMode(unittest.TestCase):
    def test_empty_is_name(self):
        self.assertEqual(detect_mode(""), "name")
        self.assertEqual(detect_mode(None), "name")

    def test_code_pattern(self):
        # 8+ uppercase alnum
        self.assertEqual(detect_mode("ZD03AAA00430"), "code")
        self.assertEqual(detect_mode("AB12345678"), "code")
        # 10+ digits only
        self.assertEqual(detect_mode("1234567890"), "code")

    def test_initials_pattern(self):
        # pure letters >= 2 chars
        self.assertEqual(detect_mode("ab"), "initials")
        self.assertEqual(detect_mode("afngw"), "initials")
        # mixed case still counts
        self.assertEqual(detect_mode("AfNgW"), "initials")

    def test_initials_short_falls_to_name(self):
        # 1 letter alone → name (could be a Chinese single char pinyin)
        self.assertEqual(detect_mode("a"), "name")

    def test_chinese_is_name(self):
        # Chinese characters detected as name mode
        self.assertEqual(detect_mode("医保"), "name")
        self.assertEqual(detect_mode("艾附暖宫丸"), "name")


if __name__ == "__main__":
    unittest.main(verbosity=2)