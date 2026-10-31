"""SQLite layer: the plugin loads ``sdk/hermes_board_sdk.py`` so schema and writes live in one file."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from . import PLUGIN_ROOT

SDK_PATH = PLUGIN_ROOT / "sdk" / "hermes_board_sdk.py"
_MODULE_NAME = "hermes_board_core._sdk_impl"


def _load_sdk() -> ModuleType:
    existing = sys.modules.get(_MODULE_NAME)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, SDK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging error
        raise ImportError(f"cannot load SDK from {SDK_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


sdk = _load_sdk()
BoardDB = sdk.BoardDB


def sdk_sha256() -> str:
    return hashlib.sha256(SDK_PATH.read_bytes()).hexdigest()


def open_db(path: Path) -> "BoardDB":
    return BoardDB(path)


__all__ = ["BoardDB", "SDK_PATH", "open_db", "sdk", "sdk_sha256"]
