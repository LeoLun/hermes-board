from __future__ import annotations

import json
import unittest

from helpers import BoardTestCase

import cardkit
from hermes_board_core.cards import CardStore
from hermes_board_core.cron_sync import CronSync
from hermes_board_core.errors import BoardError
from hermes_board_core.paths import Paths
from hermes_board_core.store import BoardDB, SDK_PATH


class CardStoreTest(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.paths = Paths(self.host.data_dir(), self.host.scripts_root())
        self.db = BoardDB(self.paths.db_file)
        self.board = set()
        self.cron_sync = CronSync(self.paths, self.db, self.host)
        self.store = CardStore(self.paths, self.db, self.host, self.cron_sync, on_board=lambda cid: cid in self.board)

    def snapshot(self, card_id="demo"):
        files = {}
        for base in (self.paths.card_dir(card_id), self.paths.card_scripts_dir(card_id)):
            if base.exists():
                for p in sorted(base.rglob("*")):
                    if p.is_file() and p.name != ".meta.json":
                        files[str(p.relative_to(self.tmp))] = p.read_text()
        return files

    def test_install_writes_both_sides_and_sdk(self):
        result = self.store.install(cardkit.package())
        self.assertEqual(result, {"card": "demo", "revision": 1, "created": True, "warnings": []})
        self.assertTrue((self.paths.card_dir("demo") / "card.json").is_file())
        self.assertTrue((self.paths.card_dir("demo") / "index.html").is_file())
        self.assertTrue((self.paths.card_scripts_dir("demo") / "fetch.py").is_file())
        self.assertEqual(self.paths.sdk_file.read_bytes(), SDK_PATH.read_bytes())
        self.assertEqual(self.store.ids(), ["demo"])
        self.assertEqual(self.store.available(), {"demo": {"sizes": ["4x4", "6x4"]}})
        job = next(iter(self.cron.jobs.values()))
        self.assertEqual(job["script"], "hermes-board/demo/fetch.py")
        self.assertFalse(job["enabled"], "a card that is not on the board keeps its cron paused")
        leftovers = [p.name for p in self.paths.cards_dir.iterdir() if p.name.startswith(".")]
        self.assertEqual(leftovers, [])

    def test_update_requires_replace_and_bumps_revision(self):
        self.store.install(cardkit.package())
        with self.assertRaises(BoardError) as ctx:
            self.store.install(cardkit.package())
        self.assertEqual(ctx.exception.code, "exists")
        result = self.store.install(cardkit.package(title="新标题"), replace=True)
        self.assertEqual(result["revision"], 2)
        self.assertFalse(result["created"])
        self.assertEqual(self.store.info("demo")["title"], "新标题")
        self.assertEqual(self.store.document("demo")["revision"], 2)
        self.assertEqual(len(self.cron.jobs), 1)

    def test_traversal_is_rejected_without_writing(self):
        pkg = cardkit.package(scripts={"fetch.py": cardkit.SCRIPT, "../../evil.py": "print('x')"})
        with self.assertRaises(BoardError) as ctx:
            self.store.install(pkg)
        self.assertEqual(ctx.exception.code, "invalid")
        self.assertFalse((self.tmp / "evil.py").exists())
        self.assertFalse(self.paths.card_dir("demo").exists())
        self.assertEqual(self.cron.jobs, {})

    def test_cron_failure_on_update_rolls_back_files_and_cron(self):
        self.store.install(cardkit.package())
        before = self.snapshot()
        job_before = json.loads(json.dumps(list(self.cron.jobs.values())))
        pkg = cardkit.package(title="v2", scripts={"fetch.py": cardkit.SCRIPT + "\n# v2\n", "extra.py": cardkit.SCRIPT})
        pkg["manifest"]["scripts"]["fetch"]["schedule"] = "every 15m"
        pkg["manifest"]["scripts"]["extra"] = {"file": "extra.py", "schedule": "every 5m"}
        self.cron.fail_on = "create"
        with self.assertRaises(BoardError):
            self.store.install(pkg, replace=True)
        self.cron.fail_on = None
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.store.info("demo")["revision"], 1)
        self.assertEqual(list(self.cron.jobs.values()), job_before)
        self.assertEqual([b["schedule"] for b in self.db.list_bindings("demo")], ["every 30m"])

    def test_cron_failure_on_fresh_install_leaves_nothing(self):
        self.cron.fail_on = "pause"
        with self.assertRaises(BoardError):
            self.store.install(cardkit.package())
        self.cron.fail_on = None
        self.assertFalse(self.paths.card_dir("demo").exists())
        self.assertFalse(self.paths.card_scripts_dir("demo").exists())
        self.assertEqual(self.cron.jobs, {})
        self.assertEqual(self.db.list_bindings(), [])

    def test_delete_moves_to_trash_and_clears_data(self):
        self.store.install(cardkit.package())
        self.db.put_dataset("demo", "current", {"n": 1})
        result = self.store.delete("demo")
        trash = self.paths.trash_dir
        entries = list(trash.iterdir())
        self.assertEqual(len(entries), 1)
        self.assertTrue((entries[0] / "card" / "card.json").is_file())
        self.assertTrue((entries[0] / "scripts" / "fetch.py").is_file())
        self.assertEqual(result["card"], "demo")
        self.assertEqual(self.db.list_datasets("demo"), {})
        self.assertEqual(self.cron.jobs, {})
        with self.assertRaises(BoardError):
            self.store.delete("demo")

    def test_sdk_sync_by_hash(self):
        self.assertTrue(self.store.sync_sdk())
        self.assertFalse(self.store.sync_sdk())
        self.paths.sdk_file.write_text("# tampered\n")
        self.assertTrue(self.store.sync_sdk())
        self.assertEqual(self.paths.sdk_file.read_bytes(), SDK_PATH.read_bytes())

    def test_invalid_card_on_disk_is_reported(self):
        self.store.install(cardkit.package())
        (self.paths.card_dir("demo") / "card.json").write_text("{broken")
        info = self.store.info("demo")
        self.assertEqual(info["status"], "invalid")
        self.assertEqual(self.store.available(), {})
        with self.assertRaises(BoardError):
            self.store.manifest("demo")


if __name__ == "__main__":
    unittest.main()
