"""Multi-user Kanban must pin storage to the bound profile, not a forged cookie."""

from __future__ import annotations

import importlib
import os
import sys
import types
from unittest import mock

import pytest
from starlette.testclient import TestClient

from app.domain.auth import _hash_password, create_session
from app.domain.users import create_user, invalidate_users_cache
from app.main import create_app


class _EnvTrackingKanban:
    DEFAULT_BOARD = "default"

    def __init__(self):
        self.connect_calls: list[str | None] = []

    def _normalize_board_slug(self, raw):
        return str(raw or "").strip().lower() or None

    def board_exists(self, slug):
        return True

    def init_db(self, board=None):
        return None

    def connect(self, board=None):
        self.connect_calls.append(os.environ.get("HERMES_KANBAN_HOME"))
        return mock.MagicMock(
            __enter__=lambda s: s,
            __exit__=lambda *a: None,
            execute=mock.MagicMock(
                return_value=mock.MagicMock(fetchone=lambda: {"latest": 0}, fetchall=list)
            ),
        )

    def list_tasks(self, conn, **kwargs):
        return []

    def list_boards(self, include_archived=False):
        return [{"slug": "default", "name": "Default"}]

    def get_current_board(self):
        return "default"

    def clear_current_board(self):
        return None

    def known_assignees(self, conn):
        return []


@pytest.fixture
def multi_user_kanban_env(tmp_path, monkeypatch):
    state = tmp_path / "webui"
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    (state / "sessions").mkdir(parents=True)
    for name in ("alice", "bob"):
        (hermes_home / "profiles" / name).mkdir(parents=True)

    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", "")

    import app.domain.config as config
    import app.domain.auth as auth
    import app.domain.users as users
    import app.domain.profiles as profiles

    importlib.reload(config)
    auth = importlib.reload(auth)
    users = importlib.reload(users)
    profiles = importlib.reload(profiles)

    config.STATE_DIR = state
    auth._sessions.clear()
    profiles._DEFAULT_HERMES_HOME = hermes_home
    profiles._active_profile = "default"
    profiles._profiles_list_cache = None
    profiles._invalidate_root_profile_cache()
    profiles.get_hermes_home_for_profile = lambda name: (
        hermes_home if name in (None, "", "default") else hermes_home / "profiles" / name
    )

    invalidate_users_cache()
    create_user(
        "alice@localhost",
        role="user",
        profile_name="alice",
        password_hash=_hash_password("alice-pass"),
    )
    create_user(
        "bob@localhost",
        role="user",
        profile_name="bob",
        password_hash=_hash_password("bob-pass"),
    )

    fake = _EnvTrackingKanban()
    fake_hermes_cli = types.ModuleType("hermes_cli")
    fake_hermes_cli.kanban_db = fake
    monkeypatch.setitem(sys.modules, "hermes_cli", fake_hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db", fake)

    import app.domain.kanban_bridge as bridge

    importlib.reload(bridge)

    yield {
        "hermes_home": hermes_home,
        "fake": fake,
        "auth": auth,
    }

    for key in list(sys.modules):
        if key == "hermes_cli" or key.startswith("hermes_cli."):
            del sys.modules[key]


def test_v1_kanban_ignores_foreign_profile_cookie_for_regular_user(multi_user_kanban_env):
    env = multi_user_kanban_env
    alice_home = str(env["hermes_home"] / "profiles" / "alice")
    bob_home = str(env["hermes_home"] / "profiles" / "bob")
    session_cookie = env["auth"].create_session(user_id="alice@localhost", role="user")

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/kanban/board",
            cookies={
                "hermes_session": session_cookie,
                "hermes_profile": "bob",
            },
        )

    assert response.status_code == 200
    assert env["fake"].connect_calls, "kanban connect should have been called"
    assert env["fake"].connect_calls[-1] == alice_home
    assert env["fake"].connect_calls[-1] != bob_home
