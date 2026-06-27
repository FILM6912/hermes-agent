"""FastAPI dependency stubs for profile context and auth."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request

from app.core.security import (
    CurrentUser,
    get_current_user,
    require_admin,
    require_current_user,
    require_insights_access,
    require_logs_access,
    require_roles_manage,
    require_settings_system,
    require_users_manage,
    require_workspaces_manage,
)
from app.domain.helpers import get_profile_cookie
from app.domain.profiles import clear_request_profile, set_request_profile


def get_request_profile(request: Request) -> str | None:
    """Read active profile from cookie without mutating thread-local state."""
    class _HeaderShim:
        def __init__(self, headers: Any) -> None:
            self.headers = headers

    shim = _HeaderShim(request.headers)
    return get_profile_cookie(shim)


async def profile_context(request: Request) -> str | None:
    """Depends stub: set per-request profile for downstream legacy/services."""
    profile = get_request_profile(request)
    if profile:
        set_request_profile(profile)
    try:
        yield profile
    finally:
        clear_request_profile()


ProfileContext = Annotated[str | None, Depends(profile_context)]


async def require_auth(request: Request) -> None:
    """Depends stub: enforce auth (middleware handles requests today)."""
    from app.core.security import check_auth_request

    denied = check_auth_request(request)
    if denied is not None:
        raise _AuthRequired(denied)


async def current_user(request: Request) -> CurrentUser:
    """Depends: return authenticated user or raise 401."""
    return require_current_user(request)


async def admin_user(request: Request) -> CurrentUser:
    """Depends: return authenticated admin or raise 401/403."""
    return require_admin(request)


async def insights_reader(request: Request) -> CurrentUser:
    """Depends: return user with insights:read (or admin override)."""
    return require_insights_access(request)


async def logs_reader(request: Request) -> CurrentUser:
    """Depends: return user with logs:read (or admin override)."""
    return require_logs_access(request)


async def workspaces_manager(request: Request) -> CurrentUser:
    return require_workspaces_manage(request)


async def users_manager(request: Request) -> CurrentUser:
    return require_users_manage(request)


async def roles_manager(request: Request) -> CurrentUser:
    return require_roles_manage(request)


async def settings_system_operator(request: Request) -> CurrentUser:
    return require_settings_system(request)


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]
AdminUserDep = Annotated[CurrentUser, Depends(admin_user)]
InsightsReaderDep = Annotated[CurrentUser, Depends(insights_reader)]
LogsReaderDep = Annotated[CurrentUser, Depends(logs_reader)]
WorkspacesManageDep = Annotated[CurrentUser, Depends(workspaces_manager)]
UsersManageDep = Annotated[CurrentUser, Depends(users_manager)]
RolesManageDep = Annotated[CurrentUser, Depends(roles_manager)]
SettingsSystemDep = Annotated[CurrentUser, Depends(settings_system_operator)]


class _AuthRequired(Exception):
    def __init__(self, response) -> None:
        self.response = response


__all__ = [
    "AdminUserDep",
    "CurrentUserDep",
    "InsightsReaderDep",
    "LogsReaderDep",
    "RolesManageDep",
    "SettingsSystemDep",
    "UsersManageDep",
    "WorkspacesManageDep",
    "ProfileContext",
    "admin_user",
    "current_user",
    "get_request_profile",
    "insights_reader",
    "logs_reader",
    "profile_context",
    "require_auth",
    "roles_manager",
    "settings_system_operator",
    "users_manager",
    "workspaces_manager",
]
