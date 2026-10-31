"""Action runner for card scripts (design §8.2)."""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Optional

from .constants import BRIDGE, LIMITS
from .errors import BoardError
from .host import Host
from .paths import Paths
from .store import sdk
from .validator import validate_value

logger = logging.getLogger("hermes_board")
RESULT_PREFIX = "HERMES_BOARD_RESULT "
STALE_GRACE_MS = 30_000


class _Capture(threading.Thread):
    """Drain a pipe, keeping only the last ``limit`` bytes so the child never blocks."""

    def __init__(self, stream, limit: int) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.limit = limit
        self.chunks: deque[bytes] = deque()
        self.size = 0

    def run(self) -> None:
        try:
            for chunk in iter(lambda: self.stream.read(8192), b""):
                self.chunks.append(chunk)
                self.size += len(chunk)
                while self.size - len(self.chunks[0]) >= self.limit:
                    self.size -= len(self.chunks.popleft())
        except (OSError, ValueError):
            pass

    def text(self) -> str:
        data = b"".join(self.chunks)[-self.limit:]
        return data.decode("utf-8", "replace")


class Runner:
    def __init__(self, paths: Paths, db: Any, host: Host, cards: Any, events: Any,
                 max_workers: Optional[int] = None) -> None:
        self.paths = paths
        self.db = db
        self.host = host
        self.cards = cards
        self.events = events
        self._pool = ThreadPoolExecutor(max_workers=max_workers or LIMITS["maxConcurrentRuns"],
                                        thread_name_prefix="hermes-board-run")
        self._lock = threading.Lock()
        self._active: dict[tuple[str, str], str] = {}
        self._futures: dict[str, Future] = {}

    # ── public ────────────────────────────────────────────────────────────
    def start(self, card_id: str, script: str, args: Any = None, trigger: str = "action") -> dict[str, Any]:
        manifest = self.cards.manifest(card_id)
        decl = (manifest.get("scripts") or {}).get(script)
        if not isinstance(decl, dict):
            raise BoardError("not_found", f"卡片 {card_id} 没有声明脚本 {script}")
        if trigger == "action" and not decl.get("callable"):
            raise BoardError("invalid", f"脚本 {script} 没有声明 callable，不能从卡片调用")
        args = {} if args is None else args
        if not isinstance(args, dict):
            raise BoardError("invalid", "args 必须是对象")
        if len(sdk.dumps(args).encode("utf-8")) > BRIDGE["maxParamBytes"]:
            raise BoardError("invalid", "args 过大")
        if isinstance(decl.get("args"), dict):
            errors = validate_value(decl["args"], args, "args")
            if errors:
                raise BoardError("invalid", "；".join(errors[:5]), errors=errors)
        timeout = min(int(decl.get("timeoutSec", LIMITS["actionTimeoutDefault"])), LIMITS["actionTimeoutMax"])
        with self._lock:
            active = self._active_run(card_id, script, timeout)
            if active is not None:
                return {"runId": active["runId"], "status": active["status"], "deduplicated": True}
            min_interval = int(decl.get("minIntervalSec", 0) or 0)
            if min_interval and trigger in ("action", "tool"):
                last = self.db.last_started(card_id, "script", script)
                wait_ms = (last + min_interval * 1000 - sdk.now_ms()) if last is not None else 0
                if wait_ms > 0:
                    raise BoardError("rate_limited", f"脚本 {script} 每 {min_interval} 秒最多运行一次",
                                     retryAfterMs=wait_ms)
            run_id = self.db.create_run(card_id, "script", script, trigger, status="queued")
            self._active[(card_id, script)] = run_id
            future = self._pool.submit(self._execute, run_id, card_id, script, dict(decl), args, trigger, timeout)
            self._futures[run_id] = future
        return {"runId": run_id, "status": "queued"}

    def wait(self, run_id: str, timeout: Optional[float] = None) -> dict[str, Any]:
        future = self._futures.get(run_id)
        if future is not None:
            future.result(timeout=timeout)
        run = self.db.get_run(run_id)
        if run is None:
            raise BoardError("not_found", f"运行记录不存在：{run_id}")
        return run

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)

    # ── internals ─────────────────────────────────────────────────────────
    def _active_run(self, card_id: str, script: str, timeout: int) -> Optional[dict[str, Any]]:
        run_id = self._active.get((card_id, script))
        if run_id is not None:
            run = self.db.get_run(run_id)
            if run is not None and run["status"] in ("queued", "running"):
                return run
            self._active.pop((card_id, script), None)
        run = self.db.active_run(card_id, "script", script)  # e.g. a cron-triggered run in progress
        if run is not None and sdk.now_ms() - run["createdAt"] <= timeout * 1000 + STALE_GRACE_MS:
            return run
        return None

    def _execute(self, run_id: str, card_id: str, script: str, decl: dict[str, Any], args: dict[str, Any],
                 trigger: str, timeout: int) -> None:
        status, error, exit_code, out_text, err_text = "failed", None, None, "", ""
        args_path = None
        try:
            path = self.paths.script_file(card_id, decl["file"])
            if not path.is_file():
                raise BoardError("not_found", f"脚本文件不存在：{decl['file']}")
            self.paths.tmp_dir.mkdir(parents=True, exist_ok=True)
            fd, args_path = tempfile.mkstemp(prefix=f"{card_id}-{script}-", suffix=".json", dir=str(self.paths.tmp_dir))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(args, handle, ensure_ascii=False)
            env = self.host.subprocess_env()
            env.update({"HERMES_BOARD_RUN_ID": run_id, "HERMES_BOARD_TRIGGER": trigger,
                        "HERMES_BOARD_ARGS_FILE": args_path})
            cmd = [sys.executable, str(path)] if path.suffix == ".py" else ["bash", str(path)]
            self.db.update_run(run_id, status="running", started_at=sdk.now_ms())
            proc = subprocess.Popen(cmd, cwd=str(path.parent), env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            out_cap = _Capture(proc.stdout, LIMITS["outputCaptureBytes"])
            err_cap = _Capture(proc.stderr, LIMITS["outputCaptureBytes"])
            out_cap.start()
            err_cap.start()
            try:
                exit_code = proc.wait(timeout=timeout)
                status = "succeeded" if exit_code == 0 else "failed"
            except subprocess.TimeoutExpired:
                self._kill_group(proc)
                exit_code = proc.wait()
                status = "timeout"
                error = f"运行超过 {timeout} 秒，已终止"
            out_cap.join(timeout=5)
            err_cap.join(timeout=5)
            for stream in (proc.stdout, proc.stderr):
                try:
                    stream.close()
                except OSError:
                    pass
            out_text, err_text = out_cap.text(), err_cap.text()
        except BoardError as exc:
            error = exc.message
        except Exception as exc:  # unexpected runner failure must still finish the run
            logger.exception("hermes-board: run %s crashed", run_id)
            error = f"执行器错误：{exc}"
        finally:
            if args_path:
                try:
                    os.unlink(args_path)
                except OSError:
                    pass
        fields: dict[str, Any] = {"status": status, "finished_at": sdk.now_ms(), "exit_code": exit_code,
                                  "stdout_tail": out_text, "stderr_tail": err_text}
        result = self._result_line(out_text)
        if result is not None:
            fields["result_json"] = result
        current = self.db.get_run(run_id) or {}
        if error is not None:
            fields["error"] = error
        elif status == "failed" and not current.get("error"):
            fields["error"] = (err_text.strip().splitlines() or [f"退出码 {exit_code}"])[-1][:500]
        try:
            self.db.update_run(run_id, **fields)
        finally:
            with self._lock:
                if self._active.get((card_id, script)) == run_id:
                    self._active.pop((card_id, script), None)
                self._futures.pop(run_id, None)
        try:
            self.events.run_finished(card_id, run_id, script, status)
        except Exception:  # pragma: no cover - events are best effort
            pass

    @staticmethod
    def _result_line(out_text: str) -> Optional[str]:
        lines = [line for line in out_text.strip().splitlines() if line.strip()]
        if not lines or not lines[-1].startswith(RESULT_PREFIX):
            return None
        try:
            return sdk.dumps(json.loads(lines[-1][len(RESULT_PREFIX):]))
        except (ValueError, sdk.BoardError):
            return None

    @staticmethod
    def _kill_group(proc: subprocess.Popen) -> None:
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pgid, sig)
            except OSError:
                return
            try:
                proc.wait(timeout=2)
                if sig == signal.SIGTERM:
                    os.killpg(pgid, signal.SIGKILL)  # make sure grandchildren are gone too
                return
            except subprocess.TimeoutExpired:
                continue
            except OSError:
                return


__all__ = ["Runner", "RESULT_PREFIX"]
