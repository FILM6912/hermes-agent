# coding: utf-8
"""Nested sub-workspaces with virtual /workspace paths (multi-user mode)."""

from __future__ import annotations

import importlib
import shutil
import sys
from types import ModuleType

import pytest
from starlette.testclient import TestClient

import app.domain.profiles as profiles_mod
import app.domain.workspace as workspace_mod
from app.domain.users import create_user, invalidate_users_cache
from app.main import create_app


class _ProfileInfo:
    def __init__(self, name, path, **kwargs):
        self.name = name
        self.path = path
        self.is_default = kwargs.get("is_default", name == "default")


@pytest.fixture
def multi_user_env(tmp_path, monkeypatch):
    state = tmp_path / "webui"
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    film_home = hermes_home / "profiles" / "film"
    film_home.mkdir(parents=True)
    (hermes_home / "workspace" / "film").mkdir(parents=True)
    (state / "sessions").mkdir(parents=True)

    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", "legacy-secret")

    import app.domain.config as config
    import app.domain.auth as auth
    import app.domain.users as users
    import app.domain.profiles as profiles
    import app.domain.models as models
    import app.domain.workspace as workspace

    importlib.reload(config)
    auth = importlib.reload(auth)
    users = importlib.reload(users)
    profiles = importlib.reload(profiles)
    models = importlib.reload(models)
    workspace = importlib.reload(workspace)

    config.STATE_DIR = state
    users.USERS_FILE = state / "users.json"
    auth._sessions.clear()
    profiles._DEFAULT_HERMES_HOME = hermes_home
    profiles._active_profile = "film"
    profiles._profiles_list_cache = None
    profiles._invalidate_root_profile_cache()
    profiles.get_hermes_home_for_profile = lambda name: (
        hermes_home if name in (None, "", "default") else hermes_home / "profiles" / name
    )

    cli_mod = ModuleType("hermes_cli.profiles")
    cli_mod.list_profiles = lambda: [
        _ProfileInfo("default", hermes_home, is_default=True),
        _ProfileInfo("film", film_home),
    ]
    sys.modules["hermes_cli"] = ModuleType("hermes_cli")
    sys.modules["hermes_cli.profiles"] = cli_mod

    invalidate_users_cache()
    users.create_user("film", role="user", password="secret", profile_name="film")
    users.create_user("admin", role="admin", password="secret")

    return {
        "hermes_home": hermes_home,
        "film_home": film_home,
        "workspace": workspace,
        "profiles": profiles,
    }


def test_virtual_path_resolution(multi_user_env):
    profile_home = multi_user_env["film_home"]
    root = workspace_mod.profile_workspace_dir(profile_home)
    project = root / "project1"
    project.mkdir()

    assert workspace_mod.virtual_path_to_disk("/workspace", profile_home) == root.resolve()
    assert workspace_mod.virtual_path_to_disk("/workspace/project1", profile_home) == project.resolve()
    assert workspace_mod.disk_path_to_virtual(project, profile_home) == "/workspace/project1"
    assert workspace_mod.disk_path_to_virtual(root, profile_home) == "/workspace"
    assert workspace_mod.virtual_path_to_disk("/workspace/.", profile_home) == root.resolve()


def test_add_nested_workspace_persists_registry(multi_user_env):
    profile_home = multi_user_env["film_home"]
    ws = multi_user_env["workspace"]
    entry = ws.add_nested_workspace(
        name="project1",
        parent="/workspace",
        profile_home=profile_home,
        create=True,
    )
    assert entry["path"] == "/workspace/project1"
    disk = ws.virtual_path_to_disk(entry["path"], profile_home)
    assert disk.is_dir()

    loaded = ws.load_workspaces_for_profile(profile_home)
    paths = [row["path"] for row in loaded]
    assert "/workspace" in paths
    assert "/workspace/project1" in paths


def test_nested_workspace_api_for_regular_user(multi_user_env):
    client = TestClient(create_app())
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "film", "password": "secret"},
    )
    assert login.status_code == 200
    cookie = login.cookies.get("hermes_session")

    listed = client.get("/api/v1/workspaces", cookies={"hermes_session": cookie})
    assert listed.status_code == 200
    body = listed.json()
    assert body.get("nested_workspaces") is True
    assert any(row["path"] == "/workspace" for row in body["workspaces"])

    created = client.post(
        "/api/v1/workspaces/add",
        json={"path": "project1", "name": "Project One", "parent": "/workspace", "create": True},
        cookies={"hermes_session": cookie},
    )
    assert created.status_code == 200
    assert created.json().get("path") == "/workspace/project1"
    paths = {row["path"] for row in created.json()["workspaces"]}
    assert "/workspace/project1" in paths

    profile_home = multi_user_env["film_home"]
    disk = workspace_mod.virtual_path_to_disk("/workspace/project1", profile_home)
    assert disk.is_dir()


def test_resolve_trusted_workspace_recreates_registered_nested_workspace(
    multi_user_env,
):
    """Regression: ``Path does not exist: .../workspace/<profile>/test``.

    workspaces.json can reference ``/workspace/test`` while the on-disk folder
    under the profile root is missing (wiped mount, create:false, etc.).
    """
    profile_home = multi_user_env["film_home"]
    ws = multi_user_env["workspace"]
    hermes_home = multi_user_env["hermes_home"]

    entry = ws.add_nested_workspace(
        name="test",
        parent="/workspace",
        profile_home=profile_home,
        create=True,
    )
    disk = ws.virtual_path_to_disk(entry["path"], profile_home)
    assert disk.is_dir()
    shutil.rmtree(disk)

    resolved = ws.resolve_trusted_workspace("/workspace/test")

    assert resolved == disk.resolve()
    assert disk.is_dir()


def test_resolve_trusted_workspace_does_not_create_unregistered_nested_path(
    multi_user_env,
):
    profile_home = multi_user_env["film_home"]
    ws = multi_user_env["workspace"]
    root = ws.profile_workspace_dir(profile_home)
    ghost = root / "ghost"
    assert not ghost.exists()

    with pytest.raises(ValueError, match="Path does not exist"):
        ws.resolve_trusted_workspace(str(ghost))
    assert not ghost.exists()


def test_legacy_single_workspace_unchanged_without_multi_user(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    state = tmp_path / "webui_state"
    state.mkdir(parents=True)
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "0")
    import app.domain.config as config
    import app.domain.users as users

    importlib.reload(config)
    users = importlib.reload(users)
    workspace = importlib.reload(workspace_mod)
    users.USERS_FILE = state / "users.json"
    users.invalidate_users_cache()

    assert workspace.nested_workspaces_enabled() is False
    workspaces = workspace.load_workspaces()
    assert len(workspaces) == 1
    assert workspaces[0]["path"] == workspace.profile_workspace_rel()
