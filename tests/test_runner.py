from __future__ import annotations

import os
import time
import unittest

from helpers import BoardTestCase

import cardkit
from hermes_board_core.board import get_board
from hermes_board_core.errors import BoardError

SDK_HEAD = """import sys, pathlib, time, subprocess
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "_sdk"))
from hermes_board_sdk import Card
card = Card()
"""

SCRIPTS = {
    "slow.py": SDK_HEAD + "time.sleep(card.args.get('sec', 0.3))\ncard.result({'slept': True})\n",
    "spawn.py": SDK_HEAD + "child = subprocess.Popen(['sleep', '30'])\ncard.state.set('child', child.pid)\ntime.sleep(30)\n",
    "loud.py": "print('x' * 200000)\nprint('END')\n",
    "result.sh": "echo hello\necho 'HERMES_BOARD_RESULT {\"a\": 1}'\n",
    "boom.py": "raise RuntimeError('boom')\n",
    "hidden.py": "print('hidden')\n",
}

DECLS = {
    "slow": {"file": "slow.py", "callable": True, "timeoutSec": 30,
             "args": {"type": "object", "properties": {"sec": {"type": "number"}}, "additionalProperties": False}},
    "spawn": {"file": "spawn.py", "callable": True, "timeoutSec": 1},
    "loud": {"file": "loud.py", "callable": True},
    "shres": {"file": "result.sh", "callable": True},
    "boom": {"file": "boom.py", "callable": True},
    "hidden": {"file": "hidden.py"},
    "limited": {"file": "slow.py", "callable": True, "minIntervalSec": 60},
}


def _pkg(card_id):
    pkg = cardkit.package(card_id, scripts=dict(SCRIPTS))
    pkg["manifest"]["scripts"] = {k: dict(v) for k, v in DECLS.items()}
    return pkg


class RunnerTest(BoardTestCase):
    bundled_cards = False

    def setUp(self):
        super().setUp()
        self.board = get_board()
        self.board.cards.install(_pkg("runner"))
        self.runner = self.board.runner

    def finish(self, run_id, timeout=20):
        return self.runner.wait(run_id, timeout=timeout)

    def test_callable_and_args_validation(self):
        with self.assertRaises(BoardError) as ctx:
            self.runner.start("runner", "hidden")
        self.assertIn("callable", ctx.exception.message)
        run = self.finish(self.runner.start("runner", "hidden", trigger="tool")["runId"])
        self.assertEqual(run["status"], "succeeded")
        self.assertIn("hidden", run["stdoutTail"])
        with self.assertRaises(BoardError) as ctx:
            self.runner.start("runner", "slow", {"sec": "x"})
        self.assertEqual(ctx.exception.code, "invalid")
        with self.assertRaises(BoardError):
            self.runner.start("runner", "slow", {"other": 1})
        with self.assertRaises(BoardError) as ctx:
            self.runner.start("runner", "nope")
        self.assertEqual(ctx.exception.code, "not_found")

    def test_single_flight(self):
        first = self.runner.start("runner", "slow", {"sec": 1})
        second = self.runner.start("runner", "slow", {"sec": 1})
        self.assertTrue(second["deduplicated"])
        self.assertEqual(first["runId"], second["runId"])
        run = self.finish(first["runId"])
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["result"], {"slept": True})
        third = self.runner.start("runner", "slow", {"sec": 0})
        self.assertNotEqual(third["runId"], first["runId"])
        self.finish(third["runId"])

    def test_global_concurrency_is_four(self):
        for i in range(1, 5):
            self.board.cards.install(_pkg(f"runner{i}"))
        ids = [self.runner.start(cid, "slow", {"sec": 1.5})["runId"]
               for cid in ("runner", "runner1", "runner2", "runner3", "runner4")]
        time.sleep(0.7)
        statuses = [self.board.db.get_run(r)["status"] for r in ids]
        self.assertEqual(statuses.count("running"), 4, statuses)
        self.assertEqual(statuses.count("queued"), 1, statuses)
        for r in ids:
            self.assertEqual(self.finish(r)["status"], "succeeded")

    def test_timeout_kills_process_group(self):
        run = self.finish(self.runner.start("runner", "spawn")["runId"])
        self.assertEqual(run["status"], "timeout")
        child = self.board.db.get_state("runner", "child")["value"]
        deadline = time.monotonic() + 5
        alive = True
        while time.monotonic() < deadline:
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                alive = False
                break
            except PermissionError:
                break
            time.sleep(0.1)
        self.assertFalse(alive, "grandchild sleep process should be killed with the group")

    def test_output_truncated_and_sh_result(self):
        run = self.finish(self.runner.start("runner", "loud")["runId"])
        self.assertLessEqual(len(run["stdoutTail"].encode()), 4096)
        self.assertTrue(run["stdoutTail"].rstrip().endswith("END"))
        run = self.finish(self.runner.start("runner", "shres")["runId"])
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["result"], {"a": 1})

    def test_failure_and_event(self):
        run = self.finish(self.runner.start("runner", "boom")["runId"])
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["exitCode"], 1)
        self.assertIn("boom", run["error"])
        finished = [p for e, p in self.host.events if e == "run.finished"]
        self.assertEqual(finished[-1]["runId"], run["runId"])
        self.assertEqual(finished[-1]["status"], "failed")

    def test_min_interval(self):
        first = self.runner.start("runner", "limited", {"sec": 0})
        self.finish(first["runId"])
        with self.assertRaises(BoardError) as ctx:
            self.runner.start("runner", "limited", {"sec": 0})
        self.assertEqual(ctx.exception.code, "rate_limited")
        self.assertGreater(ctx.exception.details["retryAfterMs"], 0)


if __name__ == "__main__":
    unittest.main()
