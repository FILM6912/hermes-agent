"""Rollback workspace validation for multi-user canonical profile paths."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest

from app.domain.users import UserAccess
from app.domain.auth import _hash_password


class _ProfileInfo:
    def __init__(self, name, path, **kwargs):
        self.name = name
        self.path = path
        self.is_default = kwargs.get("is_default", name == "default")


@pytest.fixture
def rollback_multi_user_env(tmp_path, monkeypatch):
    state = tmp_path / "webui"
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    (hermes_home / "workspace" / "alice").mkdir(parents=True)
    (hermes_home / "workspace" / "bob").mkdir(parents=True)
    (hermes_home / "workspace" / "admin").mkdir(parents=True)
    (hermes_home / "profiles" / "alice").mkdir(parents=True)
    (hermes_home / "profiles" / "bob").mkdir(parents=True)
    (hermes_home / "profiles" / "admin").mkdir(parents=True)

    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", "")
    monkeypatch.delenv("HERMES_WEBUI_PROFILE_WORKSPACE", raising=False)
    monkeypatch.delenv("HERMES_WEBUI_DEFAULT_WORKSPACE", raising=False)

    import app.domain.config as config
    import app.domain.auth as auth
    import app.domain.users as users
    import app.domain.profiles as profiles
    import app.domain.workspace as workspace
    import app.domain.rollback as rollback

    users_file = state / "users.json"

    importlib.reload(config)
    auth = importlib.reload(auth)
    users = importlib.reload(users)
    profiles = importlib.reload(profiles)
    workspace = importlib.reload(workspace)
    rollback = importlib.reload(rollback)

    users.USERS_FILE = users_file
    users.STATE_DIR = state
    config.STATE_DIR = state
    auth.STATE_DIR = state
    auth._sessions.clear()

    profiles._DEFAULT_HERMES_HOME = hermes_home
    profiles._active_profile = "default"
    profiles._profiles_list_cache = None
    profiles._invalidate_root_profile_cache()
    profiles.get_hermes_home_for_profile = lambda name: (
        hermes_home if name in (None, "", "default") else hermes_home / "profiles" / name
    )
    workspace._default_hermes_home = lambda: hermes_home  # type: ignore[attr-defined]

    cli_mod = ModuleType("hermes_cli.profiles")
    cli_mod.list_profiles = lambda: [
        _ProfileInfo("default", hermes_home, is_default=True),
        _ProfileInfo("alice", hermes_home / "profiles" / "alice"),
        _ProfileInfo("bob", hermes_home / "profiles" / "bob"),
    ]
    sys.modules["hermes_cli"] = ModuleType("hermes_cli")
    sys.modules["hermes_cli.profiles"] = cli_mod

    users.create_user(
        "admin@example.com",
        role="admin",
        password_hash=_hash_password("admin-pass"),
    )
    users.create_user(
        "alice@example.com",
        role="user",
        profile_name="alice",
        password_hash=_hash_password("alice-pass"),
    )
    users.invalidate_users_cache()

    workspace.sync_assigned_profile_workspaces_into_account(
        "admin@example.com",
        ["admin"],
        primary_profile_name="admin",
    )
    workspace.sync_assigned_profile_workspaces_into_account(
        "alice@example.com",
        ["alice"],
        primary_profile_name="alice",
    )

    yield {
        "rollback": rollback,
        "workspace": workspace,
        "profiles": profiles,
        "hermes_home": hermes_home,
        "auth": auth,
    }

    auth._sessions.clear()
    users.invalidate_users_cache()
    for key in list(sys.modules):
        if key == "hermes_cli" or key.startswith("hermes_cli."):
            del sys.modules[key]


def test_resolve_workspace_accepts_canonical_shared_layout_path(rollback_multi_user_env):
    env = rollback_multi_user_env
    alice_access = UserAccess(
        multi_user_enabled=True,
        role="user",
        user_id="alice@example.com",
        username="alice@example.com",
        profile_name="alice",
        profile_names=("alice",),
    )
    alice_ws = str(
        env["workspace"].profile_workspace_dir(
            env["hermes_home"] / "profiles" / "alice",
            access=alice_access,
        ).resolve()
    )
    admin_access = UserAccess(
        multi_user_enabled=True,
        role="admin",
        user_id="admin@example.com",
        username="admin@example.com",
        profile_name="admin",
        profile_names=("admin",),
    )

    resolved = env["rollback"]._resolve_workspace(alice_ws, access=alice_access)
    assert resolved == alice_ws

    with pytest.raises(ValueError, match="not in configured list"):
        env["rollback"]._resolve_workspace(alice_ws, access=admin_access)


def test_resolve_workspace_denies_other_users_workspace(rollback_multi_user_env):
    env = rollback_multi_user_env
    bob_ws = str(
        env["workspace"].profile_workspace_dir(
            env["hermes_home"] / "profiles" / "bob"
        ).resolve()
    )
    alice_access = UserAccess(
        multi_user_enabled=True,
        role="user",
        user_id="alice@example.com",
        username="alice@example.com",
        profile_name="alice",
    )

    allowed = env["rollback"]._allowed_workspace_paths(alice_access)
    assert bob_ws not in allowed
    with pytest.raises(ValueError, match="not in configured list"):
        env["rollback"]._resolve_workspace(bob_ws, access=alice_access)


def test_list_checkpoints_empty_for_valid_canonical_workspace(rollback_multi_user_env):
    env = rollback_multi_user_env
    alice_ws = str(
        env["workspace"].profile_workspace_dir(
            env["hermes_home"] / "profiles" / "alice"
        ).resolve()
    )
    alice_access = UserAccess(
        multi_user_enabled=True,
        role="user",
        user_id="alice@example.com",
        username="alice@example.com",
        profile_name="alice",
    )

    payload = env["rollback"].list_checkpoints(alice_ws, access=alice_access)
    assert payload["workspace"] == alice_ws
    assert payload["checkpoints"] == []
