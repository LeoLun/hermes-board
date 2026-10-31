from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from helpers import ROOT, BoardTestCase

from hermes_board_core import validator
from hermes_board_core.board import get_board
from hermes_board_core.validator import load_package_dir

TEMPLATE = ROOT / "skills" / "card-author" / "templates" / "basic-card"
SKILL_DIR = ROOT / "skills" / "card-author"


class TemplateTest(BoardTestCase):
    bundled_cards = False

    def test_template_passes_strict_validation(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(validator.main([str(TEMPLATE), "--strict"]), 0, out.getvalue())

    def test_template_installs_and_runs(self):
        board = get_board()
        result = board.install_card(load_package_dir(TEMPLATE))
        self.assertTrue(result["created"])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(len(result["runs"]), 1)
        run = board.runner.wait(result["runs"][0], timeout=20)
        self.assertEqual(run["status"], "succeeded", run)
        snap = board.db.get_dataset("basic-card", "current")["value"]
        self.assertEqual(snap["label"], "1 分钟平均负载")
        self.assertEqual(len(board.db.query_series("basic-card", "history")), 1)

    def test_skill_references_exist(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        for rel in ("references/manifest.md", "references/design-standard.md", "references/runtime-api.md",
                    "references/script-sdk.md", "templates/basic-card/card.json",
                    "templates/basic-card/index.html", "templates/basic-card/scripts/fetch.py"):
            self.assertIn(rel, text)
            self.assertTrue((SKILL_DIR / rel).is_file(), rel)


if __name__ == "__main__":
    unittest.main()
