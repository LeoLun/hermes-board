from __future__ import annotations

import json
import unittest

from helpers import BoardTestCase

import cardkit
from hermes_board_core.board import get_board
from hermes_board_core.tool import ACTIONS, SCHEMA, handle


def call(**args):
    return json.loads(handle(args))


class ToolTest(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.board = get_board()
        self.wait_runs(self.board)

    def assert_err(self, result, code):
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], code, result)
        self.assertTrue(result["error"]["message"])
        return result["error"]

    def test_schema(self):
        self.assertEqual(SCHEMA["name"], "board_manage")
        self.assertEqual(SCHEMA["parameters"]["properties"]["action"]["enum"], list(ACTIONS))
        self.assertEqual(len(ACTIONS), 9)

    def test_list_and_get(self):
        result = call(action="list")
        self.assertTrue(result["ok"])
        self.assertEqual([c["id"] for c in result["cards"]], ["alpha", "beta"])
        self.assertEqual(result["layout"]["revision"], 1)
        alpha = result["cards"][0]
        self.assertTrue(alpha["onBoard"])
        self.assertEqual(alpha["scripts"][0]["lastRun"]["status"], "succeeded")
        got = call(action="get", card="alpha")
        self.assertEqual(got["manifest"]["id"], "alpha")
        self.assertIn("HermesCard", got["html"])
        self.assertIn("fetch.py", got["scripts"])
        self.assert_err(call(action="get", card="ghost"), "not_found")
        self.assert_err(call(action="get"), "invalid")

    def test_validate(self):
        good = call(action="validate", package=cardkit.package("gamma"))
        self.assertEqual((good["ok"], good["valid"], good["errors"]), (True, True, []))
        bad = call(action="validate", package=cardkit.package("gamma", sizes=["5x5"]))
        self.assertTrue(bad["ok"])
        self.assertFalse(bad["valid"])
        self.assertTrue(bad["errors"])
        self.assertFalse(self.board.cards.exists("gamma"))

    def test_save_places_first_fit_and_runs_on_install(self):
        pkg = cardkit.package("gamma")
        pkg["manifest"]["scripts"]["fetch"]["runOnInstall"] = True
        result = call(action="save", package=pkg)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["created"])
        self.assertEqual((result["placed"]["x"], result["placed"]["y"]), (10, 0))
        self.assertEqual(len(result["runs"]), 1)
        self.assertEqual(self.board.runner.wait(result["runs"][0], timeout=20)["status"], "succeeded")
        self.assert_err(call(action="save", package=pkg), "exists")
        again = call(action="save", package=pkg, replace=True)
        self.assertEqual(again["revision"], 2)
        self.assertEqual(again["placed"]["x"], 10, "an update keeps the card where it is")
        err = self.assert_err(call(action="save", package=cardkit.package("delta", defaultSize="12x8")), "invalid")
        self.assertTrue(err["errors"])

    def test_save_with_explicit_place(self):
        result = call(action="save", package=cardkit.package("gamma"), place={"x": 0, "y": 0, "size": "6x4"})
        self.assertTrue(result["ok"], result)
        items = {i["card"]: i for i in self.board.layout.get()["items"]}
        self.assertEqual((items["gamma"]["x"], items["gamma"]["y"], items["gamma"]["w"]), (0, 0, 6))
        self.assertGreaterEqual(items["alpha"]["y"], 4, "existing cards are pushed down")

    def test_remove(self):
        self.assert_err(call(action="remove", card="beta"), "invalid")
        self.assertTrue(self.board.is_on_board("beta"))
        result = call(action="remove", card="alpha", confirm=True)
        self.assertEqual((result["removedFromBoard"], result["deleted"]), (True, False))
        self.assertTrue(self.board.cards.exists("alpha"))
        self.assertFalse(next(iter(self.cron.jobs.values()))["enabled"])
        result = call(action="remove", card="alpha", deletePackage=True, confirm=True)
        self.assertTrue(result["deleted"])
        self.assertFalse(self.board.cards.exists("alpha"))
        self.assertEqual(self.cron.jobs, {})
        self.assert_err(call(action="remove", card="ghost", confirm=True), "not_found")

    def test_run_returns_tails(self):
        result = call(action="run", card="alpha", script="fetch", args={"n": 4})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["result"], {"ok": True, "n": 4})
        self.assertEqual(result["stdoutTail"], "")
        self.assertEqual(result["stderrTail"], "")
        self.assertEqual(result["exitCode"], 0)
        queued = call(action="run", card="alpha", script="fetch", wait=False)
        self.assertIn(queued["status"], ("queued", "running"))
        self.board.runner.wait(queued["runId"], timeout=20)
        self.assert_err(call(action="run", card="alpha", script="nope"), "not_found")
        self.assert_err(call(action="run", card="alpha", script="fetch", args={"n": "x"}), "invalid")

    def test_data(self):
        self.assertEqual(call(action="data", card="alpha", kind="data")["items"]["current"]["value"], {"n": 1})
        self.assertEqual(call(action="data", card="alpha", kind="data", name="current")["value"], {"n": 1})
        self.assertEqual(len(call(action="data", card="alpha", kind="series", name="count")["points"]), 1)
        self.assertEqual(call(action="data", card="alpha", kind="state", name="city"),
                         {"ok": True, "value": "北京", "stored": False})
        self.assertEqual(len(call(action="data", card="alpha", kind="runs")["runs"]), 1)
        self.assert_err(call(action="data", card="alpha", kind="bogus"), "invalid")
        self.assert_err(call(action="data", card="alpha", kind="series"), "invalid")

    def test_place(self):
        result = call(action="place", card="beta", x=0, y=0, size="8x4")
        self.assertTrue(result["ok"], result)
        items = {i["card"]: i for i in result["layout"]["items"]}
        self.assertEqual((items["beta"]["x"], items["beta"]["y"], items["beta"]["w"]), (0, 0, 8))
        self.assertGreaterEqual(items["alpha"]["y"], 4)
        self.assert_err(call(action="place", card="beta", x=0, y=0, size="4x4"), "invalid")
        self.assert_err(call(action="place", card="beta", x=30, y=0), "invalid")

    def test_restore_default(self):
        current = self.board.cards.read_package("alpha")
        self.board.cards.install({"manifest": dict(current["manifest"], title="改过"), "html": current["html"],
                                  "scripts": current["scripts"]}, replace=True, source="agent")
        result = call(action="restore_default", card="alpha")
        self.assertTrue(result["ok"], result)
        info = self.board.cards.info("alpha")
        self.assertEqual((info["title"], info["source"], info["revision"]), ("演示", "bundled", 3))
        self.assert_err(call(action="restore_default", card="ghost"), "not_found")

    def test_never_raises(self):
        self.assert_err(json.loads(handle("nope")), "invalid")
        self.assert_err(call(action="explode"), "invalid")
        self.assert_err(call(action="save", package={"manifest": 1}), "invalid")


if __name__ == "__main__":
    unittest.main()
