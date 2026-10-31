"""Error type shared by the core, the API and the Agent tool."""
from __future__ import annotations

from typing import Any

from .store import sdk

BoardError = sdk.BoardError

HTTP_STATUS = {
    "invalid": 400,
    "not_found": 404,
    "conflict": 409,
    "exists": 409,
    "rate_limited": 429,
    "busy": 429,
    "ai_unavailable": 501,
    "cron_unavailable": 503,
}


def error_payload(exc: BaseException) -> dict[str, Any]:
    code = getattr(exc, "code", None) or "internal"
    message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
    payload: dict[str, Any] = {"code": code, "message": message}
    details = getattr(exc, "details", None)
    if details:
        payload.update(details)
    return payload


def http_status(exc: BaseException) -> int:
    return HTTP_STATUS.get(getattr(exc, "code", ""), 500)


__all__ = ["BoardError", "HTTP_STATUS", "error_payload", "http_status"]
