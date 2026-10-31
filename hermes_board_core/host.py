"""Adapter to Hermes internals. Every host import is lazy and every capability degrades.

Tests replace the active host with :func:`set_host` so no unit test touches a real
Hermes installation, profile or cron store.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

from .constants import PLUGIN_ID

logger = logging.getLogger("hermes_board")

_ENV_WHITELIST = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "USER", "LOGNAME", "SHELL")
_INTERVAL_RE = re.compile(r"^every\s+(\d+)\s*(m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)$", re.I)
_CRON_FIELD_RE = re.compile(r"^[\d*/,\-]+$")


class Host:
    """Real Hermes host with graceful fallbacks when an internal API is missing."""

    # ── locations ─────────────────────────────────────────────────────────
    def hermes_home(self) -> Path:
        try:
            from hermes_constants import get_hermes_home  # type: ignore

            return Path(get_hermes_home())
        except Exception:
            env = os.environ.get("HERMES_HOME")
            return Path(env) if env else Path.home() / ".hermes"

    def data_dir(self) -> Path:
        try:
            from plugins.plugin_storage import plugin_data_dir  # type: ignore

            return Path(plugin_data_dir(PLUGIN_ID))
        except Exception:
            path = self.hermes_home() / "plugin-data" / PLUGIN_ID
            path.mkdir(parents=True, exist_ok=True)
            return path

    def scripts_root(self) -> Path:
        return self.hermes_home() / "scripts" / PLUGIN_ID

    # ── subprocess environment (same factory Hermes cron scripts use) ────
    def subprocess_env(self) -> dict[str, str]:
        try:
            from tools.environments.local import build_subprocess_env  # type: ignore

            env = dict(build_subprocess_env(strip_launch_profile=True))
        except Exception:
            env = {k: v for k, v in os.environ.items() if k in _ENV_WHITELIST}
        env["HERMES_HOME"] = str(self.hermes_home())
        return env

    # ── events ────────────────────────────────────────────────────────────
    def broadcast(self, event: str, payload: Optional[dict[str, Any]] = None) -> bool:
        try:
            from hermes_cli.plugin_events import broadcast_plugin_event  # type: ignore

            broadcast_plugin_event(PLUGIN_ID, event, payload or {})
            return True
        except Exception as exc:  # events are an accelerator; polling is the fallback
            logger.debug("hermes-board: broadcast %s failed: %s", event, exc)
            return False

    # ── cron ──────────────────────────────────────────────────────────────
    def cron(self) -> Optional[ModuleType]:
        try:
            import cron.jobs as jobs  # type: ignore
        except Exception:
            return None
        required = ("create_job", "update_job", "remove_job", "pause_job", "resume_job", "get_job", "list_jobs",
                    "parse_schedule")
        return jobs if all(callable(getattr(jobs, name, None)) for name in required) else None

    def parse_schedule(self, schedule: str) -> dict[str, Any]:
        jobs = self.cron()
        if jobs is not None:
            try:
                return jobs.parse_schedule(schedule)
            except Exception as exc:
                raise ValueError(str(exc)) from exc
        return fallback_parse_schedule(schedule)

    # ── llm ───────────────────────────────────────────────────────────────
    def llm(self) -> Any:
        from . import ai

        return ai.get_llm()


def fallback_parse_schedule(schedule: str) -> dict[str, Any]:
    """Conservative parser used only when Hermes cron is not importable."""
    if not isinstance(schedule, str) or not schedule.strip():
        raise ValueError("schedule 不能为空")
    text = schedule.strip()
    m = _INTERVAL_RE.match(text)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()[0]
        minutes = n * {"m": 1, "h": 60, "d": 1440}[unit]
        if minutes < 1:
            raise ValueError("间隔至少 1 分钟")
        return {"kind": "interval", "minutes": minutes, "display": text}
    fields = text.split()
    if len(fields) == 5 and all(_CRON_FIELD_RE.match(f) for f in fields):
        return {"kind": "cron", "expr": text, "display": text}
    raise ValueError(f"无法解析的 schedule：{schedule!r}")


_active: Host = Host()


def get_host() -> Host:
    return _active


def set_host(host: Host) -> Host:
    """Swap the active host (tests); returns the previous one."""
    global _active
    previous, _active = _active, host
    return previous


__all__ = ["Host", "fallback_parse_schedule", "get_host", "set_host"]
