from __future__ import annotations

import os
import subprocess
import sys
import unittest

from helpers import BoardTestCase

import cardkit
from hermes_board_core.cards import CardStore
from hermes_board_core.paths import Paths
from hermes_board_core.store import BoardDB, sdk

HEAD = """import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "_sdk"))
from hermes_board_sdk import Card
card = Card()
"""


class SdkTest(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.paths = Paths(self.host.data_dir(), self.host.scripts_root())
        self.db = BoardDB(self.paths.db_file)
        self.store = CardStore(self.paths, self.db, self.host)

    def install(self, scripts):
        pkg = cardkit.package(scripts={"fetch.py": cardkit.SCRIPT, **scripts})
        for name in scripts:
            pkg["manifest"]["scripts"][name.split(".")[0]] = {"file": name}
        self.store.install(pkg)

    def run_like_cron(self, file_name):
        env = {k: os.environ[k] for k in ("PATH", "LANG") if k in os.environ}
        path = self.paths.script_file("demo", file_name)
        return subprocess.run([sys.executable, str(path)], cwd=str(path.parent), env=env, capture_output=True,
                              text=True, timeout=30)

    def test_cron_run_is_silent_and_recorded(self):
        self.install({})
        proc = self.run_like_cron("fetch.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(self.db.get_dataset("demo", "current")["value"], {"n": 1})
        self.assertEqual([p["value"] for p in self.db.query_series("demo", "count")], [1])
        runs = self.db.list_runs("demo")
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual((run["trigger"], run["status"], run["name"]), ("cron", "succeeded", "fetch"))
        self.assertEqual(run["result"], {"ok": True, "n": 1})
        self.assertEqual(run["progress"], 0.5)
        self.assertEqual(run["exitCode"], 0)

    def test_state_default_and_inference(self):
        self.install({"city.py": HEAD + "card.data.set('city', card.state.get('city'))\n"
                                        "card.data.set('who', [card.id, str(card.home)])\n"})
        proc = self.run_like_cron("city.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.db.get_dataset("demo", "city")["value"], "北京")
        self.assertEqual(self.db.get_dataset("demo", "who")["value"], ["demo", str(self.tmp)])

    def test_exception_marks_failed(self):
        self.install({"boom.py": HEAD + "raise ValueError('坏了')\n"})
        proc = self.run_like_cron("boom.py")
        self.assertNotEqual(proc.returncode, 0)
        run = self.db.list_runs("demo")[0]
        self.assertEqual(run["status"], "failed")
        self.assertIn("坏了", run["error"])

    def test_fail_marks_failed(self):
        self.install({"quit.py": HEAD + "card.fail('数据源不可用')\n"})
        proc = self.run_like_cron("quit.py")
        self.assertEqual(proc.returncode, 1)
        run = self.db.list_runs("demo")[0]
        self.assertEqual((run["status"], run["error"]), ("failed", "数据源不可用"))

    def test_uninstalled_card_is_refused(self):
        with self.assertRaises(sdk.BoardError):
            sdk.Card(card_id="ghost", hermes_home=self.tmp)

    def test_explicit_run_context_is_reused(self):
        self.install({})
        run_id = self.db.create_run("demo", "script", "fetch", "action", status="running", started=True)
        args = self.tmp / "args.json"
        args.write_text('{"n": 7}')
        env = {k: os.environ[k] for k in ("PATH", "LANG") if k in os.environ}
        env.update({"HERMES_BOARD_RUN_ID": run_id, "HERMES_BOARD_TRIGGER": "action",
                    "HERMES_BOARD_ARGS_FILE": str(args)})
        path = self.paths.script_file("demo", "fetch.py")
        proc = subprocess.run([sys.executable, str(path)], cwd=str(path.parent), env=env, capture_output=True,
                              text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.db.list_runs("demo")), 1)
        run = self.db.get_run(run_id)
        self.assertEqual(run["result"], {"ok": True, "n": 7})
        self.assertEqual(run["status"], "running", "the runner, not the SDK, finalizes action runs")


if __name__ == "__main__":
    unittest.main()
