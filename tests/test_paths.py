from __future__ import annotations

import json
import os
import unittest

from helpers import ROOT, BoardTestCase  # noqa: F401  (sets sys.path)

from hermes_board_core import constants
from hermes_board_core.errors import BoardError
from hermes_board_core.paths import Paths, check_card_id, check_key, safe_child
from hermes_board_core.store import sdk


class ConstantsTest(unittest.TestCase):
    def test_sdk_limits_mirror_shared_constants(self):
        shared = json.loads((ROOT / "shared" / "constants.json").read_text(encoding="utf-8"))["limits"]
        for key, value in sdk.LIMITS.items():
            self.assertEqual(shared[key], value, key)

    def test_presets_and_parse(self):
        self.assertEqual(constants.PRESETS, (
            "4x4", "4x6", "6x4", "6x6", "8x4", "8x6", "8x8", "12x4", "12x6", "12x8", "24x4",
        ))
        self.assertEqual(constants.parse_size("12x6"), (12, 6))
        self.assertEqual(constants.parse_size("24x4"), (24, 4))
        for bad in ("6", "x4", "6x", "a x b", 64, None):
            with self.assertRaises(ValueError):
                constants.parse_size(bad)  # type: ignore[arg-type]


class PathsTest(BoardTestCase):
    def test_card_id_rules(self):
        for ok in ("weather", "world-clock", "a1"):
            self.assertEqual(check_card_id(ok), ok)
        for bad in ("A", "1abc", "a", "a_b", "../x", "x" * 49, "", None):
            with self.assertRaises(BoardError):
                check_card_id(bad)

    def test_key_rules(self):
        self.assertEqual(check_key("数据集", "cpu.load_1m"), "cpu.load_1m")
        for bad in ("", "a/b", "a b", "x" * 65):
            with self.assertRaises(BoardError):
                check_key("数据集", bad)

    def test_safe_child_rejects_traversal_and_symlink_escape(self):
        base = self.tmp / "base"
        base.mkdir()
        outside = self.tmp / "outside"
        outside.mkdir()
        os.symlink(outside, base / "link")
        for bad in ("..", "../x", "a/b", "", ".", "link"):
            with self.assertRaises(BoardError, msg=bad):
                safe_child(base, bad)
        self.assertEqual(safe_child(base, "ok.py"), base / "ok.py")

    def test_paths_layout(self):
        paths = Paths(self.tmp / "plugin-data" / "hermes-board", self.tmp / "scripts" / "hermes-board")
        self.assertEqual(paths.card_dir("weather"), self.tmp / "plugin-data" / "hermes-board" / "cards" / "weather")
        self.assertEqual(paths.cron_script_ref("weather", "fetch_weather.py"), "hermes-board/weather/fetch_weather.py")
        with self.assertRaises(BoardError):
            paths.script_file("weather", "../evil.py")
        with self.assertRaises(BoardError):
            paths.script_file("weather", "Fetch.PY")


if __name__ == "__main__":
    unittest.main()
