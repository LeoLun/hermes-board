"""hermes-board script SDK (standard library only).

The plugin copies this file to ``$HERMES_HOME/scripts/hermes-board/_sdk/`` and
also loads it directly as its own SQLite layer, so the schema and every write
path exist in exactly one place.

Card scripts use it like this::

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "_sdk"))
    from hermes_board_sdk import Card

    card = Card()
    city = card.state.get("city", "北京")
    card.data.set("current", {"temp": 21})
    card.series.append("temp", 21.5)
    card.progress(0.5, "正在处理")
    card.result({"ok": True})
"""
from __future__ import annotations

import atexit
import json
import os
import re
import sqlite3
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

SDK_VERSION = 1
SCHEMA_VERSION = 1
PLUGIN_ID = "hermes-board"

# Mirrors shared/constants.json (tests assert they stay equal).
LIMITS = {
    "datasetBytes": 262144,
    "seriesPointBytes": 4096,
    "stateValueBytes": 65536,
    "stateCardBytes": 1048576,
    "seriesQueryLimit": 5000,
    "seriesDefaultMaxAgeDays": 30,
    "seriesDefaultMaxPoints": 20000,
    "runsPerCard": 100,
    "changesRetentionMs": 86400000,
    "outputTailBytes": 4096,
}

CARD_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,47}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
RUN_KINDS = ("script", "ai")
RUN_TRIGGERS = ("cron", "action", "install", "tool", "manual")
RUN_STATUSES = ("queued", "running", "succeeded", "failed", "timeout", "cancelled")
TERMINAL_STATUSES = ("succeeded", "failed", "timeout", "cancelled")
CHANGE_KINDS = ("data", "series", "state", "run", "card", "layout")
PRUNE_EVERY_WRITES = 200
PRUNE_EVERY_MS = 10 * 60 * 1000
PRUNE_BATCH = 5000
MAX_CHANGES_PER_POLL = 1000

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS datasets (card_id TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL, PRIMARY KEY (card_id, key));
CREATE TABLE IF NOT EXISTS series_points (id INTEGER PRIMARY KEY, card_id TEXT NOT NULL, series TEXT NOT NULL,
  ts INTEGER NOT NULL, value_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_series ON series_points (card_id, series, ts);
CREATE TABLE IF NOT EXISTS card_state (card_id TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL, PRIMARY KEY (card_id, key));
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, card_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('script','ai')), name TEXT NOT NULL,
  trigger TEXT NOT NULL CHECK (trigger IN ('cron','action','install','tool','manual')),
  status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','timeout','cancelled')),
  progress REAL, message TEXT, created_at INTEGER NOT NULL, started_at INTEGER, finished_at INTEGER,
  exit_code INTEGER, result_json TEXT, error TEXT, stdout_tail TEXT, stderr_tail TEXT);
CREATE INDEX IF NOT EXISTS idx_runs_card ON runs (card_id, created_at DESC);
CREATE TABLE IF NOT EXISTS changes (seq INTEGER PRIMARY KEY AUTOINCREMENT, card_id TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('data','series','state','run','card','layout')),
  name TEXT, at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS cron_bindings (card_id TEXT NOT NULL, script TEXT NOT NULL, job_id TEXT NOT NULL,
  schedule TEXT NOT NULL, paused INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (card_id, script));
"""

RUN_COLUMNS = ("status", "progress", "message", "started_at", "finished_at", "exit_code",
               "result_json", "error", "stdout_tail", "stderr_tail")


class BoardError(Exception):
    """Error with a stable machine code (``invalid``, ``not_found`` …)."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def now_ms() -> int:
    return int(time.time() * 1000)


def _retry_locked(fn: Any, budget: float = 5.0) -> Any:
    """Retry ``fn`` while SQLite reports the database as locked/busy, up to ``budget`` seconds."""
    deadline = time.monotonic() + budget
    while True:
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            text = str(exc).lower()
            if ("locked" not in text and "busy" not in text) or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise BoardError("invalid", f"值无法序列化为 JSON：{exc}") from exc


def _check_key(kind: str, key: str) -> str:
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise BoardError("invalid", f"{kind} 名称不合法：{key!r}（需匹配 {KEY_RE.pattern}）")
    return key


def _check_card(card_id: str) -> str:
    if not isinstance(card_id, str) or not CARD_ID_RE.match(card_id):
        raise BoardError("invalid", f"卡片 id 不合法：{card_id!r}")
    return card_id


def _tail(text: Optional[str], limit: int = LIMITS["outputTailBytes"]) -> Optional[str]:
    if text is None:
        return None
    raw = text.encode("utf-8", "replace")
    if len(raw) <= limit:
        return text
    return raw[-limit:].decode("utf-8", "ignore")


def _loads(text: Optional[str]) -> Any:
    return None if text is None else json.loads(text)


class BoardDB:
    """All SQLite access for hermes-board (WAL, busy_timeout 5000ms, UTC ms)."""

    def __init__(self, path: os.PathLike | str) -> None:
        self.path = Path(path)
        self._migrated = False

    # ── connection & schema ────────────────────────────────────────────────
    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000")
            # WAL persists in the file; switching (and first-time schema creation) can return
            # SQLITE_BUSY without consulting the busy handler when two processes race on a new file.
            if str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
                _retry_locked(lambda: conn.execute("PRAGMA journal_mode = WAL"))
            if not self._migrated:
                _retry_locked(lambda: self._migrate(conn))
            yield conn
        finally:
            conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def _migrate(self, conn: sqlite3.Connection) -> None:
        conn.executescript(SCHEMA_SQL)
        row = conn.execute("SELECT value FROM meta WHERE key='schemaVersion'").fetchone()
        if row is None:
            conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schemaVersion', ?)", (str(SCHEMA_VERSION),))
        elif int(row["value"]) > SCHEMA_VERSION:
            raise BoardError("invalid", f"数据库结构版本 {row['value']} 高于当前支持的 {SCHEMA_VERSION}，请更新插件")
        self._migrated = True

    def migrate(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='schemaVersion'").fetchone()
            return int(row["value"])

    # ── meta ──────────────────────────────────────────────────────────────
    def get_meta(self, key: str) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return None if row is None else row["value"]

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, value))

    # ── changes ───────────────────────────────────────────────────────────
    def _change(self, conn: sqlite3.Connection, card_id: Optional[str], kind: str, name: Optional[str]) -> int:
        if kind not in CHANGE_KINDS:
            raise BoardError("invalid", f"未知的变更类型：{kind}")
        cur = conn.execute("INSERT INTO changes (card_id, kind, name, at) VALUES (?, ?, ?, ?)",
                           (card_id, kind, name, now_ms()))
        seq = int(cur.lastrowid)
        if seq % 200 == 0:
            conn.execute("DELETE FROM changes WHERE at < ?", (now_ms() - LIMITS["changesRetentionMs"],))
        return seq

    def add_change(self, card_id: Optional[str], kind: str, name: Optional[str] = None) -> int:
        with self.tx() as conn:
            return self._change(conn, card_id, kind, name)

    def prune_changes(self, older_than_ms: Optional[int] = None) -> int:
        cutoff = now_ms() - LIMITS["changesRetentionMs"] if older_than_ms is None else older_than_ms
        with self.tx() as conn:
            return conn.execute("DELETE FROM changes WHERE at < ?", (cutoff,)).rowcount

    def current_seq(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='changes'").fetchone()
            return 0 if row is None else int(row["seq"])

    def changes_since(self, since: int) -> dict[str, Any]:
        since = max(0, int(since))
        with self.connect() as conn:
            row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='changes'").fetchone()
            current = 0 if row is None else int(row["seq"])
            min_row = conn.execute("SELECT MIN(seq) AS m FROM changes").fetchone()
            min_seq = min_row["m"] if min_row and min_row["m"] is not None else current + 1
            if since > current or (since < min_seq - 1 and since != current):
                return {"seq": current, "changes": [], "reset": True}
            rows = conn.execute(
                "SELECT seq, card_id, kind, name FROM changes WHERE seq > ? ORDER BY seq LIMIT ?",
                (since, MAX_CHANGES_PER_POLL + 1)).fetchall()
        if len(rows) > MAX_CHANGES_PER_POLL:
            return {"seq": current, "changes": [], "reset": True}
        seen: set[tuple] = set()
        out = []
        for r in rows:
            key = (r["card_id"], r["kind"], r["name"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"card": r["card_id"], "kind": r["kind"], "name": r["name"]})
        return {"seq": current, "changes": out}

    # ── datasets ──────────────────────────────────────────────────────────
    def put_dataset(self, card_id: str, key: str, value: Any) -> int:
        _check_card(card_id)
        _check_key("数据集", key)
        text = dumps(value)
        if len(text.encode("utf-8")) > LIMITS["datasetBytes"]:
            raise BoardError("invalid", f"数据集 {key} 超过 256 KiB 上限")
        at = now_ms()
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO datasets (card_id, key, value_json, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(card_id, key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (card_id, key, text, at))
            self._change(conn, card_id, "data", key)
        return at

    def get_dataset(self, card_id: str, key: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT value_json, updated_at FROM datasets WHERE card_id=? AND key=?",
                               (card_id, key)).fetchone()
        if row is None:
            return None
        return {"value": _loads(row["value_json"]), "updatedAt": row["updated_at"]}

    def list_datasets(self, card_id: str) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value_json, updated_at FROM datasets WHERE card_id=? ORDER BY key",
                                (card_id,)).fetchall()
        return {r["key"]: {"value": _loads(r["value_json"]), "updatedAt": r["updated_at"]} for r in rows}

    # ── series ────────────────────────────────────────────────────────────
    def append_series(self, card_id: str, name: str, value: Any, ts: Optional[int] = None,
                      retention: Optional[dict[str, int]] = None) -> int:
        _check_card(card_id)
        _check_key("序列", name)
        text = dumps(value)
        if len(text.encode("utf-8")) > LIMITS["seriesPointBytes"]:
            raise BoardError("invalid", f"序列 {name} 单点超过 4 KiB 上限")
        ts = now_ms() if ts is None else int(ts)
        with self.tx() as conn:
            conn.execute("INSERT INTO series_points (card_id, series, ts, value_json) VALUES (?, ?, ?, ?)",
                         (card_id, name, ts, text))
            self._change(conn, card_id, "series", name)
            meta_key = f"prune:{card_id}:{name}"
            row = conn.execute("SELECT value FROM meta WHERE key=?", (meta_key,)).fetchone()
            count, last = (0, 0)
            if row is not None:
                count, last = (int(x) for x in row["value"].split(","))
            count += 1
            now = now_ms()
            due = count >= PRUNE_EVERY_WRITES or (now - last) >= PRUNE_EVERY_MS
            if due:
                self._prune_series(conn, card_id, name, retention)
                count, last = 0, now
            conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (meta_key, f"{count},{last}"))
        return ts

    def _prune_series(self, conn: sqlite3.Connection, card_id: str, name: str,
                      retention: Optional[dict[str, int]]) -> int:
        retention = retention or {}
        max_age = int(retention.get("maxAgeDays", LIMITS["seriesDefaultMaxAgeDays"]))
        max_points = int(retention.get("maxPoints", LIMITS["seriesDefaultMaxPoints"]))
        cutoff = now_ms() - max_age * 86400000
        removed = conn.execute(
            "DELETE FROM series_points WHERE id IN (SELECT id FROM series_points WHERE card_id=? AND series=? "
            "AND ts < ? LIMIT ?)", (card_id, name, cutoff, PRUNE_BATCH)).rowcount
        total = conn.execute("SELECT COUNT(*) AS n FROM series_points WHERE card_id=? AND series=?",
                             (card_id, name)).fetchone()["n"]
        excess = total - max_points
        if excess > 0:
            removed += conn.execute(
                "DELETE FROM series_points WHERE id IN (SELECT id FROM series_points WHERE card_id=? AND series=? "
                "ORDER BY ts ASC, id ASC LIMIT ?)", (card_id, name, min(excess, PRUNE_BATCH))).rowcount
        return removed

    def prune_series(self, card_id: str, name: str, retention: Optional[dict[str, int]] = None) -> int:
        with self.tx() as conn:
            return self._prune_series(conn, card_id, name, retention)

    def query_series(self, card_id: str, name: str, since: Optional[int] = None, until: Optional[int] = None,
                     limit: int = 1000, order: str = "asc") -> list[dict[str, Any]]:
        _check_key("序列", name)
        if order not in ("asc", "desc"):
            raise BoardError("invalid", "order 只能是 asc 或 desc")
        limit = int(limit)
        if limit < 1 or limit > LIMITS["seriesQueryLimit"]:
            raise BoardError("invalid", f"limit 必须在 1 到 {LIMITS['seriesQueryLimit']} 之间")
        sql = "SELECT ts, value_json FROM series_points WHERE card_id=? AND series=?"
        params: list[Any] = [card_id, name]
        if since is not None:
            sql += " AND ts >= ?"
            params.append(int(since))
        if until is not None:
            sql += " AND ts <= ?"
            params.append(int(until))
        sql += f" ORDER BY ts {order.upper()}, id {order.upper()} LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{"ts": r["ts"], "value": _loads(r["value_json"])} for r in rows]

    # ── card state ────────────────────────────────────────────────────────
    def get_state(self, card_id: str, key: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT value_json, updated_at FROM card_state WHERE card_id=? AND key=?",
                               (card_id, key)).fetchone()
        if row is None:
            return None
        return {"value": _loads(row["value_json"]), "updatedAt": row["updated_at"]}

    def list_state(self, card_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value_json FROM card_state WHERE card_id=? ORDER BY key",
                                (card_id,)).fetchall()
        return {r["key"]: _loads(r["value_json"]) for r in rows}

    def set_state(self, card_id: str, key: str, value: Any) -> int:
        _check_card(card_id)
        _check_key("状态", key)
        text = dumps(value)
        size = len(text.encode("utf-8"))
        if size > LIMITS["stateValueBytes"]:
            raise BoardError("invalid", f"状态 {key} 超过 64 KiB 上限")
        at = now_ms()
        with self.tx() as conn:
            row = conn.execute("SELECT COALESCE(SUM(LENGTH(CAST(value_json AS BLOB))), 0) AS n FROM card_state "
                               "WHERE card_id=? AND key<>?", (card_id, key)).fetchone()
            if int(row["n"]) + size > LIMITS["stateCardBytes"]:
                raise BoardError("invalid", "该卡片的状态合计超过 1 MiB 上限")
            conn.execute(
                "INSERT INTO card_state (card_id, key, value_json, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(card_id, key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (card_id, key, text, at))
            self._change(conn, card_id, "state", key)
        return at

    def delete_state(self, card_id: str, key: str) -> bool:
        _check_key("状态", key)
        with self.tx() as conn:
            n = conn.execute("DELETE FROM card_state WHERE card_id=? AND key=?", (card_id, key)).rowcount
            if n:
                self._change(conn, card_id, "state", key)
        return bool(n)

    # ── runs ──────────────────────────────────────────────────────────────
    def create_run(self, card_id: str, kind: str, name: str, trigger: str, status: str = "queued",
                   run_id: Optional[str] = None, started: bool = False) -> str:
        if kind not in RUN_KINDS or trigger not in RUN_TRIGGERS or status not in RUN_STATUSES:
            raise BoardError("invalid", "运行记录字段不合法")
        run_id = run_id or uuid.uuid4().hex
        at = now_ms()
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, card_id, kind, name, trigger, status, created_at, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, card_id, kind, name, trigger, status, at, at if started else None))
            self._change(conn, card_id, "run", name)
        return run_id

    def update_run(self, run_id: str, **fields: Any) -> None:
        unknown = set(fields) - set(RUN_COLUMNS)
        if unknown:
            raise BoardError("invalid", f"未知的运行字段：{sorted(unknown)}")
        if "status" in fields and fields["status"] not in RUN_STATUSES:
            raise BoardError("invalid", f"未知的运行状态：{fields['status']}")
        for col in ("stdout_tail", "stderr_tail", "error"):
            if col in fields:
                fields[col] = _tail(fields[col])
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.tx() as conn:
            row = conn.execute("SELECT card_id, name FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise BoardError("not_found", f"运行记录不存在：{run_id}")
            conn.execute(f"UPDATE runs SET {cols} WHERE run_id=?", (*fields.values(), run_id))
            self._change(conn, row["card_id"], "run", row["name"])
            if fields.get("status") in TERMINAL_STATUSES:
                conn.execute(
                    "DELETE FROM runs WHERE card_id=? AND run_id NOT IN (SELECT run_id FROM runs WHERE card_id=? "
                    "ORDER BY created_at DESC, rowid DESC LIMIT ?) AND status IN ('succeeded','failed','timeout','cancelled')",
                    (row["card_id"], row["card_id"], LIMITS["runsPerCard"]))

    @staticmethod
    def _run_row(r: sqlite3.Row) -> dict[str, Any]:
        return {
            "runId": r["run_id"], "card": r["card_id"], "kind": r["kind"], "name": r["name"],
            "trigger": r["trigger"], "status": r["status"], "progress": r["progress"], "message": r["message"],
            "createdAt": r["created_at"], "startedAt": r["started_at"], "finishedAt": r["finished_at"],
            "exitCode": r["exit_code"], "result": _loads(r["result_json"]), "error": r["error"],
            "stdoutTail": r["stdout_tail"], "stderrTail": r["stderr_tail"],
        }

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return None if row is None else self._run_row(row)

    def list_runs(self, card_id: str, limit: int = 20, name: Optional[str] = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), LIMITS["runsPerCard"]))
        sql = "SELECT * FROM runs WHERE card_id=?"
        params: list[Any] = [card_id]
        if name is not None:
            sql += " AND name=?"
            params.append(name)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._run_row(r) for r in rows]

    def active_run(self, card_id: str, kind: str, name: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE card_id=? AND kind=? AND name=? AND status IN ('queued','running') "
                "ORDER BY created_at DESC LIMIT 1", (card_id, kind, name)).fetchone()
        return None if row is None else self._run_row(row)

    def last_started(self, card_id: str, kind: str, name: str, trigger: Optional[str] = None) -> Optional[int]:
        sql = "SELECT MAX(created_at) AS t FROM runs WHERE card_id=? AND kind=? AND name=?"
        params: list[Any] = [card_id, kind, name]
        if trigger is not None:
            sql += " AND trigger=?"
            params.append(trigger)
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return None if row is None or row["t"] is None else int(row["t"])

    def fail_stale_runs(self, older_than_ms: int) -> int:
        """Mark queued/running rows older than the cutoff as failed (process died)."""
        with self.tx() as conn:
            return conn.execute(
                "UPDATE runs SET status='failed', error='运行进程已退出（服务重启）', finished_at=? "
                "WHERE status IN ('queued','running') AND created_at < ?", (now_ms(), older_than_ms)).rowcount

    # ── cron bindings ─────────────────────────────────────────────────────
    def list_bindings(self, card_id: Optional[str] = None) -> list[dict[str, Any]]:
        sql = "SELECT card_id, script, job_id, schedule, paused FROM cron_bindings"
        params: tuple = ()
        if card_id is not None:
            sql += " WHERE card_id=?"
            params = (card_id,)
        with self.connect() as conn:
            rows = conn.execute(sql + " ORDER BY card_id, script", params).fetchall()
        return [{"card": r["card_id"], "script": r["script"], "jobId": r["job_id"], "schedule": r["schedule"],
                 "paused": bool(r["paused"])} for r in rows]

    def put_binding(self, card_id: str, script: str, job_id: str, schedule: str, paused: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO cron_bindings (card_id, script, job_id, schedule, paused) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(card_id, script) DO UPDATE SET job_id=excluded.job_id, schedule=excluded.schedule, "
                "paused=excluded.paused", (card_id, script, job_id, schedule, 1 if paused else 0))

    def delete_binding(self, card_id: str, script: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM cron_bindings WHERE card_id=? AND script=?", (card_id, script))

    # ── card removal ──────────────────────────────────────────────────────
    def delete_card_data(self, card_id: str) -> None:
        with self.tx() as conn:
            for table in ("datasets", "series_points", "card_state", "runs", "cron_bindings"):
                conn.execute(f"DELETE FROM {table} WHERE card_id=?", (card_id,))
            conn.execute("DELETE FROM meta WHERE key LIKE ?", (f"prune:{card_id}:%",))
            self._change(conn, card_id, "card", None)


# ── script-facing API ──────────────────────────────────────────────────────

class _Datasets:
    def __init__(self, card: "Card") -> None:
        self._card = card

    def set(self, key: str, value: Any) -> None:
        self._card.db.put_dataset(self._card.id, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        row = self._card.db.get_dataset(self._card.id, key)
        return default if row is None else row["value"]

    def list(self) -> dict[str, Any]:
        return {k: v["value"] for k, v in self._card.db.list_datasets(self._card.id).items()}


class _Series:
    def __init__(self, card: "Card") -> None:
        self._card = card

    def append(self, name: str, value: Any, ts: Optional[int] = None) -> None:
        decl = (self._card.manifest.get("series") or {}).get(name) or {}
        self._card.db.append_series(self._card.id, name, value, ts=ts, retention=decl.get("retention"))

    def query(self, name: str, since: Optional[int] = None, until: Optional[int] = None, limit: int = 1000,
              order: str = "asc") -> list[dict[str, Any]]:
        return self._card.db.query_series(self._card.id, name, since, until, limit, order)


class _State:
    def __init__(self, card: "Card") -> None:
        self._card = card

    def get(self, key: str, default: Any = None) -> Any:
        row = self._card.db.get_state(self._card.id, key)
        if row is not None:
            return row["value"]
        decl = (self._card.manifest.get("state") or {}).get(key) or {}
        return decl.get("default", default) if default is None else default

    def set(self, key: str, value: Any) -> None:
        self._card.db.set_state(self._card.id, key, value)

    def delete(self, key: str) -> None:
        self._card.db.delete_state(self._card.id, key)


def _main_script_path() -> Optional[Path]:
    main = sys.modules.get("__main__")
    path = getattr(main, "__file__", None) or (sys.argv[0] if sys.argv and sys.argv[0] else None)
    return Path(path).resolve() if path else None


class Card:
    """Context for one card script run (cron, action, install, tool or manual)."""

    def __init__(self, card_id: Optional[str] = None, hermes_home: Optional[os.PathLike | str] = None,
                 script_path: Optional[os.PathLike | str] = None) -> None:
        script = Path(script_path).resolve() if script_path else _main_script_path()
        if hermes_home is None:
            if script is None or len(script.parents) < 4 or script.parents[1].name != PLUGIN_ID:
                raise BoardError("invalid", "无法从脚本路径推断 HERMES_HOME：脚本应位于 "
                                            "$HERMES_HOME/scripts/hermes-board/<卡片>/ 下")
            hermes_home = script.parents[3]
        if card_id is None:
            if script is None:
                raise BoardError("invalid", "无法推断卡片 id")
            card_id = script.parent.name
        self.id = _check_card(card_id)
        self.home = Path(hermes_home)
        self.data_dir = self.home / "plugin-data" / PLUGIN_ID
        manifest_path = self.data_dir / "cards" / self.id / "card.json"
        if not manifest_path.is_file():
            raise BoardError("not_found", f"卡片 {self.id} 未安装（缺少 {manifest_path}）")
        self.manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.db = BoardDB(self.data_dir / "board.sqlite3")
        self.script_file = script.name if script else None
        self.script_name = self._script_name()
        self.run_id = os.environ.get("HERMES_BOARD_RUN_ID") or None
        self.trigger = os.environ.get("HERMES_BOARD_TRIGGER") or ("cron" if self.run_id is None else "action")
        self.args: dict[str, Any] = self._load_args()
        self.data = _Datasets(self)
        self.series = _Series(self)
        self.state = _State(self)
        self._failed = False
        self._finalized = False
        self._own_run = False
        if self.run_id is None:
            self._own_run = True
            self.run_id = self.db.create_run(self.id, "script", self.script_name or "script", "cron",
                                             status="running", started=True)
            atexit.register(self._finalize)
            previous_hook = sys.excepthook

            def _hook(exc_type, exc, tb):  # pragma: no cover - exercised via subprocess tests
                self._record_failure("".join(traceback.format_exception(exc_type, exc, tb)))
                previous_hook(exc_type, exc, tb)

            sys.excepthook = _hook

    def _script_name(self) -> Optional[str]:
        for name, decl in (self.manifest.get("scripts") or {}).items():
            if decl.get("file") == self.script_file:
                return name
        return None

    def _load_args(self) -> dict[str, Any]:
        path = os.environ.get("HERMES_BOARD_ARGS_FILE")
        if not path:
            return {}
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def progress(self, fraction: Optional[float], message: Optional[str] = None) -> None:
        fields: dict[str, Any] = {}
        if fraction is not None:
            fields["progress"] = max(0.0, min(1.0, float(fraction)))
        if message is not None:
            fields["message"] = str(message)[:500]
        if fields:
            self.db.update_run(self.run_id, **fields)

    def result(self, value: Any) -> None:
        self.db.update_run(self.run_id, result_json=dumps(value))

    def fail(self, message: str, exit_code: int = 1) -> None:
        self._record_failure(message)
        raise SystemExit(exit_code)

    def _record_failure(self, message: str) -> None:
        self._failed = True
        if self._own_run and not self._finalized:
            self._finalized = True
            self.db.update_run(self.run_id, status="failed", error=message, finished_at=now_ms(), exit_code=1)
        elif not self._own_run:
            self.db.update_run(self.run_id, error=message)

    def _finalize(self) -> None:
        if self._finalized or not self._own_run:
            return
        self._finalized = True
        self.db.update_run(self.run_id, status="failed" if self._failed else "succeeded", finished_at=now_ms(),
                           exit_code=1 if self._failed else 0)


__all__ = ["BoardDB", "BoardError", "Card", "SCHEMA_SQL", "SCHEMA_VERSION", "SDK_VERSION", "LIMITS", "now_ms"]
