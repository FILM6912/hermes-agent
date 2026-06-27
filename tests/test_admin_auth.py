"""Tests for admin/user role auth and profile-access gates."""

from __future__ import annotations

import importlib
import time

import pytest
from fastapi import HTTPException

from app.core.security import (
    CurrentUser,
    get_current_user,
    require_admin,
    require_current_user,
    user_can_access_profile,
)
from app.domain.auth import _hash_password, create_session


class _FakeRequest:
    def __init__(self, cookie: str | None = None) -> None:
        self.cookies = {"hermes_session": cookie} if cookie else {}
        self.headers = {}


@pytest.fixture
def auth_env(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state_dir))
    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", "legacy-secret")
    monkeypatch.delenv("HERMES_WEBUI_MULTI_USER", raising=False)

    import app.domain.auth as auth
    import app.domain.users as users

    auth = importlib.reload(auth)
    users = importlib.reload(users)
    monkeypatch.setattr(auth, "STATE_DIR", state_dir, raising=False)
    monkeypatch.setattr(users, "STATE_DIR", state_dir, raising=False)
    monkeypatch.setattr(users, "USERS_FILE", state_dir / "users.json", raising=False)
    users.invalidate_users_cache()
    auth._sessions.clear()
    return {"auth": auth, "users": users, "state_dir": state_dir}


def test_legacy_mode_session_is_admin(auth_env):
    auth = auth_env["auth"]
    cookie = auth.create_session()
    info = auth.get_session_info(cookie)
    assert info is not None
    assert info["user_id"] == "legacy"
    assert info["role"] == "admin"

    request = _FakeRequest(cookie)
    user = get_current_user(request)
    assert user is not None
    assert user.is_admin
    assert user.user_id == "legacy"


def test_legacy_mode_no_users_file_allows_any_profile(auth_env):
    user = CurrentUser(user_id="legacy", role="admin", profile_name=None)
    assert user_can_access_profile(user, "alice")
    assert user_can_access_profile(user, "bob")


def test_multi_user_login_stores_role_in_session(auth_env):
    auth = auth_env["auth"]
    users = auth_env["users"]
    users.create_user(
        "alice",
        role="user",
        profile_name="alice",
        password="user-pass",
    )

    repo = importlib.import_module("app.repositories.auth").AuthRepository()
    payload, status, cookie = repo.login(
        "user-pass",
        client_ip="127.0.0.1",
        username="alice",
    )
    assert status == 200
    assert payload["ok"] is True
    assert payload["role"] == "user"
    assert payload["user_id"] == "alice"
    assert cookie is not None

    info = auth.get_session_info(cookie)
    assert info["user_id"] == "alice"
    assert info["role"] == "user"


def test_user_cannot_access_other_profile(auth_env):
    users = auth_env["users"]
    users.create_user(
        "alice",
        role="user",
        profile_name="alice",
        password="user-pass",
    )
    repo = importlib.import_module("app.repositories.auth").AuthRepository()
    _, _, cookie = repo.login("user-pass", client_ip="127.0.0.1", username="alice")

    request = _FakeRequest(cookie)
    user = get_current_user(request)
    assert user is not None
    assert not user.is_admin
    assert user_can_access_profile(user, "alice")
    assert not user_can_access_profile(user, "bob")


def test_admin_user_passes_require_admin(auth_env):
    auth = auth_env["auth"]
    cookie = auth.create_session(user_id="admin", role="admin")
    request = _FakeRequest(cookie)
    user = require_admin(request)
    assert user.is_admin


def test_regular_user_rejected_by_require_admin(auth_env):
    auth = auth_env["auth"]
    users = auth_env["users"]
    users.create_user("alice", role="user", profile_name="alice", password="x")
    cookie = auth.create_session(user_id="alice", role="user")
    request = _FakeRequest(cookie)
    with pytest.raises(HTTPException) as exc:
        require_admin(request)
    assert exc.value.status_code == 403


def test_unauthenticated_request_raises_401(auth_env):
    request = _FakeRequest()
    with pytest.raises(HTTPException) as exc:
        require_current_user(request)
    assert exc.value.status_code == 401


def test_auth_status_includes_user_fields(auth_env):
    auth = auth_env["auth"]
    cookie = auth.create_session(user_id="legacy", role="admin")
    payload = auth.get_auth_status_payload(cookie)
    assert payload["logged_in"] is True
    assert payload["user_id"] == "legacy"
    assert payload["role"] == "admin"
    assert payload["multi_user"] is False


def test_legacy_float_session_entries_still_validate(auth_env):
    auth = auth_env["auth"]

    token = "legacy-float-token"
    auth._sessions[token] = time.time() + 3600
    sig = auth.hmac.new(auth._signing_key(), token.encode(), auth.hashlib.sha256).hexdigest()
    cookie = f"{token}.{sig}"
    assert auth.verify_session(cookie)
    info = auth.get_session_info(cookie)
    assert info["user_id"] == "legacy"
    assert info["role"] == "admin"


def test_auth_status_permissions_refresh_after_role_update(
    auth_env, monkeypatch, tmp_path,
) -> None:
    auth = auth_env["auth"]
    users = auth_env["users"]
    roles_path = tmp_path / "roles.json"
    monkeypatch.setattr("app.domain.roles.ROLES_FILE", roles_path)
    monkeypatch.setattr("app.domain.roles._use_supabase_store", lambda: False)
    from app.domain.roles import ensure_default_roles, invalidate_roles_cache, update_role

    invalidate_roles_cache()
    ensure_default_roles()
    users.create_user(
        "alice@example.com",
        role="user",
        profile_name="alice",
        password="user-pass",
    )
    cookie = auth.create_session(user_id="alice@example.com", role="user")

    before = auth.get_auth_status_payload(cookie)
    assert before["permissions"].get("rag:approve") is not True

    update_role("user", permissions={"rag:approve": True})

    after = auth.get_auth_status_payload(cookie)
    assert after["permissions"].get("rag:approve") is True


def test_auth_status_uses_live_user_role_not_stale_session(
    auth_env, monkeypatch, tmp_path,
) -> None:
    auth = auth_env["auth"]
    users = auth_env["users"]
    roles_path = tmp_path / "roles.json"
    monkeypatch.setattr("app.domain.roles.ROLES_FILE", roles_path)
    monkeypatch.setattr("app.domain.roles._use_supabase_store", lambda: False)
    from app.domain.roles import ensure_default_roles, invalidate_roles_cache

    invalidate_roles_cache()
    ensure_default_roles()
    users.create_user(
        "alice@example.com",
        role="user",
        profile_name="alice",
        password="user-pass",
    )
    cookie = auth.create_session(user_id="alice@example.com", role="user")
    users.update_user("alice@example.com", role="supervisor")

    payload = auth.get_auth_status_payload(cookie)
    assert payload["role"] == "supervisor"
    assert payload["permissions"].get("rag:approve") is True
    assert auth.get_session_info(cookie)["role"] == "user"
