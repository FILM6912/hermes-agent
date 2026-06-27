"""End-to-end tests for multi-user admin, profile binding, and legacy auth."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Callable

import pytest
from starlette.testclient import TestClient

from app.core.config import get_settings
from app.domain.auth import COOKIE_NAME, _hash_password, _sessions
from app.domain.users import create_user, users_file_exists
from app.main import create_app
from app.repositories.sessions import SessionRepository


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / "webui"
    state_dir.mkdir()
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state_dir))
    monkeypatch.setenv("HERMES_HOME", str(state_dir))
    monkeypatch.setenv("HERMES_BASE_HOME", str(state_dir))

    import app.domain.config as config

    importlib.reload(config)
    import app.domain.auth as auth_mod

    auth_mod._sessions.clear()
    importlib.reload(auth_mod)
    import app.domain.users as users_domain

    importlib.reload(users_domain)

    get_settings.cache_clear()
    yield state_dir
    auth_mod._sessions.clear()
    get_settings.cache_clear()


def _make_client() -> TestClient:
    return TestClient(create_app())


def _login(client: TestClient, *, email: str | None, password: str) -> None:
    payload: dict[str, str] = {"password": password}
    if email is not None:
        payload["email"] = email
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200, response.text
    assert response.json().get("ok") is True


def _seed_multi_user_users() -> None:
    create_user("admin@example.com", role="admin", password="admin-pass")
    create_user("alice@example.com", role="user", profile_name="profa", password="alice-pass")
    create_user("bob@example.com", role="user", profile_name="profb", password="bob-pass")


def _fake_sessions() -> list[dict]:
    return [
        {
            "session_id": "sess-a1",
            "profile": "profa",
            "title": "Alice chat",
            "updated_at": 100,
            "archived": False,
        },
        {
            "session_id": "sess-b1",
            "profile": "profb",
            "title": "Bob chat",
            "updated_at": 200,
            "archived": False,
        },
    ]


@pytest.fixture
def multi_user_setup(isolated_state: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[], TestClient]:
    assert users_file_exists()
    _seed_multi_user_users()

    def factory() -> TestClient:
        return _make_client()

    return factory


def test_admin_lists_users_and_cross_profile_session_summaries(
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_multi_user_users()
    monkeypatch.setattr(
        SessionRepository,
        "list_sessions",
        lambda self, diag=None: _fake_sessions(),
    )

    client = _make_client()
    _login(client, email="admin@example.com", password="admin-pass")

    users_resp = client.get("/api/v1/admin/users")
    assert users_resp.status_code == 200
    names = {row["email"] for row in users_resp.json()["users"]}
    assert names == {"admin@example.com", "alice@example.com", "bob@example.com"}

    alice_detail = client.get("/api/v1/admin/users/alice@example.com")
    assert alice_detail.status_code == 200
    alice_payload = alice_detail.json()
    assert alice_payload["profile"] == {"name": "profa"}
    bob_detail = client.get("/api/v1/admin/users/bob@example.com")
    assert bob_detail.status_code == 200
    assert bob_detail.json()["profile"] == {"name": "profb"}

    sessions_resp = client.get("/api/v1/sessions", params={"all_profiles": "1"})
    assert sessions_resp.status_code == 200
    session_ids = {row["session_id"] for row in sessions_resp.json()["sessions"]}
    assert session_ids == {"sess-a1", "sess-b1"}


def test_user_cannot_switch_to_other_users_profile(isolated_state: Path) -> None:
    _seed_multi_user_users()
    client = _make_client()
    _login(client, email="alice@example.com", password="alice-pass")

    switch_resp = client.post("/api/v1/profile/switch", json={"name": "profb"})
    assert switch_resp.status_code == 403
    assert "profb" in switch_resp.json()["detail"]


def test_user_sessions_hidden_from_other_users(
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_multi_user_users()
    monkeypatch.setattr(
        "app.services.sessions.SessionRepository.list_sessions",
        lambda self, diag=None: _fake_sessions(),
    )

    alice_client = _make_client()
    _login(alice_client, email="alice@example.com", password="alice-pass")
    alice_sessions = alice_client.get("/api/v1/sessions")
    assert alice_sessions.status_code == 200
    alice_ids = {row["session_id"] for row in alice_sessions.json()["sessions"]}
    assert alice_ids == {"sess-a1"}

    bob_client = _make_client()
    _login(bob_client, email="bob@example.com", password="bob-pass")
    bob_sessions = bob_client.get("/api/v1/sessions", params={"all_profiles": "1"})
    assert bob_sessions.status_code == 200
    bob_ids = {row["session_id"] for row in bob_sessions.json()["sessions"]}
    assert bob_ids == {"sess-b1"}
    assert "sess-a1" not in bob_ids


def test_legacy_mode_without_users_json_still_works(
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.config import save_settings

    assert not users_file_exists()
    save_settings({"_set_password": "legacy-pass"})
    from app.domain.auth import _invalidate_password_hash_cache

    _invalidate_password_hash_cache()

    client = _make_client()
    status_before = client.get("/api/v1/auth/status")
    assert status_before.status_code == 200
    assert status_before.json()["auth_enabled"] is True

    _login(client, email=None, password="legacy-pass")
    status_after = client.get("/api/v1/auth/status")
    assert status_after.status_code == 200
    assert status_after.json()["logged_in"] is True

    profiles_resp = client.get("/api/v1/profiles")
    assert profiles_resp.status_code == 200
    assert "profiles" in profiles_resp.json()

    admin_users = client.get("/api/v1/admin/users")
    assert admin_users.status_code == 200
    assert admin_users.json()["users"] == []
