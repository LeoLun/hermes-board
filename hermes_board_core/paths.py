"""Locations and naming rules (design §3)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import BoardError

CARD_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,47}$")
SCRIPT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
SCRIPT_FILE_RE = re.compile(r"^[a-z0-9_-]{1,48}\.(py|sh)$")
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
AI_NAME_RE = SCRIPT_NAME_RE


def check_card_id(card_id: object) -> str:
    if not isinstance(card_id, str) or not CARD_ID_RE.match(card_id):
        raise BoardError("invalid", f"卡片 id 不合法：{card_id!r}（需匹配 {CARD_ID_RE.pattern}）")
    return card_id


def check_key(kind: str, key: object) -> str:
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise BoardError("invalid", f"{kind}名称不合法：{key!r}（需匹配 {KEY_RE.pattern}）")
    return key


def safe_child(base: Path, name: str) -> Path:
    """Join ``name`` under ``base`` and refuse anything that resolves outside it."""
    if not name or "/" in name or "\\" in name or name in (".", "..") or "\x00" in name:
        raise BoardError("invalid", f"文件名不合法：{name!r}")
    base_resolved = base.resolve()
    target = (base / name).resolve()
    if target.parent != base_resolved:
        raise BoardError("invalid", f"路径越界：{name!r}")
    return base / name


@dataclass(frozen=True)
class Paths:
    data_dir: Path
    scripts_root: Path

    @property
    def board_file(self) -> Path:
        return self.data_dir / "board.json"

    @property
    def db_file(self) -> Path:
        return self.data_dir / "board.sqlite3"

    @property
    def cards_dir(self) -> Path:
        return self.data_dir / "cards"

    @property
    def trash_dir(self) -> Path:
        return self.data_dir / "trash"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def init_lock(self) -> Path:
        return self.data_dir / ".init.lock"

    @property
    def install_lock(self) -> Path:
        return self.data_dir / ".install.lock"

    @property
    def layout_lock(self) -> Path:
        return self.data_dir / ".layout.lock"

    @property
    def sdk_dir(self) -> Path:
        return self.scripts_root / "_sdk"

    @property
    def sdk_file(self) -> Path:
        return self.sdk_dir / "hermes_board_sdk.py"

    def card_dir(self, card_id: str) -> Path:
        return safe_child(self.cards_dir, check_card_id(card_id))

    def card_scripts_dir(self, card_id: str) -> Path:
        return safe_child(self.scripts_root, check_card_id(card_id))

    def script_file(self, card_id: str, file_name: str) -> Path:
        if not SCRIPT_FILE_RE.match(file_name or ""):
            raise BoardError("invalid", f"脚本文件名不合法：{file_name!r}")
        return safe_child(self.card_scripts_dir(card_id), file_name)

    def cron_script_ref(self, card_id: str, file_name: str) -> str:
        """Path relative to ``$HERMES_HOME/scripts`` as Hermes cron expects."""
        self.script_file(card_id, file_name)
        return f"{self.scripts_root.name}/{card_id}/{file_name}"


__all__ = ["AI_NAME_RE", "CARD_ID_RE", "KEY_RE", "Paths", "SCRIPT_FILE_RE", "SCRIPT_NAME_RE", "check_card_id",
           "check_key", "safe_child"]
