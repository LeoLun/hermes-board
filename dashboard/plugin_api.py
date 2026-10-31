"""REST API for the Hermes Desktop board page, mounted at ``/api/plugins/hermes-board``."""
from __future__ import annotations

import functools
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import JSONResponse

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from hermes_board_core.board import get_board  # noqa: E402
from hermes_board_core.errors import error_payload, http_status  # noqa: E402
from hermes_board_core.paths import check_card_id, check_key  # noqa: E402

logger = logging.getLogger("hermes_board")
NO_STORE = {"Cache-Control": "no-store"}
router = APIRouter()


def api(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Uniform ``{detail: {code, message}}`` errors and ``no-store`` on every response."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = fn(*args, **kwargs)
        except HTTPException:
            raise
        except sqlite3.Error as exc:
            logger.warning("hermes-board: sqlite error: %s", exc)
            raise HTTPException(status_code=429, detail={"code": "busy", "message": "数据库忙，请稍后重试"},
                                headers=NO_STORE) from exc
        except Exception as exc:
            if getattr(exc, "code", None) is None:
                logger.exception("hermes-board: unexpected API error")
                raise HTTPException(status_code=500, detail={"code": "internal", "message": str(exc)},
                                    headers=NO_STORE) from exc
            raise HTTPException(status_code=http_status(exc), detail=error_payload(exc), headers=NO_STORE) from exc
        return JSONResponse(content=result, headers=NO_STORE)

    return wrapper


def _body(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        from hermes_board_core.errors import BoardError

        raise BoardError("invalid", "请求体必须是 JSON 对象")
    return payload


def _card(board: Any, card_id: str) -> dict[str, Any]:
    return board.cards.manifest(check_card_id(card_id))


# ── health & board ────────────────────────────────────────────────────────

@router.get("/health")
@api
def health() -> dict[str, Any]:
    board = get_board(initialize=False)
    try:
        board.ensure_initialized()
    except Exception as exc:  # health must still answer
        logger.warning("hermes-board: init failed: %s", exc)
        return {**board.health(), "ok": False, "error": str(exc)}
    return board.health()


@router.get("/board")
@api
def read_board() -> dict[str, Any]:
    return get_board().view()


@router.put("/board")
@api
def write_board(payload: Any = Body(...)) -> dict[str, Any]:
    body = _body(payload)
    return {"layout": get_board().save_layout(body.get("items"), body.get("baseRevision"), "desktop")}


@router.post("/board/items")
@api
def add_board_item(payload: Any = Body(...)) -> dict[str, Any]:
    body = _body(payload)
    layout = get_board().add_item(body.get("card"), body.get("size"), body.get("x"), body.get("y"),
                                  base_revision=body.get("baseRevision"), updated_by="desktop")
    return {"layout": layout}


@router.delete("/board/items/{card_id}")
@api
def remove_board_item(card_id: str, baseRevision: Optional[int] = Query(default=None)) -> dict[str, Any]:
    return {"layout": get_board().remove_item(check_card_id(card_id), base_revision=baseRevision,
                                              updated_by="desktop")}


# ── card content & data ───────────────────────────────────────────────────

@router.get("/cards/{card_id}/document")
@api
def card_document(card_id: str, known: Optional[str] = Query(default=None)) -> dict[str, Any]:
    doc = get_board().cards.document(check_card_id(card_id))
    if known and known == doc["sha256"]:
        return {"unchanged": True, "sha256": doc["sha256"], "revision": doc["revision"]}
    return doc


@router.get("/cards/{card_id}/data")
@api
def card_datasets(card_id: str) -> dict[str, Any]:
    board = get_board()
    _card(board, card_id)
    return {"items": board.db.list_datasets(card_id)}


@router.get("/cards/{card_id}/data/{key}")
@api
def card_dataset(card_id: str, key: str) -> dict[str, Any]:
    board = get_board()
    _card(board, card_id)
    row = board.db.get_dataset(card_id, check_key("数据集", key))
    return row or {"value": None, "updatedAt": None}


@router.get("/cards/{card_id}/series/{name}")
@api
def card_series(card_id: str, name: str, since: Optional[int] = Query(default=None),
                until: Optional[int] = Query(default=None), limit: int = Query(default=1000),
                order: str = Query(default="asc")) -> dict[str, Any]:
    board = get_board()
    _card(board, card_id)
    return {"points": board.db.query_series(card_id, check_key("序列", name), since, until, limit, order)}


@router.get("/cards/{card_id}/state/{key}")
@api
def card_state_get(card_id: str, key: str) -> dict[str, Any]:
    board = get_board()
    manifest = _card(board, card_id)
    row = board.db.get_state(card_id, check_key("状态", key))
    if row is not None:
        return row
    decl = (manifest.get("state") or {}).get(key) or {}
    return {"value": decl.get("default"), "updatedAt": None}


@router.put("/cards/{card_id}/state/{key}")
@api
def card_state_put(card_id: str, key: str, payload: Any = Body(...)) -> dict[str, Any]:
    body = _body(payload)
    if "value" not in body:
        from hermes_board_core.errors import BoardError

        raise BoardError("invalid", "请求体需要 {value}")
    board = get_board()
    _card(board, card_id)
    return {"updatedAt": board.db.set_state(card_id, check_key("状态", key), body["value"])}


@router.delete("/cards/{card_id}/state/{key}")
@api
def card_state_delete(card_id: str, key: str) -> dict[str, Any]:
    board = get_board()
    _card(board, card_id)
    return {"deleted": board.db.delete_state(card_id, check_key("状态", key))}


# ── runs & ai ─────────────────────────────────────────────────────────────

@router.post("/cards/{card_id}/runs")
@api
def start_run(card_id: str, payload: Any = Body(...)) -> dict[str, Any]:
    body = _body(payload)
    # Cards always run as "action" (callable scripts only, min interval applies); the Desktop host's
    # "立即运行" menu uses "manual", which may run any declared script.
    trigger = body.get("trigger", "action")
    if trigger not in ("action", "manual"):
        from hermes_board_core.errors import BoardError

        raise BoardError("invalid", "trigger 只能是 action 或 manual")
    return get_board().runner.start(check_card_id(card_id), body.get("script"), body.get("args"), trigger=trigger)


@router.get("/cards/{card_id}/runs")
@api
def list_runs(card_id: str, limit: int = Query(default=20)) -> dict[str, Any]:
    board = get_board()
    _card(board, card_id)
    return {"runs": board.db.list_runs(card_id, limit=limit)}


@router.get("/runs/{run_id}")
@api
def read_run(run_id: str) -> dict[str, Any]:
    run = get_board().db.get_run(run_id)
    if run is None:
        from hermes_board_core.errors import BoardError

        raise BoardError("not_found", f"运行记录不存在：{run_id}")
    return run


@router.post("/cards/{card_id}/ai/{name}")
@api
def invoke_ai(card_id: str, name: str, payload: Any = Body(...)) -> dict[str, Any]:
    body = _body(payload)
    return get_board().ai.run(check_card_id(card_id), name, body.get("input"))


@router.get("/changes")
@api
def changes(since: Optional[int] = Query(default=None)) -> dict[str, Any]:
    return get_board().changes(since)
