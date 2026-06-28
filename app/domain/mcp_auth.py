"""Bearer authentication for per-user MCP API keys and optional service keys."""

from __future__ import annotations

import hmac
import os

from app.core.security import CurrentUser
from app.domain.auth import verify_session
from app.domain.mcp_keys import lookup_user_by_mcp_api_key

MCP_SERVICE_USER_ID = "mcp-service"


def configured_mcp_service_key() -> str:
    return (
        os.environ.get("MCP_API_KEY") or os.environ.get("MCP_SERVICE_API_KEY") or ""
    ).strip()


def is_mcp_service_key(raw_key: str) -> bool:
    service_key = configured_mcp_service_key()
    candidate = str(raw_key or "").strip()
    if not service_key or not candidate:
        return False
    return hmac.compare_digest(candidate, service_key)


def resolve_user_from_mcp_api_key(raw_key: str) -> CurrentUser | None:
    """Map a per-user MCP API key to a ``CurrentUser`` with that account's role."""
    candidate = str(raw_key or "").strip()
    if not candidate or is_mcp_service_key(candidate):
        return None
    user = lookup_user_by_mcp_api_key(candidate)
    if user is None:
        return None
    if not user.get("enabled", True):
        return None
    email = str(user.get("email") or user.get("id") or "").strip().lower()
    if not email:
        return None
    role = str(user.get("role") or "user").strip().lower() or "user"
    profile_name = str(user.get("profile_name") or "").strip() or None
    profile_names = user.get("profile_names")
    if isinstance(profile_names, list):
        names = tuple(str(item).strip() for item in profile_names if str(item or "").strip())
    else:
        names = (profile_name,) if profile_name else ()
    return CurrentUser(
        user_id=email,
        role=role,
        profile_name=profile_name,
        profile_names=names,
    )


def resolve_mcp_service_user() -> CurrentUser:
    return CurrentUser(user_id=MCP_SERVICE_USER_ID, role="admin", profile_name=None)


def resolve_user_from_mcp_bearer(raw_key: str) -> CurrentUser | None:
    if is_mcp_service_key(raw_key):
        return resolve_mcp_service_user()
    return resolve_user_from_mcp_api_key(raw_key)


def is_valid_mcp_bearer(raw_key: str | None) -> bool:
    token = str(raw_key or "").strip()
    if not token:
        return False
    if verify_session(token):
        return True
    if is_mcp_service_key(token):
        return True
    return resolve_user_from_mcp_api_key(token) is not None
