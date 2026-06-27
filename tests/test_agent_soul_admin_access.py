# coding: utf-8
"""Agent Soul (SOUL.md) is admin-only when multi-user mode is enabled."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest
from starlette.testclient import TestClient

from app.domain.auth import _hash_password, create_session
from app.domain.users import create_user
from app.main import create_app


class _ProfileInfo:
    def __init__(self, name, path, **kwargs):
        self.name = name
        self.path = path
        self.is_default = kwargs.get("is_default", name == "default")


@pytest.fixture
def soul_multi_user_env(tmp_path, monkeypatch):
    state = tmp_path / "webui"
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    (state / "sessions").mkdir(parents=True)
    (hermes_home / "profiles" / "alice").mkdir(parents=True)
    (hermes_home / "SOUL.md").write_text("# Default soul\n", encoding="utf-8")
    (hermes_home / "profiles" / "alice" / "SOUL.md").write_text(
        "# Alice soul\n", encoding="utf-8"
    )

    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", "legacy-secret")

    import app.domain.config as config
    import app.domain.auth as auth
    import app.domain.users as users
    import app.domain.profiles as profiles

    importlib.reload(config)
    auth = importlib.reload(auth)
    users = importlib.reload(users)
    profiles = importlib.reload(profiles)

    auth._sessions.clear()
    profiles._DEFAULT_HERMES_HOME = hermes_home
    profiles._active_profile = "default"
    profiles._profiles_list_cache = None
    profiles._invalidate_root_profile_cache()
    profiles.get_hermes_home_for_profile = lambda name: (
        hermes_home
        if name in (None, "", "default")
        else hermes_home / "profiles" / name
    )

    cli_mod = ModuleType("hermes_cli.profiles")
    cli_mod.list_profiles = lambda: [
        _ProfileInfo("default", hermes_home, is_default=True),
        _ProfileInfo("alice", hermes_home / "profiles" / "alice"),
    ]
    sys.modules["hermes_cli"] = ModuleType("hermes_cli")
    sys.modules["hermes_cli.profiles"] = cli_mod

    create_user(
        "admin",
        role="admin",
        password_hash=_hash_password("admin-pass"),
    )
    create_user(
        "alice",
        role="user",
        profile_name="alice",
        password_hash=_hash_password("alice-pass"),
    )

    yield {
        "auth": auth,
        "profiles": profiles,
        "hermes_home": hermes_home,
    }

    for key in list(sys.modules):
        if key == "hermes_cli" or key.startswith("hermes_cli."):
            del sys.modules[key]


def _cookie(auth_mod, *, user_id: str, role: str) -> str:
    return auth_mod.create_session(user_id=user_id, role=role)


def test_user_cannot_write_soul_memory(soul_multi_user_env):
    env = soul_multi_user_env
    app = create_app()
    alice_cookie = _cookie(env["auth"], user_id="alice", role="user")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/memory/write",
            json={"section": "soul", "content": "# Hacked soul"},
            cookies={"hermes_session": alice_cookie},
        )
    assert response.status_code == 403
    body = response.json()
    assert "agent_soul:access" in (body.get("detail") or body.get("error") or "")


def test_admin_can_write_soul_memory(soul_multi_user_env):
    env = soul_multi_user_env
    app = create_app()
    admin_cookie = _cookie(env["auth"], user_id="admin", role="admin")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/memory/write",
            json={"section": "soul", "content": "# Admin soul edit"},
            cookies={"hermes_session": admin_cookie},
        )
    assert response.status_code == 200
    assert response.json().get("ok") is True


def test_user_memory_read_omits_soul_fields(soul_multi_user_env):
    env = soul_multi_user_env
    app = create_app()
    alice_cookie = _cookie(env["auth"], user_id="alice", role="user")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/memory",
            cookies={"hermes_session": alice_cookie},
        )
    assert response.status_code == 200
    payload = response.json()
    assert "soul" not in payload
    assert "soul_path" not in payload
    assert "soul_mtime" not in payload
    assert "memory" in payload


def test_admin_memory_read_includes_soul_fields(soul_multi_user_env):
    env = soul_multi_user_env
    app = create_app()
    admin_cookie = _cookie(env["auth"], user_id="admin", role="admin")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/memory",
            cookies={"hermes_session": admin_cookie},
        )
    assert response.status_code == 200
    payload = response.json()
    assert "soul" in payload
    assert payload["soul_path"].endswith("SOUL.md")


def test_user_cannot_sync_profile_from_default(soul_multi_user_env):
    env = soul_multi_user_env
    app = create_app()
    alice_cookie = _cookie(env["auth"], user_id="alice", role="user")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/profile/sync-from-default",
            json={"name": "alice"},
            cookies={"hermes_session": alice_cookie},
        )
    assert response.status_code == 403
    body = response.json()
    assert "agent_soul:access" in (body.get("detail") or body.get("error") or "")


def test_admin_can_sync_profile_from_default(soul_multi_user_env, monkeypatch):
    env = soul_multi_user_env
    monkeypatch.setattr(
        env["profiles"],
        "_is_root_profile",
        lambda name: name == "default",
    )
    app = create_app()
    admin_cookie = _cookie(env["auth"], user_id="admin", role="admin")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/profile/sync-from-default",
            json={"name": "alice"},
            cookies={"hermes_session": admin_cookie},
        )
    assert response.status_code == 200
    assert response.json().get("ok") is True


def test_panels_hide_agent_soul_for_non_admin():
    from pathlib import Path

    panels = (Path(__file__).resolve().parent.parent / "static-legacy" / "panels.js").read_text(
        encoding="utf-8"
    )
    assert "function _canAccessAgentSoul(" in panels
    assert "s.key === 'soul' && !canSoul" in panels
    assert "profile_sync_items_soul" in panels
    assert "canSoul === false" in panels or "canSoul !== false" in panels
