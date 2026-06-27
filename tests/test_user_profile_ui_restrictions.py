"""Profile management API and UI restrictions for non-admin users."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import app.domain.profiles as profiles_mod
from app.api.v1.endpoints import profiles as profiles_endpoint
from app.domain.auth import COOKIE_NAME, _sessions, create_session
from app.domain.users import USERS_FILE, create_user, invalidate_users_cache
from app.services.profiles import ProfileService


@pytest.fixture
def profile_restrict_env(tmp_path, monkeypatch):
    state_dir = tmp_path / "webui"
    hermes_home = tmp_path / ".hermes"
    state_dir.mkdir()
    hermes_home.mkdir()
    (hermes_home / "profiles" / "alice").mkdir(parents=True)
    (hermes_home / "profiles" / "bob").mkdir(parents=True)

    users_file = state_dir / "users.json"
    sessions_file = state_dir / ".sessions.json"

    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state_dir))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", "")

    monkeypatch.setattr("app.domain.config.STATE_DIR", state_dir)
    monkeypatch.setattr("app.domain.users.STATE_DIR", state_dir)
    monkeypatch.setattr("app.domain.users.USERS_FILE", users_file)
    monkeypatch.setattr("app.domain.auth.STATE_DIR", state_dir)
    monkeypatch.setattr("app.domain.auth._SESSIONS_FILE", sessions_file)

    monkeypatch.setattr(profiles_mod, "_DEFAULT_HERMES_HOME", hermes_home)
    monkeypatch.setattr(profiles_mod, "_active_profile", "alice")
    profiles_mod._profiles_list_cache = None

    monkeypatch.setattr(
        profiles_mod,
        "list_profiles_api",
        lambda: [
            {
                "name": "alice",
                "path": str(hermes_home / "profiles" / "alice"),
                "is_default": False,
                "is_active": True,
                "gateway_running": False,
                "model": None,
                "provider": None,
                "has_env": False,
                "skill_count": 0,
            },
            {
                "name": "bob",
                "path": str(hermes_home / "profiles" / "bob"),
                "is_default": False,
                "is_active": False,
                "gateway_running": False,
                "model": None,
                "provider": None,
                "has_env": False,
                "skill_count": 0,
            },
        ],
    )

    invalidate_users_cache()
    _sessions.clear()
    create_user("admin", role="admin", password_hash="a" * 64)
    create_user("alice", role="user", profile_name="alice", password_hash="b" * 64)

    yield {"hermes_home": hermes_home}

    invalidate_users_cache()
    _sessions.clear()


@pytest.fixture
def api_client(profile_restrict_env):
    app = FastAPI()
    app.include_router(profiles_endpoint.router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client


def _cookie(username: str, role: str) -> str:
    return f"{COOKIE_NAME}={create_session(user_id=username, role=role)}"


def test_admin_can_list_profiles(api_client):
    response = api_client.get(
        "/api/v1/profiles",
        headers={"Cookie": _cookie("admin", "admin")},
    )
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["profiles"]}
    assert names == {"alice", "bob"}


def test_regular_user_delete_profile_returns_403(api_client, monkeypatch):
    monkeypatch.setattr(
        profiles_mod,
        "delete_profile_api",
        lambda name: (_ for _ in ()).throw(AssertionError("should not delete")),
    )
    response = api_client.post(
        "/api/v1/profile/delete",
        json={"name": "alice"},
        headers={"Cookie": _cookie("alice", "user")},
    )
    assert response.status_code == 403


def test_regular_user_sync_profile_returns_403(api_client, monkeypatch):
    monkeypatch.setattr(
        profiles_mod,
        "sync_profile_from_default_api",
        lambda name: (_ for _ in ()).throw(AssertionError("should not sync")),
    )
    response = api_client.post(
        "/api/v1/profile/sync-from-default",
        json={"name": "alice"},
        headers={"Cookie": _cookie("alice", "user")},
    )
    assert response.status_code == 403


def test_service_delete_and_sync_require_admin(profile_restrict_env):
    from app.core.security import CurrentUser

    service = ProfileService()
    user = CurrentUser(user_id="alice", role="user", profile_name="alice")
    with pytest.raises(profiles_mod.ProfileAccessError):
        service.delete_profile("alice", user=user)
    with pytest.raises(profiles_mod.ProfileAccessError):
        service.sync_profile_from_default("alice", user=user)
    with pytest.raises(profiles_mod.ProfileAccessError):
        service.sync_all_profiles_from_default(user=user)
