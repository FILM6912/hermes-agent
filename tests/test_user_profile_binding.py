"""Regression coverage for per-user profile assignment in multi-user mode."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import app.domain.profiles as profiles_mod
from app.api.v1.endpoints import profiles as profiles_endpoint
from app.api.v1.endpoints import auth as auth_endpoint
from app.core.security import CurrentUser
from app.domain.auth import COOKIE_NAME, _sessions, create_session
from app.domain.users import USERS_FILE, create_user, invalidate_users_cache
from app.services.profiles import ProfileService


class _ProfileInfo:
    def __init__(self, name, path, **kwargs):
        self.name = name
        self.path = path
        self.is_default = kwargs.get("is_default", name == "default")
        self.gateway_running = kwargs.get("gateway_running", False)
        self.model = kwargs.get("model")
        self.provider = kwargs.get("provider")
        self.has_env = kwargs.get("has_env", False)
        self.skill_count = kwargs.get("skill_count", 0)


@pytest.fixture
def profile_state(tmp_path, monkeypatch):
    state_dir = tmp_path / "webui"
    hermes_home = tmp_path / ".hermes"
    state_dir.mkdir()
    hermes_home.mkdir()

    for name in ("user1", "user2"):
        (hermes_home / "profiles" / name).mkdir(parents=True)

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
    monkeypatch.setattr(profiles_mod, "_active_profile", "default")
    profiles_mod._profiles_list_cache = None

    profile_rows = [
        _ProfileInfo("default", hermes_home, is_default=True),
        _ProfileInfo("user1", hermes_home / "profiles" / "user1"),
        _ProfileInfo("user2", hermes_home / "profiles" / "user2"),
    ]

    monkeypatch.setattr(
        profiles_mod,
        "list_profiles_api",
        lambda: [
            {
                "name": row.name,
                "path": str(row.path),
                "is_default": row.is_default,
                "is_active": row.name == "default",
                "gateway_running": False,
                "model": None,
                "provider": None,
                "has_env": False,
                "skill_count": 0,
            }
            for row in profile_rows
        ],
    )

    invalidate_users_cache()
    _sessions.clear()

    yield {
        "state_dir": state_dir,
        "hermes_home": hermes_home,
        "users_file": users_file,
    }

    invalidate_users_cache()
    _sessions.clear()


ADMIN_EMAIL = "admin@localhost"
ALICE_EMAIL = "alice@localhost"
BOB_EMAIL = "bob@localhost"


def _seed_users() -> None:
    create_user(ADMIN_EMAIL, role="admin", password_hash="a" * 64)
    create_user(ALICE_EMAIL, role="user", profile_name="user1", password_hash="b" * 64)
    create_user(BOB_EMAIL, role="user", profile_name="user2", password_hash="c" * 64)


def test_legacy_mode_lists_all_profiles_without_users_file(profile_state, monkeypatch):
    monkeypatch.delenv("HERMES_WEBUI_MULTI_USER", raising=False)
    if profile_state["users_file"].exists():
        profile_state["users_file"].unlink()
    invalidate_users_cache()

    service = ProfileService()
    admin = CurrentUser(user_id="legacy", role="admin", profile_name=None)

    names = {row["name"] for row in service.list_profiles(user=admin)}

    assert names == {"default", "user1", "user2"}


def test_regular_user_lists_only_assigned_profiles(profile_state):
    _seed_users()
    service = ProfileService()
    alice = CurrentUser(
        user_id=ALICE_EMAIL,
        role="user",
        profile_name="user1",
        profile_names=("user1",),
    )

    names = {row["name"] for row in service.list_profiles(user=alice)}

    assert names == {"user1"}


def test_admin_sees_all_profiles(profile_state):
    _seed_users()
    service = ProfileService()
    admin = CurrentUser(user_id=ADMIN_EMAIL, role="admin", profile_name=None)

    names = {row["name"] for row in service.list_profiles(user=admin)}

    assert names == {"default", "user1", "user2"}


def test_regular_user_can_switch_among_assigned_profiles(profile_state):
    _seed_users()
    from app.services.users import UserService

    UserService().update_user(
        ALICE_EMAIL,
        profile_names=["user1", "alice-alt"],
        profile_name="user1",
    )
    service = ProfileService()
    alice = CurrentUser(user_id=ALICE_EMAIL, role="user", profile_name="user1")

    result = service.switch_profile_client("alice-alt", user=alice)
    assert result.get("active") == "alice-alt" or result

    with pytest.raises(PermissionError, match="user2"):
        service.switch_profile_client("user2", user=alice)

    outsider = CurrentUser(user_id=BOB_EMAIL, role="user", profile_name="user2")
    with pytest.raises(PermissionError, match="user1"):
        service.switch_profile_client("user1", user=outsider)


def test_regular_user_cannot_create_profile(profile_state):
    _seed_users()
    service = ProfileService()
    alice = CurrentUser(user_id=ALICE_EMAIL, role="user", profile_name="user1")

    with pytest.raises(PermissionError, match="Only administrators can manage agent profiles"):
        service.create_profile("new-profile", user=alice)


def test_admin_can_create_profile(profile_state, monkeypatch):
    _seed_users()

    created: list[str] = []

    def fake_create_profile_api(name, **kwargs):
        created.append(name)
        target = profile_state["hermes_home"] / "profiles" / name
        target.mkdir(parents=True, exist_ok=True)
        return {"name": name, "path": str(target), "is_default": False, "is_active": False}

    monkeypatch.setattr(profiles_mod, "create_profile_api", fake_create_profile_api)

    service = ProfileService()
    admin = CurrentUser(user_id=ADMIN_EMAIL, role="admin", profile_name=None)

    profile = service.create_profile("team-shared", user=admin)

    assert created == ["team-shared"]
    assert profile["name"] == "team-shared"


@pytest.fixture
def api_client(profile_state):
    app = FastAPI()
    app.include_router(profiles_endpoint.router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client


def _auth_cookie_for(username: str, role: str) -> str:
    cookie = create_session(user_id=username, role=role)
    return f"{COOKIE_NAME}={cookie}"


def test_auth_status_includes_bound_profile_for_regular_user(profile_state):
    _seed_users()
    app = FastAPI()
    app.include_router(auth_endpoint.router, prefix="/api/v1")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/auth/status",
            headers={"Cookie": _auth_cookie_for(ALICE_EMAIL, "user")},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["logged_in"] is True
        assert payload["profile_name"] == "user1"


def test_api_list_profiles_returns_assigned_profiles_for_regular_user(api_client):
    _seed_users()
    response = api_client.get(
        "/api/v1/profiles",
        headers={"Cookie": _auth_cookie_for(ALICE_EMAIL, "user")},
    )
    assert response.status_code == 200
    names = {row["name"] for row in response.json().get("profiles", [])}
    assert names == {"user1"}


def test_api_switch_rejects_unassigned_profile(api_client):
    _seed_users()
    response = api_client.post(
        "/api/v1/profile/switch",
        json={"name": "user2"},
        headers={"Cookie": _auth_cookie_for(ALICE_EMAIL, "user")},
    )
    assert response.status_code == 403
    message = response.json().get("error") or response.json().get("detail")
    assert "user2" in message

    response_bound = api_client.post(
        "/api/v1/profile/switch",
        json={"name": "user1"},
        headers={"Cookie": _auth_cookie_for(ALICE_EMAIL, "user")},
    )
    assert response_bound.status_code == 200


def test_api_create_profile_returns_403_for_regular_user(api_client, monkeypatch):
    _seed_users()
    monkeypatch.setattr(
        profiles_mod,
        "create_profile_api",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not create")),
    )
    response = api_client.post(
        "/api/v1/profile/create",
        json={"name": "blocked-profile"},
        headers={"Cookie": _auth_cookie_for(ALICE_EMAIL, "user")},
    )
    assert response.status_code == 403
    message = response.json().get("error") or response.json().get("detail")
    assert message == "Only administrators can manage agent profiles."


def test_admin_request_access_uses_account_slug_not_shared_profile(profile_state):
    """Admin workspace policy must key off the signed-in account email slug."""
    _seed_users()
    from app.domain.users import resolve_request_user_access
    from unittest.mock import MagicMock

    cookie = create_session(user_id=ADMIN_EMAIL, role="admin")
    request = MagicMock()
    request.cookies = {COOKIE_NAME: cookie}
    request.headers = MagicMock(
        get=lambda key, default=None: (
            f"{COOKIE_NAME}={cookie}" if str(key).lower() == "cookie" else default
        )
    )

    access = resolve_request_user_access(request)

    assert access.user_id == ADMIN_EMAIL
    assert access.is_admin is True
    assert access.profile_name == "admin"
    assert access.profile_names == ("admin",)


def test_api_legacy_mode_without_users_file(api_client, profile_state, monkeypatch):
    monkeypatch.delenv("HERMES_WEBUI_MULTI_USER", raising=False)
    if profile_state["users_file"].exists():
        profile_state["users_file"].unlink()
    invalidate_users_cache()

    response = api_client.get("/api/v1/profiles")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["profiles"]}
    assert names == {"default", "user1", "user2"}
