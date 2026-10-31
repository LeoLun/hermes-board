"""Builds valid card packages for tests; override pieces per case."""
from __future__ import annotations

import copy
from typing import Any

HTML = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>演示</title>
<style>.value { color: var(--hb-ink); font-weight: 600; }</style>
</head>
<body>
<main class="hb-card">
  <header class="hb-header"><h2 class="hb-title">演示</h2></header>
  <div id="out" class="hb-state">加载中</div>
</main>
<script>
  HermesCard.ready();
  HermesCard.data.get('current').then(function (v) {
    HermesCard.ui.state(document.getElementById('out'), v ? 'ready' : 'empty');
  });
</script>
</body>
</html>
"""

SCRIPT = """import json, os, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "_sdk"))
from hermes_board_sdk import Card

card = Card()
n = card.args.get("n", 1)
card.data.set("current", {"n": n})
card.series.append("count", n)
card.progress(0.5, "半程")
card.result({"ok": True, "n": n})
"""


def manifest(card_id: str = "demo", **overrides: Any) -> dict[str, Any]:
    base = {
        "schema": "hermes-board/card@1",
        "id": card_id,
        "title": "演示",
        "description": "测试用卡片",
        "version": "1.0.0",
        "entry": "index.html",
        "sizes": ["4x4", "6x4"],
        "defaultSize": "4x4",
        "scripts": {
            "fetch": {"file": "fetch.py", "schedule": "every 30m", "callable": True, "runOnInstall": False,
                      "timeoutSec": 30,
                      "args": {"type": "object", "properties": {"n": {"type": "integer", "minimum": 0}},
                               "additionalProperties": False}},
        },
        "datasets": {"current": {"description": "当前值"}},
        "series": {"count": {"description": "计数", "retention": {"maxAgeDays": 7, "maxPoints": 100}}},
        "state": {"city": {"description": "城市", "default": "北京"}},
    }
    base.update(overrides)
    return base


def package(card_id: str = "demo", html: str = HTML, scripts: dict[str, str] | None = None,
            **manifest_overrides: Any) -> dict[str, Any]:
    return {
        "manifest": manifest(card_id, **manifest_overrides),
        "html": html,
        "scripts": copy.deepcopy(scripts) if scripts is not None else {"fetch.py": SCRIPT},
    }
