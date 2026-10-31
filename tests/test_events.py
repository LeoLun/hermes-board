from __future__ import annotations

import unittest

from helpers import BoardTestCase

import cardkit
from hermes_board_core.board import get_board


class EventsTest(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.board = get_board()
        self.wait_runs(self.board)
        self.host.events.clear()

    def names(self):
        return [e for e, _ in self.host.events]

    def test_install_and_layout(self):
        self.board.install_card(cardkit.package("gamma"))
        self.assertIn("card.updated", self.names())
        self.assertIn("layout.updated", self.names())
        updated = dict(self.host.events)["card.updated"]
        self.assertEqual(updated, {"card": "gamma", "revision": 1})
        self.host.events.clear()
        layout = self.board.layout.get()
        self.board.save_layout(layout["items"], layout["revision"])
        self.assertEqual(self.host.events, [("layout.updated", {"revision": layout["revision"] + 1,
                                                                 "updatedBy": "desktop"})])

    def test_remove_and_run(self):
        self.board.remove_card("beta", delete_package=True, confirm=True)
        self.assertIn(("card.removed", {"card": "beta"}), self.host.events)
        run_id = self.board.runner.start("alpha", "fetch", {})["runId"]
        self.board.runner.wait(run_id, timeout=20)
        finished = [p for e, p in self.host.events if e == "run.finished"]
        self.assertEqual(finished, [{"card": "alpha", "runId": run_id, "name": "fetch", "status": "succeeded"}])


if __name__ == "__main__":
    unittest.main()
