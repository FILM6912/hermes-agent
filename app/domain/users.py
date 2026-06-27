"""WebUI multi-user account storage and helpers."""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.domain.auth import (
    COOKIE_NAME,
    _hash_password,
    _session_token_from_cookie_value,
    get_session_entry,
    resolve_session_credential_from_request,
    verify_session,
)
from app.domain.config import STATE_DIR

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)

LEGACY_ADMIN_USER_ID = "legacy"
USERS_FILE = STATE_DIR / "users.json"
_SESSION_USERS_FILE = STATE_DIR / ".session_users.json"

_users_cache: dict[str, Any] | None = None
_users_cache_lock = threading.Lock()

_USERNAME_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]{2,31}$")
_EMAIL_RE = re.compile(
    r"^[a-z0-9._%+-]+@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$|"
    r"^[a-z0-9._%+-]+@localhost$",
)


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_username(value: str) -> str:
    """Backward-compatible alias for account key normalization."""
    return normalize_email(value)


def validate_email_format(value: str) -> str:
    """Require a normalized email address for new accounts and renames."""
    cleaned = normalize_email(value)
    if not cleaned:
        raise UserError("email is required")
    if not _EMAIL_RE.match(cleaned):
        raise UserError("Invalid email address")
    return cleaned


def validate_username_format(value: str) -> str:
    """Legacy alias — prefer validate_email_format for new code."""
    return validate_email_format(value)


def _is_legacy_slug_identifier(value: str) -> bool:
    cleaned = normalize_email(value)
    return bool(cleaned and _USERNAME_SLUG_RE.match(cleaned) and "@" not in cleaned)


def profile_name_from_email(email: str) -> str:
    """Derive a valid Hermes profile id from an email (or legacy slug key)."""
    cleaned = normalize_email(email)
    if "@" in cleaned:
        local = cleaned.split("@", 1)[0]
        slug = re.sub(r"[^a-z0-9_-]", "-", local).strip("-")
        slug = re.sub(r"-{2,}", "-", slug)
        if not slug:
            slug = "user"
        if not slug[0].isalpha():
            slug = f"u{slug}"
        return slug[:64]
    return cleaned


def profile_name_from_username(username: str) -> str:
    return profile_name_from_email(username)


def _row_email(row: dict[str, Any]) -> str:
    return str(row.get("email") or row.get("username") or "").strip().lower()


def _optional_org_field(row: dict[str, Any], key: str) -> str | None:
    value = str(row.get(key) or "").strip()
    return value or None


def _user_department_ref(row: dict[str, Any]) -> str | None:
    from app.domain.departments import normalize_department_ref

    dept_id = _optional_org_field(row, "department_id")
    if dept_id:
        return normalize_department_ref(dept_id)
    return normalize_department_ref(_optional_org_field(row, "department"))


def _apply_department_fields(row: dict[str, Any], department: str | None) -> None:
    cleaned = str(department).strip().lower() if department else None
    if cleaned == "":
        cleaned = None
    row["department"] = cleaned
    row["department_id"] = cleaned


class UserError(ValueError):
    """Raised when a user record violates storage invariants."""


class UserNotFoundError(UserError):
    """Raised when a username is not present in the users store."""


@dataclass(frozen=True)
class UserRecord:
    email: str
    role: str
    profile_name: str | None
    profile_names: tuple[str, ...] = ()
    display_name: str | None = None
    department: str | None = None
    position: str | None = None
    password_hash: str | None = None
    enabled: bool = True
    created_at: float | None = None

    @property
    def username(self) -> str:
        """Legacy alias — account key is the normalized email."""
        return self.email

    def assigned_profile_names(self) -> tuple[str, ...]:
        """Hermes profiles this account may use (default is profile_name)."""
        if self.profile_names:
            return self.profile_names
        if self.profile_name:
            return (self.profile_name,)
        return ()


@dataclass(frozen=True)
class UserAccess:
    """Resolved profile-access policy for the current request."""

    multi_user_enabled: bool
    user_id: str | None = None
    username: str | None = None
    role: str = "admin"
    profile_name: str | None = None
    profile_names: tuple[str, ...] = ()
    department: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"
    @property
    def restricts_profiles(self) -> bool:
        from app.domain.roles import role_requires_profile

        return self.multi_user_enabled and role_requires_profile(self.role)

    def allowed_profile_names(self) -> tuple[str, ...]:
        if not self.multi_user_enabled or self.role == "admin":
            return ()
        if self.profile_names:
            return self.profile_names
        if self.profile_name:
            return (self.profile_name,)
        return ("default",)

def legacy_user_access() -> UserAccess:
    return UserAccess(multi_user_enabled=False)


def invalidate_users_cache() -> None:
    global _users_cache
    with _users_cache_lock:
        _users_cache = None


def users_file_exists() -> bool:
    try:
        from app.storage.repositories.users import get_users_repository

        repo = get_users_repository()
        if repo.has_users():
            return True
        if not _use_supabase_store():
            if repo.maybe_migrate_legacy(json_path=USERS_FILE):
                return True
            return USERS_FILE.is_file()
    except Exception:
        logger.debug("WebUI DB users probe failed; checking users.json", exc_info=True)
        if not _use_supabase_store():
            return USERS_FILE.is_file()
    return False


def is_multi_user_enabled() -> bool:
    env = os.getenv("HERMES_WEBUI_MULTI_USER", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    return users_file_exists()


def is_multi_user_mode() -> bool:
    return is_multi_user_enabled()


def legacy_admin_user() -> UserRecord:
    return UserRecord(
        email=LEGACY_ADMIN_USER_ID,
        role="admin",
        profile_name=None,
    )


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "users": {}, "profile_bindings": {}}


def _is_valid_account_email(value: str) -> bool:
    cleaned = normalize_email(value)
    return bool(cleaned and _EMAIL_RE.match(cleaned))


def _sanitize_users_store(store: dict[str, Any]) -> bool:
    """Drop corrupt user rows (e.g. empty dict keys from lost email) and repair legacy rows."""
    raw_users = store.get("users")
    if not isinstance(raw_users, dict):
        store["users"] = {}
        store["profile_bindings"] = {}
        return True

    bindings = store.get("profile_bindings")
    if not isinstance(bindings, dict):
        bindings = {}
        store["profile_bindings"] = bindings

    cleaned_users: dict[str, Any] = {}
    changed = False

    for account_key, row in raw_users.items():
        if not isinstance(row, dict):
            changed = True
            continue

        norm_key = normalize_email(account_key)
        resolved = _row_email(row) or norm_key
        if not _is_valid_account_email(resolved):
            logger.warning(
                "Removing corrupt user store entry (account_key=%r, resolved=%r)",
                account_key,
                resolved,
            )
            changed = True
            continue

        repaired = dict(row)
        repaired.pop("username", None)
        if repaired.get("email") != resolved:
            repaired["email"] = resolved
            changed = True

        if resolved in cleaned_users:
            logger.warning(
                "Removing duplicate user store entry for %r (account_key=%r)",
                resolved,
                account_key,
            )
            changed = True
            continue

        if norm_key != resolved or account_key != resolved:
            changed = True
        cleaned_users[resolved] = repaired

    if cleaned_users != raw_users:
        changed = True

    valid_accounts = set(cleaned_users.keys())
    for profile_name, bound_user in list(bindings.items()):
        bound = normalize_email(bound_user)
        if not bound or bound not in valid_accounts:
            bindings.pop(profile_name, None)
            changed = True

    store["users"] = cleaned_users
    store["profile_bindings"] = bindings
    return changed


def _use_supabase_store() -> bool:
    try:
        from app.storage.config import supabase_storage_enabled

        return supabase_storage_enabled()
    except Exception:
        return False


def _load_store_unlocked() -> dict[str, Any]:
    global _users_cache
    use_supabase = _use_supabase_store()
    if _users_cache is not None and not use_supabase:
        return _users_cache
    raw: Any | None = None
    try:
        from app.storage.repositories.users import get_users_repository

        repo = get_users_repository()
        repo.maybe_migrate_legacy(json_path=USERS_FILE)
        raw = repo.load_store()
    except Exception:
        logger.debug("Failed to read users store from WebUI DB tables", exc_info=True)
        raw = None
        try:
            from app.storage.config import supabase_storage_enabled
            from app.storage.repositories.users import get_users_repository

            if supabase_storage_enabled():
                repo = get_users_repository()
                rows = repo.list_all()
                if rows:
                    updated_at = 0.0
                    users_map = {row["email"]: row for row in rows if row.get("email")}
                    for row in users_map.values():
                        ts = float(row.get("updated_at") or row.get("created_at") or 0.0)
                        updated_at = max(updated_at, ts)
                    raw = {
                        "version": 1,
                        "updated_at": updated_at or time.time(),
                        "users": users_map,
                        "profile_bindings": {},
                    }
        except Exception:
            logger.debug("Supabase users fallback load failed", exc_info=True)
    if raw is None and USERS_FILE.is_file() and not use_supabase:
        try:
            raw = json.loads(USERS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                try:
                    from app.storage.repositories.users import get_users_repository

                    repo = get_users_repository()
                    repo.import_legacy_document(
                        raw,
                        json_path=USERS_FILE,
                    )
                    raw = repo.load_store()
                except Exception:
                    logger.debug(
                        "Failed to import users.json into webui_users",
                        exc_info=True,
                    )
        except Exception:
            logger.debug("Failed to read users store from JSON", exc_info=True)
    if raw is None:
        _users_cache = _empty_store()
        return _users_cache
    if not isinstance(raw, dict):
        _users_cache = _empty_store()
        return _users_cache
    users = raw.get("users")
    bindings = raw.get("profile_bindings")
    store_payload = {
        "version": raw.get("version", 1),
        "updated_at": raw.get("updated_at"),
        "users": users if isinstance(users, dict) else {},
        "profile_bindings": bindings if isinstance(bindings, dict) else {},
    }
    if _sanitize_users_store(store_payload):
        _save_store_unlocked(store_payload)
    if use_supabase:
        return store_payload
    _users_cache = store_payload
    return _users_cache


def _load_store() -> dict[str, Any]:
    with _users_cache_lock:
        store = _load_store_unlocked()
        return {
            "version": store.get("version", 1),
            "updated_at": store.get("updated_at"),
            "users": dict(store.get("users") or {}),
            "profile_bindings": dict(store.get("profile_bindings") or {}),
        }


def _save_store_unlocked(store: dict[str, Any]) -> None:
    global _users_cache
    payload = {
        "version": store.get("version", 1),
        "updated_at": time.time(),
        "users": dict(store.get("users") or {}),
        "profile_bindings": dict(store.get("profile_bindings") or {}),
    }
    try:
        from app.storage.repositories.users import get_users_repository

        get_users_repository().save_store(payload, json_path=USERS_FILE)
    except Exception:
        logger.debug("WebUI DB users save failed; using JSON fallback", exc_info=True)
        try:
            from app.storage.config import supabase_storage_enabled

            if not supabase_storage_enabled():
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=STATE_DIR, suffix=".users.tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(payload, handle, indent=2, sort_keys=True)
                        handle.write("\n")
                    Path(tmp).chmod(0o600)
                    Path(tmp).replace(USERS_FILE)
                except Exception:
                    try:
                        Path(tmp).unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise
        except Exception:
            logger.debug("JSON fallback save for users store failed", exc_info=True)
            raise
    _users_cache = payload if not _use_supabase_store() else None


def _save_store(store: dict[str, Any]) -> None:
    with _users_cache_lock:
        _save_store_unlocked(store)


def _public_user(row: dict[str, Any]) -> dict[str, Any]:
    display_name = str(row.get("display_name") or "").strip() or None
    names = profile_names_from_row(row)
    primary = primary_profile_from_row(row)
    email = _row_email(row)
    role = str(row["role"])
    workspace_path = None
    workspaces: list[dict[str, str]] = []
    assigned_profiles: list[dict[str, str]] = []
    from app.domain.roles import role_requires_profile

    if role_requires_profile(role):
        from app.domain.workspace import (
            account_workspace_display_for_user,
            account_workspaces_for_user,
            assigned_profiles_for_user,
        )

        workspaces = account_workspaces_for_user(
            email,
            role,
            names,
            primary_profile_name=primary,
        )
        assigned_profiles = assigned_profiles_for_user(names)
        workspace_path = (
            workspaces[0]["path"]
            if workspaces
            else account_workspace_display_for_user(email, role)
        )
    return {
        "email": email,
        "role": role,
        "profile_name": primary,
        "profile_names": names,
        "display_name": display_name,
        "department": _user_department_ref(row),
        "position": _optional_org_field(row, "position"),
        "workspace_path": workspace_path,
        "workspaces": workspaces,
        "assigned_profiles": assigned_profiles,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "created_by": _optional_org_field(row, "created_by"),
        "updated_by": _optional_org_field(row, "updated_by"),
        "enabled": bool(row.get("enabled", True)),
        "has_mcp_api_key": bool(str(row.get("mcp_api_key_hash") or "").strip()),
        "password_hash": row.get("password_hash"),
    }


def _record_from_row(row: dict[str, Any]) -> UserRecord:
    display_name = str(row.get("display_name") or "").strip() or None
    names = tuple(profile_names_from_row(row))
    primary = primary_profile_from_row(row)
    return UserRecord(
        email=_row_email(row),
        role=str(row["role"]),
        profile_name=primary,
        profile_names=names,
        display_name=display_name,
        department=_user_department_ref(row),
        position=_optional_org_field(row, "position"),
        password_hash=row.get("password_hash"),
        enabled=bool(row.get("enabled", True)),
        created_at=row.get("created_at"),
    )


def _normalize_profile_name_list(
    profile_names: list[str] | None,
    primary: str | None,
) -> list[str]:
    """Dedupe profile ids; ensure *primary* is first when provided."""
    ordered: list[str] = []
    for raw in profile_names or []:
        name = str(raw or "").strip()
        if name and name not in ordered:
            ordered.append(name)
    primary_clean = str(primary or "").strip()
    if primary_clean:
        if primary_clean in ordered:
            ordered = [primary_clean] + [n for n in ordered if n != primary_clean]
        else:
            ordered = [primary_clean, *ordered]
    return ordered


def profile_names_from_row(row: dict[str, Any]) -> list[str]:
    raw = row.get("profile_names")
    names: list[str] = []
    if isinstance(raw, list):
        names = _normalize_profile_name_list(raw, row.get("profile_name"))
    elif row.get("profile_name"):
        names = _normalize_profile_name_list(None, row.get("profile_name"))
    return names


def primary_profile_from_row(row: dict[str, Any]) -> str | None:
    names = profile_names_from_row(row)
    explicit = str(row.get("profile_name") or "").strip()
    if explicit:
        return explicit
    return names[0] if names else None


def _validate_role_profile(
    role: str,
    profile_name: str | None,
    profile_names: list[str] | None = None,
) -> None:
    from app.domain.roles import RoleNotFoundError, get_role, role_requires_profile

    try:
        get_role(role)
    except RoleNotFoundError as exc:
        raise UserError(f"unknown role {role!r}") from exc

    names = _normalize_profile_name_list(profile_names, profile_name)
    if role_requires_profile(role) and not names:
        raise UserError(f"role={role} accounts require at least one profile")
    if role_requires_profile(role):
        try:
            from app.domain.profiles import _is_root_profile

            for pname in names:
                if _is_root_profile(pname):
                    raise UserError(
                        "The built-in default profile cannot be assigned to user accounts"
                    )
        except ImportError:
            if "default" in names:
                raise UserError(
                    "The built-in default profile cannot be assigned to user accounts"
                )
    if not role_requires_profile(role) and (profile_name or names):
        raise UserError(f"role={role} accounts must not have profile bindings")


def _validate_department_field(department: str | None) -> None:
    from app.domain.departments import department_exists, normalize_department_ref

    cleaned = normalize_department_ref(department)
    if cleaned and not department_exists(cleaned):
        raise UserError(f"unknown department {cleaned!r}")


def _sync_profile_bindings_for_user(
    store: dict[str, Any],
    email: str,
    profile_names: list[str],
) -> None:
    bindings = store["profile_bindings"]
    target = set(profile_names)
    for pname, bound in list(bindings.items()):
        if bound == email and pname not in target:
            bindings.pop(pname, None)
    for pname in profile_names:
        _assert_profile_available(store, pname, except_username=email)
        bindings[pname] = email


def user_may_access_profile(profile_name: str, user: UserRecord | None) -> bool:
    if user is None or user.role == "admin":
        return True
    from app.domain.profiles import _profiles_match

    for allowed in user.assigned_profile_names():
        if _profiles_match(profile_name, allowed):
            return True
    return False


def _assert_profile_available(
    store: dict[str, Any],
    profile_name: str,
    *,
    except_username: str | None = None,
) -> None:
    bound_user = store.get("profile_bindings", {}).get(profile_name)
    if bound_user and bound_user != except_username:
        raise UserError(f"profile_name {profile_name!r} is already assigned to another user")


def _audit_actor() -> str:
    from app.storage.audit import actor_or_system

    return actor_or_system()


def get_user(email: str) -> UserRecord | None:
    key = normalize_email(email)
    row = _load_store().get("users", {}).get(key)
    if not isinstance(row, dict):
        return None
    return _record_from_row(row)


def get_user_public(email: str) -> dict[str, Any] | None:
    """Return the same public user dict as ``list_users()`` for one account."""
    key = normalize_email(email)
    row = _load_store().get("users", {}).get(key)
    if not isinstance(row, dict):
        return None
    public = _public_user(row)
    public.pop("password_hash", None)
    return public


def list_users() -> list[dict[str, Any]]:
    store = _load_store()
    result: list[dict[str, Any]] = []
    for account_key in sorted(store.get("users", {}).keys()):
        row = store["users"][account_key]
        if not isinstance(row, dict):
            continue
        public = _public_user(row)
        public.pop("password_hash", None)
        result.append(public)
    return result


def create_user(
    email: str,
    *,
    role: str = "user",
    profile_name: str | None = None,
    profile_names: list[str] | None = None,
    display_name: str | None = None,
    department: str | None = None,
    position: str | None = None,
    password_hash: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    from app.domain.roles import role_requires_profile

    cleaned_email = validate_email_format(email)
    role = str(role or "user").strip().lower()
    profile_name = str(profile_name).strip() if profile_name else None
    if profile_name == "":
        profile_name = None
    if role_requires_profile(role) and not profile_name and not profile_names:
        profile_name = profile_name_from_email(cleaned_email)
    resolved_names = (
        _normalize_profile_name_list(profile_names, profile_name)
        if role_requires_profile(role)
        else []
    )
    if role_requires_profile(role):
        profile_name = resolved_names[0] if resolved_names else None
    cleaned_display_name = str(display_name).strip() if display_name else None
    if cleaned_display_name == "":
        cleaned_display_name = None
    cleaned_department = str(department).strip().lower() if department else None
    if cleaned_department == "":
        cleaned_department = None
    _validate_department_field(cleaned_department)
    cleaned_position = str(position).strip() if position else None
    if cleaned_position == "":
        cleaned_position = None
    _validate_role_profile(role, profile_name, resolved_names)

    if password_hash is None and password:
        password_hash = _hash_password(password)
    if not password_hash:
        raise UserError("password or password_hash is required")

    with _users_cache_lock:
        cached = _load_store_unlocked()
        store = {
            "version": cached.get("version", 1),
            "updated_at": cached.get("updated_at"),
            "users": dict(cached.get("users") or {}),
            "profile_bindings": dict(cached.get("profile_bindings") or {}),
        }
        users = store["users"]
        bindings = store["profile_bindings"]
        if cleaned_email in users:
            raise UserError(f"email {cleaned_email!r} already exists")
        now = time.time()
        actor = _audit_actor()
        row = {
            "email": cleaned_email,
            "role": role,
            "profile_name": profile_name if role_requires_profile(role) else None,
            "profile_names": resolved_names if role_requires_profile(role) else [],
            "display_name": cleaned_display_name,
            "department": cleaned_department,
            "department_id": cleaned_department,
            "position": cleaned_position,
            "password_hash": password_hash,
            "enabled": True,
            "created_at": now,
            "updated_at": now,
            "created_by": actor,
            "updated_by": actor,
        }
        users[cleaned_email] = row
        if role_requires_profile(role) and resolved_names:
            _sync_profile_bindings_for_user(store, cleaned_email, resolved_names)
        _save_store_unlocked(store)
        return _public_user(row)


def update_user(account_key: str, **fields: Any) -> dict[str, Any]:
    cleaned_key = normalize_email(account_key)
    with _users_cache_lock:
        cached = _load_store_unlocked()
        store = {
            "version": cached.get("version", 1),
            "updated_at": cached.get("updated_at"),
            "users": dict(cached.get("users") or {}),
            "profile_bindings": dict(cached.get("profile_bindings") or {}),
        }
        users = store["users"]
        bindings = store["profile_bindings"]
        row = users.get(cleaned_key)
        if not isinstance(row, dict):
            raise UserNotFoundError(f"user {cleaned_key!r} not found")

        role = str(fields["role"]).strip().lower() if "role" in fields and fields["role"] is not None else row["role"]
        from app.domain.roles import role_requires_profile

        if not role_requires_profile(role):
            profile_name = None
            resolved_names: list[str] = []
        else:
            if "profile_names" in fields and fields["profile_names"] is not None:
                raw_names = fields["profile_names"]
                if not isinstance(raw_names, list):
                    raise UserError("profile_names must be a list of profile ids")
                primary_hint = (
                    str(fields["profile_name"]).strip()
                    if "profile_name" in fields and fields["profile_name"] is not None
                    else row.get("profile_name")
                )
                resolved_names = _normalize_profile_name_list(raw_names, primary_hint)
            elif "profile_name" in fields and fields["profile_name"] is not None:
                profile_name = str(fields["profile_name"]).strip() or None
                resolved_names = _normalize_profile_name_list(
                    profile_names_from_row(row),
                    profile_name,
                )
            else:
                resolved_names = profile_names_from_row(row)
            profile_name = resolved_names[0] if resolved_names else None
        if profile_name == "":
            profile_name = None
        _validate_role_profile(role, profile_name, resolved_names)

        if role_requires_profile(role) and resolved_names:
            _sync_profile_bindings_for_user(store, cleaned_key, resolved_names)
        elif not role_requires_profile(role):
            for pname, bound in list(bindings.items()):
                if bound == cleaned_key:
                    bindings.pop(pname, None)

        updated = dict(row)
        # Resolve account email before dropping legacy ``username`` (rows keyed by
        # email may only store ``username``, not ``email``).
        account_email = _row_email(updated) or cleaned_key
        updated.pop("username", None)
        updated["role"] = role
        updated["profile_name"] = profile_name if role_requires_profile(role) else None
        updated["profile_names"] = resolved_names if role_requires_profile(role) else []
        if "password_hash" in fields and fields["password_hash"] is not None:
            updated["password_hash"] = fields["password_hash"]
        elif "password" in fields and fields["password"]:
            updated["password_hash"] = _hash_password(str(fields["password"]))
        if "display_name" in fields:
            cleaned_display = str(fields["display_name"]).strip() if fields["display_name"] else ""
            updated["display_name"] = cleaned_display or None
        if "department" in fields:
            cleaned_department = (
                str(fields["department"]).strip().lower() if fields["department"] else ""
            )
            _apply_department_fields(updated, cleaned_department or None)
            _validate_department_field(updated["department"])
        if "position" in fields:
            cleaned_position = str(fields["position"]).strip() if fields["position"] else ""
            updated["position"] = cleaned_position or None
        if "enabled" in fields and fields["enabled"] is not None:
            updated["enabled"] = bool(fields["enabled"])

        new_email = account_email
        if "new_email" in fields and fields["new_email"] is not None:
            new_email = validate_email_format(str(fields["new_email"]))
        elif "new_username" in fields and fields["new_username"] is not None:
            new_email = validate_email_format(str(fields["new_username"]))
        if not _is_valid_account_email(new_email):
            raise UserError("account email could not be resolved")
        updated["email"] = new_email
        updated["updated_at"] = time.time()
        updated["updated_by"] = _audit_actor()
        if not str(updated.get("created_by") or "").strip():
            updated["created_by"] = updated["updated_by"]

        if new_email != cleaned_key:
            if new_email in users:
                raise UserError(f"email {new_email!r} already exists")
            users.pop(cleaned_key, None)
            if role_requires_profile(role) and resolved_names:
                _sync_profile_bindings_for_user(store, new_email, resolved_names)
        users[new_email] = updated
        _save_store_unlocked(store)
        return _public_user(updated)


def profile_bound_to_user(profile_name: str, username: str) -> bool:
    """Return True when *profile_name* is exclusively bound to *username*."""
    cleaned_profile = str(profile_name or "").strip()
    cleaned_user = str(username or "").strip().lower()
    if not cleaned_profile or not cleaned_user:
        return False
    store = _load_store()
    bindings = store.get("profile_bindings") or {}
    return bindings.get(cleaned_profile) == cleaned_user


def profiles_orphaned_after_unassign(removed_profile_names: list[str]) -> list[str]:
    """Return profile ids with no users.json assignment — safe to delete on disk."""
    removable: list[str] = []
    for profile_name in removed_profile_names:
        pname = str(profile_name or "").strip()
        if not pname:
            continue
        store = _load_store()
        bindings = store.get("profile_bindings") or {}
        if bindings.get(pname):
            continue
        still_assigned = False
        for row in (store.get("users") or {}).values():
            if not isinstance(row, dict):
                continue
            if pname in profile_names_from_row(row):
                still_assigned = True
                break
        if still_assigned:
            continue
        try:
            from app.domain.profiles import _is_root_profile

            if _is_root_profile(pname):
                continue
        except ImportError:
            if pname == "default":
                continue
        removable.append(pname)
    return removable


def cascade_profile_name_for_user_delete(username: str) -> str | None:
    """Return one profile safe to delete when removing *username* (legacy helper)."""
    names = cascade_profile_names_for_user_delete(username)
    return names[0] if names else None


def cascade_profile_names_for_user_delete(username: str) -> list[str]:
    """Profiles exclusively bound to *username* that may be removed with the account."""
    cleaned_username = str(username or "").strip().lower()
    if not cleaned_username:
        return []
    store = _load_store()
    users = store.get("users") or {}
    row = users.get(cleaned_username)
    if not isinstance(row, dict):
        return []
    if str(row.get("role") or "").strip().lower() != "user":
        return []
    candidates = profile_names_from_row(row)
    removable: list[str] = []
    for profile_name in candidates:
        if not profile_bound_to_user(profile_name, cleaned_username):
            continue
        shared = False
        for other_name, other in users.items():
            if other_name == cleaned_username or not isinstance(other, dict):
                continue
            if profile_name in profile_names_from_row(other):
                shared = True
                break
        if shared:
            continue
        try:
            from app.domain.profiles import _is_root_profile

            if _is_root_profile(profile_name):
                continue
        except ImportError:
            if profile_name == "default":
                continue
        removable.append(profile_name)
    return removable


def delete_user(username: str) -> None:
    """Remove a user account and unbind their profile from users.json."""
    cleaned_username = str(username or "").strip().lower()
    with _users_cache_lock:
        cached = _load_store_unlocked()
        store = {
            "version": cached.get("version", 1),
            "updated_at": cached.get("updated_at"),
            "users": dict(cached.get("users") or {}),
            "profile_bindings": dict(cached.get("profile_bindings") or {}),
        }
        users = store["users"]
        bindings = store["profile_bindings"]
        row = users.pop(cleaned_username, None)
        if row is None:
            raise UserNotFoundError(f"user {cleaned_username!r} not found")
        for pname in profile_names_from_row(row):
            if bindings.get(pname) == cleaned_username:
                bindings.pop(pname, None)
        _save_store_unlocked(store)


def _constant_time_str_equal(left: str, right: str) -> bool:
    """Constant-time string compare (UTF-8 safe — hmac.compare_digest is ASCII-only)."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def verify_user_password(email: str, plain: str) -> UserRecord | None:
    user = get_user(str(email or "").strip().lower())
    if user is None or not user.password_hash or not user.enabled:
        return None
    if _constant_time_str_equal(user.password_hash, _hash_password(plain)):
        return user
    if _constant_time_str_equal(user.password_hash, plain):
        return user
    return None


def bootstrap_default_admin() -> dict[str, Any] | None:
    """Create the first admin account when multi-user mode is enabled and users.json is absent."""
    if users_file_exists():
        return None
    env_flag = os.getenv("HERMES_WEBUI_MULTI_USER", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not env_flag:
        return None

    from app.domain.auth import get_password_hash

    admin_raw = os.getenv("HERMES_WEBUI_ADMIN_USER", "admin@localhost").strip().lower()
    admin_username = admin_raw or "admin@localhost"
    try:
        admin_email = validate_email_format(admin_username)
    except UserError:
        if _is_legacy_slug_identifier(admin_username):
            admin_email = f"{admin_username}@localhost"
        else:
            raise
    admin_display_name = os.getenv("HERMES_WEBUI_ADMIN_DISPLAY_NAME", "").strip() or None
    admin_password = os.getenv("HERMES_WEBUI_ADMIN_PASSWORD", "").strip()
    password_hash: str | None = None
    if admin_password:
        password_hash = _hash_password(admin_password)
    else:
        password_hash = get_password_hash()
    if not password_hash:
        msg = (
            "HERMES_WEBUI_MULTI_USER=1 but no admin password is configured "
            "(set HERMES_WEBUI_ADMIN_PASSWORD or HERMES_WEBUI_PASSWORD)"
        )
        print(f"[!!] WARNING: {msg}", flush=True)
        logger.warning(msg)
        return None
    from app.domain.roles import ensure_default_roles

    ensure_default_roles()
    try:
        user = create_user(
            admin_email,
            role="admin",
            display_name=admin_display_name,
            password_hash=password_hash,
        )
    except UserError as exc:
        msg = f"multi-user admin bootstrap failed: {exc}"
        print(f"[!!] WARNING: {msg}", flush=True)
        logger.warning(msg)
        return None
    user.pop("password_hash", None)
    print(
        f"[ok] Multi-user mode: created default admin user {admin_email!r} "
        "(password not logged)",
        flush=True,
    )
    return user


def promote_install_to_multi_user(
    *,
    admin_username: str | None = None,
    admin_password: str | None = None,
    current_password: str | None = None,
) -> dict[str, Any]:
    """Promote a legacy install by creating users.json with the first admin user."""
    if users_file_exists():
        return {"status": "skipped", "reason": "users.json already exists"}

    from app.domain.auth import is_password_auth_enabled, verify_password

    if is_password_auth_enabled():
        if not current_password or not verify_password(current_password):
            return {"status": "error", "error": "current_password required or invalid"}

    raw_admin = (
        admin_username or os.getenv("HERMES_WEBUI_ADMIN_USER") or "admin@localhost"
    ).strip().lower()
    try:
        username = validate_email_format(raw_admin)
    except UserError:
        username = f"{raw_admin}@localhost" if raw_admin else "admin@localhost"
    display_name = os.getenv("HERMES_WEBUI_ADMIN_DISPLAY_NAME", "").strip() or None
    password = (admin_password or "").strip()
    if not password and is_password_auth_enabled():
        password = (current_password or "").strip()
    if not password:
        password = os.getenv("HERMES_WEBUI_ADMIN_PASSWORD", "").strip()
    if not password:
        return {
            "status": "error",
            "error": "admin_password required (body or HERMES_WEBUI_ADMIN_PASSWORD)",
        }

    try:
        user = create_user(
            username,
            role="admin",
            display_name=display_name,
            password=password,
        )
    except UserError as exc:
        return {"status": "error", "error": str(exc)}

    user.pop("password_hash", None)
    return {"status": "created", "email": username, "user": user}


def session_token_from_cookie(cookie_value: str | None) -> str | None:
    from app.domain.auth import _session_token_from_cookie_value

    if not cookie_value:
        return None
    return _session_token_from_cookie_value(cookie_value)


def resolve_current_user(session_token: str | None) -> dict[str, Any]:
    """Resolve a session token to a dependency-friendly user payload."""
    if not users_file_exists():
        admin = legacy_admin_user()
        return {
            "username": admin.username,
            "role": admin.role,
            "profile_name": admin.profile_name,
            "created_at": None,
        }
    if not session_token:
        raise UserNotFoundError("Authentication required")
    entry = get_session_entry(session_token)
    if not isinstance(entry, dict):
        raise UserNotFoundError("Authentication required")
    user_id = str(entry.get("user_id") or LEGACY_ADMIN_USER_ID)
    user = get_user(user_id)
    if user is None:
        raise UserNotFoundError("Authentication required")
    names = user.assigned_profile_names()
    return {
        "email": user.email,
        "role": user.role,
        "profile_name": user.profile_name,
        "profile_names": list(names),
        "display_name": user.display_name,
        "department": user.department,
        "position": user.position,
        "created_at": user.created_at,
    }


def resolve_request_user_access(request: Request | None) -> UserAccess:
    """Resolve profile-access policy for an authenticated HTTP request."""
    if not is_multi_user_enabled():
        return legacy_user_access()
    if request is None:
        return UserAccess(multi_user_enabled=True, role="user", profile_name=None)

    session_cred = resolve_session_credential_from_request(request)
    if session_cred:
        token = _session_token_from_cookie_value(session_cred)
        if not token:
            return UserAccess(multi_user_enabled=True, role="user", profile_name=None)

        entry = get_session_entry(token)
        if not isinstance(entry, dict):
            return UserAccess(multi_user_enabled=True, role="user", profile_name=None)

        user_id = str(entry.get("user_id") or LEGACY_ADMIN_USER_ID)
        if user_id == LEGACY_ADMIN_USER_ID:
            return UserAccess(multi_user_enabled=True, role="admin")

        user = get_user(user_id)
        if user is None:
            return UserAccess(multi_user_enabled=True, role="user", profile_name=None)

        from app.domain.users import profile_name_from_email
        from app.domain.roles import role_requires_profile

        if not role_requires_profile(user.role):
            slug = profile_name_from_email(user.email)
            return UserAccess(
                multi_user_enabled=True,
                user_id=user.email,
                username=user.email,
                role=user.role,
                profile_name=slug,
                profile_names=(slug,),
                department=user.department,
            )

        return UserAccess(
            multi_user_enabled=True,
            user_id=user.email,
            username=user.email,
            role=user.role,
            profile_name=user.profile_name,
            profile_names=user.assigned_profile_names(),
            department=user.department,
        )

    from app.domain.auth import parse_bearer_authorization
    from app.document_api.mcp_auth import resolve_user_from_mcp_bearer

    bearer = parse_bearer_authorization(request.headers.get("authorization"))
    mcp_user = resolve_user_from_mcp_bearer(bearer) if bearer else None
    if mcp_user is None:
        return UserAccess(multi_user_enabled=True, role="user", profile_name=None)

    user = get_user(mcp_user.user_id)
    if user is None and mcp_user.user_id == "mcp-service":
        return UserAccess(multi_user_enabled=True, role="admin")

    if user is None:
        return UserAccess(
            multi_user_enabled=True,
            user_id=mcp_user.user_id,
            username=mcp_user.user_id,
            role=mcp_user.role,
            profile_name=mcp_user.profile_name,
            profile_names=mcp_user.profile_names,
        )

    from app.domain.roles import role_requires_profile

    if not role_requires_profile(user.role):
        from app.domain.users import profile_name_from_email

        slug = profile_name_from_email(user.email)
        return UserAccess(
            multi_user_enabled=True,
            user_id=user.email,
            username=user.email,
            role=user.role,
            profile_name=slug,
            profile_names=(slug,),
            department=user.department,
        )

    return UserAccess(
        multi_user_enabled=True,
        user_id=user.email,
        username=user.email,
        role=user.role,
        profile_name=user.profile_name,
        profile_names=user.assigned_profile_names(),
        department=user.department,
    )


def session_allowed_for_access(
    session_profile: str | None,
    access: UserAccess,
) -> bool:
    """Return True when *access* may read a session tagged with *session_profile*."""
    if not access.restricts_profiles:
        return True
    from app.domain.profiles import _profiles_match

    allowed = access.allowed_profile_names()
    if not allowed:
        return True
    return any(_profiles_match(session_profile, name) for name in allowed)
