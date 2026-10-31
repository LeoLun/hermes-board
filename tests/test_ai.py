from __future__ import annotations

import json
import unittest

from helpers import BoardTestCase, FakeLlm

import cardkit
from hermes_board_core.board import get_board
from hermes_board_core.errors import BoardError

AI = {"pick": {"system": "从节点里选出延迟最低的一个", "maxTokens": 500,
               "inputSchema": {"type": "object", "required": ["nodes"],
                               "properties": {"nodes": {"type": "array", "items": {"type": "object"}}}},
               "outputSchema": {"type": "object", "required": ["node"], "additionalProperties": False,
                                "properties": {"node": {"type": "string"}, "reason": {"type": "string"}}}}}
NODES = {"nodes": [{"name": "hk", "ms": 40}, {"name": "jp", "ms": 80}]}


class AiTest(BoardTestCase):
    bundled_cards = False

    def setUp(self):
        super().setUp()
        self.board = get_board()
        self.board.cards.install(cardkit.package("nodes", ai=AI))

    def test_success_records_run_and_passes_contract(self):
        llm = FakeLlm(parsed={"node": "hk", "reason": "延迟最低"})
        self.host._llm = llm
        result = self.board.ai.run("nodes", "pick", NODES)
        self.assertEqual(result["parsed"], {"node": "hk", "reason": "延迟最低"})
        self.assertEqual((result["model"], result["provider"]), ("fake-model", "fake"))
        self.assertEqual(result["usage"]["total_tokens"], 15)
        call = llm.calls[0]
        self.assertEqual(call["instructions"], AI["pick"]["system"])
        self.assertEqual(json.loads(call["input"][0]["text"]), NODES)
        self.assertEqual(call["json_schema"], AI["pick"]["outputSchema"])
        self.assertEqual(call["purpose"], "hermes-board.nodes.pick")
        self.assertEqual(call["max_tokens"], 500)
        run = self.board.db.get_run(result["runId"])
        self.assertEqual((run["kind"], run["status"]), ("ai", "succeeded"))

    def test_input_validation(self):
        self.host._llm = FakeLlm(parsed={"node": "hk"})
        with self.assertRaises(BoardError) as ctx:
            self.board.ai.run("nodes", "pick", {"nodes": "x"})
        self.assertEqual(ctx.exception.code, "invalid")
        with self.assertRaises(BoardError) as ctx:
            self.board.ai.run("nodes", "pick", {"nodes": [{"pad": "x" * 33000}]})
        self.assertIn("32 KiB", ctx.exception.message)
        self.assertEqual(self.board.db.list_runs("nodes"), [])

    def test_output_must_match_schema(self):
        self.host._llm = FakeLlm(parsed={"server": "hk"})
        with self.assertRaises(BoardError) as ctx:
            self.board.ai.run("nodes", "pick", NODES)
        self.assertEqual(ctx.exception.code, "invalid")
        self.assertEqual(self.board.db.list_runs("nodes")[0]["status"], "failed")

    def test_llm_failure_and_unavailable(self):
        self.host._llm = FakeLlm(error=RuntimeError("provider down"))
        with self.assertRaises(BoardError) as ctx:
            self.board.ai.run("nodes", "pick", NODES)
        self.assertEqual(ctx.exception.code, "ai_unavailable")
        self.assertIn("provider down", self.board.db.list_runs("nodes")[0]["error"])
        self.host._llm = None
        with self.assertRaises(BoardError) as ctx:
            self.board.ai.run("nodes", "pick", NODES)
        self.assertEqual(ctx.exception.code, "ai_unavailable")
        self.assertFalse(self.board.health()["aiAvailable"])


if __name__ == "__main__":
    unittest.main()
