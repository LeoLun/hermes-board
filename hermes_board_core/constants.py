"""Shared constants loaded from ``shared/constants.json`` (single source for Python and JS)."""
from __future__ import annotations

import json
from typing import Any

from . import PLUGIN_ROOT

_RAW: dict[str, Any] = json.loads((PLUGIN_ROOT / "shared" / "constants.json").read_text(encoding="utf-8"))

PLUGIN_ID: str = _RAW["pluginId"]
PLUGIN_VERSION: str = _RAW["pluginVersion"]
API_VERSION: int = _RAW["apiVersion"]
PROTOCOL: int = _RAW["protocol"]
LAYOUT_SCHEMA: str = _RAW["layoutSchema"]
CARD_SCHEMA: str = _RAW["cardSchema"]
COLUMNS: int = _RAW["grid"]["columns"]
PRESETS: tuple[str, ...] = tuple(_RAW["presets"])
LIMITS: dict[str, int] = dict(_RAW["limits"])
BRIDGE: dict[str, int] = dict(_RAW["bridge"])


def parse_size(label: str) -> tuple[int, int]:
    """``"6x4"`` → ``(6, 4)``; raises ``ValueError`` for anything malformed."""
    if not isinstance(label, str) or "x" not in label:
        raise ValueError(f"尺寸格式不合法：{label!r}")
    w, h = label.split("x", 1)
    if not (w.isdigit() and h.isdigit()):
        raise ValueError(f"尺寸格式不合法：{label!r}")
    return int(w), int(h)


def size_label(w: int, h: int) -> str:
    return f"{w}x{h}"


def raw() -> dict[str, Any]:
    return json.loads(json.dumps(_RAW))
