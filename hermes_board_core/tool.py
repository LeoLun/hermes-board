"""``board_manage`` Agent tool (design §13). Never raises: errors come back as JSON."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from .board import get_board
from .constants import LIMITS
from .errors import error_payload
from .paths import check_card_id, check_key

logger = logging.getLogger("hermes_board")
ACTIONS = ("list", "get", "validate", "save", "remove", "run", "data", "place", "restore_default")
TERMINAL = ("succeeded", "failed", "timeout", "cancelled")

SCHEMA: dict[str, Any] = {
    "name": "board_manage",
    "description": (
        "管理 Hermes 看板（hermes-board）上的卡片：list 列出卡片和布局；get 读取卡片包；validate 只校验；"
        "save 安装或更新卡片包并放上看板；remove 从看板移除（deletePackage 时删除卡片包）；run 运行卡片脚本并返回输出；"
        "data 读取数据集、序列、状态或运行记录；place 调整位置和尺寸；restore_default 恢复内置默认卡片。"
        "创建或修改卡片前，先加载技能 hermes-board:card-author。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "card": {"type": "string", "description": "卡片 id，如 weather"},
            "package": {
                "type": "object",
                "description": "卡片包：{manifest: card.json 对象, html: index.html 全文, scripts: {文件名: 源码}}",
                "properties": {
                    "manifest": {"type": "object"},
                    "html": {"type": "string"},
                    "scripts": {"type": "object"},
                },
            },
            "place": {
                "type": "object",
                "description": "save 时的放置位置 {x, y, size}；省略则新卡片自动放到首个空位",
                "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "size": {"type": "string"}},
            },
            "replace": {"type": "boolean", "description": "save 更新已有卡片时必须为 true"},
            "deletePackage": {"type": "boolean", "description": "remove 时同时删除卡片包、cron 和数据"},
            "confirm": {"type": "boolean", "description": "remove 必须为 true"},
            "script": {"type": "string", "description": "run 的脚本名（card.json scripts 中的键）"},
            "args": {"type": "object", "description": "run 的参数"},
            "wait": {"type": "boolean", "description": "run 是否等待结束，默认 true"},
            "kind": {"type": "string", "enum": ["data", "series", "state", "runs"], "description": "data 的读取类型"},
            "name": {"type": "string", "description": "数据集、序列或状态的名称"},
            "limit": {"type": "integer", "description": "序列点数或运行记录条数"},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "size": {"type": "string", "description": "预设尺寸，如 6x4"},
        },
        "required": ["action"],
    },
}


def _ok(**payload: Any) -> str:
    return json.dumps({"ok": True, **payload}, ensure_ascii=False, default=str)


def _err(code: str, message: str, **extra: Any) -> str:
    return json.dumps({"ok": False, "error": {"code": code, "message": message, **extra}}, ensure_ascii=False,
                      default=str)


def _require(args: dict[str, Any], key: str) -> Any:
    if args.get(key) in (None, ""):
        from .errors import BoardError

        raise BoardError("invalid", f"{args.get('action')} 需要参数 {key}")
    return args[key]


def _list(board: Any) -> dict[str, Any]:
    view = board.view()
    cards = []
    for c in view["cards"]:
        cards.append({k: c.get(k) for k in ("id", "title", "version", "revision", "status", "onBoard", "sizes",
                                            "defaultSize", "source", "scripts", "ai", "errors") if k in c})
    layout = view["layout"]
    return {"cards": cards, "layout": {"revision": layout["revision"], "items": layout["items"]}}


def _wait_run(board: Any, run_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    run = board.db.get_run(run_id)
    while run is not None and run["status"] not in TERMINAL and time.monotonic() < deadline:
        time.sleep(0.1)
        run = board.db.get_run(run_id)
    return run or {}


def _run(board: Any, args: dict[str, Any]) -> dict[str, Any]:
    card_id = check_card_id(_require(args, "card"))
    script = _require(args, "script")
    started = board.runner.start(card_id, script, args.get("args") or {}, trigger="tool")
    if args.get("wait", True) is False:
        return started
    decl = (board.cards.manifest(card_id).get("scripts") or {}).get(script) or {}
    timeout = min(int(decl.get("timeoutSec", LIMITS["actionTimeoutDefault"])), LIMITS["actionTimeoutMax"]) + 15
    run = _wait_run(board, started["runId"], timeout)
    keys = ("runId", "status", "exitCode", "result", "error", "progress", "message", "stdoutTail", "stderrTail",
            "startedAt", "finishedAt")
    out = {k: run.get(k) for k in keys}
    if started.get("deduplicated"):
        out["deduplicated"] = True
    return out


def _data(board: Any, args: dict[str, Any]) -> dict[str, Any]:
    card_id = check_card_id(_require(args, "card"))
    manifest = board.cards.manifest(card_id)
    kind = args.get("kind") or "data"
    name = args.get("name")
    limit = int(args.get("limit") or 50)
    if kind == "data":
        if name:
            return board.db.get_dataset(card_id, check_key("数据集", name)) or {"value": None, "updatedAt": None}
        return {"items": board.db.list_datasets(card_id)}
    if kind == "series":
        points = board.db.query_series(card_id, check_key("序列", _require(args, "name")),
                                       limit=max(1, min(limit, LIMITS["seriesQueryLimit"])), order="desc")
        return {"points": list(reversed(points))}
    if kind == "state":
        if name:
            row = board.db.get_state(card_id, check_key("状态", name))
            default = ((manifest.get("state") or {}).get(name) or {}).get("default")
            return {"value": row["value"] if row else default, "stored": row is not None}
        return {"items": board.db.list_state(card_id)}
    if kind == "runs":
        return {"runs": board.db.list_runs(card_id, limit=max(1, min(limit, LIMITS["runsPerCard"])))}
    from .errors import BoardError

    raise BoardError("invalid", f"未知的 kind：{kind}")


def dispatch(args: dict[str, Any]) -> dict[str, Any]:
    action = args.get("action")
    if action not in ACTIONS:
        from .errors import BoardError

        raise BoardError("invalid", f"未知的 action：{action!r}，可选 {', '.join(ACTIONS)}")
    board = get_board()
    if action == "list":
        return _list(board)
    if action == "get":
        return board.cards.read_package(check_card_id(_require(args, "card")))
    if action == "validate":
        report = board.cards.validate(_require(args, "package"))
        return {"valid": report["ok"], "errors": report["errors"], "warnings": report["warnings"]}
    if action == "save":
        place = args.get("place", "auto")
        if place in (None, ""):
            place = "auto"
        return board.install_card(_require(args, "package"), replace=bool(args.get("replace")), place=place)
    if action == "remove":
        return board.remove_card(_require(args, "card"), delete_package=bool(args.get("deletePackage")),
                                 confirm=args.get("confirm") is True)
    if action == "run":
        return _run(board, args)
    if action == "data":
        return _data(board, args)
    if action == "place":
        layout = board.place(_require(args, "card"), int(_require(args, "x")), int(_require(args, "y")),
                             args.get("size"), updated_by="agent")
        return {"layout": {"revision": layout["revision"], "items": layout["items"]}}
    return board.restore_default(_require(args, "card"))


def handle(args: Any = None, **_kwargs: Any) -> str:
    try:
        if not isinstance(args, dict):
            return _err("invalid", "参数必须是对象")
        return _ok(**dispatch(args))
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code is None:
            logger.exception("hermes-board: board_manage failed")
            return _err("internal", str(exc) or type(exc).__name__)
        payload = error_payload(exc)
        return _err(payload.pop("code"), payload.pop("message"), **payload)


__all__ = ["ACTIONS", "SCHEMA", "dispatch", "handle"]
