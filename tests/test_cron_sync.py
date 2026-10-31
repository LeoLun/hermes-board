from __future__ import annotations

import unittest

from helpers import BoardTestCase, FakeHost

import cardkit
from hermes_board_core.cron_sync import CronSync, job_name
from hermes_board_core.paths import Paths
from hermes_board_core.store import BoardDB


class CronSyncTest(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.paths = Paths(self.host.data_dir(), self.host.scripts_root())
        self.db = BoardDB(self.paths.db_file)
        self.sync = CronSync(self.paths, self.db, self.host)

    def ops(self):
        return [c[0] for c in self.cron.calls]

    def test_install_on_board_creates_job(self):
        self.sync.sync_card("demo", cardkit.manifest(), on_board=True)
        self.assertEqual(self.ops(), ["create"])
        job = next(iter(self.cron.jobs.values()))
        self.assertEqual(job["name"], job_name("demo", "fetch"))
        self.assertTrue(job["no_agent"])
        self.assertEqual(job["deliver"], "local")
        self.assertEqual(job["script"], "hermes-board/demo/fetch.py")
        self.assertEqual(self.db.list_bindings("demo")[0]["paused"], False)

    def test_install_off_board_creates_paused(self):
        self.sync.sync_card("demo", cardkit.manifest(), on_board=False)
        self.assertEqual(self.ops(), ["create", "pause"])
        self.assertTrue(self.db.list_bindings("demo")[0]["paused"])

    def test_update_schedule_and_remove_script(self):
        self.sync.sync_card("demo", cardkit.manifest(), on_board=True)
        m = cardkit.manifest()
        m["scripts"]["fetch"]["schedule"] = "every 15m"
        self.sync.sync_card("demo", m, on_board=True)
        self.assertEqual(self.cron.calls[-1][0], "update")
        job = next(iter(self.cron.jobs.values()))
        self.assertEqual(job["schedule"], {"kind": "interval", "minutes": 15, "display": "every 15m"})
        self.sync.sync_card("demo", m, on_board=True)
        self.assertEqual(self.cron.calls[-1][0], "update", "no extra calls when nothing changed")
        m["scripts"]["fetch"].pop("schedule")
        self.sync.sync_card("demo", m, on_board=True)
        self.assertEqual(self.cron.calls[-1][0], "remove")
        self.assertEqual(self.cron.jobs, {})
        self.assertEqual(self.db.list_bindings("demo"), [])

    def test_board_membership_pauses_and_resumes(self):
        self.sync.sync_card("demo", cardkit.manifest(), on_board=True)
        self.sync.set_paused("demo", True)
        self.assertEqual(self.cron.calls[-1][0], "pause")
        self.sync.set_paused("demo", True)
        self.assertEqual(self.ops().count("pause"), 1)
        self.sync.set_paused("demo", False)
        self.assertEqual(self.cron.calls[-1][0], "resume")
        self.assertFalse(self.db.list_bindings("demo")[0]["paused"])

    def test_remove_card(self):
        self.sync.sync_card("demo", cardkit.manifest(), on_board=True)
        self.sync.remove_card("demo")
        self.assertEqual(self.cron.jobs, {})
        self.assertEqual(self.db.list_bindings(), [])

    def test_reconcile_recreates_missing_and_removes_orphans(self):
        self.sync.sync_card("demo", cardkit.manifest(), on_board=True)
        lost = next(iter(self.cron.jobs))
        del self.cron.jobs[lost]
        orphan = self.cron.create_job(schedule="every 5m", name="hermes-board:ghost:x", script="hermes-board/ghost/x.py",
                                      no_agent=True, deliver="local")
        foreign = self.cron.create_job(schedule="every 5m", name="someone-else", script="x.py")
        self.db.put_binding("gone", "fetch", "job-missing", "every 1h", False)
        stats = self.sync.reconcile({"demo": cardkit.manifest()}, on_board=["demo"])
        names = sorted(j["name"] for j in self.cron.jobs.values())
        self.assertEqual(names, ["hermes-board:demo:fetch", "someone-else"])
        self.assertNotIn(orphan["id"], self.cron.jobs)
        self.assertIn(foreign["id"], self.cron.jobs)
        self.assertEqual(stats["orphansRemoved"], 1)
        self.assertEqual([b["card"] for b in self.db.list_bindings()], ["demo"])

    def test_status(self):
        self.sync.sync_card("demo", cardkit.manifest(), on_board=False)
        status = self.sync.status("demo")
        self.assertTrue(status["fetch"]["paused"])
        self.assertEqual(status["fetch"]["state"], "paused")


class CronUnavailableTest(BoardTestCase):
    with_cron = False

    def test_degrades_without_cron(self):
        paths = Paths(self.host.data_dir(), self.host.scripts_root())
        db = BoardDB(paths.db_file)
        sync = CronSync(paths, db, self.host)
        self.assertFalse(sync.available())
        sync.sync_card("demo", cardkit.manifest(), on_board=True)
        sync.set_paused("demo", True)
        self.assertEqual(sync.reconcile({"demo": cardkit.manifest()}, ["demo"]), {"synced": 0, "orphansRemoved": 0})
        self.assertEqual(sync.status("demo"), {})
        self.assertIsInstance(self.host, FakeHost)


if __name__ == "__main__":
    unittest.main()
