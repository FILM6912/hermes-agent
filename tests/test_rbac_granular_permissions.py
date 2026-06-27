"""Granular RBAC permissions align with the Roles catalog."""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api.v1.endpoints import admin as admin_endpoint
from app.api.v1.endpoints import system as system_endpoint
from app.domain.auth import COOKIE_NAME, _hash_password, create_session
from app.domain.users import create_user, invalidate_users_cache
from app.main import create_app


@pytest.fixture
def rbac_env(tmp_path, monkeypatch):
    state = tmp_path / "webui"
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    session_dir = state / "sessions"
    session_dir.mkdir(parents=True)
    roles_path = state / "roles.json"

    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", "legacy-secret")
    monkeypatch.setattr("app.domain.roles.ROLES_FILE", roles_path)
    monkeypatch.setattr("app.domain.roles._use_supabase_store", lambda: False)

    import app.domain.config as config
    import app.domain.auth as auth
    import app.domain.roles as roles

    importlib.reload(config)
    auth = importlib.reload(auth)
    roles = importlib.reload(roles)
    roles.invalidate_roles_cache()
    roles.ensure_default_roles()

    invalidate_users_cache()
    create_user("admin@example.com", role="admin", password_hash=_hash_password("admin-pass"))
    create_user(
        "ops@example.com",
        role="user",
        profile_name="default",
        password_hash=_hash_password("ops-pass"),
    )

    yield {"auth": auth, "roles": roles}

    invalidate_users_cache()
    auth._sessions.clear()


def _cookie(auth_mod, *, user_id: str, role: str) -> dict[str, str]:
    token = create_session(user_id=user_id, role=role)
    return {"Cookie": f"{COOKIE_NAME}={token}"}


@pytest.fixture
def client(rbac_env):
    return TestClient(create_app())


def test_workspaces_manage_without_users_manage(client, rbac_env):
    rbac_env["roles"].update_role("user", permissions={"workspaces:manage": True})
    response = client.get(
        "/api/v1/admin/workspaces",
        headers=_cookie(rbac_env["auth"], user_id="ops@example.com", role="user"),
    )
    assert response.status_code == 200


def test_users_manage_required_for_user_list(client, rbac_env):
    rbac_env["roles"].update_role("user", permissions={"roles:manage": True})
    response = client.get(
        "/api/v1/admin/users",
        headers=_cookie(rbac_env["auth"], user_id="ops@example.com", role="user"),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Permission required: users:manage"


def test_roles_manage_allows_roles_api(client, rbac_env):
    rbac_env["roles"].update_role("user", permissions={"roles:manage": True})
    response = client.get(
        "/api/v1/admin/roles",
        headers=_cookie(rbac_env["auth"], user_id="ops@example.com", role="user"),
    )
    assert response.status_code == 200


def test_settings_system_required_for_shutdown(client, rbac_env):
    response = client.post(
        "/api/v1/shutdown",
        headers=_cookie(rbac_env["auth"], user_id="ops@example.com", role="user"),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Permission required: settings:system"

    rbac_env["roles"].update_role("user", permissions={"settings:system": True})
    response_ok = client.post(
        "/api/v1/shutdown",
        headers=_cookie(rbac_env["auth"], user_id="ops@example.com", role="user"),
    )
    assert response_ok.status_code == 200
