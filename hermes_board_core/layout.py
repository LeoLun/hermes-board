"""Layout DSL (board.json) — design §4."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from . import PLUGIN_ROOT
from .constants import COLUMNS, LAYOUT_SCHEMA, LIMITS, PRESETS, parse_size, size_label
from .errors import BoardError
from .fsutil import atomic_write_json, file_lock
from .paths import CARD_ID_RE, Paths

TOP_KEYS = {"schema", "boardId", "title", "revision", "updatedAt", "updatedBy", "grid", "items"}
ITEM_KEYS = {"id", "card", "x", "y", "w", "h"}
SERVER_KEYS = {"revision", "updatedAt", "updatedBy"}
UPDATED_BY = {"desktop", "agent", "init", "api"}
DEFAULT_LAYOUT_FILE = PLUGIN_ROOT / "cards" / "default-layout.json"


def utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def empty_layout() -> dict[str, Any]:
    return {"schema": LAYOUT_SCHEMA, "boardId": "default", "title": "看板", "revision": 0,
            "updatedAt": utc_iso(), "updatedBy": "init", "grid": {"columns": COLUMNS}, "items": []}


# ── geometry ──────────────────────────────────────────────────────────────

def overlaps(a: Mapping[str, int], b: Mapping[str, int]) -> bool:
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]


def first_fit(items: Iterable[Mapping[str, int]], w: int, h: int, columns: int = COLUMNS) -> tuple[int, int]:
    """Smallest ``y`` then smallest ``x`` where a ``w×h`` rect overlaps nothing."""
    placed = list(items)
    if w > columns:
        raise BoardError("invalid", f"宽度 {w} 超过 {columns} 列")
    bottom = max((i["y"] + i["h"] for i in placed), default=0)
    for y in range(0, bottom + 1):
        for x in range(0, columns - w + 1):
            rect = {"x": x, "y": y, "w": w, "h": h}
            if not any(overlaps(rect, p) for p in placed):
                return x, y
    return 0, bottom  # unreachable: y == bottom is always free


def push_down(items: list[dict[str, Any]], active: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Place ``active`` at its rect; colliding cards move down in (y, x) order, chaining."""
    placed = [dict(active)]
    others = sorted((dict(i) for i in items if i["id"] != active["id"]), key=lambda i: (i["y"], i["x"], i["id"]))
    for item in others:
        while True:
            hits = [p for p in placed if overlaps(item, p)]
            if not hits:
                break
            item["y"] = max(p["y"] + p["h"] for p in hits)
        placed.append(item)
    order = {i["id"]: n for n, i in enumerate(items)}
    if active["id"] not in order:
        order[active["id"]] = len(order)
    return sorted(placed, key=lambda i: order[i["id"]])


# ── validation ────────────────────────────────────────────────────────────

def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_items(items: Any, cards: Mapping[str, Mapping[str, Any]], preserved: Iterable[str] = ()) -> list[dict[str, int]]:
    """Validate layout items.

    ``cards`` maps every *available* card id to ``{"sizes": [...]}``. A card that is not
    available may only appear when it is already in the stored layout (``preserved``) —
    that keeps the "卡片不可用" placeholder instead of silently dropping it.
    """
    if not isinstance(items, list):
        raise BoardError("invalid", "items 必须是数组")
    if len(items) > LIMITS["maxItems"]:
        raise BoardError("invalid", f"看板最多 {LIMITS['maxItems']} 项")
    preserved_ids = set(preserved)
    out: list[dict[str, int]] = []
    seen: set[str] = set()
    for n, item in enumerate(items):
        where = f"items[{n}]"
        if not isinstance(item, dict):
            raise BoardError("invalid", f"{where} 必须是对象")
        extra = set(item) - ITEM_KEYS
        missing = ITEM_KEYS - set(item)
        if extra:
            raise BoardError("invalid", f"{where} 含未知字段：{sorted(extra)}")
        if missing:
            raise BoardError("invalid", f"{where} 缺少字段：{sorted(missing)}")
        card = item["card"]
        if not isinstance(card, str) or not CARD_ID_RE.match(card):
            raise BoardError("invalid", f"{where}.card 不合法：{card!r}")
        if item["id"] != card:
            raise BoardError("invalid", f"{where}.id 必须等于 card（v1 每个卡片最多一个实例）")
        if card in seen:
            raise BoardError("invalid", f"卡片 {card} 在看板上重复出现")
        seen.add(card)
        for key in ("x", "y", "w", "h"):
            if not _is_int(item[key]):
                raise BoardError("invalid", f"{where}.{key} 必须是整数")
        x, y, w, h = item["x"], item["y"], item["w"], item["h"]
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > COLUMNS:
            raise BoardError("invalid", f"{where} 越界：x={x} y={y} w={w} h={h}（x+w 不能超过 {COLUMNS}）")
        label = size_label(w, h)
        if label not in PRESETS:
            raise BoardError("invalid", f"{where} 尺寸 {label} 不是预设尺寸")
        info = cards.get(card)
        if info is None:
            if card not in preserved_ids:
                raise BoardError("invalid", f"{where} 引用了未安装或不可用的卡片：{card}")
        elif label not in info.get("sizes", ()):
            raise BoardError("invalid", f"{where} 尺寸 {label} 不在卡片 {card} 允许的尺寸里")
        out.append({"id": card, "card": card, "x": x, "y": y, "w": w, "h": h})
    for i, a in enumerate(out):
        for b in out[i + 1:]:
            if overlaps(a, b):
                raise BoardError("invalid", f"卡片 {a['id']} 与 {b['id']} 重叠")
    return out


def migrate(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise BoardError("invalid", "board.json 不是对象")
    schema = doc.get("schema")
    if schema == LAYOUT_SCHEMA:
        return doc
    if isinstance(schema, str) and schema.startswith("hermes-board/layout@"):
        version = schema.rsplit("@", 1)[1]
        if version.isdigit() and int(version) > 1:
            raise BoardError("invalid", f"布局结构 {schema} 比当前插件支持的版本新，请更新插件", newer=True)
    raise BoardError("invalid", f"未知的布局结构：{schema!r}")


def load_default_items() -> list[dict[str, int]]:
    return json.loads(DEFAULT_LAYOUT_FILE.read_text(encoding="utf-8"))["items"]


class LayoutStore:
    def __init__(self, paths: Paths, db: Any) -> None:
        self.paths = paths
        self.db = db

    def exists(self) -> bool:
        return self.paths.board_file.is_file()

    def read(self) -> Optional[dict[str, Any]]:
        path: Path = self.paths.board_file
        if not path.is_file():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise BoardError("invalid", f"board.json 无法解析：{exc}") from exc
        return migrate(doc)

    def get(self) -> dict[str, Any]:
        return self.read() or empty_layout()

    def _commit(self, current: dict[str, Any], items: list[dict[str, int]], updated_by: str) -> dict[str, Any]:
        doc = {key: current[key] for key in TOP_KEYS if key in current}
        doc.update({"schema": LAYOUT_SCHEMA, "boardId": current.get("boardId", "default"),
                    "title": current.get("title", "看板"), "grid": {"columns": COLUMNS}, "items": items,
                    "revision": int(current.get("revision", 0)) + 1, "updatedAt": utc_iso(),
                    "updatedBy": updated_by if updated_by in UPDATED_BY else "api"})
        atomic_write_json(self.paths.board_file, doc)
        self.db.add_change(None, "layout", "board")
        return doc

    def write(self, items: Any, *, base_revision: Any, updated_by: str,
              cards: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        if not _is_int(base_revision):
            raise BoardError("invalid", "baseRevision 必须是整数")
        with file_lock(self.paths.layout_lock):
            current = self.get()
            if base_revision != current["revision"]:
                raise BoardError("conflict", "布局已在其他地方更新", current=current)
            preserved = {i["card"] for i in current["items"]}
            normalized = validate_items(items, cards, preserved)
            return self._commit(current, normalized, updated_by)

    def mutate(self, fn: Callable[[dict[str, Any]], list[dict[str, Any]]], *, updated_by: str,
               cards: Mapping[str, Mapping[str, Any]], base_revision: Optional[int] = None) -> dict[str, Any]:
        """Server-side edit under the layout lock (tool / API item operations)."""
        with file_lock(self.paths.layout_lock):
            current = self.get()
            if base_revision is not None and base_revision != current["revision"]:
                raise BoardError("conflict", "布局已在其他地方更新", current=current)
            items = fn(json.loads(json.dumps(current)))
            preserved = {i["card"] for i in current["items"]}
            normalized = validate_items(items, cards, preserved)
            return self._commit(current, normalized, updated_by)

    def initialize(self, items: list[dict[str, Any]], cards: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        with file_lock(self.paths.layout_lock):
            current = self.read()
            if current is not None:
                return current
            normalized = validate_items(items, cards)
            return self._commit(empty_layout(), normalized, "init")


def place_new(items: list[dict[str, Any]], card: str, size: str) -> list[dict[str, Any]]:
    w, h = parse_size(size)
    x, y = first_fit(items, w, h)
    return items + [{"id": card, "card": card, "x": x, "y": y, "w": w, "h": h}]


__all__ = ["LayoutStore", "empty_layout", "first_fit", "load_default_items", "migrate", "overlaps", "place_new",
           "push_down", "validate_items"]
