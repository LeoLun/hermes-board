"""hermes-board: customizable card board for Hermes (remote plugin + Desktop page)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    # Import the core by its top-level name so this module and dashboard/plugin_api.py
    # share one hermes_board_core instance (and therefore one ctx.llm handle).
    sys.path.insert(0, str(_ROOT))

from hermes_board_core import ai as _ai  # noqa: E402
from hermes_board_core.tool import SCHEMA, handle  # noqa: E402

logger = logging.getLogger("hermes_board")
SKILL_PATH = _ROOT / "skills" / "card-author" / "SKILL.md"


def register(ctx: Any) -> None:
    """Register the board tool and the card authoring skill."""
    ctx.register_skill(
        "card-author",
        SKILL_PATH,
        description="通过对话为 Hermes 看板创建或修改卡片（清单、单文件 HTML、数据脚本、cron 刷新）。",
    )
    ctx.register_tool(
        name="board_manage",
        toolset="hermes_board",
        schema=SCHEMA,
        handler=handle,
        description="管理 Hermes 看板的卡片、布局、脚本运行和数据。",
    )
    try:
        llm = getattr(ctx, "llm", None)
    except Exception as exc:  # the LLM surface is optional
        logger.debug("hermes-board: ctx.llm unavailable: %s", exc)
        llm = None
    if llm is not None:
        _ai.set_llm(llm)
