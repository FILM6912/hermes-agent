"""GET/PATCH /api/v1/auth/me — external auth proxy contract."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.domain.auth import COOKIE_NAME
from app.domain.users import create_user
from app.main import create_app


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / "webui"
    state_dir.mkdir()
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state_dir))
    monkeypatch.setenv("HERMES_HOME", str(state_dir))
    monkeypatch.setenv("HERMES_BASE_HOME", str(state_dir))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")

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


def _login_bearer(client: TestClient, *, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    token = response.json().get("access_token")
    assert token
    return token


def test_auth_me_requires_authentication(isolated_state: Path) -> None:
    client = _client()
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_auth_me_returns_supervisor_profile(isolated_state: Path) -> None:
    create_user(
        "supervisor@example.com",
        role="supervisor",
        profile_name="supervisor",
        password="supervisor-pass",
    )
    client = _client()
    token = _login_bearer(client, email="supervisor@example.com", password="supervisor-pass")

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["email"] == "supervisor@example.com"
    assert payload["role"] == "supervisor"
    assert payload["roles"] == ["supervisor"]
    assert payload["enabled"] is True
    assert payload["permissions"] == {}


def test_auth_me_patch_display_name(isolated_state: Path) -> None:
    create_user(
        "supervisor@example.com",
        role="supervisor",
        profile_name="supervisor",
        password="supervisor-pass",
        display_name="Before",
    )
    client = _client()
    token = _login_bearer(client, email="supervisor@example.com", password="supervisor-pass")

    patch = client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"display_name": "After"},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["display_name"] == "After"

    again = client.get(
        "/api/v1/auth/me",
        cookies={COOKIE_NAME: token},
    )
    assert again.status_code == 200
    assert again.json()["display_name"] == "After"
