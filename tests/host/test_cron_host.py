"""Host integration (V2 pinned as a test). Runs only when HERMES_AGENT_ROOT points at a hermes-agent checkout.

Everything happens in a child process whose HERMES_HOME is a fresh temp dir, set before any
Hermes module is imported, so the real ~/.hermes is never touched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
AGENT_ROOT = os.environ.get("HERMES_AGENT_ROOT")

CHILD = r"""
import json, os, sys
from pathlib import Path
sys.path[:0] = [{agent!r}, {root!r}, {tests!r}]
home = Path(os.environ["HERMES_HOME"]).resolve()
import cardkit
from hermes_board_core import init
init.BUNDLED_DIR = Path({bundled!r})
from hermes_board_core.host import get_host
from hermes_board_core.board import get_board

host = get_host()
out = {{"cronAvailable": host.cron() is not None, "dataDir": str(host.data_dir().resolve())}}
board = get_board()
board.install_card(cardkit.package("demo"))

import cron.jobs as cj
import cron.scheduler_script as ss
out["jobsFileInHome"] = str(Path(cj.JOBS_FILE).resolve()).startswith(str(home))
job = [j for j in cj.list_jobs(include_disabled=True) if j.get("name") == "hermes-board:demo:fetch"][0]
out["job"] = {{k: job.get(k) for k in ("no_agent", "script", "deliver", "enabled")}}
ok, text = ss._run_job_script("hermes-board/demo/fetch.py")
out["scriptOk"] = ok
out["scriptOutput"] = text
out["current"] = board.db.get_dataset("demo", "current")["value"]
out["runs"] = [(r["trigger"], r["status"]) for r in board.db.list_runs("demo")]
board.remove_item("demo")
out["pausedAfterRemove"] = not cj.get_job(job["id"])["enabled"]
board.add_item("demo")
out["resumedAfterAdd"] = bool(cj.get_job(job["id"])["enabled"])
board.remove_card("demo", delete_package=True, confirm=True)
out["jobGone"] = cj.get_job(job["id"]) is None
board.shutdown()
Path(os.environ["HB_RESULT_FILE"]).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
"""


@unittest.skipUnless(AGENT_ROOT, "set HERMES_AGENT_ROOT to run host integration tests")
class CronHostTest(unittest.TestCase):
    def test_real_cron_roundtrip(self):
        home = Path(tempfile.mkdtemp(prefix="hb-host-")).resolve()
        bundled = home / "_bundled"
        bundled.mkdir()
        (bundled / "default-layout.json").write_text('{"items": []}', encoding="utf-8")
        try:
            env = {k: os.environ[k] for k in ("PATH", "LANG", "TMPDIR", "HOME") if k in os.environ}
            env["HERMES_HOME"] = str(home)
            result_file = home / "_result.json"
            env["HB_RESULT_FILE"] = str(result_file)
            code = CHILD.format(agent=str(Path(AGENT_ROOT).resolve()), root=str(ROOT), tests=str(TESTS),
                                bundled=str(bundled))
            proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
            self.assertTrue(result_file.is_file(), proc.stdout[-2000:] + proc.stderr[-3000:])
            out = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertTrue(out["cronAvailable"])
            self.assertTrue(out["dataDir"].startswith(str(home)), out["dataDir"])
            self.assertTrue(out["jobsFileInHome"])
            self.assertEqual(out["job"], {"no_agent": True, "script": "hermes-board/demo/fetch.py",
                                          "deliver": "local", "enabled": True})
            self.assertTrue(out["scriptOk"], out["scriptOutput"])
            self.assertEqual(out["scriptOutput"].strip(), "")
            self.assertEqual(out["current"], {"n": 1})
            self.assertIn(["cron", "succeeded"], out["runs"])
            self.assertTrue(out["pausedAfterRemove"])
            self.assertTrue(out["resumedAfterAdd"])
            self.assertTrue(out["jobGone"])
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
