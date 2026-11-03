"""Default cards (tasks 10.1–10.5): strict validation, seamless 24×16 layout, init binding, weather script."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import ROOT, BoardTestCase

from hermes_board_core import board as board_mod
from hermes_board_core import init as init_mod
from hermes_board_core.board import get_board
from hermes_board_core.host import fallback_parse_schedule
from hermes_board_core.layout import validate_items
from hermes_board_core.validator import validate_package

CARDS_DIR = ROOT / "cards"
EXPECTED = ["calendar", "clock", "countdown", "note", "pomodoro", "todo", "weather", "world-clock"]

GEOCODE = {
    "北京": {"results": [{"name": "北京", "latitude": 39.9075, "longitude": 116.39723, "timezone": "Asia/Shanghai",
                          "admin1": "北京", "country": "中国"}]},
    "上海": {"results": [{"name": "上海", "latitude": 31.22222, "longitude": 121.45806, "timezone": "Asia/Shanghai",
                          "admin1": "上海", "country": "中国"}]},
}
FORECAST = {
    "current": {"time": "2026-10-31T15:00", "temperature_2m": 16.4, "relative_humidity_2m": 38,
                "apparent_temperature": 14.9, "weather_code": 2, "wind_speed_10m": 11.2, "is_day": 1},
    "daily": {"time": ["2026-10-31", "2026-11-01", "2026-11-02", "2026-11-03"],
              "weather_code": [2, 61, 3, 0],
              "temperature_2m_max": [18.2, 14.0, 12.5, 15.1],
              "temperature_2m_min": [7.1, 8.3, 5.0, 4.2],
              "precipitation_probability_max": [5, 80, 20, 0]},
}

CHILD = """
import json, runpy, sys, urllib.parse
script, home, out = sys.argv[1], sys.argv[2], sys.argv[3]
geocode, forecast = json.loads(sys.argv[4]), json.loads(sys.argv[5])
urls = []
def fake_get(url, timeout=15):
    urls.append(url)
    if "geocoding-api" in url:
        name = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["name"][0]
        return geocode.get(name, {{}})
    return forecast
mod = runpy.run_path(script, run_name="weather_under_test")
card = mod["Card"](script_path=script)
try:
    mod["main"](card=card, http_get=fake_get)
finally:
    open(out, "w", encoding="utf-8").write(json.dumps(urls))
""".replace("{{}}", "{}")


def _cells(items):
    cells = set()
    for it in items:
        for x in range(it["x"], it["x"] + it["w"]):
            for y in range(it["y"], it["y"] + it["h"]):
                if (x, y) in cells:
                    raise AssertionError(f"overlap at {(x, y)} ({it['id']})")
                cells.add((x, y))
    return cells


class BundledPackagesTest(unittest.TestCase):
    def test_exactly_eight_default_cards(self):
        self.assertEqual(init_mod.bundled_ids(CARDS_DIR), EXPECTED)

    def test_every_card_passes_strict_validation(self):
        for card_id in EXPECTED:
            with self.subTest(card=card_id):
                result = validate_package(init_mod.bundled_package(card_id, CARDS_DIR), fallback_parse_schedule)
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["warnings"], [])

    def test_default_layout_tiles_24x16_without_gaps(self):
        items = init_mod.default_items(CARDS_DIR)
        self.assertEqual(sorted(i["card"] for i in items), EXPECTED)
        cells = _cells(items)
        self.assertEqual(cells, {(x, y) for x in range(24) for y in range(16)})
        manifests = {cid: init_mod.bundled_package(cid, CARDS_DIR)["manifest"] for cid in EXPECTED}
        for it in items:
            self.assertEqual(it["id"], it["card"])
            self.assertEqual(f"{it['w']}x{it['h']}", manifests[it["card"]]["defaultSize"], it["card"])
        validate_items(items, manifests)

    def test_weather_defaults_to_beijing_every_30m(self):
        manifest = init_mod.bundled_package("weather", CARDS_DIR)["manifest"]
        self.assertIn("12x4", manifest["sizes"])
        self.assertEqual(manifest["defaultSize"], "8x8")
        self.assertEqual(manifest["state"]["city"]["default"], "北京")
        fetch = manifest["scripts"]["fetch"]
        self.assertEqual((fetch["schedule"], fetch["runOnInstall"], fetch["callable"]), ("every 30m", True, True))

    def test_default_cards_use_one_entry_with_fullscreen_rules(self):
        for card_id in EXPECTED:
            with self.subTest(card=card_id):
                manifest = init_mod.bundled_package(card_id, CARDS_DIR)["manifest"]
                self.assertEqual(manifest["entry"], "index.html")
                self.assertNotIn("fullscreenEntry", manifest)
                html = (CARDS_DIR / card_id / manifest["entry"]).read_text(encoding="utf-8")
                self.assertIn('data-size="fullscreen"', html)

    def test_weather_has_12x4_display_and_editor_layouts(self):
        html = (CARDS_DIR / "weather" / "index.html").read_text(encoding="utf-8")
        self.assertIn('html[data-size="12x4"] .content', html)
        self.assertIn('html[data-size="12x4"] .editor', html)

    def test_stateful_cards_declare_defaults(self):
        expect = {"world-clock": ("cities", ["纽约", "伦敦", "东京"]), "countdown": ("target", "元旦"),
                  "pomodoro": ("session", 1500000), "note": ("text", ""), "todo": ("items", [])}
        for card_id, (key, want) in expect.items():
            with self.subTest(card=card_id):
                default = init_mod.bundled_package(card_id, CARDS_DIR)["manifest"]["state"][key]["default"]
                if card_id == "world-clock":
                    default = [c["name"] for c in default]
                elif card_id == "countdown":
                    default = default["name"]
                elif card_id == "pomodoro":
                    default = default["remainingMs"]
                self.assertEqual(default, want)


class DefaultInitTest(BoardTestCase):
    """Initialise against the real ``cards/`` directory (runOnInstall stubbed so tests stay offline)."""

    def setUp(self) -> None:
        super().setUp()
        init_mod.BUNDLED_DIR = CARDS_DIR
        patcher = mock.patch.object(board_mod.Board, "run_on_install", autospec=True, return_value=[])
        self.run_on_install = patcher.start()
        self.addCleanup(patcher.stop)

    def test_first_init_installs_all_cards_layout_and_weather_cron(self):
        board = get_board()
        self.assertEqual(board.cards.ids(), EXPECTED)
        layout = board.layout.get()
        self.assertEqual(layout["revision"], 1)
        self.assertEqual(len(_cells(layout["items"])), 24 * 16)
        jobs = {j["name"]: j for j in self.cron.jobs.values()}
        self.assertEqual(list(jobs), ["hermes-board:weather:fetch"])
        job = jobs["hermes-board:weather:fetch"]
        self.assertTrue(job["no_agent"])
        self.assertTrue(job["enabled"])
        self.assertEqual(job["script"], "hermes-board/weather/fetch_weather.py")
        self.assertEqual(self.run_on_install.call_count, 1)
        self.assertIn("weather", self.run_on_install.call_args.args[1])
        installed = self.tmp / "scripts" / "hermes-board" / "weather" / "fetch_weather.py"
        self.assertTrue(installed.is_file())
        self.assertTrue((self.tmp / "scripts" / "hermes-board" / "_sdk" / "hermes_board_sdk.py").is_file())

    def test_init_is_idempotent(self):
        get_board()
        board_mod.shutdown_all()
        board_mod.reset_cache()
        again = get_board()
        self.assertEqual(again.layout.get()["revision"], 1)
        self.assertEqual(len(self.cron.jobs), 1)
        self.assertEqual(self.run_on_install.call_count, 1)


class WeatherScriptTest(BoardTestCase):
    """Run the installed weather script in a subprocess with an injected HTTP function (no network)."""

    def setUp(self) -> None:
        super().setUp()
        init_mod.BUNDLED_DIR = CARDS_DIR
        patcher = mock.patch.object(board_mod.Board, "run_on_install", autospec=True, return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.board = get_board()
        self.script = self.tmp / "scripts" / "hermes-board" / "weather" / "fetch_weather.py"

    def _run(self, args=None, geocode=None):
        out = self.tmp / "urls.json"
        env = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_BOARD_")}
        if args is not None:
            fd, path = tempfile.mkstemp(dir=self.tmp, suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(args, fh, ensure_ascii=False)
            env["HERMES_BOARD_ARGS_FILE"] = path
        proc = subprocess.run(
            [sys.executable, "-c", CHILD, str(self.script), str(self.tmp), str(out),
             json.dumps(GEOCODE if geocode is None else geocode, ensure_ascii=False), json.dumps(FORECAST)],
            env=env, capture_output=True, text=True, timeout=60)
        urls = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
        return proc, urls

    def test_default_city_beijing_writes_current_and_forecast(self):
        proc, urls = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("name=%E5%8C%97%E4%BA%AC", urls[0])
        self.assertIn("timezone=Asia%2FShanghai", urls[1])
        current = self.board.db.get_dataset("weather", "current")["value"]
        self.assertEqual((current["city"], current["temp"], current["text"]), ("北京", 16.4, "局部多云"))
        self.assertEqual((current["high"], current["low"], current["humidity"]), (18.2, 7.1, 38))
        forecast = self.board.db.get_dataset("weather", "forecast")["value"]
        self.assertEqual([d["date"] for d in forecast], ["2026-11-01", "2026-11-02", "2026-11-03"])
        self.assertEqual([d["kind"] for d in forecast], ["rain", "cloudy", "clear"])
        self.assertEqual(len(self.board.db.query_series("weather", "temp", None, None, 10, "asc")), 1)
        runs = self.board.db.list_runs("weather")
        self.assertEqual((runs[0]["trigger"], runs[0]["status"]), ("cron", "succeeded"))
        self.assertIsNone(self.board.db.get_state("weather", "city"))

    def test_city_argument_switches_city_after_successful_lookup(self):
        proc, _ = self._run(args={"city": "上海"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.board.db.get_state("weather", "city")["value"], "上海")
        self.assertEqual(self.board.db.get_dataset("weather", "current")["value"]["city"], "上海")

    def test_unknown_city_fails_without_touching_state(self):
        proc, _ = self._run(args={"city": "不存在的城市"}, geocode={})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIsNone(self.board.db.get_state("weather", "city"))
        self.assertIsNone(self.board.db.get_dataset("weather", "current"))
        run = self.board.db.list_runs("weather")[0]
        self.assertEqual(run["status"], "failed")
        self.assertIn("找不到城市", run["error"])


if __name__ == "__main__":
    unittest.main()
