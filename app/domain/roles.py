"""Dynamic WebUI role definitions and permission checks."""

from __future__ import annotations

import json
import logging
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from types import MappingProxyType
from pathlib import Path
from typing import Any

from app.domain.config import STATE_DIR

logger = logging.getLogger(__name__)

ROLES_FILE = STATE_DIR / "roles.json"
_ROLE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_BUILTIN_ADMIN = "admin"
_BUILTIN_USER = "user"
_BUILTIN_SUPERVISOR = "supervisor"

PERMISSION_CATALOG: dict[str, str] = {
    "*": "Full access (wildcard)",
    "users:manage": "Manage user accounts",
    "roles:manage": "Manage role definitions",
    "profiles:manage": "Create, delete, and sync profiles",
    "profiles:switch_all": "Switch to any profile",
    "upload:file": "Upload files",
    "workspace:read": "Read workspace files",
    "workspace:write": "Write workspace files",
    "chat:send": "Send chat messages",
    "sessions:own": "Access sessions for assigned profiles",
    "sessions:all": "Access sessions for all profiles",
    "settings:personal": "Personal UI settings",
    "settings:system": "System settings and shutdown",
    "insights:read": "View usage insights",
    "logs:read": "View server logs",
    "agent_soul:access": "Access Agent Soul (SOUL.md)",
    "workspaces:manage": "Manage shared workspace folders",
    "rag:ingest": "Ingest documents into RAG (upload / jobs)",
    "rag:search": "Search and list RAG documents",
    "rag:approve": "Approve pending RAG ingest (commit to vector store)",
    "rag:manage": "Manage RAG documents (delete, rename, reject, cancel jobs)",
    "transcript-report:read": "View transcript audio reports (same department)",
    "transcript-report:create": "Upload transcript audio (same department)",
    "transcript-report:edit": "Process/re-transcribe transcript audio (same department)",
    "transcript-report:delete": "Delete transcript audio rows (same department)",
}

_DEFAULT_USER_PERMISSIONS = [
    "chat:send",
    "upload:file",
    "workspace:read",
    "workspace:write",
    "sessions:own",
    "settings:personal",
    "rag:ingest",
    "rag:search",
    "transcript-report:read",
    "transcript-report:create",
    "transcript-report:edit",
]

_DEFAULT_SUPERVISOR_PERMISSIONS = [
    "chat:send",
    "upload:file",
    "workspace:read",
    "sessions:own",
    "settings:personal",
    "rag:ingest",
    "rag:search",
    "rag:approve",
    "transcript-report:read",
    "transcript-report:create",
    "transcript-report:edit",
    "transcript-report:delete",
]

DEFAULT_ROLES: dict[str, dict[str, Any]] = {
    _BUILTIN_ADMIN: {
        "label": "Administrator",
        "description": "Full system access",
        "permissions": {"*": True},
        "requires_profile": False,
        "builtin": True,
    },
    _BUILTIN_USER: {
        "label": "User",
        "description": "Standard user bound to assigned profiles",
        "permissions": {
            key: (key in _DEFAULT_USER_PERMISSIONS)
            for key in PERMISSION_CATALOG
            if key != "*"
        },
        "requires_profile": True,
        "builtin": True,
    },
    _BUILTIN_SUPERVISOR: {
        "label": "หัวหน้า",
        "description": "Supervisor — approve RAG ingest and search",
        "permissions": {
            key: (key in _DEFAULT_SUPERVISOR_PERMISSIONS)
            for key in PERMISSION_CATALOG
            if key != "*"
        },
        "requires_profile": True,
        "builtin": True,
    },
}


def permissions_from_enabled_list(enabled: list[str]) -> dict[str, bool]:
    """Build a permission map from a legacy enabled-id list."""
    if "*" in enabled:
        return {"*": True}
    return {
        key: (key in enabled)
        for key in PERMISSION_CATALOG
        if key != "*"
    }


def coerce_permissions_map(raw: Any) -> dict[str, bool]:
    """Normalize list/dict/JSON permissions into ``{permission_id: bool}``."""
    if isinstance(raw, dict):
        result: dict[str, bool] = {}
        for key, value in raw.items():
            token = str(key or "").strip()
            if not token:
                continue
            if token != "*" and token not in PERMISSION_CATALOG:
                logger.debug("Ignoring unknown permission %r in stored role map", token)
                continue
            result[token] = bool(value)
        if result.get("*"):
            return {"*": True}
        return result
    if isinstance(raw, list):
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw:
            token = str(item or "").strip()
            if not token or token in seen:
                continue
            if token != "*" and token not in PERMISSION_CATALOG:
                logger.debug("Ignoring unknown permission %r in stored role map", token)
                continue
            seen.add(token)
            cleaned.append(token)
        if "*" in cleaned:
            return {"*": True}
        return permissions_from_enabled_list(cleaned)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return coerce_permissions_map(parsed)
    return {}


def permissions_map_has_any(perms: dict[str, bool]) -> bool:
    return bool(perms.get("*")) or any(bool(v) for k, v in perms.items() if k != "*")


def permission_granted(perms: dict[str, bool], permission: str) -> bool:
    if perms.get("*"):
        return True
    return bool(perms.get(permission))

_roles_cache: dict[str, Any] | None = None
_roles_cache_lock = threading.Lock()


class RoleError(ValueError):
    """Raised when a role record violates storage invariants."""


class RoleNotFoundError(RoleError):
    """Raised when a role id is not present in the roles store."""


@dataclass(frozen=True)
class RoleRecord:
    role_id: str
    label: str
    description: str | None
    permissions: MappingProxyType
    requires_profile: bool
    builtin: bool = False


def invalidate_roles_cache() -> None:
    global _roles_cache
    with _roles_cache_lock:
        _roles_cache = None


def _use_supabase_store() -> bool:
    try:
        from app.storage.config import supabase_storage_enabled

        return supabase_storage_enabled()
    except Exception:
        return False


def _supabase_repo():
    from app.storage.repositories.roles import get_roles_repository

    repo = get_roles_repository()
    repo.maybe_migrate_legacy(json_path=ROLES_FILE)
    return repo


def _role_row_from_repo(row: dict[str, Any]) -> RoleRecord:
    return _record_from_row(
        str(row.get("id") or ""),
        {
            "label": row.get("label"),
            "description": row.get("description"),
            "permissions": row.get("permissions"),
            "requires_profile": row.get("requires_profile"),
            "builtin": row.get("builtin"),
        },
    )


def _sync_builtin_roles_supabase(repo: Any) -> None:
    for role_id, default_row in DEFAULT_ROLES.items():
        if not bool(default_row.get("builtin")):
            continue
        default_map = coerce_permissions_map(default_row.get("permissions"))
        existing = repo.get(role_id)
        if existing is None:
            repo.upsert({"id": role_id, **default_row})
            continue
        current = coerce_permissions_map(existing.get("permissions"))
        if current.get("*"):
            continue
        if not permissions_map_has_any(current):
            repo.upsert({**existing, "permissions": default_map})
            continue
        merged = dict(current)
        changed = False
        for key, enabled in default_map.items():
            if key == "*":
                continue
            if enabled and key not in merged:
                merged[key] = True
                changed = True
        if changed:
            repo.upsert({**existing, "permissions": merged})


def validate_role_id(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned or not _ROLE_ID_RE.match(cleaned):
        raise RoleError(
            "role id must start with a letter and use lowercase letters, digits, _ or -"
        )
    return cleaned


def generate_role_id() -> str:
    """Return a random id that satisfies ``validate_role_id``."""
    return f"r{secrets.token_hex(4)}"


def allocate_role_id() -> str:
    """Pick a random role id that is not already in use."""
    ensure_default_roles()
    for _ in range(16):
        candidate = generate_role_id()
        if not role_exists(candidate):
            return candidate
    raise RoleError("could not allocate a unique role id")


def _merge_permissions_patch(existing: Any, patch: Any) -> dict[str, bool]:
    """Merge a PATCH permissions object into the stored map (unset keys unchanged)."""
    incoming = coerce_permissions_map(patch)
    if not incoming:
        return coerce_permissions_map(existing)
    if incoming.get("*"):
        return {"*": True}

    existing_map = coerce_permissions_map(existing)
    if existing_map.get("*"):
        base: dict[str, bool] = {
            key: True for key in PERMISSION_CATALOG if key != "*"
        }
    else:
        base = dict(existing_map)

    for key, value in incoming.items():
        if key == "*":
            continue
        base[key] = bool(value)

    base.pop("*", None)
    return base


def _normalize_permissions(raw: Any) -> dict[str, bool]:
    return coerce_permissions_map(raw)


def _record_from_row(role_id: str, row: dict[str, Any]) -> RoleRecord:
    permissions = MappingProxyType(coerce_permissions_map(row.get("permissions")))
    return RoleRecord(
        role_id=role_id,
        label=str(row.get("label") or role_id).strip() or role_id,
        description=str(row.get("description") or "").strip() or None,
        permissions=permissions,
        requires_profile=bool(row.get("requires_profile", False)),
        builtin=bool(row.get("builtin", False)),
    )


def _public_role(record: RoleRecord) -> dict[str, Any]:
    return {
        "id": record.role_id,
        "label": record.label,
        "description": record.description,
        "permissions": dict(record.permissions),
        "requires_profile": record.requires_profile,
        "builtin": record.builtin,
    }


def _load_store_unlocked() -> dict[str, Any]:
    global _roles_cache
    if _roles_cache is not None and not _use_supabase_store():
        return _roles_cache
    payload: dict[str, Any] = {
        "version": 1,
        "updated_at": time.time(),
        "roles": dict(DEFAULT_ROLES),
    }
    if ROLES_FILE.is_file():
        try:
            raw = json.loads(ROLES_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("roles"), dict):
                payload = raw
        except Exception:
            logger.warning("Failed to read roles.json; using defaults", exc_info=True)
    _roles_cache = payload
    return payload


def _save_store_unlocked(store: dict[str, Any]) -> None:
    global _roles_cache
    store = dict(store)
    store["version"] = int(store.get("version") or 1)
    store["updated_at"] = time.time()
    roles = store.get("roles")
    if not isinstance(roles, dict):
        raise RoleError("roles store is invalid")
    ROLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=ROLES_FILE.parent,
        prefix=".roles.",
        suffix=".tmp",
    )
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=2, sort_keys=True)
            handle.write("\n")
        Path(tmp_path).chmod(0o600)
        Path(tmp_path).replace(ROLES_FILE)
    finally:
        tmp = Path(tmp_path)
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    _roles_cache = store


def ensure_default_roles() -> None:
    """Create roles.json with built-in roles when missing; sync builtin permissions."""
    if _use_supabase_store():
        repo = _supabase_repo()
        if not repo.has_roles():
            repo.seed_defaults(DEFAULT_ROLES)
        _sync_builtin_roles_supabase(repo)
        return
    with _roles_cache_lock:
        if not ROLES_FILE.is_file():
            _save_store_unlocked(
                {
                    "version": 1,
                    "updated_at": time.time(),
                    "roles": dict(DEFAULT_ROLES),
                }
            )
            return
        store = {
            "version": _load_store_unlocked().get("version", 1),
            "updated_at": _load_store_unlocked().get("updated_at"),
            "roles": dict(_load_store_unlocked().get("roles") or {}),
        }
        changed = False
        for role_id, default_row in DEFAULT_ROLES.items():
            if not bool(default_row.get("builtin")):
                continue
            row = store["roles"].get(role_id)
            if not isinstance(row, dict):
                continue
            default_map = coerce_permissions_map(default_row.get("permissions"))
            current = coerce_permissions_map(row.get("permissions"))
            if current.get("*"):
                continue
            if not permissions_map_has_any(current):
                row = dict(row)
                row["permissions"] = default_map
                store["roles"][role_id] = row
                changed = True
                continue
            merged = dict(current)
            row_changed = False
            for key, enabled in default_map.items():
                if key == "*":
                    continue
                if enabled and key not in merged:
                    merged[key] = True
                    row_changed = True
            if row_changed:
                row = dict(row)
                row["permissions"] = merged
                store["roles"][role_id] = row
                changed = True
        if changed:
            _save_store_unlocked(store)


def list_roles() -> list[dict[str, Any]]:
    ensure_default_roles()
    if _use_supabase_store():
        return [
            {
                **_public_role(_role_row_from_repo(row)),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "created_by": row.get("created_by"),
                "updated_by": row.get("updated_by"),
            }
            for row in _supabase_repo().list_all()
        ]
    store = _load_store_unlocked()
    roles = store.get("roles") or {}
    result: list[dict[str, Any]] = []
    for role_id in sorted(roles.keys()):
        row = roles.get(role_id)
        if not isinstance(row, dict):
            continue
        result.append(_public_role(_record_from_row(str(role_id), row)))
    return result


def list_permission_catalog() -> list[dict[str, str]]:
    return [
        {"id": key, "label": label}
        for key, label in PERMISSION_CATALOG.items()
        if key != "*"
    ]


def get_role(role_id: str) -> RoleRecord:
    ensure_default_roles()
    cleaned = validate_role_id(role_id)
    if _use_supabase_store():
        row = _supabase_repo().get(cleaned)
        if row is None:
            raise RoleNotFoundError(f"role {cleaned!r} not found")
        return _role_row_from_repo(row)
    row = _load_store_unlocked().get("roles", {}).get(cleaned)
    if not isinstance(row, dict):
        raise RoleNotFoundError(f"role {cleaned!r} not found")
    return _record_from_row(cleaned, row)


def role_exists(role_id: str) -> bool:
    try:
        get_role(role_id)
        return True
    except (RoleError, RoleNotFoundError):
        return False


def role_requires_profile(role_id: str) -> bool:
    try:
        return get_role(role_id).requires_profile
    except RoleNotFoundError:
        return role_id != _BUILTIN_ADMIN


def resolve_role_permissions(role_id: str) -> dict[str, bool]:
    try:
        return dict(get_role(role_id).permissions)
    except RoleNotFoundError:
        if role_id == _BUILTIN_ADMIN:
            return {"*": True}
        return permissions_from_enabled_list(_DEFAULT_USER_PERMISSIONS)


def role_has_permission(role_id: str, permission: str) -> bool:
    return permission_granted(resolve_role_permissions(role_id), permission)


def role_has_full_access(role_id: str) -> bool:
    return bool(resolve_role_permissions(role_id).get("*"))


def count_users_with_role(role_id: str) -> int:
    from app.domain.users import list_users

    cleaned = str(role_id or "").strip().lower()
    return sum(1 for row in list_users() if str(row.get("role") or "").lower() == cleaned)


def create_role(
    role_id: str | None = None,
    *,
    label: str,
    description: str | None = None,
    permissions: dict[str, bool] | list[str] | None = None,
    requires_profile: bool = False,
) -> dict[str, Any]:
    cleaned = validate_role_id(role_id) if role_id else allocate_role_id()
    ensure_default_roles()
    normalized_permissions = _normalize_permissions(permissions or {})
    if not permissions_map_has_any(normalized_permissions):
        raise RoleError("at least one permission is required")
    if _use_supabase_store():
        repo = _supabase_repo()
        if repo.get(cleaned) is not None:
            raise RoleError(f"role {cleaned!r} already exists")
        row = {
            "id": cleaned,
            "label": str(label or cleaned).strip() or cleaned,
            "description": str(description or "").strip() or None,
            "permissions": normalized_permissions,
            "requires_profile": bool(requires_profile),
            "builtin": False,
        }
        repo.upsert(row)
        return _public_role(_role_row_from_repo(row))
    with _roles_cache_lock:
        store = {
            "version": _load_store_unlocked().get("version", 1),
            "updated_at": _load_store_unlocked().get("updated_at"),
            "roles": dict(_load_store_unlocked().get("roles") or {}),
        }
        if cleaned in store["roles"]:
            raise RoleError(f"role {cleaned!r} already exists")
        row = {
            "label": str(label or cleaned).strip() or cleaned,
            "description": str(description or "").strip() or None,
            "permissions": normalized_permissions,
            "requires_profile": bool(requires_profile),
            "builtin": False,
        }
        store["roles"][cleaned] = row
        _save_store_unlocked(store)
        return _public_role(_record_from_row(cleaned, row))


def update_role(role_id: str, **fields: Any) -> dict[str, Any]:
    cleaned = validate_role_id(role_id)
    ensure_default_roles()
    if _use_supabase_store():
        repo = _supabase_repo()
        existing = repo.get(cleaned)
        if existing is None:
            raise RoleNotFoundError(f"role {cleaned!r} not found")
        updated = dict(existing)
        if "label" in fields and fields["label"] is not None:
            updated["label"] = str(fields["label"]).strip() or cleaned
        if "description" in fields:
            updated["description"] = str(fields["description"] or "").strip() or None
        if "permissions" in fields and fields["permissions"] is not None:
            normalized = _merge_permissions_patch(updated.get("permissions"), fields["permissions"])
            if not permissions_map_has_any(normalized):
                raise RoleError("at least one permission is required")
            updated["permissions"] = normalized
        if "requires_profile" in fields and fields["requires_profile"] is not None:
            updated["requires_profile"] = bool(fields["requires_profile"])
        repo.upsert(updated)
        return _public_role(_role_row_from_repo(updated))
    with _roles_cache_lock:
        store = {
            "version": _load_store_unlocked().get("version", 1),
            "updated_at": _load_store_unlocked().get("updated_at"),
            "roles": dict(_load_store_unlocked().get("roles") or {}),
        }
        row = store["roles"].get(cleaned)
        if not isinstance(row, dict):
            raise RoleNotFoundError(f"role {cleaned!r} not found")
        updated = dict(row)
        if "label" in fields and fields["label"] is not None:
            updated["label"] = str(fields["label"]).strip() or cleaned
        if "description" in fields:
            updated["description"] = str(fields["description"] or "").strip() or None
        if "permissions" in fields and fields["permissions"] is not None:
            merged = _merge_permissions_patch(updated.get("permissions"), fields["permissions"])
            updated["permissions"] = merged
            if not updated["permissions"]:
                raise RoleError("at least one permission is required")
        if "requires_profile" in fields and fields["requires_profile"] is not None:
            updated["requires_profile"] = bool(fields["requires_profile"])
        store["roles"][cleaned] = updated
        _save_store_unlocked(store)
        return _public_role(_record_from_row(cleaned, updated))


def delete_role(role_id: str) -> None:
    cleaned = validate_role_id(role_id)
    ensure_default_roles()
    if _use_supabase_store():
        repo = _supabase_repo()
        existing = repo.get(cleaned)
        if existing is None:
            raise RoleNotFoundError(f"role {cleaned!r} not found")
        if bool(existing.get("builtin")):
            raise RoleError(f"built-in role {cleaned!r} cannot be deleted")
        assigned = count_users_with_role(cleaned)
        if assigned:
            raise RoleError(
                f"role {cleaned!r} is assigned to {assigned} user(s); reassign them first"
            )
        if len(repo.list_all()) <= 1:
            raise RoleError("at least one role must remain")
        repo.delete(cleaned)
        return
    with _roles_cache_lock:
        store = {
            "version": _load_store_unlocked().get("version", 1),
            "updated_at": _load_store_unlocked().get("updated_at"),
            "roles": dict(_load_store_unlocked().get("roles") or {}),
        }
        row = store["roles"].get(cleaned)
        if not isinstance(row, dict):
            raise RoleNotFoundError(f"role {cleaned!r} not found")
        if bool(row.get("builtin")):
            raise RoleError(f"built-in role {cleaned!r} cannot be deleted")
        assigned = count_users_with_role(cleaned)
        if assigned:
            raise RoleError(
                f"role {cleaned!r} is assigned to {assigned} user(s); reassign them first"
            )
        store["roles"].pop(cleaned, None)
        if not store["roles"]:
            raise RoleError("at least one role must remain")
        _save_store_unlocked(store)
