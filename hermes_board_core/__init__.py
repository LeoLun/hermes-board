"""hermes-board server core (imported by the Hermes plugin and its dashboard API)."""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

__all__ = ["PLUGIN_ROOT"]
