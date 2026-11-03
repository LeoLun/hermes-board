"""Idempotent first-run initialisation under ``.init.lock`` (design §14)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from . import PLUGIN_ROOT
from .constants import PLUGIN_VERSION
from .fsutil import file_lock
from .validator import load_package_dir

logger = logging.getLogger("hermes_board")
BUNDLED_DIR = PLUGIN_ROOT / "cards"
VERSION_META = "pluginVersion"


def bundled_ids(bundled_dir: Optional[Path] = None) -> list[str]:
    base = bundled_dir or BUNDLED_DIR
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / "card.json").is_file())


def bundled_package(card_id: str, bundled_dir: Optional[Path] = None) -> dict[str, Any]:
    base = bundled_dir or BUNDLED_DIR
    return load_package_dir(base / card_id)


def default_items(bundled_dir: Optional[Path] = None) -> list[dict[str, Any]]:
    path = (bundled_dir or BUNDLED_DIR) / "default-layout.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("items", [])


def upgrade_bundled(board: Any, bundled_dir: Optional[Path] = None) -> list[str]:
    """Upgrade untouched default cards while preserving user-installed replacements."""
    upgraded: list[str] = []
    for card_id in bundled_ids(bundled_dir):
        if not board.cards.is_unmodified_bundled(card_id):
            continue
        package = bundled_package(card_id, bundled_dir)
        if board.cards.matches_package(card_id, package):
            continue
        board.cards.install(package, replace=True, source="bundled")
        upgraded.append(card_id)
    return upgraded


def initialize(board: Any, bundled_dir: Optional[Path] = None) -> dict[str, Any]:
    paths = board.paths
    with file_lock(paths.init_lock):
        if paths.board_file.exists():
            if board.db.get_meta(VERSION_META) != PLUGIN_VERSION:
                upgraded = upgrade_bundled(board, bundled_dir)
                board.cards.sync_sdk()
                board.cron.reconcile(board.cards.manifests(), board.on_board_ids())
                board.db.set_meta(VERSION_META, PLUGIN_VERSION)
                return {"initialized": False, "reconciled": True, "upgraded": upgraded}
            return {"initialized": False}
        items = default_items(bundled_dir)
        wanted = {i["card"] for i in items}
        board.assume_on_board(wanted)
        installed: list[str] = []
        try:
            for card_id in bundled_ids(bundled_dir):
                if board.cards.exists(card_id):
                    continue
                try:
                    board.cards.install(bundled_package(card_id, bundled_dir), source="bundled")
                    installed.append(card_id)
                except Exception as exc:  # one broken bundled card must not block the board
                    logger.warning("hermes-board: bundled card %s failed to install: %s", card_id, exc)
            available = board.cards.available()
            layout_items = [i for i in items if i["card"] in available]
            doc = board.layout.initialize(layout_items, available)
        finally:
            board.assume_on_board(set())
        board.cards.sync_sdk()
        board.cron.reconcile(board.cards.manifests(), board.on_board_ids())
        board.db.set_meta(VERSION_META, PLUGIN_VERSION)
        runs = board.run_on_install([i["card"] for i in doc["items"]])
        board.events.layout_updated(doc["revision"], "init")
        return {"initialized": True, "installed": installed, "runs": runs}


__all__ = ["BUNDLED_DIR", "bundled_ids", "bundled_package", "default_items", "upgrade_bundled", "initialize"]
