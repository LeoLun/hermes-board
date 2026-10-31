"""Test helpers: every test runs in a temporary HERMES_HOME with a fake host and fake cron."""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermes_board_core import host as host_mod  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def load_cases() -> dict[str, Any]:
    cases = json.loads((FIXTURES / "layout-cases.json").read_text(encoding="utf-8"))
    return cases


class FakeCron:
    """In-memory stand-in for ``cron.jobs`` with the same call shapes (V2-verified)."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple] = []
        self._n = 0
        self.fail_on: Optional[str] = None

    def _maybe_fail(self, op: str) -> None:
        if self.fail_on == op:
            raise RuntimeError(f"fake cron failure on {op}")

    def parse_schedule(self, schedule: str) -> dict[str, Any]:
        return host_mod.fallback_parse_schedule(schedule)

    def create_job(self, prompt=None, schedule=None, name=None, script=None, no_agent=False, deliver=None, **kw):
        self._maybe_fail("create")
        self._n += 1
        job_id = f"job{self._n}"
        job = {"id": job_id, "name": name, "script": script, "schedule": self.parse_schedule(schedule),
               "no_agent": no_agent, "deliver": deliver, "enabled": True, "state": "scheduled", "prompt": prompt}
        self.jobs[job_id] = job
        self.calls.append(("create", job_id, name))
        return copy.deepcopy(job)

    def update_job(self, job_id, updates):
        self._maybe_fail("update")
        job = self.jobs.get(job_id)
        if job is None:
            return None
        job.update(copy.deepcopy(updates))
        self.calls.append(("update", job_id, tuple(sorted(updates))))
        return copy.deepcopy(job)

    def pause_job(self, job_id, reason=None):
        self._maybe_fail("pause")
        job = self.jobs.get(job_id)
        if job is None:
            return None
        job.update({"enabled": False, "state": "paused", "paused_reason": reason})
        self.calls.append(("pause", job_id))
        return copy.deepcopy(job)

    def resume_job(self, job_id):
        self._maybe_fail("resume")
        job = self.jobs.get(job_id)
        if job is None:
            return None
        job.update({"enabled": True, "state": "scheduled", "paused_reason": None})
        self.calls.append(("resume", job_id))
        return copy.deepcopy(job)

    def remove_job(self, job_id):
        self._maybe_fail("remove")
        self.calls.append(("remove", job_id))
        return self.jobs.pop(job_id, None) is not None

    def get_job(self, job_id):
        job = self.jobs.get(job_id)
        return None if job is None else copy.deepcopy(job)

    def list_jobs(self, include_disabled=False):
        return [copy.deepcopy(j) for j in self.jobs.values() if include_disabled or j["enabled"]]


class FakeLlm:
    def __init__(self, parsed: Any = None, error: Optional[Exception] = None) -> None:
        self.parsed = parsed
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error

        class _Usage:
            input_tokens = 10
            output_tokens = 5
            total_tokens = 15
            cost_usd = None

        class _Result:
            pass

        result = _Result()
        result.parsed = self.parsed
        result.text = json.dumps(self.parsed, ensure_ascii=False)
        result.provider = "fake"
        result.model = "fake-model"
        result.usage = _Usage()
        result.content_type = "json"
        return result


class FakeHost(host_mod.Host):
    def __init__(self, home: Path, cron: Optional[FakeCron] = None, llm: Any = None) -> None:
        self.home = home
        self._cron = cron
        self._llm = llm
        self.events: list[tuple[str, dict[str, Any]]] = []

    def hermes_home(self) -> Path:
        return self.home

    def data_dir(self) -> Path:
        path = self.home / "plugin-data" / "hermes-board"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def subprocess_env(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TMPDIR") if k in os.environ}
        env["HERMES_HOME"] = str(self.home)
        return env

    def broadcast(self, event, payload=None):
        self.events.append((event, payload or {}))
        return True

    def cron(self):
        return self._cron

    def parse_schedule(self, schedule):
        if self._cron is not None:
            return self._cron.parse_schedule(schedule)
        return host_mod.fallback_parse_schedule(schedule)

    def llm(self):
        return self._llm


class BoardTestCase(unittest.TestCase):
    with_cron = True
    bundled_cards = True

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hb-test-")).resolve()
        self.cron = FakeCron() if self.with_cron else None
        self.host = FakeHost(self.tmp, cron=self.cron)
        self._prev_host = host_mod.set_host(self.host)
        from hermes_board_core import init as init_mod

        self.bundled = make_bundled(self.tmp / "bundled", self.bundled_cards)
        self._prev_bundled = init_mod.BUNDLED_DIR
        init_mod.BUNDLED_DIR = self.bundled
        try:
            from hermes_board_core import board as board_mod

            board_mod.reset_cache()
        except ImportError:
            pass

    def tearDown(self) -> None:
        try:
            from hermes_board_core import board as board_mod

            board_mod.shutdown_all()
            board_mod.reset_cache()
        except ImportError:
            pass
        from hermes_board_core import init as init_mod

        init_mod.BUNDLED_DIR = self._prev_bundled
        host_mod.set_host(self._prev_host)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait_runs(self, board, timeout: float = 20.0) -> None:
        """Block until every run of every card is terminal."""
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with board.db.connect() as conn:
                n = conn.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]
            if n == 0:
                return
            time.sleep(0.05)
        raise AssertionError("runs did not finish in time")


def make_bundled(target: Path, with_cards: bool = True) -> Path:
    """Write a tiny bundled ``cards/`` directory (alpha + beta) used instead of the real defaults."""
    import cardkit

    target.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    if with_cards:
        alpha = cardkit.package("alpha")
        alpha["manifest"]["scripts"]["fetch"]["runOnInstall"] = True
        beta = cardkit.package("beta", scripts={}, sizes=["6x4", "8x4"], defaultSize="6x4")
        beta["manifest"].pop("scripts")
        beta["manifest"].pop("datasets")
        beta["manifest"].pop("series")
        for pkg in (alpha, beta):
            directory = target / pkg["manifest"]["id"]
            (directory / "scripts").mkdir(parents=True, exist_ok=True)
            (directory / "card.json").write_text(json.dumps(pkg["manifest"], ensure_ascii=False), encoding="utf-8")
            (directory / "index.html").write_text(pkg["html"], encoding="utf-8")
            for name, src in pkg["scripts"].items():
                (directory / "scripts" / name).write_text(src, encoding="utf-8")
        items = [{"id": "alpha", "card": "alpha", "x": 0, "y": 0, "w": 4, "h": 4},
                 {"id": "beta", "card": "beta", "x": 4, "y": 0, "w": 6, "h": 4}]
    (target / "default-layout.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    return target
