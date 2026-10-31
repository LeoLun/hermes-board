"""Sync card scripts that declare ``schedule`` to Hermes native cron (design §8.3)."""
from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, Optional

from .host import Host
from .paths import Paths

logger = logging.getLogger("hermes_board")
JOB_PREFIX = "hermes-board:"
PAUSE_REASON = "hermes-board: 卡片不在看板上"


def job_name(card_id: str, script: str) -> str:
    return f"{JOB_PREFIX}{card_id}:{script}"


class CronSync:
    def __init__(self, paths: Paths, db: Any, host: Host) -> None:
        self.paths = paths
        self.db = db
        self.host = host

    def _jobs(self):
        return self.host.cron()

    def available(self) -> bool:
        return self._jobs() is not None

    @staticmethod
    def scheduled_scripts(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {name: decl for name, decl in (manifest.get("scripts") or {}).items()
                if isinstance(decl, dict) and decl.get("schedule")}

    # ── per-card sync ─────────────────────────────────────────────────────
    def sync_card(self, card_id: str, manifest: Mapping[str, Any], on_board: bool) -> None:
        """Create/update/pause/resume/remove this card's jobs so they match ``manifest``.

        Bindings are written right after each job change, so a failure part-way leaves a
        state that a later ``sync_card`` (rollback) or ``remove_card`` can fully undo.
        """
        jobs = self._jobs()
        if jobs is None:
            return
        wanted = self.scheduled_scripts(manifest)
        bindings = {b["script"]: b for b in self.db.list_bindings(card_id)}
        for script, binding in bindings.items():
            if script not in wanted:
                jobs.remove_job(binding["jobId"])
                self.db.delete_binding(card_id, script)
        for script, decl in wanted.items():
            ref = self.paths.cron_script_ref(card_id, decl["file"])
            schedule = decl["schedule"]
            binding = bindings.get(script)
            job = jobs.get_job(binding["jobId"]) if binding else None
            if job is None:
                job = jobs.create_job(prompt=None, schedule=schedule, name=job_name(card_id, script), script=ref,
                                      no_agent=True, deliver="local")
                self.db.put_binding(card_id, script, job["id"], schedule, False)
                if not on_board:
                    jobs.pause_job(job["id"], reason=PAUSE_REASON)
                    self.db.put_binding(card_id, script, job["id"], schedule, True)
                continue
            updates: dict[str, Any] = {}
            if binding["schedule"] != schedule:
                updates["schedule"] = jobs.parse_schedule(schedule)
            if job.get("script") != ref:
                updates["script"] = ref
            if updates:
                jobs.update_job(job["id"], updates)
            paused = not bool(job.get("enabled", True))
            if on_board and paused:
                jobs.resume_job(job["id"])
                paused = False
            elif not on_board and not paused:
                jobs.pause_job(job["id"], reason=PAUSE_REASON)
                paused = True
            self.db.put_binding(card_id, script, job["id"], schedule, paused)

    def set_paused(self, card_id: str, paused: bool) -> None:
        jobs = self._jobs()
        if jobs is None:
            return
        for binding in self.db.list_bindings(card_id):
            job = jobs.get_job(binding["jobId"])
            if job is None:
                continue
            if paused and job.get("enabled", True):
                jobs.pause_job(binding["jobId"], reason=PAUSE_REASON)
            elif not paused and not job.get("enabled", True):
                jobs.resume_job(binding["jobId"])
            self.db.put_binding(card_id, binding["script"], binding["jobId"], binding["schedule"], paused)

    def remove_card(self, card_id: str) -> None:
        jobs = self._jobs()
        for binding in self.db.list_bindings(card_id):
            if jobs is not None:
                try:
                    jobs.remove_job(binding["jobId"])
                except Exception as exc:  # job may already be gone
                    logger.warning("hermes-board: remove cron job %s failed: %s", binding["jobId"], exc)
            self.db.delete_binding(card_id, binding["script"])

    # ── full reconcile (first init / plugin version change) ──────────────
    def reconcile(self, manifests: Mapping[str, Mapping[str, Any]], on_board: Iterable[str]) -> dict[str, int]:
        jobs = self._jobs()
        stats = {"synced": 0, "orphansRemoved": 0}
        if jobs is None:
            return stats
        board = set(on_board)
        for card_id, manifest in manifests.items():
            try:
                self.sync_card(card_id, manifest, card_id in board)
                stats["synced"] += 1
            except Exception as exc:
                logger.warning("hermes-board: cron sync for %s failed: %s", card_id, exc)
        for binding in self.db.list_bindings():
            if binding["card"] not in manifests:
                self.remove_card(binding["card"])
        bound = {b["jobId"] for b in self.db.list_bindings()}
        for job in jobs.list_jobs(include_disabled=True):
            name = job.get("name") or ""
            if name.startswith(JOB_PREFIX) and job.get("id") not in bound:
                jobs.remove_job(job["id"])
                stats["orphansRemoved"] += 1
        return stats

    # ── status for /board and the tool ────────────────────────────────────
    def status(self, card_id: str) -> dict[str, Optional[dict[str, Any]]]:
        jobs = self._jobs()
        out: dict[str, Optional[dict[str, Any]]] = {}
        for binding in self.db.list_bindings(card_id):
            if jobs is None:
                out[binding["script"]] = {"jobId": binding["jobId"], "paused": binding["paused"], "state": "unavailable"}
                continue
            job = jobs.get_job(binding["jobId"])
            if job is None:
                out[binding["script"]] = None
            else:
                out[binding["script"]] = {"jobId": job["id"], "paused": not bool(job.get("enabled", True)),
                                          "state": job.get("state"), "nextRunAt": job.get("next_run_at"),
                                          "lastRunAt": job.get("last_run_at"), "lastStatus": job.get("last_status")}
        return out


__all__ = ["CronSync", "JOB_PREFIX", "job_name"]
