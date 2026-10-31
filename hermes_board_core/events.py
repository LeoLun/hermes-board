"""Desktop events (``plugin.hermes-board.<event>``). Polling ``/changes`` is the fallback."""
from __future__ import annotations

from typing import Any, Optional

from .host import Host


class Events:
    def __init__(self, host: Host) -> None:
        self.host = host

    def _send(self, event: str, payload: dict[str, Any]) -> None:
        self.host.broadcast(event, payload)

    def layout_updated(self, revision: int, updated_by: str) -> None:
        self._send("layout.updated", {"revision": revision, "updatedBy": updated_by})

    def card_updated(self, card_id: str, revision: Optional[int] = None) -> None:
        self._send("card.updated", {"card": card_id, "revision": revision})

    def card_removed(self, card_id: str) -> None:
        self._send("card.removed", {"card": card_id})

    def run_finished(self, card_id: str, run_id: str, name: str, status: str) -> None:
        self._send("run.finished", {"card": card_id, "runId": run_id, "name": name, "status": status})


__all__ = ["Events"]
