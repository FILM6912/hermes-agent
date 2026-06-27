"""Tests for /api/v1/admin/users endpoints."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest
from starlette.testclient import TestClient

from app.api.dependencies import admin_user
from app.core.config import get_settings
from app.core.security import CurrentUser
from app.domain.users import USERS_FILE, invalidate_users_cache
from app.main import create_app


def _hermes_home_from_env() -> Path:
    return Path(os.environ["HERMES_HOME"]).resolve()


class _ProfileInfo:
    def __init__(self, name, path, **kwargs):
        self.name = name
        self.path = path
        self.is_default = kwargs.get("is_default", name == "default")


@pytest.fixture
def users_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / "webui"
    hermes_home = tmp_path / ".hermes"
    state_dir.mkdir()
    hermes_home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state_dir))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setattr("app.domain.config.STATE_DIR", state_dir)
    monkeypatch.setattr("app.domain.users.USERS_FILE", state_dir / "users.json")

    import app.domain.profiles as profiles
    import app.domain.workspace as workspace

    profiles = importlib.reload(profiles)
    workspace = importlib.reload(workspace)

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

    get_settings.cache_clear()
    invalidate_users_cache()
    yield state_dir
    invalidate_users_cache()
    get_settings.cache_clear()
    for key in list(sys.modules):
        if key == "hermes_cli" or key.startswith("hermes_cli."):
            del sys.modules[key]


@pytest.fixture
def admin_client(users_state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("app.middleware.security.check_auth_request", lambda request: None)
    app = create_app()

    async def _admin_user() -> CurrentUser:
        return CurrentUser(
            user_id="admin@example.com",
            role="admin",
            profile_name="admin",
            profile_names=("admin",),
        )

    app.dependency_overrides[admin_user] = _admin_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def user_client(users_state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("app.middleware.security.check_auth_request", lambda request: None)
    app = create_app()

    async def _deny_admin() -> CurrentUser:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[admin_user] = _deny_admin
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_list_assignable_profiles(admin_client: TestClient, users_state_dir: Path) -> None:
    admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "zara@example.com",
            "password": "secret-pass",
            "role": "user",
            "profile_name": "zara-profile",
        },
    )
    response = admin_client.get("/api/v1/admin/profiles")
    assert response.status_code == 200
    names = set(response.json().get("profiles") or [])
    assert "zara-profile" in names
    assert "default" not in names


def test_list_users_includes_workspace_path_for_regular_users(
    admin_client: TestClient,
) -> None:
    admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "walt@example.com",
            "password": "secret-pass",
            "role": "user",
            "profile_name": "walt",
        },
    )
    response = admin_client.get("/api/v1/admin/users")
    assert response.status_code == 200
    users = {row["email"]: row for row in response.json()["users"]}
    walt = users["walt@example.com"]
    assert walt["workspace_path"]
    assert isinstance(walt.get("workspaces"), list)
    assert len(walt["workspaces"]) >= 1
    workspace_blob = " ".join(
        str(ws.get("path") or "") for ws in walt["workspaces"]
    ) + str(walt["workspace_path"])
    assert "walt" in workspace_blob or walt["workspace_path"] == "/workspace"
    assert isinstance(walt.get("assigned_profiles"), list)
    assert walt["assigned_profiles"][0]["name"] == "walt"
    assert users.get("admin@example.com", {}).get("workspace_path") in (None, "")


def test_list_users_shows_workspace_per_assigned_profile_legacy_mount(
    admin_client: TestClient,
    users_state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home = _hermes_home_from_env()
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setattr(
        "app.domain.workspace._default_hermes_home",
        lambda: hermes_home,
    )
    shared = hermes_home / "workspace"
    monkeypatch.setattr(
        "app.domain.workspace._shared_workspace_root",
        lambda _home: shared.resolve(),
    )
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "alpha").mkdir()
    (shared / "beta").mkdir()

    admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "multi@example.com",
            "password": "secret-pass",
            "role": "user",
            "profile_name": "alpha",
            "profile_names": ["alpha", "beta"],
        },
    )
    response = admin_client.get("/api/v1/admin/users")
    row = {u["email"]: u for u in response.json()["users"]}["multi@example.com"]
    labels = " ".join(ws["name"] for ws in row["workspaces"])
    paths = " ".join(ws["path"] for ws in row["workspaces"])
    assert len(row["workspaces"]) == 1
    assert "/workspace" in paths or "workspace" in paths


def test_assigned_profiles_share_account_workspace_list(
    users_state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.users import UserAccess
    from app.domain.workspace import (
        list_all_profile_workspaces,
        sync_assigned_profile_workspaces_into_account,
    )

    hermes_home = _hermes_home_from_env()
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setattr(
        "app.domain.workspace._default_hermes_home",
        lambda: hermes_home,
    )
    shared = hermes_home / "workspace"
    monkeypatch.setattr(
        "app.domain.workspace._shared_workspace_root",
        lambda _home: shared.resolve(),
    )
    (shared / "shared").mkdir(parents=True, exist_ok=True)
    (hermes_home / "profiles" / "alpha").mkdir(parents=True, exist_ok=True)
    (hermes_home / "profiles" / "beta").mkdir(parents=True, exist_ok=True)

    email = "shared@example.com"
    sync_assigned_profile_workspaces_into_account(
        email,
        ["alpha", "beta"],
        primary_profile_name="alpha",
    )
    access_alpha = UserAccess(
        multi_user_enabled=True,
        user_id=email,
        username=email,
        role="user",
        profile_name="alpha",
        profile_names=("alpha", "beta"),
    )
    access_beta = UserAccess(
        multi_user_enabled=True,
        user_id=email,
        username=email,
        role="user",
        profile_name="beta",
        profile_names=("alpha", "beta"),
    )
    paths_alpha = {row["path"] for row in list_all_profile_workspaces(access=access_alpha)}
    paths_beta = {row["path"] for row in list_all_profile_workspaces(access=access_beta)}
    assert paths_alpha == paths_beta
    assert paths_alpha == {"/workspace"}


def test_admin_workspace_rename_and_delete(
    admin_client: TestClient,
    users_state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    hermes_home = _hermes_home_from_env()
    monkeypatch.setattr(
        "app.domain.workspace._default_hermes_home",
        lambda: hermes_home,
    )
    shared = hermes_home / "workspace"
    shared.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "app.domain.workspace._shared_workspace_root",
        lambda _home: shared.resolve(),
    )
    (shared / "admin").mkdir()

    rename_resp = admin_client.patch(
        "/api/v1/admin/workspaces",
        json={"path": "workspace/admin", "name": "admin-renamed"},
    )
    assert rename_resp.status_code == 200
    names = {row["name"] for row in rename_resp.json()["workspaces"]}
    assert "admin-renamed" in names
    assert (shared / "admin-renamed").is_dir()
    assert not (shared / "admin").exists()

    delete_resp = admin_client.request(
        "DELETE",
        "/api/v1/admin/workspaces",
        json={"path": "workspace/admin-renamed"},
    )
    assert delete_resp.status_code == 200
    assert "admin-renamed" not in {row["name"] for row in delete_resp.json()["workspaces"]}
    assert not (shared / "admin-renamed").exists()


def test_patch_user_workspace_paths(
    admin_client: TestClient,
    users_state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    hermes_home = _hermes_home_from_env()
    monkeypatch.setattr(
        "app.domain.workspace._default_hermes_home",
        lambda: hermes_home,
    )
    shared = hermes_home / "workspace"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "multi").mkdir()
    monkeypatch.setattr(
        "app.domain.workspace._shared_workspace_root",
        lambda _home: shared.resolve(),
    )

    admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "picker@example.com",
            "password": "secret-pass",
            "role": "user",
            "profile_name": "alpha",
            "profile_names": ["alpha", "beta"],
        },
    )
    detail = admin_client.get("/api/v1/admin/users/picker@example.com").json()
    paths = [row["path"] for row in detail.get("available_workspaces") or []]
    assert "/workspace" in paths

    patch_resp = admin_client.patch(
        "/api/v1/admin/users/picker@example.com",
        json={"workspace_paths": ["/workspace"]},
    )
    assert patch_resp.status_code == 200
    after = admin_client.get("/api/v1/admin/users/picker@example.com").json()
    saved = {row["path"] for row in after.get("workspaces") or []}
    assert "/workspace" in saved


def test_list_users_empty(admin_client: TestClient) -> None:
    response = admin_client.get("/api/v1/admin/users")
    assert response.status_code == 200
    assert response.json() == {"users": []}


def test_create_list_get_update_delete_user(admin_client: TestClient, users_state_dir: Path) -> None:
    create_resp = admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "alice@example.com",
            "password": "secret-pass",
            "role": "user",
            "profile_name": "alice-profile",
            "department": "Engineering",
            "position": "Developer",
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()["user"]
    assert created["email"] == "alice@example.com"
    assert created["role"] == "user"
    assert created["profile_name"] == "alice-profile"
    assert created["department"] == "Engineering"
    assert created["position"] == "Developer"
    assert created["created_at"] is not None

    list_resp = admin_client.get("/api/v1/admin/users")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["users"]) == 1

    detail_resp = admin_client.get("/api/v1/admin/users/alice@example.com")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["profile"] == {"name": "alice-profile"}
    assert detail["session_summary"] == {"total": 0, "active": 0, "archived": 0}

    patch_resp = admin_client.patch(
        "/api/v1/admin/users/alice@example.com",
        json={"role": "admin"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["user"]["role"] == "admin"
    assert patch_resp.json()["user"]["profile_name"] is None

    rename_resp = admin_client.patch(
        "/api/v1/admin/users/alice@example.com",
        json={
            "email": "alice.wonder@example.com",
            "display_name": "Alice",
            "department": "R&D",
        },
    )
    assert rename_resp.status_code == 200
    renamed = rename_resp.json()["user"]
    assert renamed["email"] == "alice.wonder@example.com"
    assert renamed["display_name"] == "Alice"
    assert renamed["department"] == "R&D"
    assert admin_client.get("/api/v1/admin/users/alice@example.com").status_code == 404
    assert admin_client.get("/api/v1/admin/users/alice.wonder@example.com").status_code == 200

    delete_resp = admin_client.delete("/api/v1/admin/users/alice.wonder@example.com")
    assert delete_resp.status_code == 204
    assert admin_client.get("/api/v1/admin/users").json()["users"] == []


def test_create_admin_user_without_profile(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "root@example.com",
            "password": "admin-pass",
            "role": "admin",
        },
    )
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "admin"
    assert response.json()["user"]["profile_name"] is None


def test_create_user_defaults_profile_for_user_role(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "bob@example.com",
            "password": "secret-pass",
            "role": "user",
        },
    )
    assert response.status_code == 201
    created = response.json()["user"]
    assert created["role"] == "user"
    assert created["profile_name"] == "bob"


def test_duplicate_email_rejected(admin_client: TestClient) -> None:
    payload = {
        "email": "carol@example.com",
        "password": "secret-pass",
        "role": "user",
        "profile_name": "carol-profile",
    }
    assert admin_client.post("/api/v1/admin/users", json=payload).status_code == 201
    dup = admin_client.post("/api/v1/admin/users", json=payload)
    assert dup.status_code == 409


def test_duplicate_profile_binding_rejected(admin_client: TestClient) -> None:
    first = admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "dana@example.com",
            "password": "secret-pass",
            "role": "user",
            "profile_name": "shared-profile",
        },
    )
    assert first.status_code == 201
    second = admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "erin@example.com",
            "password": "secret-pass",
            "role": "user",
            "profile_name": "shared-profile",
        },
    )
    assert second.status_code == 409


def test_create_user_with_multiple_profile_names(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "multi@example.com",
            "password": "secret-pass",
            "role": "user",
            "profile_name": "multi-primary",
            "profile_names": ["multi-primary", "multi-secondary"],
        },
    )
    assert response.status_code == 201
    user = response.json()["user"]
    assert user["profile_name"] == "multi-primary"
    assert user["profile_names"] == ["multi-primary", "multi-secondary"]

    patch_resp = admin_client.patch(
        "/api/v1/admin/users/multi@example.com",
        json={"profile_names": ["multi-primary", "multi-secondary", "multi-tertiary"]},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["user"]["profile_names"] == [
        "multi-primary",
        "multi-secondary",
        "multi-tertiary",
    ]


def test_assign_builtin_default_profile_rejected(admin_client: TestClient) -> None:
    admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "norma@example.com",
            "password": "secret-pass",
            "role": "user",
            "profile_name": "norma-profile",
        },
    )
    response = admin_client.patch(
        "/api/v1/admin/users/norma@example.com",
        json={
            "profile_name": "default",
            "profile_names": ["default", "norma-profile"],
        },
    )
    assert response.status_code == 400
    assert "default profile" in response.json()["detail"].lower()


def test_non_admin_forbidden(user_client: TestClient) -> None:
    response = user_client.get("/api/v1/admin/users")
    assert response.status_code == 403
    assert response.json()["error"] == "Admin access required"


def test_get_missing_user_returns_404(admin_client: TestClient) -> None:
    response = admin_client.get("/api/v1/admin/users/missing@example.com")
    assert response.status_code == 404


def test_patch_without_fields_returns_400(admin_client: TestClient) -> None:
    admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "frank@example.com",
            "password": "secret-pass",
            "role": "user",
            "profile_name": "frank-profile",
        },
    )
    response = admin_client.patch("/api/v1/admin/users/frank@example.com", json={})
    assert response.status_code == 400


def test_users_file_persisted(users_state_dir: Path, admin_client: TestClient) -> None:
    admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "grace@example.com",
            "password": "secret-pass",
            "role": "user",
            "profile_name": "grace-profile",
        },
    )
    users_file = users_state_dir / "users.json"
    assert users_file.exists()
    payload = json.loads(users_file.read_text(encoding="utf-8"))
    assert "grace@example.com" in payload.get("users", {})
    row = payload["users"]["grace@example.com"]
    assert row.get("email") == "grace@example.com"


def test_login_accepts_email_field(admin_client: TestClient, users_state_dir: Path) -> None:
    admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "login@example.com",
            "password": "secret-pass",
            "role": "admin",
        },
    )
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "secret-pass"},
        )
    assert resp.status_code == 200
    assert resp.json()["email"] == "login@example.com"


def test_login_legacy_username_field_alias(admin_client: TestClient) -> None:
    admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "legacy@example.com",
            "password": "secret-pass",
            "role": "admin",
        },
    )
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "legacy@example.com", "password": "secret-pass"},
        )
    assert resp.status_code == 200
    assert resp.json()["email"] == "legacy@example.com"


def test_patch_display_name_only_preserves_email_legacy_row(
    admin_client: TestClient,
    users_state_dir: Path,
) -> None:
    """Legacy rows may store login id in ``username`` only; partial PATCH must not clear email."""
    email = "legacyrow@example.com"
    store = {
        "version": 1,
        "users": {
            email: {
                "username": email,
                "role": "admin",
                "password_hash": "deadbeef",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        },
        "profile_bindings": {},
    }
    users_path = users_state_dir / "users.json"
    users_path.write_text(json.dumps(store), encoding="utf-8")
    invalidate_users_cache()

    resp = admin_client.patch(
        f"/api/v1/admin/users/{email}",
        json={"display_name": "Legacy Display"},
    )
    assert resp.status_code == 200
    user = resp.json()["user"]
    assert user["email"] == email
    assert user["display_name"] == "Legacy Display"

    on_disk = json.loads(users_path.read_text(encoding="utf-8"))
    row = on_disk["users"][email]
    assert row.get("email") == email


def test_user_update_stamps_updated_by_request_actor(
    users_state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain import users as users_domain
    from app.domain.users import UserAccess
    from app.domain.workspace import clear_request_user_access, set_request_user_access

    users_domain.create_user(
        "target@example.com",
        password="secret-pass",
        role="admin",
    )
    access = UserAccess(
        multi_user_enabled=True,
        user_id="admin@example.com",
        username="admin@example.com",
        role="admin",
        profile_name=None,
        profile_names=(),
    )
    token = set_request_user_access(access)
    try:
        updated = users_domain.update_user(
            "target@example.com",
            display_name="Updated Name",
        )
    finally:
        clear_request_user_access(token)

    assert updated["updated_by"] == "admin@example.com"
    assert updated["updated_at"] is not None

    on_disk = json.loads((users_state_dir / "users.json").read_text(encoding="utf-8"))
    row = on_disk["users"]["target@example.com"]
    assert row["updated_by"] == "admin@example.com"


def test_get_user_detail_includes_audit_fields(admin_client: TestClient) -> None:
    admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "audit@example.com",
            "password": "secret-pass",
            "role": "admin",
        },
    )
    detail = admin_client.get("/api/v1/admin/users/audit@example.com").json()
    assert detail["created_at"] is not None
    assert "created_by" in detail
    assert "updated_by" in detail
    assert "updated_at" in detail

    patch_resp = admin_client.patch(
        "/api/v1/admin/users/audit@example.com",
        json={"display_name": "Audit User"},
    )
    assert patch_resp.status_code == 200
    user = patch_resp.json()["user"]
    assert user.get("updated_at") is not None
    assert "updated_by" in user

    refreshed = admin_client.get("/api/v1/admin/users/audit@example.com").json()
    assert refreshed.get("display_name") == "Audit User"
    assert refreshed.get("updated_at") is not None
    assert refreshed.get("updated_by") is not None
