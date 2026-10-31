"""``Board`` facade shared by the REST API and the Agent tool, cached per profile data dir."""
from __future__ import annotations

import threading
from typing import Any, Optional

from . import init as init_mod
from .ai import AiRunner
from .cards import CardStore
from .constants import API_VERSION, PLUGIN_VERSION, parse_size
from .cron_sync import CronSync
from .errors import BoardError
from .events import Events
from .host import Host, get_host
from .layout import LayoutStore, place_new, push_down
from .paths import Paths, check_card_id
from .runner import Runner
from .store import BoardDB, sdk

STALE_RUN_MS = 15 * 60 * 1000


class Board:
    def __init__(self, host: Host) -> None:
        self.host = host
        self.paths = Paths(host.data_dir(), host.scripts_root())
        self.db = BoardDB(self.paths.db_file)
        self.db.migrate()
        self.db.fail_stale_runs(sdk.now_ms() - STALE_RUN_MS)
        self.events = Events(host)
        self.layout = LayoutStore(self.paths, self.db)
        self.cron = CronSync(self.paths, self.db, host)
        self._assumed: set[str] = set()
        self.cards = CardStore(self.paths, self.db, host, self.cron, on_board=self.is_on_board)
        self.runner = Runner(self.paths, self.db, host, self.cards, self.events)
        self.ai = AiRunner(self.cards, self.db, host)
        self._initialized = False
        self._init_lock = threading.Lock()

    # ── lifecycle ─────────────────────────────────────────────────────────
    def ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if not self._initialized:
                init_mod.initialize(self, init_mod.BUNDLED_DIR)
                self._initialized = True

    def shutdown(self) -> None:
        self.runner.shutdown(wait=True)

    # ── board membership ──────────────────────────────────────────────────
    def assume_on_board(self, ids: set[str]) -> None:
        self._assumed = set(ids)

    def on_board_ids(self) -> set[str]:
        try:
            return {i["card"] for i in self.layout.get()["items"]}
        except BoardError:
            return set()

    def is_on_board(self, card_id: str) -> bool:
        return card_id in self._assumed or card_id in self.on_board_ids()

    def _after_layout(self, before: set[str], doc: dict[str, Any]) -> None:
        after = {i["card"] for i in doc["items"]}
        for card_id in sorted(before - after):
            self.cron.set_paused(card_id, True)
        for card_id in sorted(after - before):
            self.cron.set_paused(card_id, False)
        self.events.layout_updated(doc["revision"], doc.get("updatedBy", "api"))

    # ── views ─────────────────────────────────────────────────────────────
    def card_summary(self, info: dict[str, Any], on_board: set[str]) -> dict[str, Any]:
        manifest = info.get("manifest") or {}
        cron_status = self.cron.status(info["id"]) if info["status"] == "ok" else {}
        scripts = []
        for name, decl in (manifest.get("scripts") or {}).items():
            if not isinstance(decl, dict):
                continue
            last = self.db.list_runs(info["id"], limit=1, name=name)
            scripts.append({
                "name": name, "schedule": decl.get("schedule"), "callable": bool(decl.get("callable")),
                "description": decl.get("description"),
                "cron": cron_status.get(name) if decl.get("schedule") else None,
                "cronAvailable": self.cron.available(),
                "lastRun": ({k: last[0][k] for k in ("runId", "status", "trigger", "createdAt", "finishedAt", "error")}
                            if last else None),
            })
        out = {k: v for k, v in info.items() if k != "manifest"}
        out.update({"onBoard": info["id"] in on_board, "scripts": scripts,
                    "ai": sorted((manifest.get("ai") or {}).keys())})
        return out

    def view(self) -> dict[str, Any]:
        layout = self.layout.get()
        on_board = {i["card"] for i in layout["items"]}
        return {"layout": layout, "cards": [self.card_summary(c, on_board) for c in self.cards.list()]}

    def health(self) -> dict[str, Any]:
        return {"ok": True, "pluginVersion": PLUGIN_VERSION, "apiVersion": API_VERSION,
                "schemaVersion": self.db.migrate(), "cronAvailable": self.cron.available(),
                "aiAvailable": self.ai.available()}

    def changes(self, since: Optional[int]) -> dict[str, Any]:
        if since is None:
            return {"seq": self.db.current_seq(), "changes": []}
        return self.db.changes_since(since)

    # ── layout operations ─────────────────────────────────────────────────
    def save_layout(self, items: Any, base_revision: Any, updated_by: str = "desktop") -> dict[str, Any]:
        before = self.on_board_ids()
        doc = self.layout.write(items, base_revision=base_revision, updated_by=updated_by,
                                cards=self.cards.available())
        self._after_layout(before, doc)
        return doc

    def _size_for(self, manifest: dict[str, Any], size: Optional[str]) -> str:
        size = size or manifest["defaultSize"]
        if size not in manifest["sizes"]:
            raise BoardError("invalid", f"尺寸 {size} 不在卡片 {manifest['id']} 允许的尺寸 {manifest['sizes']} 里")
        return size

    def add_item(self, card_id: str, size: Optional[str] = None, x: Optional[int] = None, y: Optional[int] = None,
                 base_revision: Optional[int] = None, updated_by: str = "desktop") -> dict[str, Any]:
        manifest = self.cards.manifest(check_card_id(card_id))
        size = self._size_for(manifest, size)
        before = self.on_board_ids()

        def apply(doc: dict[str, Any]) -> list[dict[str, Any]]:
            items = doc["items"]
            if any(i["card"] == card_id for i in items):
                raise BoardError("exists", f"卡片 {card_id} 已在看板上")
            if x is None or y is None:
                return place_new(items, card_id, size)
            w, h = parse_size(size)
            return push_down(items, {"id": card_id, "card": card_id, "x": x, "y": y, "w": w, "h": h})

        doc = self.layout.mutate(apply, updated_by=updated_by, cards=self.cards.available(),
                                 base_revision=base_revision)
        self._after_layout(before, doc)
        return doc

    def remove_item(self, card_id: str, base_revision: Optional[int] = None,
                    updated_by: str = "desktop") -> dict[str, Any]:
        before = self.on_board_ids()

        def apply(doc: dict[str, Any]) -> list[dict[str, Any]]:
            if not any(i["card"] == card_id for i in doc["items"]):
                raise BoardError("not_found", f"卡片 {card_id} 不在看板上")
            return [i for i in doc["items"] if i["card"] != card_id]

        doc = self.layout.mutate(apply, updated_by=updated_by, cards=self.cards.available(),
                                 base_revision=base_revision)
        self._after_layout(before, doc)
        return doc

    def place(self, card_id: str, x: int, y: int, size: Optional[str] = None,
              updated_by: str = "agent") -> dict[str, Any]:
        manifest = self.cards.manifest(check_card_id(card_id))
        before = self.on_board_ids()

        def apply(doc: dict[str, Any]) -> list[dict[str, Any]]:
            current = next((i for i in doc["items"] if i["card"] == card_id), None)
            if current is None:
                raise BoardError("not_found", f"卡片 {card_id} 不在看板上")
            label = size or f"{current['w']}x{current['h']}"
            w, h = parse_size(self._size_for(manifest, label))
            return push_down(doc["items"], {"id": card_id, "card": card_id, "x": x, "y": y, "w": w, "h": h})

        doc = self.layout.mutate(apply, updated_by=updated_by, cards=self.cards.available())
        self._after_layout(before, doc)
        return doc

    # ── card operations ───────────────────────────────────────────────────
    def run_on_install(self, card_ids: list[str]) -> list[str]:
        runs = []
        for card_id in card_ids:
            try:
                manifest = self.cards.manifest(card_id)
            except BoardError:
                continue
            for name, decl in (manifest.get("scripts") or {}).items():
                if isinstance(decl, dict) and decl.get("runOnInstall"):
                    try:
                        runs.append(self.runner.start(card_id, name, {}, trigger="install")["runId"])
                    except BoardError:
                        continue
        return runs

    def install_card(self, package: Any, *, replace: bool = False, place: Any = "auto",
                     source: str = "agent") -> dict[str, Any]:
        result = self.cards.install(package, replace=replace, source=source)
        card_id = result["card"]
        self.events.card_updated(card_id, result["revision"])
        manifest = self.cards.manifest(card_id)
        layout = self.layout.get()
        current = next((i for i in layout["items"] if i["card"] == card_id), None)
        placed = None
        if current is not None:
            if f"{current['w']}x{current['h']}" not in manifest["sizes"]:
                w, h = parse_size(manifest["defaultSize"])
                doc = self.place(card_id, current["x"], current["y"], manifest["defaultSize"], updated_by="agent")
                placed = next(i for i in doc["items"] if i["card"] == card_id)
            else:
                placed = current
        elif isinstance(place, dict):
            doc = self.add_item(card_id, place.get("size"), place.get("x"), place.get("y"), updated_by="agent")
            placed = next(i for i in doc["items"] if i["card"] == card_id)
        elif place == "auto" and result["created"]:
            doc = self.add_item(card_id, updated_by="agent")
            placed = next(i for i in doc["items"] if i["card"] == card_id)
        result["placed"] = placed
        result["runs"] = self.run_on_install([card_id])
        return result

    def remove_card(self, card_id: str, *, delete_package: bool = False, confirm: bool = False) -> dict[str, Any]:
        check_card_id(card_id)
        if confirm is not True:
            raise BoardError("invalid", "移除卡片需要 confirm: true")
        out: dict[str, Any] = {"card": card_id, "removedFromBoard": False, "deleted": False}
        if self.is_on_board(card_id):
            self.remove_item(card_id, updated_by="agent")
            out["removedFromBoard"] = True
        if delete_package:
            out.update(self.cards.delete(card_id))
            out["deleted"] = True
            self.events.card_removed(card_id)
        elif not out["removedFromBoard"] and not self.cards.exists(card_id):
            raise BoardError("not_found", f"卡片 {card_id} 不存在")
        return out

    def restore_default(self, card_id: str) -> dict[str, Any]:
        check_card_id(card_id)
        if card_id not in init_mod.bundled_ids(init_mod.BUNDLED_DIR):
            raise BoardError("not_found", f"{card_id} 不是内置默认卡片")
        package = init_mod.bundled_package(card_id, init_mod.BUNDLED_DIR)
        return self.install_card(package, replace=self.cards.exists(card_id), place="auto", source="bundled")


_cache: dict[str, Board] = {}
_cache_lock = threading.Lock()


def get_board(host: Optional[Host] = None, initialize: bool = True) -> Board:
    host = host or get_host()
    key = str(host.data_dir())
    with _cache_lock:
        board = _cache.get(key)
        if board is None or board.host is not host:
            board = Board(host)
            _cache[key] = board
    if initialize:
        board.ensure_initialized()
    return board


def reset_cache() -> None:
    with _cache_lock:
        _cache.clear()


def shutdown_all() -> None:
    with _cache_lock:
        boards = list(_cache.values())
    for board in boards:
        board.shutdown()


__all__ = ["Board", "get_board", "reset_cache", "shutdown_all"]
