"""Per-user MCP API keys (hashed in ``webui_users.mcp_api_key_hash``)."""

from __future__ import annotations

import secrets
from typing import Any

from app.document_api.mcp_auth import MCP_USER_KEY_PREFIX, hash_mcp_api_key
from app.domain.users import UserNotFoundError, get_user, is_multi_user_enabled, normalize_email
from app.storage.repositories.users import get_users_repository


def user_has_mcp_api_key(email: str) -> bool:
    if not is_multi_user_enabled():
        return False
    row = get_users_repository().get_by_email(normalize_email(email))
    return bool(row and str(row.get("mcp_api_key_hash") or "").strip())


def lookup_user_by_mcp_api_key(raw_key: str) -> dict[str, Any] | None:
    if not is_multi_user_enabled():
        return None
    candidate = str(raw_key or "").strip()
    if not candidate:
        return None
    return get_users_repository().find_by_mcp_api_key_hash(hash_mcp_api_key(candidate))


def generate_user_mcp_api_key(email: str, *, actor: str | None = None) -> str:
    if not is_multi_user_enabled():
        raise UserNotFoundError("Multi-user mode is required for MCP API keys")
    key = normalize_email(email)
    if get_user(key) is None:
        raise UserNotFoundError(f"user {key!r} not found")
    plain = MCP_USER_KEY_PREFIX + secrets.token_urlsafe(32)
    get_users_repository().set_mcp_api_key_hash(
        key,
        hash_mcp_api_key(plain),
        updated_by=actor or key,
    )
    from app.domain.users import invalidate_users_cache

    invalidate_users_cache()
    return plain


def revoke_user_mcp_api_key(email: str, *, actor: str | None = None) -> None:
    if not is_multi_user_enabled():
        raise UserNotFoundError("Multi-user mode is required for MCP API keys")
    key = normalize_email(email)
    if get_user(key) is None:
        raise UserNotFoundError(f"user {key!r} not found")
    get_users_repository().set_mcp_api_key_hash(
        key,
        None,
        updated_by=actor or key,
    )
    from app.domain.users import invalidate_users_cache

    invalidate_users_cache()
