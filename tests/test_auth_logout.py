"""HTTP integration tests for POST /api/v1/auth/logout."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.domain.auth import COOKIE_NAME, _sessions, verify_session
from app.domain.users import create_user
from app.main import create_app


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

    from app.core.config import get_settings

    get_settings.cache_clear()
    yield state_dir
    auth_mod._sessions.clear()
    get_settings.cache_clear()


def _client() -> TestClient:
    return TestClient(create_app())


def _login(client: TestClient, *, username: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    cookie = response.cookies.get(COOKIE_NAME)
    assert cookie
    return cookie


def test_logout_invalidates_multi_user_session(isolated_state: Path) -> None:
    create_user("alice", role="user", profile_name="profa", password="alice-pass")
    client = _client()
    cookie = _login(client, username="alice", password="alice-pass")
    assert verify_session(cookie)

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert logout.json().get("ok") is True
    assert not verify_session(cookie)
    assert COOKIE_NAME not in logout.cookies or not logout.cookies.get(COOKIE_NAME)

    status = client.get("/api/v1/auth/status")
    assert status.status_code == 200
    assert status.json().get("logged_in") is False


def test_logout_works_without_valid_session_cookie(isolated_state: Path) -> None:
    create_user("alice", role="user", profile_name="profa", password="alice-pass")
    client = _client()
    cookie = _login(client, username="alice", password="alice-pass")
    token = cookie.split(".", 1)[0]
    _sessions.pop(token, None)

    logout = client.post("/api/v1/auth/logout", cookies={COOKIE_NAME: cookie})
    assert logout.status_code == 200
    assert logout.json().get("ok") is True


def test_logout_legacy_single_password_mode(isolated_state: Path) -> None:
    from app.domain.config import save_settings

    save_settings({"_set_password": "legacy-pass"})
    from app.domain.auth import _invalidate_password_hash_cache

    _invalidate_password_hash_cache()

    client = _client()
    login = client.post("/api/v1/auth/login", json={"password": "legacy-pass"})
    assert login.status_code == 200
    cookie = login.cookies.get(COOKIE_NAME)
    assert cookie and verify_session(cookie)

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert not verify_session(cookie)

    protected = client.get("/api/v1/sessions")
    assert protected.status_code == 401


def test_sign_out_controls_present_in_settings_html() -> None:
    html = Path(__file__).resolve().parents[1].joinpath("static/index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="btnSignOut"' in html
    assert 'id="settingsMenuSignOut"' in html
    assert 'onclick="signOut()"' in html
