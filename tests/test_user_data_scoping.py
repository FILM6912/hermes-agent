"""Multi-user data scoping for sessions and workspace list/detail."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest
from starlette.testclient import TestClient

from app.domain.auth import _hash_password, create_session
from app.domain.models import Session
from app.domain.users import UserAccess, create_user, session_allowed_for_access
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
    (state / "sessions").mkdir(parents=True)
    (hermes_home / "profiles" / "alice").mkdir(parents=True)
    (hermes_home / "profiles" / "bob").mkdir(parents=True)
    (hermes_home / "profiles" / "admin").mkdir(parents=True)
    (hermes_home / "workspace" / "alice").mkdir(parents=True)
    (hermes_home / "workspace" / "bob").mkdir(parents=True)
    (hermes_home / "workspace" / "admin").mkdir(parents=True)
    (hermes_home / "workspace").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", "legacy-secret")
    monkeypatch.delenv("HERMES_WEBUI_PROFILE_WORKSPACE", raising=False)
    monkeypatch.delenv("HERMES_WEBUI_DEFAULT_WORKSPACE", raising=False)
    monkeypatch.delenv("HERMES_WEBUI_WORKSPACE_NAME", raising=False)

    import app.domain.config as config
    import app.domain.auth as auth
    import app.domain.users as users
    import app.domain.profiles as profiles
    import app.domain.models as models
    import app.domain.workspace as workspace

    session_dir = state / "sessions"
    config.STATE_DIR = state
    config.SESSION_DIR = session_dir
    config.SESSION_INDEX_FILE = session_dir / "_index.json"
    models.SESSION_DIR = session_dir
    models.SESSION_INDEX_FILE = session_dir / "_index.json"
    users.USERS_FILE = state / "users.json"
    users.STATE_DIR = state
    auth.STATE_DIR = state

    auth._sessions.clear()
    users.invalidate_users_cache()
    monkeypatch.setattr(profiles, "_DEFAULT_HERMES_HOME", hermes_home)
    profiles._active_profile = "default"
    profiles._profiles_list_cache = None
    profiles._invalidate_root_profile_cache()
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda name: (
            hermes_home if name in (None, "", "default") else hermes_home / "profiles" / name
        ),
    )
    monkeypatch.setattr(
        "app.domain.workspace._default_hermes_home",
        lambda: hermes_home,
    )

    cli_mod = ModuleType("hermes_cli.profiles")
    cli_mod.list_profiles = lambda: [
        _ProfileInfo("default", hermes_home, is_default=True),
        _ProfileInfo("admin", hermes_home / "profiles" / "admin"),
        _ProfileInfo("alice", hermes_home / "profiles" / "alice"),
        _ProfileInfo("bob", hermes_home / "profiles" / "bob"),
    ]
    sys.modules["hermes_cli"] = ModuleType("hermes_cli")
    sys.modules["hermes_cli.profiles"] = cli_mod

    create_user(
        "admin@example.com",
        role="admin",
        password_hash=_hash_password("admin-pass"),
    )
    create_user(
        "alice@example.com",
        role="user",
        profile_name="alice",
        password_hash=_hash_password("alice-pass"),
    )

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
        "auth": auth,
        "users": users,
        "profiles": profiles,
        "models": models,
        "workspace": workspace,
        "hermes_home": hermes_home,
        "state": state,
        "session_dir": session_dir,
    }

    auth._sessions.clear()
    users.invalidate_users_cache()
    for key in list(sys.modules):
        if key == "hermes_cli" or key.startswith("hermes_cli."):
            del sys.modules[key]


def _auth_cookie(auth_mod, *, user_id: str, role: str) -> str:
    return auth_mod.create_session(user_id=user_id, role=role)


def _persist_session(models_mod, session_id: str, *, profile: str, title: str) -> None:
    models_mod.SESSION_INDEX_FILE.unlink(missing_ok=True)
    session = Session(
        session_id=session_id,
        title=title,
        workspace=str(models_mod.get_last_workspace()),
        model="test-model",
        profile=profile,
        messages=[{"role": "user", "content": "hello"}],
    )
    session.save()
    assert (models_mod.SESSION_DIR / f"{session_id}.json").is_file()


def test_session_allowed_for_access_respects_bound_profile():
    admin_access = UserAccess(multi_user_enabled=True, role="admin")
    alice_access = UserAccess(
        multi_user_enabled=True,
        role="user",
        profile_name="alice",
    )

    assert session_allowed_for_access("alice", admin_access)
    assert session_allowed_for_access("bob", admin_access)
    assert session_allowed_for_access("alice", alice_access)
    assert not session_allowed_for_access("bob", alice_access)


def test_list_sidebar_scopes_non_admin_to_bound_profile(multi_user_env):
    from app.services.sessions import SessionService

    env = multi_user_env
    _persist_session(env["models"], "sessalice", profile="alice", title="Alice chat")
    _persist_session(env["models"], "sessbob", profile="bob", title="Bob chat")

    service = SessionService()
    alice_access = UserAccess(
        multi_user_enabled=True,
        role="user",
        profile_name="alice",
    )
    admin_access = UserAccess(multi_user_enabled=True, role="admin")

    alice_payload = service.list_sidebar(access=alice_access)
    admin_payload = service.list_sidebar(all_profiles=True, access=admin_access)

    alice_ids = {row["session_id"] for row in alice_payload["sessions"]}
    admin_ids = {row["session_id"] for row in admin_payload["sessions"]}

    assert "sessalice" in alice_ids
    assert "sessbob" not in alice_ids
    assert {"sessalice", "sessbob"}.issubset(admin_ids)


def test_list_sidebar_ignores_all_profiles_for_non_admin(multi_user_env):
    from app.services.sessions import SessionService

    env = multi_user_env
    _persist_session(env["models"], "sessalice", profile="alice", title="Alice chat")
    _persist_session(env["models"], "sessbob", profile="bob", title="Bob chat")

    service = SessionService()
    alice_access = UserAccess(
        multi_user_enabled=True,
        role="user",
        profile_name="alice",
    )
    payload = service.list_sidebar(all_profiles=True, access=alice_access)
    ids = {row["session_id"] for row in payload["sessions"]}

    assert ids == {"sessalice"}
    assert payload["all_profiles"] is False


def test_list_all_profile_workspaces_scopes_non_admin(multi_user_env, monkeypatch):
    workspace_mod = multi_user_env["workspace"]
    env = multi_user_env
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda name: (
            env["hermes_home"]
            if name in (None, "", "default")
            else env["hermes_home"] / "profiles" / name
        ),
    )
    monkeypatch.setattr(
        "app.domain.workspace._default_hermes_home",
        lambda: env["hermes_home"],
    )
    monkeypatch.setattr(
        env["profiles"],
        "get_active_hermes_home",
        lambda: env["hermes_home"] / "profiles" / "alice",
    )
    monkeypatch.setattr(env["profiles"], "get_active_profile_name", lambda: "alice")

    alice_access = UserAccess(
        multi_user_enabled=True,
        role="user",
        user_id="alice@example.com",
        username="alice@example.com",
        profile_name="alice",
        profile_names=("alice",),
    )
    admin_access = UserAccess(
        multi_user_enabled=True,
        role="admin",
        user_id="admin@example.com",
        username="admin@example.com",
        profile_name="admin",
        profile_names=("admin",),
    )

    alice_workspaces = workspace_mod.list_all_profile_workspaces(access=alice_access)
    admin_workspaces = workspace_mod.list_all_profile_workspaces(access=admin_access)

    assert len(alice_workspaces) == 1
    assert len(admin_workspaces) == 1
    assert alice_workspaces[0]["path"] == "/workspace"
    assert admin_workspaces[0]["path"] == "/workspace"
    assert alice_workspaces[0]["name"] == "alice"
    assert admin_workspaces[0]["name"] == "admin"
    alice_disk = alice_workspaces[0].get("disk_path") or alice_workspaces[0]["path"]
    admin_disk = admin_workspaces[0].get("disk_path") or admin_workspaces[0]["path"]
    assert alice_disk != admin_disk


def test_v1_sessions_and_workspace_endpoints_scope_non_admin(multi_user_env, monkeypatch):
    env = multi_user_env
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(env["state"]))
    monkeypatch.setenv("HERMES_HOME", str(env["hermes_home"]))
    monkeypatch.setenv("HERMES_BASE_HOME", str(env["hermes_home"]))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")

    import app.domain.config as config
    import app.domain.models as models
    import app.domain.workspace as workspace

    import app.domain.profiles as profiles

    config.STATE_DIR = env["state"]
    config.SESSION_DIR = env["session_dir"]
    config.SESSION_INDEX_FILE = env["session_dir"] / "_index.json"
    models.SESSION_DIR = env["session_dir"]
    models.SESSION_INDEX_FILE = env["session_dir"] / "_index.json"
    monkeypatch.setattr(profiles, "_DEFAULT_HERMES_HOME", env["hermes_home"])
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda name: (
            env["hermes_home"]
            if name in (None, "", "default")
            else env["hermes_home"] / "profiles" / name
        ),
    )
    monkeypatch.setattr(
        "app.domain.workspace._default_hermes_home",
        lambda: env["hermes_home"],
    )

    _persist_session(env["models"], "sessalice", profile="alice", title="Alice chat")
    _persist_session(env["models"], "sessbob", profile="bob", title="Bob chat")

    app = create_app()
    with TestClient(app) as client:
        admin_cookie = _auth_cookie(env["auth"], user_id="admin@example.com", role="admin")
        alice_cookie = _auth_cookie(env["auth"], user_id="alice@example.com", role="user")

        admin_sessions = client.get(
            "/api/v1/sessions",
            params={"all_profiles": "1"},
            cookies={"hermes_session": admin_cookie},
        )
        assert admin_sessions.status_code == 200
        admin_ids = {row["session_id"] for row in admin_sessions.json()["sessions"]}
        assert {"sessalice", "sessbob"}.issubset(admin_ids)

        alice_sessions = client.get(
            "/api/v1/sessions",
            cookies={"hermes_session": alice_cookie},
        )
        assert alice_sessions.status_code == 200
        alice_ids = {row["session_id"] for row in alice_sessions.json()["sessions"]}
        assert alice_ids == {"sessalice"}

        denied_detail = client.get(
            "/api/v1/session",
            params={"session_id": "sessbob", "messages": "0"},
            cookies={"hermes_session": alice_cookie},
        )
        assert denied_detail.status_code == 404

        allowed_detail = client.get(
            "/api/v1/session",
            params={"session_id": "sessalice", "messages": "0"},
            cookies={"hermes_session": alice_cookie},
        )
        assert allowed_detail.status_code == 200
        assert allowed_detail.json()["session"]["session_id"] == "sessalice"

        admin_workspaces = client.get(
            "/api/v1/workspaces",
            cookies={"hermes_session": admin_cookie},
        )
        assert admin_workspaces.status_code == 200
        admin_paths = {row["path"] for row in admin_workspaces.json()["workspaces"]}

        alice_workspaces = client.get(
            "/api/v1/workspaces",
            cookies={"hermes_session": alice_cookie},
        )
        assert alice_workspaces.status_code == 200
        alice_paths = {row["path"] for row in alice_workspaces.json()["workspaces"]}
        assert alice_paths == {"/workspace"}
        assert admin_paths == {"/workspace"}
        admin_disk = {
            row.get("disk_path") or row["path"]
            for row in admin_workspaces.json()["workspaces"]
        }
        alice_disk = {
            row.get("disk_path") or row["path"]
            for row in alice_workspaces.json()["workspaces"]
        }
        assert admin_disk.isdisjoint(alice_disk) or admin_disk != alice_disk

        denied_list = client.get(
            "/api/v1/list",
            params={"session_id": "sessbob", "path": "."},
            cookies={"hermes_session": alice_cookie},
        )
        assert denied_list.status_code == 404

        allowed_list = client.get(
            "/api/v1/list",
            params={"session_id": "sessalice", "path": "."},
            cookies={"hermes_session": alice_cookie},
        )
        assert allowed_list.status_code == 200
        assert "entries" in allowed_list.json()

        admin_marker = env["hermes_home"] / "workspace" / "admin" / "admin_only.txt"
        admin_marker.write_text("secret", encoding="utf-8")
        alice_marker = env["hermes_home"] / "workspace" / "alice" / "alice_only.txt"
        alice_marker.write_text("mine", encoding="utf-8")

        foreign_list = client.get(
            "/api/v1/list",
            params={
                "workspace": str(env["hermes_home"] / "workspace" / "admin"),
                "path": ".",
            },
            cookies={"hermes_session": alice_cookie},
        )
        assert foreign_list.status_code == 200
        foreign_names = {
            row["name"] for row in foreign_list.json().get("entries", []) if row.get("name")
        }
        assert "alice_only.txt" in foreign_names
        assert "admin_only.txt" not in foreign_names


def test_user_create_session_tags_bound_profile(multi_user_env, monkeypatch):
    """Regular users must own sessions they create (profile tag, not server default)."""
    env = multi_user_env
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(env["state"]))
    monkeypatch.setenv("HERMES_HOME", str(env["hermes_home"]))
    monkeypatch.setenv("HERMES_BASE_HOME", str(env["hermes_home"]))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")

    import app.domain.config as config
    import app.domain.models as models
    import app.domain.workspace as workspace
    import app.domain.profiles as profiles

    config.STATE_DIR = env["state"]
    config.SESSION_DIR = env["session_dir"]
    config.SESSION_INDEX_FILE = env["session_dir"] / "_index.json"
    models.SESSION_DIR = env["session_dir"]
    models.SESSION_INDEX_FILE = env["session_dir"] / "_index.json"
    workspace._default_hermes_home = lambda: env["hermes_home"]  # type: ignore[attr-defined]
    profiles.get_hermes_home_for_profile = lambda name: (
        env["hermes_home"]
        if name in (None, "", "default")
        else env["hermes_home"] / "profiles" / name
    )
    profiles._DEFAULT_HERMES_HOME = env["hermes_home"]
    profiles._active_profile = "default"
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        profiles.get_hermes_home_for_profile,
    )
    monkeypatch.setattr(
        "app.domain.workspace._default_hermes_home",
        lambda: env["hermes_home"],
    )

    app = create_app()
    with TestClient(app) as client:
        alice_cookie = _auth_cookie(env["auth"], user_id="alice@example.com", role="user")
        created = client.post(
            "/api/v1/session/new",
            json={"workspace": "/workspace"},
            cookies={"hermes_session": alice_cookie},
        )
        assert created.status_code == 200
        body = created.json()
        sid = body["session"]["session_id"]
        assert body["session"].get("profile") == "alice"

        detail = client.get(
            "/api/v1/session",
            params={"session_id": sid, "messages": "0"},
            cookies={"hermes_session": alice_cookie},
        )
        assert detail.status_code == 200
        assert detail.json()["session"]["session_id"] == sid
