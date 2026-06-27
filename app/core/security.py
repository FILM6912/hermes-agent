"""Auth helpers for FastAPI middleware and dependency injection."""

from __future__ import annotations

import http.cookies
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.auth import (
    COOKIE_NAME,
    PUBLIC_PATHS,
    check_auth,
    is_auth_enabled,
    parse_cookie,
    resolve_session_credential_from_handler,
    resolve_session_credential_from_request,
    verify_session,
)
from app.domain.users import (
    UserAccess,
    is_multi_user_enabled,
    legacy_user_access,
    resolve_request_user_access,
)

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    role: str
    profile_name: str | None = None
    profile_names: tuple[str, ...] = ()

    @property
    def is_admin(self) -> bool:
        from app.domain.roles import role_has_full_access

        return role_has_full_access(self.role)

    @classmethod
    def from_access(cls, access: UserAccess) -> CurrentUser:
        user_id = access.user_id or access.username or "legacy"
        return cls(
            user_id=user_id,
            role=access.role,
            profile_name=access.profile_name,
            profile_names=access.profile_names,
        )

    @classmethod
    def legacy_admin(cls) -> CurrentUser:
        return cls(user_id="legacy", role="admin", profile_name=None)


def _parse_cookie_header(cookie_header: str) -> str | None:
    if not cookie_header:
        return None
    cookie = http.cookies.SimpleCookie()
    try:
        cookie.load(cookie_header)
    except http.cookies.CookieError:
        return None
    morsel = cookie.get(COOKIE_NAME)
    return morsel.value if morsel else None


def _session_cookie_from_request(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME) or _parse_cookie_header(
        request.headers.get("cookie", "")
    )


def get_current_user(request: Request) -> CurrentUser | None:
    """Return the authenticated user for this request, or None."""
    if not is_auth_enabled():
        return CurrentUser.legacy_admin()
    session_cred = resolve_session_credential_from_request(request)
    if session_cred:
        if not is_multi_user_enabled():
            return CurrentUser.legacy_admin()
        return CurrentUser.from_access(resolve_request_user_access(request))

    from app.document_api.mcp_auth import resolve_authenticated_user_for_mcp

    return resolve_authenticated_user_for_mcp(request)


def require_current_user(request: Request) -> CurrentUser:
    """Return the authenticated user or raise HTTPException(401)."""
    from fastapi import HTTPException

    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def user_has_permission(user: CurrentUser | None, permission: str) -> bool:
    """Return True when the user's role grants *permission* (or wildcard)."""
    if user is None:
        return False
    if not is_multi_user_enabled():
        return True
    from app.domain.roles import role_has_permission

    return role_has_permission(user.role, permission)


def resolve_user_permissions(user: CurrentUser | None) -> dict[str, bool]:
    if user is None:
        return {}
    if not is_multi_user_enabled():
        return {"*": True}
    from app.domain.roles import resolve_role_permissions

    return resolve_role_permissions(user.role)


def require_permission(request: Request, permission: str) -> CurrentUser:
    """Return an authenticated user with *permission* or raise 401/403."""
    from fastapi import HTTPException

    user = require_current_user(request)
    if not user_has_permission(user, permission):
        raise HTTPException(
            status_code=403,
            detail=f"Permission required: {permission}",
        )
    return user


def require_admin(request: Request) -> CurrentUser:
    """Return a user with admin-level access or raise HTTPException(401/403)."""
    from fastapi import HTTPException

    user = require_current_user(request)
    if not (
        user.is_admin
        or user_has_permission(user, "users:manage")
        or user_has_permission(user, "roles:manage")
    ):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class AgentSoulAccessError(PermissionError):
    """Raised when a non-admin attempts Agent Soul (SOUL.md) operations."""


AGENT_SOUL_FORBIDDEN_DETAIL = "Permission required: agent_soul:access"

INSIGHTS_FORBIDDEN_DETAIL = "Permission required: insights:read"
LOGS_FORBIDDEN_DETAIL = "Permission required: logs:read"
# Back-compat alias for legacy callers/tests.
INSIGHTS_LOGS_FORBIDDEN_DETAIL = INSIGHTS_FORBIDDEN_DETAIL
_BUILTIN_ADMIN_ROLE = "admin"


class InsightsLogsAccessError(PermissionError):
    """Raised when a non-admin attempts Insights or Logs operations."""


def _has_insights_admin_override(user: CurrentUser) -> bool:
    role = str(user.role or "").strip().lower()
    return (
        role == _BUILTIN_ADMIN_ROLE
        or user.is_admin
        or user_has_permission(user, "users:manage")
        or user_has_permission(user, "roles:manage")
    )


def user_can_access_insights(user: CurrentUser | None) -> bool:
    """Insights require ``insights:read`` (or admin override) in multi-user mode."""
    if not is_multi_user_enabled():
        return True
    if user is None:
        return False
    return _has_insights_admin_override(user) or user_has_permission(user, "insights:read")


def user_can_access_logs(user: CurrentUser | None) -> bool:
    """Logs require ``logs:read`` (or admin override) in multi-user mode."""
    if not is_multi_user_enabled():
        return True
    if user is None:
        return False
    return _has_insights_admin_override(user) or user_has_permission(user, "logs:read")


def user_can_access_insights_logs(user: CurrentUser | None) -> bool:
    """Either insights or logs permission grants legacy combined access checks."""
    return user_can_access_insights(user) or user_can_access_logs(user)


def ensure_insights_access(user: CurrentUser | None) -> None:
    if not user_can_access_insights(user):
        raise InsightsLogsAccessError(INSIGHTS_FORBIDDEN_DETAIL)


def ensure_logs_access(user: CurrentUser | None) -> None:
    if not user_can_access_logs(user):
        raise InsightsLogsAccessError(LOGS_FORBIDDEN_DETAIL)


def ensure_insights_logs_access(user: CurrentUser | None) -> None:
    """Raise InsightsLogsAccessError when the caller may not use Insights/Logs."""
    if not user_can_access_insights_logs(user):
        raise InsightsLogsAccessError(INSIGHTS_FORBIDDEN_DETAIL)


def require_insights_access(request: Request) -> CurrentUser:
    """Return an authenticated user allowed to view Insights."""
    from fastapi import HTTPException

    user = require_current_user(request)
    if not user_can_access_insights(user):
        raise HTTPException(status_code=403, detail=INSIGHTS_FORBIDDEN_DETAIL)
    return user


def require_logs_access(request: Request) -> CurrentUser:
    """Return an authenticated user allowed to view Logs."""
    from fastapi import HTTPException

    user = require_current_user(request)
    if not user_can_access_logs(user):
        raise HTTPException(status_code=403, detail=LOGS_FORBIDDEN_DETAIL)
    return user


USERS_MANAGE_FORBIDDEN_DETAIL = "Permission required: users:manage"
ROLES_MANAGE_FORBIDDEN_DETAIL = "Permission required: roles:manage"
WORKSPACES_MANAGE_FORBIDDEN_DETAIL = "Permission required: workspaces:manage"
PROFILES_MANAGE_FORBIDDEN_DETAIL = "Permission required: profiles:manage"
SETTINGS_SYSTEM_FORBIDDEN_DETAIL = "Permission required: settings:system"


def _user_role(user) -> str | None:
    role = getattr(user, "role", None)
    return str(role) if role else None


def user_has_permission_for(user, permission: str) -> bool:
    """Permission check for ``CurrentUser``, ``UserAccess``, or legacy handler users."""
    if not is_multi_user_enabled():
        return True
    if user is None:
        return False
    role = _user_role(user)
    if not role:
        return False
    from app.domain.roles import role_has_permission

    return role_has_permission(role, permission)


def user_has_full_access(user) -> bool:
    if not is_multi_user_enabled():
        return True
    if user is None:
        return False
    return bool(getattr(user, "is_admin", False))


def user_can_manage_users(user) -> bool:
    if not is_multi_user_enabled():
        return True
    if user is None:
        return False
    return user_has_full_access(user) or user_has_permission_for(user, "users:manage")


def user_can_manage_roles(user) -> bool:
    if not is_multi_user_enabled():
        return True
    if user is None:
        return False
    return (
        user_has_full_access(user)
        or user_has_permission_for(user, "roles:manage")
        or user_has_permission_for(user, "users:manage")
    )


def user_can_manage_workspaces(user) -> bool:
    if not is_multi_user_enabled():
        return True
    if user is None:
        return False
    return (
        user_has_full_access(user)
        or user_has_permission_for(user, "workspaces:manage")
        or user_has_permission_for(user, "users:manage")
    )


def user_can_manage_profiles(user) -> bool:
    if not is_multi_user_enabled():
        return True
    if user is None:
        return False
    return user_has_full_access(user) or user_has_permission_for(user, "profiles:manage")


def user_can_switch_all_profiles(user) -> bool:
    if not is_multi_user_enabled():
        return True
    if user is None:
        return False
    return user_can_manage_profiles(user) or user_has_permission_for(user, "profiles:switch_all")


def user_can_access_settings_system(user) -> bool:
    if not is_multi_user_enabled():
        return True
    if user is None:
        return False
    return user_has_full_access(user) or user_has_permission_for(user, "settings:system")


def require_users_manage(request: Request) -> CurrentUser:
    user = require_current_user(request)
    if not user_can_manage_users(user):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail=USERS_MANAGE_FORBIDDEN_DETAIL)
    return user


def require_roles_manage(request: Request) -> CurrentUser:
    user = require_current_user(request)
    if not user_can_manage_roles(user):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail=ROLES_MANAGE_FORBIDDEN_DETAIL)
    return user


def require_workspaces_manage(request: Request) -> CurrentUser:
    user = require_current_user(request)
    if not user_can_manage_workspaces(user):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail=WORKSPACES_MANAGE_FORBIDDEN_DETAIL)
    return user


def require_settings_system(request: Request) -> CurrentUser:
    user = require_current_user(request)
    if not user_can_access_settings_system(user):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail=SETTINGS_SYSTEM_FORBIDDEN_DETAIL)
    return user


def user_can_access_agent_soul(user: CurrentUser | None) -> bool:
    """Agent Soul requires agent_soul:access when multi-user mode is enabled."""
    if not is_multi_user_enabled():
        return True
    return user is not None and user_has_permission(user, "agent_soul:access")


def ensure_agent_soul_access(user: CurrentUser | None) -> None:
    """Raise AgentSoulAccessError when the caller may not touch Agent Soul."""
    if not user_can_access_agent_soul(user):
        raise AgentSoulAccessError(AGENT_SOUL_FORBIDDEN_DETAIL)


def filter_memory_payload_for_user(
    payload: dict,
    user: CurrentUser | None,
) -> dict:
    """Strip soul fields from GET /api/memory for non-admin callers."""
    if user_can_access_agent_soul(user):
        return payload
    filtered = dict(payload)
    for key in ("soul", "soul_path", "soul_mtime"):
        filtered.pop(key, None)
    return filtered


def get_current_user_from_legacy_handler(handler) -> CurrentUser | None:
    """Resolve CurrentUser from a legacy BaseHTTPRequestHandler shim."""
    if not is_auth_enabled():
        return CurrentUser.legacy_admin()
    session_cred = resolve_session_credential_from_handler(handler)
    if not session_cred:
        return None
    if not is_multi_user_enabled():
        return CurrentUser.legacy_admin()
    from app.domain.auth import get_session_info
    from app.domain.users import get_user

    info = get_session_info(session_cred)
    if not info:
        return None
    user_id = str(info.get("user_id") or "legacy")
    role = str(info.get("role") or "admin")
    if user_id == "legacy":
        return CurrentUser.legacy_admin()
    record = get_user(user_id)
    if record is not None:
        return CurrentUser(
            user_id=record.username,
            role=record.role,
            profile_name=record.profile_name,
        )
    return CurrentUser(user_id=user_id, role=role, profile_name=None)


def user_can_access_profile(user: CurrentUser | None, profile_name: str) -> bool:
    """Admins may access any profile; scoped users only their bound profile."""
    from app.domain.roles import role_requires_profile

    if user is None:
        return False
    if not role_requires_profile(user.role):
        return True
    if not profile_name:
        return False
    if user.profile_name == profile_name:
        return True
    return profile_name in user.profile_names


def resolve_effective_profile(
    user: CurrentUser | None,
    requested_profile: str | None,
) -> str | None:
    """Apply profile restrictions for profile-scoped roles."""
    from app.domain.roles import role_requires_profile

    if user is None or not role_requires_profile(user.role):
        return requested_profile
    return user.profile_name


_SPA_SHELL_PREFIXES = (
    "/chat",
    "/settings",
    "/kanban",
    "/tasks",
    "/skills",
    "/terminal",
    "/memory",
    "/insights",
    "/logs",
    "/admin",
    "/onboarding",
    "/git",
    "/register",
)


def is_spa_shell_path(path: str) -> bool:
    """HashRouter client routes may be requested as pathnames; serve the SPA shell."""
    if path in ("/", "/index.html"):
        return True
    return any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in _SPA_SHELL_PREFIXES
    )


def spa_login_redirect_url(app_path: str) -> str:
    """Build a HashRouter login URL with a safe post-auth return path."""
    safe = (app_path or "/").strip() or "/"
    if not safe.startswith("/") or safe.startswith("//"):
        safe = "/"
    if safe.startswith("/#/"):
        safe = safe[2:] or "/"
    elif safe.startswith("/#"):
        safe = safe[2:] or "/"
    next_param = urllib.parse.quote(safe, safe="/")
    return f"/#/login?next={next_param}"


def is_public_path(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    try:
        from app.api.storage_proxy import is_supabase_storage_public_path

        if is_supabase_storage_public_path(path):
            return True
    except Exception:
        pass
    try:
        from app.document_api.integration import is_document_api_public_path

        if is_document_api_public_path(path):
            return True
    except Exception:
        pass
    if is_spa_shell_path(path):
        return True
    if path.startswith("/static/") or path.startswith("/session/static/"):
        return True
    # Vite/React fingerprinted bundles must load on /login before a session exists.
    if path.startswith("/assets/") or path.startswith("/session/assets/"):
        return True
    return False


def is_csp_report_post(path: str, method: str) -> bool:
    from app.core.legacy_handler import map_legacy_path

    return map_legacy_path(path) == "/api/csp-report" and method == "POST"


def session_valid(request: Request) -> bool:
    return resolve_session_credential_from_request(request) is not None


def request_legacy_path(request: Request) -> str:
    from app.core.legacy_handler import map_legacy_path

    return map_legacy_path(request.url.path)


def check_auth_request(request: Request) -> Response | None:
    """Return a Response when the request is denied; None when allowed."""
    from starlette.responses import JSONResponse, RedirectResponse

    if not is_auth_enabled():
        return None

    raw_path = request.url.path
    try:
        from app.api.storage_proxy import is_supabase_storage_public_path

        if is_supabase_storage_public_path(raw_path):
            return None
    except Exception:
        pass
    try:
        from app.document_api.integration import is_document_api_public_path

        if is_document_api_public_path(raw_path):
            return None
    except Exception:
        pass

    try:
        from app.document_api.mcp_integration import is_mcp_mount_path
        from app.document_api.mcp_auth import mcp_mount_requires_bearer, resolve_authenticated_user_for_mcp

        if is_mcp_mount_path(raw_path):
            if not mcp_mount_requires_bearer():
                return None
            if resolve_authenticated_user_for_mcp(request) is None:
                return JSONResponse(
                    {
                        "error": (
                            "Authentication required — send "
                            "Authorization: Bearer <MCP_API_KEY or user MCP key>"
                        )
                    },
                    status_code=401,
                )
            return None
    except Exception:
        pass

    path = request_legacy_path(request)
    if is_public_path(path):
        return None
    if session_valid(request):
        return None
    if get_current_user(request) is not None:
        return None

    if path.startswith("/api/"):
        return JSONResponse(
            {"error": "Authentication required"},
            status_code=401,
        )

    path_with_query = path or "/"
    if request.url.query:
        path_with_query += "?" + request.url.query
    return RedirectResponse(
        url=spa_login_redirect_url(path_with_query),
        status_code=302,
    )


def check_auth_legacy(handler, parsed) -> bool:
    """Delegate to api.auth.check_auth for the legacy handler adapter."""
    return check_auth(handler, parsed)


__all__ = [
    "AGENT_SOUL_FORBIDDEN_DETAIL",
    "INSIGHTS_FORBIDDEN_DETAIL",
    "INSIGHTS_LOGS_FORBIDDEN_DETAIL",
    "LOGS_FORBIDDEN_DETAIL",
    "PROFILES_MANAGE_FORBIDDEN_DETAIL",
    "ROLES_MANAGE_FORBIDDEN_DETAIL",
    "SETTINGS_SYSTEM_FORBIDDEN_DETAIL",
    "USERS_MANAGE_FORBIDDEN_DETAIL",
    "WORKSPACES_MANAGE_FORBIDDEN_DETAIL",
    "AgentSoulAccessError",
    "InsightsLogsAccessError",
    "CurrentUser",
    "check_auth",
    "check_auth_legacy",
    "check_auth_request",
    "ensure_agent_soul_access",
    "ensure_insights_access",
    "ensure_insights_logs_access",
    "ensure_logs_access",
    "filter_memory_payload_for_user",
    "get_current_user",
    "get_current_user_from_legacy_handler",
    "is_auth_enabled",
    "is_csp_report_post",
    "is_multi_user_enabled",
    "is_public_path",
    "parse_cookie",
    "require_admin",
    "require_insights_access",
    "require_logs_access",
    "require_roles_manage",
    "require_settings_system",
    "require_users_manage",
    "require_workspaces_manage",
    "require_permission",
    "resolve_user_permissions",
    "user_has_permission",
    "require_current_user",
    "resolve_effective_profile",
    "session_valid",
    "user_can_access_settings_system",
    "user_can_manage_profiles",
    "user_can_manage_roles",
    "user_can_manage_users",
    "user_can_manage_workspaces",
    "user_can_switch_all_profiles",
    "user_has_permission_for",
    "user_can_access_agent_soul",
    "user_can_access_insights",
    "user_can_access_insights_logs",
    "user_can_access_logs",
    "user_can_access_profile",
]
