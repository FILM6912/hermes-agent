"""Bearer authentication for the built-in document MCP endpoint and search tools."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from typing import TYPE_CHECKING

from app.domain.auth import parse_bearer_authorization, verify_session

if TYPE_CHECKING:
    from starlette.requests import Request

    from app.core.security import CurrentUser

logger = logging.getLogger(__name__)

MCP_USER_KEY_PREFIX = "hmcp_"
MCP_SERVICE_USER_ID = "mcp-service"


def hash_mcp_api_key(raw_key: str) -> str:
    cleaned = str(raw_key or "").strip()
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def configured_mcp_service_key() -> str:
    from app.document_api.core.config import get_settings

    return (get_settings().mcp_api_key or "").strip()


def mcp_auth_enabled() -> bool:
    from app.document_api.mcp_integration import normalized_mcp_mount_path

    return normalized_mcp_mount_path() is not None


def is_mcp_service_key(raw_key: str) -> bool:
    service_key = configured_mcp_service_key()
    candidate = str(raw_key or "").strip()
    if not service_key or not candidate:
        return False
    return hmac.compare_digest(candidate, service_key)


def resolve_user_from_mcp_api_key(raw_key: str) -> CurrentUser | None:
    """Map a per-user MCP API key to a ``CurrentUser`` with that account's role."""
    from app.core.security import CurrentUser
    from app.domain.mcp_keys import lookup_user_by_mcp_api_key

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
    from app.core.security import CurrentUser

    return CurrentUser(user_id=MCP_SERVICE_USER_ID, role="admin", profile_name=None)


def resolve_user_from_mcp_bearer(raw_key: str) -> CurrentUser | None:
    if is_mcp_service_key(raw_key):
        return resolve_mcp_service_user()
    return resolve_user_from_mcp_api_key(raw_key)


def bearer_token_from_request(request: Request) -> str | None:
    return parse_bearer_authorization(request.headers.get("authorization"))


def is_valid_mcp_bearer(raw_key: str | None) -> bool:
    token = str(raw_key or "").strip()
    if not token:
        return False
    if verify_session(token):
        return True
    if is_mcp_service_key(token):
        return True
    return resolve_user_from_mcp_api_key(token) is not None


def resolve_authenticated_user_for_mcp(request: Request) -> CurrentUser | None:
    """Resolve session, service key, or per-user MCP key for MCP-protected routes."""
    from app.core.security import CurrentUser
    from app.domain.auth import resolve_session_credential_from_request
    from app.domain.users import is_multi_user_enabled, resolve_request_user_access

    session_cred = resolve_session_credential_from_request(request)
    if session_cred:
        if not is_multi_user_enabled():
            return CurrentUser.legacy_admin()
        return CurrentUser.from_access(resolve_request_user_access(request))

    bearer = bearer_token_from_request(request)
    if not bearer:
        return None
    return resolve_user_from_mcp_bearer(bearer)


def mcp_mount_requires_bearer() -> bool:
    from app.document_api.core.config import get_settings

    if not mcp_auth_enabled():
        return False
    return bool(get_settings().mcp_require_bearer)


def warn_if_mcp_auth_misconfigured() -> None:
    if not mcp_auth_enabled():
        return
    if configured_mcp_service_key():
        return
    logger.warning(
        "MCP is enabled but MCP_API_KEY is unset — only session Bearer tokens and "
        "per-user MCP keys will authenticate /mcp and search tools"
    )
