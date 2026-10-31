from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

from helpers import BoardTestCase

from hermes_board_core.store import BoardDB, sdk

BoardError = sdk.BoardError


class StoreTest(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.db = BoardDB(self.tmp / "board.sqlite3")

    def test_schema_and_wal(self):
        self.assertEqual(self.db.migrate(), 1)
        conn = sqlite3.connect(self.db.path)
        try:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        self.assertTrue({"meta", "datasets", "series_points", "card_state", "runs", "changes", "cron_bindings"} <= tables)

    def test_newer_schema_is_refused(self):
        self.db.migrate()
        self.db.set_meta("schemaVersion", "2")
        with self.assertRaises(BoardError):
            BoardDB(self.db.path).migrate()

    def test_dataset_roundtrip_and_limit(self):
        self.db.put_dataset("weather", "current", {"temp": 21, "城市": "北京"})
        row = self.db.get_dataset("weather", "current")
        self.assertEqual(row["value"], {"temp": 21, "城市": "北京"})
        self.assertIsInstance(row["updatedAt"], int)
        self.assertEqual(list(self.db.list_datasets("weather")), ["current"])
        with self.assertRaises(BoardError):
            self.db.put_dataset("weather", "big", "x" * (256 * 1024 + 1))
        with self.assertRaises(BoardError):
            self.db.put_dataset("weather", "bad key", 1)

    def test_series_query_order_limit(self):
        base = sdk.now_ms() - 10000
        for i in range(5):
            self.db.append_series("sys", "cpu", i, ts=base + i)
        self.assertEqual([p["value"] for p in self.db.query_series("sys", "cpu")], [0, 1, 2, 3, 4])
        self.assertEqual([p["value"] for p in self.db.query_series("sys", "cpu", order="desc", limit=2)], [4, 3])
        self.assertEqual([p["value"] for p in self.db.query_series("sys", "cpu", since=base + 2, until=base + 3)], [2, 3])
        with self.assertRaises(BoardError):
            self.db.query_series("sys", "cpu", limit=5001)
        with self.assertRaises(BoardError):
            self.db.append_series("sys", "cpu", "x" * 5000)

    def test_series_retention_by_points_and_age(self):
        now = sdk.now_ms()
        with mock.patch.object(sdk, "PRUNE_EVERY_WRITES", 1):
            for i in range(10):
                self.db.append_series("sys", "cpu", i, ts=now - 1000 + i, retention={"maxPoints": 3})
        self.assertEqual([p["value"] for p in self.db.query_series("sys", "cpu")], [7, 8, 9])
        self.db.append_series("sys", "mem", "old", ts=now - 3 * 86400000)
        self.db.append_series("sys", "mem", "new", ts=now)
        self.db.prune_series("sys", "mem", {"maxAgeDays": 1})
        self.assertEqual([p["value"] for p in self.db.query_series("sys", "mem")], ["new"])

    def test_state_limits(self):
        self.db.set_state("note", "text", "你好")
        self.assertEqual(self.db.get_state("note", "text")["value"], "你好")
        with self.assertRaises(BoardError):
            self.db.set_state("note", "huge", "x" * (64 * 1024))
        chunk = "y" * (60 * 1024)
        for i in range(17):
            self.db.set_state("note", f"k{i}", chunk)
        with self.assertRaises(BoardError):
            self.db.set_state("note", "k17", chunk)
        self.assertTrue(self.db.delete_state("note", "text"))
        self.assertIsNone(self.db.get_state("note", "text"))

    def test_runs_lifecycle_and_retention(self):
        run_id = self.db.create_run("weather", "script", "fetch", "action")
        self.assertEqual(self.db.active_run("weather", "script", "fetch")["runId"], run_id)
        self.db.update_run(run_id, status="running", started_at=sdk.now_ms(), progress=0.5, message="半程")
        self.db.update_run(run_id, status="succeeded", finished_at=sdk.now_ms(), exit_code=0,
                           result_json=sdk.dumps({"ok": True}), stdout_tail="o" * 10000)
        run = self.db.get_run(run_id)
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["result"], {"ok": True})
        self.assertLessEqual(len(run["stdoutTail"].encode()), 4096)
        self.assertIsNone(self.db.active_run("weather", "script", "fetch"))
        for _ in range(105):
            rid = self.db.create_run("weather", "script", "fetch", "cron")
            self.db.update_run(rid, status="succeeded")
        self.assertEqual(len(self.db.list_runs("weather", limit=100)), 100)
        with self.assertRaises(BoardError):
            self.db.update_run(run_id, bogus=1)

    def test_changes_since_dedup_and_reset(self):
        self.assertEqual(self.db.changes_since(0), {"seq": 0, "changes": []})
        self.db.put_dataset("a1", "k", 1)
        self.db.put_dataset("a1", "k", 2)
        self.db.set_state("a1", "s", 1)
        res = self.db.changes_since(0)
        self.assertEqual(res["seq"], 3)
        self.assertEqual(res["changes"], [{"card": "a1", "kind": "data", "name": "k"},
                                          {"card": "a1", "kind": "state", "name": "s"}])
        self.assertEqual(self.db.changes_since(3)["changes"], [])
        self.assertTrue(self.db.changes_since(99)["reset"])
        self.db.prune_changes(older_than_ms=sdk.now_ms() + 1)
        self.db.add_change(None, "layout", "board")
        self.assertTrue(self.db.changes_since(1)["reset"])
        self.assertFalse(self.db.changes_since(3).get("reset", False))

    def test_bindings_and_delete_card(self):
        self.db.put_binding("weather", "fetch", "job1", "every 30m", False)
        self.db.put_binding("weather", "fetch", "job2", "every 15m", True)
        self.assertEqual(self.db.list_bindings("weather"),
                         [{"card": "weather", "script": "fetch", "jobId": "job2", "schedule": "every 15m", "paused": True}])
        self.db.put_dataset("weather", "current", 1)
        self.db.append_series("weather", "temp", 1)
        self.db.set_state("weather", "city", "上海")
        self.db.create_run("weather", "script", "fetch", "cron")
        self.db.delete_card_data("weather")
        self.assertEqual(self.db.list_datasets("weather"), {})
        self.assertEqual(self.db.query_series("weather", "temp"), [])
        self.assertEqual(self.db.list_state("weather"), {})
        self.assertEqual(self.db.list_runs("weather"), [])
        self.assertEqual(self.db.list_bindings("weather"), [])


if __name__ == "__main__":
    unittest.main()
