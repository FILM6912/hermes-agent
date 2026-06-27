"""Admin user creation provisions default profile + workspace."""

from __future__ import annotations

import importlib
import json
import shutil
import sys
from types import ModuleType
import pytest
from starlette.testclient import TestClient

from app.domain.auth import COOKIE_NAME, _hash_password
from app.domain.users import USERS_FILE, create_user, invalidate_users_cache
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
    state.mkdir(parents=True)
    users_file = state / "users.json"

    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", "")

    import app.domain.config as config
    import app.domain.auth as auth
    import app.domain.users as users
    import app.domain.profiles as profiles
    import app.domain.workspace as workspace

    importlib.reload(config)
    auth = importlib.reload(auth)
    users = importlib.reload(users)
    profiles = importlib.reload(profiles)
    workspace = importlib.reload(workspace)

    users.USERS_FILE = users_file
    users.STATE_DIR = state
    config.STATE_DIR = state
    auth.STATE_DIR = state
    auth._sessions.clear()

    profiles._DEFAULT_HERMES_HOME = hermes_home
    profiles._active_profile = "default"
    profiles._profiles_list_cache = None
    profiles._invalidate_root_profile_cache()

    monkeypatch.setattr(
        workspace,
        "_default_hermes_home",
        lambda: hermes_home.resolve(),
    )

    profile_rows: list[_ProfileInfo] = [
        _ProfileInfo("default", hermes_home, is_default=True),
    ]

    def _list_profiles_api():
        active = profiles.get_active_profile_name()
        return [
            {
                "name": row.name,
                "path": str(row.path),
                "is_default": row.is_default,
                "is_active": row.name == active,
                "gateway_running": False,
                "model": None,
                "provider": None,
                "has_env": False,
                "skill_count": 0,
            }
            for row in profile_rows
        ]

    def _create_profile_api(name, **kwargs):
        target = hermes_home / "profiles" / name
        target.mkdir(parents=True, exist_ok=True)
        profile_rows.append(_ProfileInfo(name, target))
        profiles._invalidate_profiles_list_cache()
        return {"name": name, "path": str(target), "is_default": False, "is_active": False}

    def _delete_profile(name, yes=True):
        row = next((item for item in profile_rows if item.name == name), None)
        if row is None:
            raise ValueError(f"Profile '{name}' does not exist.")
        if row.is_default:
            raise ValueError("Cannot delete the default profile.")
        if row.path.is_dir():
            shutil.rmtree(row.path)
        profile_rows[:] = [item for item in profile_rows if item.name != name]
        profiles._invalidate_profiles_list_cache()

    monkeypatch.setattr(profiles, "list_profiles_api", _list_profiles_api)
    monkeypatch.setattr(profiles, "create_profile_api", _create_profile_api)
    monkeypatch.setattr(profiles, "_is_root_profile", lambda name: name == "default")

    cli_mod = ModuleType("hermes_cli.profiles")
    cli_mod.list_profiles = lambda: list(profile_rows)
    cli_mod.create_profile = lambda *args, **kwargs: None
    cli_mod.delete_profile = _delete_profile
    sys.modules["hermes_cli"] = ModuleType("hermes_cli")
    sys.modules["hermes_cli.profiles"] = cli_mod

    create_user("admin@example.com", role="admin", password_hash=_hash_password("admin-pass"))
    invalidate_users_cache()

    yield {
        "auth": auth,
        "profiles": profiles,
        "workspace": workspace,
        "hermes_home": hermes_home,
        "state": state,
        "users_file": users_file,
        "profile_rows": profile_rows,
    }

    auth._sessions.clear()
    invalidate_users_cache()
    for key in list(sys.modules):
        if key == "hermes_cli" or key.startswith("hermes_cli."):
            del sys.modules[key]


def _admin_cookie(auth_mod) -> str:
    return auth_mod.create_session(user_id="admin@example.com", role="admin")


def test_admin_create_user_provisions_profile_and_workspace(multi_user_env):
    env = multi_user_env
    client = TestClient(create_app())
    new_username = "carol@example.com"

    response = client.post(
        "/api/v1/admin/users",
        json={"email": new_username, "password": "carol-pass", "role": "user"},
        headers={"Cookie": f"{COOKIE_NAME}={_admin_cookie(env['auth'])}"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()["user"]
    assert payload["email"] == new_username
    assert payload["profile_name"] == "carol"

    profile_home = env["hermes_home"] / "profiles" / "carol"
    assert profile_home.is_dir()
    from app.domain.users import UserAccess

    carol_access = UserAccess(
        multi_user_enabled=True,
        user_id=new_username,
        username=new_username,
        role="user",
        profile_name="carol",
        profile_names=("carol",),
    )
    workspace_dir = env["workspace"].profile_workspace_dir(profile_home, access=carol_access)
    assert workspace_dir.is_dir()

    ws_file = env["hermes_home"] / "users" / "carol" / "webui_state" / "workspaces.json"
    assert ws_file.is_file()
    entries = json.loads(ws_file.read_text(encoding="utf-8"))
    assert isinstance(entries, list) and entries

    store = json.loads(env["users_file"].read_text(encoding="utf-8"))
    assert store["profile_bindings"]["carol"] == new_username


def test_created_user_sees_only_own_workspace_admin_sees_all(multi_user_env, monkeypatch):
    from app.core.security import CurrentUser
    from app.domain.users import UserAccess
    from app.services.profiles import ProfileService

    env = multi_user_env
    workspace_mod = env["workspace"]
    new_username = "dave@example.com"
    profile_name = "dave"

    client = TestClient(create_app())
    create_resp = client.post(
        "/api/v1/admin/users",
        json={"email": new_username, "password": "dave-pass", "role": "user"},
        headers={"Cookie": f"{COOKIE_NAME}={_admin_cookie(env['auth'])}"},
    )
    assert create_resp.status_code == 201

    monkeypatch.setattr(
        env["profiles"],
        "get_hermes_home_for_profile",
        lambda name: (
            env["hermes_home"]
            if name in (None, "", "default")
            else env["hermes_home"] / "profiles" / name
        ),
    )

    other_name = "other"
    other_home = env["hermes_home"] / "profiles" / other_name
    other_home.mkdir(parents=True, exist_ok=True)
    env["profile_rows"].append(_ProfileInfo(other_name, other_home))

    monkeypatch.setattr(workspace_mod, "nested_workspaces_enabled", lambda: False)

    user_access = UserAccess(
        multi_user_enabled=True,
        role="user",
        user_id=new_username,
        username=new_username,
        profile_name=profile_name,
        profile_names=(profile_name,),
    )
    user_paths = {row["path"] for row in workspace_mod.list_all_profile_workspaces(access=user_access)}
    expected_own = str(
        workspace_mod.profile_workspace_dir(
            env["hermes_home"] / "profiles" / profile_name,
            access=user_access,
        ).resolve()
    )
    assert user_paths == {expected_own}

    service = ProfileService()
    dave_profiles = {
        row["name"]
        for row in service.list_profiles(
            user=CurrentUser(user_id=new_username, role="user", profile_name=profile_name),
        )
    }
    admin_profiles = {
        row["name"]
        for row in service.list_profiles(
            user=CurrentUser(user_id="admin@example.com", role="admin", profile_name=None),
        )
    }
    assert dave_profiles == {profile_name}
    assert {profile_name, other_name, "default"}.issubset(admin_profiles)


def test_create_user_honors_explicit_profile_name(multi_user_env):
    env = multi_user_env
    client = TestClient(create_app())
    email = "erin@example.com"
    profile_name = "team-erin"

    response = client.post(
        "/api/v1/admin/users",
        json={
            "email": email,
            "password": "erin-pass",
            "role": "user",
            "profile_name": profile_name,
        },
        headers={"Cookie": f"{COOKIE_NAME}={_admin_cookie(env['auth'])}"},
    )
    assert response.status_code == 201
    assert response.json()["user"]["profile_name"] == profile_name
    assert (env["hermes_home"] / "profiles" / profile_name).is_dir()


def test_user_workspace_shared_across_assigned_profiles(multi_user_env):
    """File workspace is per account (email slug), not per agent profile."""
    from app.domain.users import UserAccess

    env = multi_user_env
    workspace_mod = env["workspace"]
    email = "ivy@example.com"
    slug = "ivy"

    client = TestClient(create_app())
    response = client.post(
        "/api/v1/admin/users",
        json={
            "email": email,
            "password": "ivy-pass",
            "role": "user",
            "profile_name": slug,
            "profile_names": [slug, "ivy-team"],
        },
        headers={"Cookie": f"{COOKIE_NAME}={_admin_cookie(env['auth'])}"},
    )
    assert response.status_code == 201

    access = UserAccess(
        multi_user_enabled=True,
        user_id=email,
        username=email,
        role="user",
        profile_name=slug,
        profile_names=(slug, "ivy-team"),
    )
    home_primary = env["hermes_home"] / "profiles" / slug
    home_team = env["hermes_home"] / "profiles" / "ivy-team"
    expected = workspace_mod._shared_workspace_root(env["hermes_home"]) / slug
    assert workspace_mod.profile_workspace_dir(home_primary, access=access).resolve() == expected.resolve()
    assert workspace_mod.profile_workspace_dir(home_team, access=access).resolve() == expected.resolve()
    user_state = env["hermes_home"] / "users" / slug / "webui_state" / "workspaces.json"
    assert user_state.is_file()


def test_update_user_unassign_removes_orphan_profile_and_config(multi_user_env):
    env = multi_user_env
    client = TestClient(create_app())
    email = "gina@example.com"
    primary = "gina"
    extra = "gina-extra"

    create_resp = client.post(
        "/api/v1/admin/users",
        json={
            "email": email,
            "password": "gina-pass",
            "role": "user",
            "profile_name": primary,
            "profile_names": [primary, extra],
        },
        headers={"Cookie": f"{COOKIE_NAME}={_admin_cookie(env['auth'])}"},
    )
    assert create_resp.status_code == 201

    extra_home = env["hermes_home"] / "profiles" / extra
    assert extra_home.is_dir()
    config_path = extra_home / "config.yaml"
    config_path.write_text("model:\n  default: test\n", encoding="utf-8")

    patch_resp = client.patch(
        f"/api/v1/admin/users/{email}",
        json={"profile_name": primary, "profile_names": [primary]},
        headers={"Cookie": f"{COOKIE_NAME}={_admin_cookie(env['auth'])}"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["user"]["profile_names"] == [primary]

    assert not extra_home.is_dir()
    assert not config_path.is_file()
    assert not any(row.name == extra for row in env["profile_rows"])
    primary_home = env["hermes_home"] / "profiles" / primary
    assert primary_home.is_dir()


def test_delete_user_removes_profile_and_workspace(multi_user_env):
    env = multi_user_env
    workspace_mod = env["workspace"]
    client = TestClient(create_app())
    email = "frank@example.com"
    profile_name = "frank"

    client.post(
        "/api/v1/admin/users",
        json={"email": email, "password": "frank-pass", "role": "user"},
        headers={"Cookie": f"{COOKIE_NAME}={_admin_cookie(env['auth'])}"},
    )
    from app.domain.users import UserAccess

    frank_access = UserAccess(
        multi_user_enabled=True,
        user_id=email,
        username=email,
        role="user",
        profile_name=profile_name,
        profile_names=(profile_name,),
    )
    profile_home = env["hermes_home"] / "profiles" / profile_name
    workspace_dir = workspace_mod.profile_workspace_dir(profile_home, access=frank_access)
    assert profile_home.is_dir()
    assert workspace_dir.is_dir()
    config_path = profile_home / "config.yaml"
    config_path.write_text("model:\n  default: frank\n", encoding="utf-8")
    ws_file = env["hermes_home"] / "users" / profile_name / "webui_state" / "workspaces.json"
    assert ws_file.is_file()

    delete_resp = client.delete(
        f"/api/v1/admin/users/{email}",
        headers={"Cookie": f"{COOKIE_NAME}={_admin_cookie(env['auth'])}"},
    )
    assert delete_resp.status_code == 204
    assert not profile_home.is_dir()
    assert not workspace_dir.is_dir()
    assert not ws_file.is_file()
    assert not config_path.is_file()

    store = json.loads(env["users_file"].read_text(encoding="utf-8"))
    assert email not in store.get("users", {})
    assert profile_name not in store.get("profile_bindings", {})
    assert not any(row.name == profile_name for row in env["profile_rows"])


def test_cascade_profile_name_skips_admin_and_root(multi_user_env):
    users_mod = importlib.import_module("app.domain.users")
    create_user(
        "hank@example.com",
        role="user",
        profile_name="hank",
        password_hash=_hash_password("hank-pass"),
    )
    invalidate_users_cache()
    assert users_mod.cascade_profile_name_for_user_delete("hank@example.com") == "hank"
    assert users_mod.cascade_profile_name_for_user_delete("admin@example.com") is None
    assert users_mod.cascade_profile_name_for_user_delete("missing") is None
    assert users_mod.cascade_profile_name_for_user_delete("default") is None
