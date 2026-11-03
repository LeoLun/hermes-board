from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from helpers import ROOT, BoardTestCase, make_bundled

from hermes_board_core import board as board_mod
from hermes_board_core.board import get_board

CHILD = """
import sys
from pathlib import Path
sys.path.insert(0, {root!r})
from hermes_board_core import init
init.BUNDLED_DIR = Path({bundled!r})
from hermes_board_core.board import get_board
b = get_board()
b.shutdown()
print("done")
"""


class InitTest(BoardTestCase):
    def test_first_init_installs_bundled_and_layout(self):
        board = get_board()
        self.wait_runs(board)
        self.assertEqual(board.cards.ids(), ["alpha", "beta"])
        layout = board.layout.get()
        self.assertEqual((layout["revision"], layout["updatedBy"]), (1, "init"))
        self.assertEqual([i["card"] for i in layout["items"]], ["alpha", "beta"])
        runs = board.db.list_runs("alpha")
        self.assertEqual([(r["trigger"], r["status"]) for r in runs], [("install", "succeeded")])
        self.assertTrue(all(j["enabled"] for j in self.cron.jobs.values()))
        self.assertEqual(board.cards.info("alpha")["source"], "bundled")

    def test_idempotent_and_does_not_override_user_cards(self):
        board = get_board()
        self.wait_runs(board)
        current = board.cards.read_package("alpha")
        board.cards.install({"manifest": dict(current["manifest"], title="我的 alpha"), "html": current["html"],
                             "scripts": current["scripts"]}, replace=True)
        board_mod.shutdown_all()
        board_mod.reset_cache()
        again = get_board()
        self.assertEqual(again.layout.get()["revision"], 1)
        self.assertEqual(again.cards.info("alpha")["title"], "我的 alpha")
        self.assertEqual(len(again.db.list_runs("alpha")), 1)

    def test_version_change_reconciles_cron(self):
        board = get_board()
        self.wait_runs(board)
        self.cron.jobs.clear()
        alpha = board.cards.read_package("alpha")
        bundled_alpha = self.bundled / "alpha" / "index.html"
        bundled_alpha.write_text(alpha["html"] + "\n<!-- bundled update -->\n", encoding="utf-8")
        meta_path = board.paths.card_dir("alpha") / ".meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.pop("packageSha256")
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        board.db.set_meta("pluginVersion", "0.0.1")
        board_mod.shutdown_all()
        board_mod.reset_cache()
        again = get_board()
        self.assertEqual([j["name"] for j in self.cron.jobs.values()], ["hermes-board:alpha:fetch"])
        self.assertIn("bundled update", again.cards.document("alpha")["html"])
        self.assertEqual(again.cards.info("alpha")["revision"], 2)

    def test_version_change_preserves_replaced_user_card(self):
        board = get_board()
        self.wait_runs(board)
        current = board.cards.read_package("alpha")
        board.cards.install({
            "manifest": dict(current["manifest"], title="我的 alpha"),
            "html": current["html"],
            "scripts": current["scripts"],
        }, replace=True, source="agent")
        (self.bundled / "alpha" / "index.html").write_text(current["html"] + "\nnew bundled\n", encoding="utf-8")
        board.db.set_meta("pluginVersion", "0.0.1")
        board_mod.shutdown_all()
        board_mod.reset_cache()
        again = get_board()
        self.assertEqual(again.cards.info("alpha")["title"], "我的 alpha")
        self.assertNotIn("new bundled", again.cards.document("alpha")["html"])

    def test_concurrent_processes_initialize_once(self):
        home = self.tmp / "concurrent-home"
        home.mkdir()
        bundled = make_bundled(self.tmp / "bundled2")
        env = {k: os.environ[k] for k in ("PATH", "LANG", "TMPDIR") if k in os.environ}
        env["HERMES_HOME"] = str(home)
        code = CHILD.format(root=str(ROOT), bundled=str(bundled))
        procs = [subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for proc in procs:
            out, err = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, err)
            self.assertIn("done", out)
        data = home / "plugin-data" / "hermes-board"
        self.assertEqual(json.loads((data / "board.json").read_text())["revision"], 1)
        self.assertEqual(sorted(p.name for p in (data / "cards").iterdir()), ["alpha", "beta"])
        self.assertTrue((home / "scripts" / "hermes-board" / "_sdk" / "hermes_board_sdk.py").is_file())
        import sqlite3

        conn = sqlite3.connect(data / "board.sqlite3")
        try:
            n = conn.execute("SELECT COUNT(*) FROM runs WHERE card_id='alpha' AND trigger='install'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
