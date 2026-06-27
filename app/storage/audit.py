"""Audit actor helpers for WebUI storage writes."""

from __future__ import annotations

from typing import Any

SYSTEM_ACTOR = "system"


def current_actor_email(*, fallback: str | None = None) -> str | None:
    """Best-effort email/id for the active WebUI user."""
    try:
        from app.domain.workspace import get_request_user_access

        access = get_request_user_access()
        if access is not None:
            for attr in ("username", "user_id", "email"):
                value = str(getattr(access, attr, None) or "").strip().lower()
                if value:
                    return value
    except Exception:
        pass
    if fallback:
        cleaned = str(fallback).strip().lower()
        if cleaned:
            return cleaned
    return None


def normalize_actor(value: Any, *, fallback: str | None = None) -> str | None:
    explicit = str(value or "").strip().lower() if value is not None else ""
    if explicit:
        return explicit
    return current_actor_email(fallback=fallback)


def actor_or_system(value: Any = None, *, fallback: str | None = None) -> str:
    return normalize_actor(value, fallback=fallback) or SYSTEM_ACTOR
