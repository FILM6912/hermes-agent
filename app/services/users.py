"""Users service — admin CRUD and bootstrap helpers."""

from __future__ import annotations

import logging
from typing import Any

from app.domain.users import UserError, UserNotFoundError
from app.repositories.sessions import SessionRepository
from app.repositories.users import UsersRepository

logger = logging.getLogger(__name__)


def _default_profile_name_for_user(email: str) -> str:
    """Return the canonical profile name for a new regular user account."""
    from app.domain.users import profile_name_from_email

    return profile_name_from_email(email)


def _profile_exists(profile_name: str) -> bool:
    from app.domain.profiles import list_profiles_api

    return any(row.get("name") == profile_name for row in list_profiles_api())


def provision_user_profile(profile_name: str, *, owner_email: str | None = None) -> None:
    """Ensure agent profile dirs exist; workspace is keyed by *owner_email* when set."""
    from app.domain.profiles import (
        _is_root_profile,
        _validate_profile_name,
        create_profile_api,
        get_hermes_home_for_profile,
    )
    from app.domain.users import UserAccess
    from app.domain.workspace import (
        clear_request_user_access,
        ensure_profile_workspace,
        ensure_profile_workspace_exists,
        profile_workspace_dir,
        set_request_user_access,
    )

    cleaned = str(profile_name or "").strip()
    if not cleaned:
        raise UserError("profile_name is required for user role")
    if _is_root_profile(cleaned):
        raise UserError(
            "The built-in default profile cannot be provisioned for user accounts"
        )
    _validate_profile_name(cleaned)

    if not _profile_exists(cleaned):
        try:
            create_profile_api(cleaned)
        except ValueError as exc:
            raise UserError(str(exc)) from exc

    profile_home = get_hermes_home_for_profile(cleaned)
    access = None
    access_token = None
    owner = str(owner_email or "").strip().lower()
    if owner:
        access = UserAccess(
            multi_user_enabled=True,
            user_id=owner,
            username=owner,
            role="user",
            profile_name=cleaned,
            profile_names=(cleaned,),
        )
        access_token = set_request_user_access(access)
    try:
        ensure_profile_workspace(profile_home, name=cleaned, access=access)
        workspace_dir = profile_workspace_dir(profile_home, access=access)
        if not workspace_dir.is_dir():
            ensure_profile_workspace_exists(workspace_dir)
        if not workspace_dir.is_dir():
            raise UserError(f"failed to create workspace for profile {cleaned!r}")
    finally:
        if access_token is not None:
            clear_request_user_access(access_token)


class UserService:
    def __init__(
        self,
        repository: UsersRepository | None = None,
        session_repository: SessionRepository | None = None,
    ) -> None:
        self._repo = repository or UsersRepository()
        self._sessions = session_repository or SessionRepository()

    def list_users(self) -> list[dict[str, Any]]:
        return self._repo.list_users()

    def get_user_detail(self, email: str) -> dict[str, Any]:
        user = self._repo.get_user(email)
        if user is None:
            raise UserNotFoundError(f"user {email!r} not found")
        profile = None
        names = user.get("profile_names") or []
        primary = user.get("profile_name")
        if primary:
            profile = {"name": primary}
        elif names:
            profile = {"name": names[0]}
        else:
            profile = None
        session_total = 0
        session_active = 0
        session_archived = 0
        session_summary = self._session_summary_for_user(user)
        session_total = session_summary["total"]
        session_active = session_summary["active"]
        session_archived = session_summary["archived"]
        workspace_path = None
        workspaces: list[dict[str, str]] = []
        available_workspaces: list[dict[str, str]] = []
        assigned_profiles: list[dict[str, str]] = []
        if user.get("role") == "user":
            from app.domain.workspace import (
                account_workspace_display_for_user,
                account_workspaces_for_user,
                assigned_profiles_for_user,
                discover_assignable_workspaces_for_user,
            )

            role_value = str(user["role"])
            names = list(user.get("profile_names") or [])
            primary = str(user.get("profile_name") or "").strip() or None
            available_workspaces = discover_assignable_workspaces_for_user(
                email,
                role_value,
                names,
                primary_profile_name=primary,
            )
            workspaces = account_workspaces_for_user(
                email,
                role_value,
                names,
                primary_profile_name=primary,
            )
            assigned_profiles = assigned_profiles_for_user(names)
            workspace_path = (
                workspaces[0]["path"]
                if workspaces
                else account_workspace_display_for_user(email, role_value)
            )
        return {
            **{k: v for k, v in user.items() if k != "password_hash"},
            "workspace_path": workspace_path,
            "workspaces": workspaces,
            "available_workspaces": available_workspaces,
            "assigned_profiles": assigned_profiles,
            "profile": profile,
            "session_summary": {
                "total": session_total,
                "active": session_active,
                "archived": session_archived,
            },
        }

    def create_user(
        self,
        email: str,
        *,
        password: str,
        role: str = "user",
        profile_name: str | None = None,
        profile_names: list[str] | None = None,
        display_name: str | None = None,
        department: str | None = None,
        position: str | None = None,
    ) -> dict[str, Any]:
        cleaned_email = str(email or "").strip().lower()
        role_value = str(role or "user").strip().lower()
        resolved_profile = str(profile_name).strip() if profile_name else None
        if resolved_profile == "":
            resolved_profile = None
        resolved_names: list[str] = []
        if role_value == "user":
            if not resolved_profile:
                resolved_profile = _default_profile_name_for_user(cleaned_email)
            from app.domain.users import _normalize_profile_name_list

            resolved_names = _normalize_profile_name_list(profile_names, resolved_profile)
            resolved_profile = resolved_names[0] if resolved_names else resolved_profile
            for pname in resolved_names:
                provision_user_profile(pname, owner_email=cleaned_email)
            from app.domain.workspace import sync_assigned_profile_workspaces_into_account

            sync_assigned_profile_workspaces_into_account(
                cleaned_email,
                resolved_names,
                primary_profile_name=resolved_profile,
            )
        elif role_value == "admin":
            admin_profile = _default_profile_name_for_user(cleaned_email)
            provision_user_profile(admin_profile, owner_email=cleaned_email)
            from app.domain.workspace import sync_assigned_profile_workspaces_into_account

            sync_assigned_profile_workspaces_into_account(
                cleaned_email,
                [admin_profile],
                primary_profile_name=admin_profile,
            )
        created = self._repo.create_user(
            cleaned_email,
            role=role_value,
            profile_name=resolved_profile,
            profile_names=resolved_names if role_value == "user" else None,
            display_name=display_name,
            department=department,
            position=position,
            password=password,
        )
        created.pop("password_hash", None)
        return created

    def update_user(
        self,
        email: str,
        *,
        new_email: str | None = None,
        role: str | None = None,
        profile_name: str | None = None,
        profile_names: list[str] | None = None,
        password: str | None = None,
        display_name: str | None = None,
        department: str | None = None,
        position: str | None = None,
        enabled: bool | None = None,
        workspace_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        before = self._repo.get_user(email)
        old_names = self._assigned_profile_names(before)
        if profile_names is not None:
            for pname in profile_names:
                cleaned = str(pname or "").strip()
                if cleaned:
                    provision_user_profile(cleaned, owner_email=email)
        elif profile_name:
            provision_user_profile(str(profile_name).strip(), owner_email=email)
        updated = self._repo.update_user(
            email,
            new_email=new_email,
            role=role,
            profile_name=profile_name,
            profile_names=profile_names,
            password=password,
            display_name=display_name,
            department=department,
            position=position,
            enabled=enabled,
        )
        updated.pop("password_hash", None)
        account_email = str(updated.get("email") or email).strip().lower()
        if str(updated.get("role") or "").strip().lower() == "user":
            from app.domain.workspace import (
                set_account_workspace_paths_for_user,
                sync_assigned_profile_workspaces_into_account,
            )

            assigned = self._assigned_profile_names(updated)
            primary = str(updated.get("profile_name") or "").strip() or None
            if workspace_paths is not None:
                try:
                    set_account_workspace_paths_for_user(
                        account_email,
                        workspace_paths,
                        assigned,
                        primary_profile_name=primary,
                    )
                except ValueError as exc:
                    raise UserError(str(exc)) from exc
            elif assigned:
                sync_assigned_profile_workspaces_into_account(
                    account_email,
                    assigned,
                    primary_profile_name=primary,
                )
        self._cleanup_profiles_unassigned_from_user(
            before=before,
            updated=updated,
            profile_names_sent=profile_names,
            role_sent=role,
            old_names=old_names,
        )
        return updated

    @staticmethod
    def _assigned_profile_names(user: dict[str, Any] | None) -> list[str]:
        if not user:
            return []
        names = list(user.get("profile_names") or [])
        primary = str(user.get("profile_name") or "").strip()
        if primary and primary not in names:
            names.insert(0, primary)
        return names

    def _cleanup_profiles_unassigned_from_user(
        self,
        *,
        before: dict[str, Any] | None,
        updated: dict[str, Any],
        profile_names_sent: list[str] | None,
        role_sent: str | None,
        old_names: list[str],
    ) -> None:
        from app.domain.users import profiles_orphaned_after_unassign

        if before is None:
            return
        removed: list[str] = []
        if role_sent == "admin" and str(before.get("role") or "") == "user":
            removed = old_names
        elif profile_names_sent is not None:
            new_names = list(updated.get("profile_names") or [])
            removed = [p for p in old_names if p not in set(new_names)]
        if not removed:
            return
        for pname in profiles_orphaned_after_unassign(removed):
            self._delete_bound_profile(pname)

    def get_account_profile(self, user_id: str) -> dict[str, Any]:
        from app.domain.users import LEGACY_ADMIN_USER_ID, get_user, is_multi_user_enabled

        multi_user = is_multi_user_enabled()
        if not multi_user or user_id == LEGACY_ADMIN_USER_ID:
            return {
                "email": None,
                "display_name": "Administrator",
                "department": None,
                "position": None,
                "role": "admin",
                "profile_name": None,
                "multi_user": False,
            }
        record = get_user(user_id)
        if record is None:
            raise UserNotFoundError(f"user {user_id!r} not found")
        return {
            "email": record.email,
            "display_name": record.display_name,
            "department": record.department,
            "position": record.position,
            "role": record.role,
            "profile_name": record.profile_name,
            "profile_names": list(record.assigned_profile_names()),
            "multi_user": True,
        }

    def get_auth_me(self, user_id: str, *, role: str) -> dict[str, Any]:
        """Return GET /api/v1/auth/me payload for external auth proxies (e.g. Corp Brain)."""
        from app.domain.roles import resolve_role_permissions
        from app.domain.users import LEGACY_ADMIN_USER_ID, get_user, is_multi_user_enabled

        if not is_multi_user_enabled() or user_id == LEGACY_ADMIN_USER_ID:
            return {
                "id": user_id or LEGACY_ADMIN_USER_ID,
                "email": "",
                "display_name": "Administrator",
                "enabled": True,
                "role": "admin",
                "roles": ["admin"],
                "permissions": {"*": True},
            }

        record = get_user(user_id)
        if record is None:
            raise UserNotFoundError(f"user {user_id!r} not found")

        email = record.email
        resolved_role = record.role or role
        return {
            "id": email,
            "email": email,
            "display_name": record.display_name or "",
            "enabled": record.enabled,
            "role": resolved_role,
            "roles": [resolved_role],
            "permissions": resolve_role_permissions(resolved_role),
            "department": record.department,
            "position": record.position,
            "profile_name": record.profile_name,
            "profile_names": list(record.assigned_profile_names()),
        }

    def update_account_profile(self, user_id: str, *, display_name: str | None) -> dict[str, Any]:
        from app.domain.users import LEGACY_ADMIN_USER_ID, is_multi_user_enabled

        if not is_multi_user_enabled() or user_id == LEGACY_ADMIN_USER_ID:
            raise UserError("Account profile is read-only in single-user mode")
        updated = self.update_user(user_id, display_name=display_name or "")
        return {
            "email": updated.get("email"),
            "display_name": updated.get("display_name"),
            "department": updated.get("department"),
            "position": updated.get("position"),
            "role": updated.get("role"),
            "profile_name": updated.get("profile_name"),
            "multi_user": True,
        }

    def delete_user(self, email: str) -> None:
        """Delete the account and remove exclusively bound profiles/workspaces."""
        from app.domain.users import cascade_profile_names_for_user_delete

        from app.domain.workspace import delete_user_account_workspace

        cascade_profiles = cascade_profile_names_for_user_delete(email)
        self._repo.delete_user(email)
        delete_user_account_workspace(email)
        for cascade_profile in cascade_profiles:
            self._delete_bound_profile(cascade_profile)

    def _delete_bound_profile(self, profile_name: str) -> None:
        """Remove Hermes profile dir, workspace, and workspaces.json for *profile_name*."""
        from app.domain.profiles import delete_profile_api, get_hermes_home_for_profile
        from app.domain.workspace import clear_profile_workspaces_registry

        profile_home = get_hermes_home_for_profile(profile_name)
        try:
            clear_profile_workspaces_registry(profile_home)
        except Exception:
            logger.warning(
                "Failed to clear workspaces registry for profile %s",
                profile_name,
                exc_info=True,
            )
        try:
            delete_profile_api(profile_name)
        except Exception:
            logger.warning(
                "Failed to delete Hermes profile %s after user removal",
                profile_name,
                exc_info=True,
            )

    def _session_summary_for_user(self, user: dict[str, Any]) -> dict[str, int]:
        from app.storage.config import supabase_storage_enabled

        email = str(user.get("email") or user.get("id") or "").strip().lower()
        if supabase_storage_enabled() and email:
            try:
                from app.storage.repositories.chat_sessions import get_chat_sessions_repository

                sessions = get_chat_sessions_repository().list_for_user(email)
                total = len(sessions)
                archived = sum(1 for session in sessions if session.get("archived"))
                return {"total": total, "active": total - archived, "archived": archived}
            except Exception:
                logger.debug(
                    "Failed to load session summary from webui_sessions for %s",
                    email,
                    exc_info=True,
                )

        session_total = 0
        session_active = 0
        session_archived = 0
        names = user.get("profile_names") or []
        primary = user.get("profile_name")
        for pname in names or ([primary] if primary else []):
            summary = self._session_summary_for_profile(pname)
            session_total += summary["total"]
            session_active += summary["active"]
            session_archived += summary["archived"]
        return {
            "total": session_total,
            "active": session_active,
            "archived": session_archived,
        }

    def _session_summary_for_profile(self, profile_name: str | None) -> dict[str, int]:
        if not profile_name:
            return {"total": 0, "active": 0, "archived": 0}
        total = active = archived = 0
        for session in self._sessions.list_sessions():
            if session.get("profile") != profile_name:
                continue
            total += 1
            if session.get("archived"):
                archived += 1
            else:
                active += 1
        return {"total": total, "active": active, "archived": archived}

    def bootstrap_default_admin(self) -> dict[str, Any] | None:
        return self._repo.bootstrap_default_admin()

    def promote_install(
        self,
        *,
        admin_email: str | None = None,
        admin_password: str | None = None,
        current_password: str | None = None,
    ) -> tuple[dict[str, Any], int]:
        result = self._repo.promote_install_to_multi_user(
            admin_email=admin_email,
            admin_password=admin_password,
            current_password=current_password,
        )
        status = result.get("status")
        if status == "created":
            return result, 201
        if status == "skipped":
            return result, 409
        return result, 400


class UsersService(UserService):
    """Compatibility alias for bootstrap-focused imports."""

    pass
