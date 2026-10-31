from __future__ import annotations

import json
import unittest
from unittest import mock

from helpers import BoardTestCase, load_cases

from hermes_board_core import layout as layout_mod
from hermes_board_core.errors import BoardError
from hermes_board_core.layout import LayoutStore, first_fit, push_down, validate_items
from hermes_board_core.paths import Paths
from hermes_board_core.store import BoardDB

CASES = load_cases()


def resolve_items(value):
    if value == "defaultLayout":
        return json.loads(json.dumps(CASES["defaultLayout"]))
    if value == "tooMany":
        return [{"id": f"c{i:02d}", "card": f"c{i:02d}", "x": 0, "y": i * 4, "w": 4, "h": 4} for i in range(65)]
    return value


class GeometryTest(unittest.TestCase):
    def test_first_fit_cases(self):
        for case in CASES["firstFit"]:
            with self.subTest(case["name"]):
                self.assertEqual(first_fit(resolve_items(case["items"]), case["w"], case["h"]),
                                 (case["expect"]["x"], case["expect"]["y"]))

    def test_push_down_cases(self):
        for case in CASES["pushDown"]:
            with self.subTest(case["name"]):
                self.assertEqual(push_down(case["items"], case["active"]), case["expect"])

    def test_default_layout_fills_grid(self):
        items = CASES["defaultLayout"]
        covered = {(x, y) for i in items for x in range(i["x"], i["x"] + i["w"]) for y in range(i["y"], i["y"] + i["h"])}
        self.assertEqual(len(covered), 24 * 16)
        self.assertEqual(sum(i["w"] * i["h"] for i in items), 24 * 16)

    def test_validate_cases(self):
        cards = {cid: {"sizes": sizes} for cid, sizes in CASES["validate"]["cards"].items()}
        for case in CASES["validate"]["cases"]:
            with self.subTest(case["name"]):
                items = resolve_items(case["items"])
                local_cards = dict(cards)
                if case["items"] == "tooMany":
                    local_cards.update({i["card"]: {"sizes": ["4x4"]} for i in items})
                if case["error"] is None:
                    validate_items(items, local_cards, case.get("preserved", ()))
                else:
                    with self.assertRaises(BoardError) as ctx:
                        validate_items(items, local_cards, case.get("preserved", ()))
                    self.assertIn(case["error"], ctx.exception.message)


class LayoutStoreTest(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.paths = Paths(self.tmp / "data", self.tmp / "scripts" / "hermes-board")
        self.db = BoardDB(self.paths.db_file)
        self.store = LayoutStore(self.paths, self.db)
        self.cards = {"weather": {"sizes": ["4x4", "8x4", "8x8"]}, "clock": {"sizes": ["4x4", "6x4", "8x4"]}}

    def test_initialize_then_write_with_revision(self):
        doc = self.store.initialize([{"id": "weather", "card": "weather", "x": 0, "y": 0, "w": 8, "h": 8}], self.cards)
        self.assertEqual(doc["revision"], 1)
        self.assertEqual(doc["updatedBy"], "init")
        again = self.store.initialize([], self.cards)
        self.assertEqual(again["revision"], 1, "initialize must not overwrite an existing board")
        items = doc["items"] + [{"id": "clock", "card": "clock", "x": 8, "y": 0, "w": 8, "h": 4}]
        doc2 = self.store.write(items, base_revision=1, updated_by="desktop", cards=self.cards)
        self.assertEqual(doc2["revision"], 2)
        self.assertEqual(doc2["updatedBy"], "desktop")
        self.assertEqual(json.loads(self.paths.board_file.read_text())["revision"], 2)
        self.assertEqual(self.db.changes_since(0)["changes"], [{"card": None, "kind": "layout", "name": "board"}])

    def test_conflict_returns_current(self):
        self.store.initialize([], self.cards)
        with self.assertRaises(BoardError) as ctx:
            self.store.write([], base_revision=0, updated_by="desktop", cards=self.cards)
        self.assertEqual(ctx.exception.code, "conflict")
        self.assertEqual(ctx.exception.details["current"]["revision"], 1)

    def test_atomic_write_keeps_old_file_on_crash(self):
        self.store.initialize([], self.cards)
        before = self.paths.board_file.read_text()
        with mock.patch("hermes_board_core.fsutil.os.replace", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                self.store.write([], base_revision=1, updated_by="desktop", cards=self.cards)
        self.assertEqual(self.paths.board_file.read_text(), before)
        leftovers = [p.name for p in self.paths.board_file.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_unavailable_card_keeps_placeholder(self):
        self.store.initialize([{"id": "weather", "card": "weather", "x": 0, "y": 0, "w": 8, "h": 8}], self.cards)
        only_clock = {"clock": self.cards["clock"]}
        doc = self.store.write([{"id": "weather", "card": "weather", "x": 0, "y": 8, "w": 8, "h": 8}],
                               base_revision=1, updated_by="desktop", cards=only_clock)
        self.assertEqual(doc["items"][0]["y"], 8)

    def test_newer_schema_refuses(self):
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.paths.board_file.write_text(json.dumps({"schema": "hermes-board/layout@2", "items": []}))
        with self.assertRaises(BoardError) as ctx:
            self.store.write([], base_revision=0, updated_by="desktop", cards=self.cards)
        self.assertIn("新", ctx.exception.message)

    def test_server_fields_ignored_from_client(self):
        self.store.initialize([], self.cards)
        doc = self.store.mutate(lambda d: layout_mod.place_new(d["items"], "clock", "8x4"), updated_by="agent",
                                cards=self.cards)
        self.assertEqual(doc["items"], [{"id": "clock", "card": "clock", "x": 0, "y": 0, "w": 8, "h": 4}])
        self.assertEqual(doc["revision"], 2)


if __name__ == "__main__":
    unittest.main()
