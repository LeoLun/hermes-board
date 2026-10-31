"""AI tasks declared in ``card.json`` → ``ctx.llm.complete_structured`` (design §8.4)."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .constants import LIMITS, PLUGIN_ID
from .errors import BoardError
from .store import sdk
from .validator import validate_value

logger = logging.getLogger("hermes_board")
AI_STALE_MS = 180_000
_llm: Any = None
_tried_default = False


def set_llm(handle: Any) -> None:
    """Called from ``register(ctx)`` with ``ctx.llm`` so the dashboard API can reuse it."""
    global _llm
    _llm = handle


def get_llm() -> Any:
    global _llm, _tried_default
    if _llm is not None:
        return _llm
    if not _tried_default:
        _tried_default = True
        try:
            from agent.plugin_llm import PluginLlm  # type: ignore

            _llm = PluginLlm(plugin_id=PLUGIN_ID)
        except Exception as exc:
            logger.debug("hermes-board: PluginLlm unavailable: %s", exc)
    return _llm


def _usage(result: Any) -> dict[str, Any]:
    usage = getattr(result, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    return {key: getattr(usage, key) for key in ("input_tokens", "output_tokens", "total_tokens", "cost_usd")
            if getattr(usage, key, None) is not None}


class AiRunner:
    def __init__(self, cards: Any, db: Any, host: Any) -> None:
        self.cards = cards
        self.db = db
        self.host = host

    def available(self) -> bool:
        return self.host.llm() is not None

    def run(self, card_id: str, name: str, value: Any, trigger: str = "action") -> dict[str, Any]:
        manifest = self.cards.manifest(card_id)
        decl = (manifest.get("ai") or {}).get(name)
        if not isinstance(decl, dict):
            raise BoardError("not_found", f"卡片 {card_id} 没有声明 AI 任务 {name}")
        text = sdk.dumps(value)
        if len(text.encode("utf-8")) > LIMITS["aiInputBytes"]:
            raise BoardError("invalid", "AI 输入超过 32 KiB 上限")
        errors = validate_value(decl["inputSchema"], value, "input")
        if errors:
            raise BoardError("invalid", "；".join(errors[:5]), errors=errors)
        llm = self.host.llm()
        if llm is None:
            raise BoardError("ai_unavailable", "当前 Hermes 没有可用的插件模型接口")
        active = self.db.active_run(card_id, "ai", name)
        if active is not None and sdk.now_ms() - active["createdAt"] < AI_STALE_MS:
            raise BoardError("busy", f"AI 任务 {name} 正在运行")
        run_id = self.db.create_run(card_id, "ai", name, trigger, status="running", started=True)
        try:
            result = llm.complete_structured(
                instructions=decl["system"],
                input=[{"type": "text", "text": text}],
                json_schema=decl["outputSchema"],
                schema_name=f"hermes_board_{name}",
                max_tokens=min(int(decl.get("maxTokens", 1000)), LIMITS["aiMaxTokens"]),
                purpose=f"hermes-board.{card_id}.{name}",
            )
        except Exception as exc:
            self.db.update_run(run_id, status="failed", error=f"模型调用失败：{exc}", finished_at=sdk.now_ms())
            raise BoardError("ai_unavailable", f"模型调用失败：{exc}") from exc
        parsed = getattr(result, "parsed", None)
        if parsed is None:
            try:
                parsed = json.loads(getattr(result, "text", "") or "")
            except ValueError:
                parsed = None
        out_errors = validate_value(decl["outputSchema"], parsed, "output") if parsed is not None else ["output 不是 JSON"]
        if out_errors:
            self.db.update_run(run_id, status="failed", error="AI 输出不符合 outputSchema：" + "；".join(out_errors[:3]),
                               finished_at=sdk.now_ms())
            raise BoardError("invalid", "AI 输出不符合 outputSchema", errors=out_errors)
        payload = {"parsed": parsed, "model": getattr(result, "model", None),
                   "provider": getattr(result, "provider", None), "usage": _usage(result)}
        self.db.update_run(run_id, status="succeeded", result_json=sdk.dumps(payload), finished_at=sdk.now_ms())
        payload["runId"] = run_id
        return payload


__all__ = ["AiRunner", "get_llm", "set_llm"]
