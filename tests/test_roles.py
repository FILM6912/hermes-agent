"""Tests for dynamic role definitions and permission checks."""

from __future__ import annotations

import json

import pytest

from app.domain.config import STATE_DIR
from app.domain.roles import (
    PERMISSION_CATALOG,
    ROLES_FILE,
    RoleError,
    RoleNotFoundError,
    coerce_permissions_map,
    create_role,
    delete_role,
    ensure_default_roles,
    get_role,
    invalidate_roles_cache,
    list_roles,
    permission_granted,
    role_has_permission,
    role_requires_profile,
    update_role,
)


@pytest.fixture(autouse=True)
def isolated_roles_file(tmp_path, monkeypatch):
    roles_path = tmp_path / "roles.json"
    monkeypatch.setattr("app.domain.roles.ROLES_FILE", roles_path)
    monkeypatch.setattr("app.domain.roles.STATE_DIR", tmp_path)
    monkeypatch.setattr("app.domain.roles._use_supabase_store", lambda: False)
    invalidate_roles_cache()
    yield
    invalidate_roles_cache()


def test_ensure_default_roles_creates_builtin_roles() -> None:
    ensure_default_roles()
    assert ROLES_FILE.is_file()
    roles = {row["id"]: row for row in list_roles()}
    assert "admin" in roles
    assert "user" in roles
    assert "supervisor" in roles
    assert roles["admin"]["permissions"] == {"*": True}
    assert roles["user"]["permissions"]["upload:file"] is True
    assert roles["supervisor"]["permissions"]["rag:approve"] is True


def test_create_update_delete_custom_role() -> None:
    ensure_default_roles()
    created = create_role(
        "reviewer",
        label="Reviewer",
        description="Read-only reviewer",
        permissions={"workspace:read": True, "sessions:own": True},
        requires_profile=True,
    )
    assert created["id"] == "reviewer"
    updated = update_role(
        "reviewer",
        permissions={"rag:approve": True},
    )
    assert updated["permissions"]["rag:approve"] is True
    assert updated["permissions"]["workspace:read"] is True
    assert updated["permissions"]["sessions:own"] is True
    delete_role("reviewer")
    with pytest.raises(RoleNotFoundError):
        get_role("reviewer")


def test_create_role_allocates_id_when_omitted() -> None:
    ensure_default_roles()
    created = create_role(
        label="Auto Id Role",
        permissions={"workspace:read": True},
    )
    role_id = created["id"]
    assert role_id.startswith("r")
    assert len(role_id) == 9
    assert get_role(role_id).label == "Auto Id Role"
    delete_role(role_id)


def test_update_role_merges_partial_permissions() -> None:
    ensure_default_roles()
    created = create_role(
        "partial-perms",
        label="Partial",
        permissions={"workspace:read": True, "chat:send": True},
    )
    updated = update_role("partial-perms", permissions={"rag:ingest": True})
    assert updated["permissions"]["workspace:read"] is True
    assert updated["permissions"]["chat:send"] is True
    assert updated["permissions"]["rag:ingest"] is True
    delete_role(created["id"])


def test_update_role_revokes_permission_from_wildcard_role() -> None:
    ensure_default_roles()
    updated = update_role("admin", permissions={"rag:ingest": False})
    perms = updated["permissions"]
    assert "*" not in perms
    assert perms["rag:ingest"] is False
    assert perms["users:manage"] is True
    ensure_default_roles()
    persisted = get_role("admin").permissions
    assert "*" not in persisted
    assert persisted["rag:ingest"] is False
    assert role_has_permission("admin", "users:manage") is True
    assert role_has_permission("admin", "rag:ingest") is False
    update_role("admin", permissions={"*": True})


def test_update_role_revokes_single_permission_from_granular_role() -> None:
    ensure_default_roles()
    updated = update_role("supervisor", permissions={"rag:approve": False})
    assert updated["permissions"]["rag:approve"] is False
    assert role_has_permission("supervisor", "rag:approve") is False
    update_role("supervisor", permissions={"rag:approve": True})


def test_builtin_role_cannot_be_deleted() -> None:
    ensure_default_roles()
    with pytest.raises(RoleError, match="built-in"):
        delete_role("admin")


def test_role_has_permission_wildcard_and_specific() -> None:
    ensure_default_roles()
    assert role_has_permission("admin", "upload:file") is True
    assert role_has_permission("user", "upload:file") is True
    assert role_has_permission("user", "rag:ingest") is True
    assert role_has_permission("user", "rag:approve") is False
    assert role_has_permission("user", "users:manage") is False
    assert role_has_permission("supervisor", "rag:approve") is True
    assert role_has_permission("supervisor", "users:manage") is False


def test_role_requires_profile_flags() -> None:
    ensure_default_roles()
    assert role_requires_profile("admin") is False
    assert role_requires_profile("user") is True
    assert role_requires_profile("supervisor") is True


def test_roles_json_persists_permissions_map() -> None:
    ensure_default_roles()
    payload = json.loads(ROLES_FILE.read_text(encoding="utf-8"))
    assert isinstance(payload["roles"]["admin"]["permissions"], dict)
    assert payload["roles"]["supervisor"]["label"] == "หัวหน้า"


def test_coerce_permissions_map_ignores_removed_catalog_keys() -> None:
    perms = coerce_permissions_map({"file:approve": True, "rag:search": True})
    assert "file:approve" not in perms
    assert perms["rag:search"] is True


def test_get_role_exposes_permission_map() -> None:
    ensure_default_roles()
    admin = get_role("admin")
    assert permission_granted(admin.permissions, "users:manage") is True
    user = get_role("user")
    assert user.permissions["users:manage"] is False
    assert user.permissions["chat:send"] is True
    assert len(user.permissions) == len(PERMISSION_CATALOG) - 1
