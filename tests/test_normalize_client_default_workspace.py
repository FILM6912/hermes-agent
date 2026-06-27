"""Regression: multi-user settings expose virtual default_workspace to the React shell."""

from pathlib import Path
from types import SimpleNamespace

from app.domain.users import UserAccess
from app.domain.workspace import (
    VIRTUAL_WORKSPACE_ROOT,
    normalize_client_default_workspace,
    resolve_trusted_workspace,
    set_request_user_access,
    clear_request_user_access,
)


def test_normalize_maps_profile_subdir_to_virtual_root(monkeypatch, tmp_path):
    profile_home = tmp_path / "profiles" / "admin"
    shared_root = tmp_path / "workspace"
    profile_ws = shared_root / "admin"
    profile_ws.mkdir(parents=True)

    monkeypatch.setattr(
        "app.domain.workspace.nested_workspaces_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda _name: profile_home,
    )
    monkeypatch.setattr(
        "app.domain.workspace.profile_workspace_dir",
        lambda _home, access=None: profile_ws,
    )
    monkeypatch.setattr(
        "app.domain.workspace.disk_path_to_virtual",
        lambda *_args, **_kwargs: None,
    )

    settings = {"default_workspace": str(shared_root)}
    access = SimpleNamespace(
        multi_user_enabled=True,
        profile_name="admin",
        restricts_profiles=False,
        user_id="admin@example.com",
        username="admin@example.com",
    )
    normalize_client_default_workspace(settings, access)
    assert settings["default_workspace"] == VIRTUAL_WORKSPACE_ROOT


def test_normalize_maps_exact_disk_path_to_virtual(monkeypatch, tmp_path):
    profile_home = tmp_path / "profiles" / "admin"
    profile_ws = tmp_path / "workspace" / "admin"
    profile_ws.mkdir(parents=True)

    monkeypatch.setattr(
        "app.domain.workspace.nested_workspaces_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda _name: profile_home,
    )
    monkeypatch.setattr(
        "app.domain.workspace.disk_path_to_virtual",
        lambda disk, _home=None, access=None: VIRTUAL_WORKSPACE_ROOT
        if Path(disk) == profile_ws
        else None,
    )

    settings = {"default_workspace": str(profile_ws)}
    access = SimpleNamespace(
        multi_user_enabled=True,
        profile_name="admin",
        restricts_profiles=False,
        user_id="admin@example.com",
        username="admin@example.com",
    )
    normalize_client_default_workspace(settings, access)
    assert settings["default_workspace"] == VIRTUAL_WORKSPACE_ROOT


def test_normalize_remaps_foreign_admin_default_for_regular_user(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    admin_ws.mkdir(parents=True)
    pathom_ws.mkdir(parents=True)

    monkeypatch.setattr(
        "app.domain.workspace.nested_workspaces_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.domain.workspace._default_hermes_home",
        lambda: hermes_home,
    )
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda name: hermes_home / "profiles" / name,
    )
    monkeypatch.setattr(
        "app.domain.workspace.profile_workspace_dir",
        lambda _home, access=None: pathom_ws,
    )
    monkeypatch.setattr(
        "app.domain.workspace.disk_path_to_virtual",
        lambda *_args, **_kwargs: None,
    )

    settings = {"default_workspace": str(admin_ws)}
    access = UserAccess(
        multi_user_enabled=True,
        user_id="pathom_u@example.com",
        username="pathom_u@example.com",
        role="user",
        profile_name="admin",
    )
    normalize_client_default_workspace(settings, access)
    assert settings["default_workspace"] == VIRTUAL_WORKSPACE_ROOT


def test_normalize_maps_admin_disk_to_virtual_root_not_workspace_admin(
    monkeypatch,
    tmp_path,
):
    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    admin_ws.mkdir(parents=True)
    pathom_ws.mkdir(parents=True)
    (hermes_home / "profiles" / "pathom_u").mkdir(parents=True)

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda name: hermes_home / "profiles" / name,
    )

    access = UserAccess(
        multi_user_enabled=True,
        user_id="pathom_u@example.com",
        username="pathom_u@example.com",
        role="user",
        profile_name="admin",
        profile_names=("admin",),
    )
    settings = {"default_workspace": str(admin_ws)}
    normalize_client_default_workspace(settings, access)
    assert settings["default_workspace"] == VIRTUAL_WORKSPACE_ROOT


def test_resolve_trusted_workspace_remaps_foreign_admin_disk_path(
    monkeypatch,
    tmp_path,
):
    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    admin_ws.mkdir(parents=True)
    pathom_ws.mkdir(parents=True)
    (admin_ws / "secret.txt").write_text("nope", encoding="utf-8")
    (pathom_ws / "mine.txt").write_text("ok", encoding="utf-8")
    (hermes_home / "profiles" / "pathom_u").mkdir(parents=True)

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setattr("app.domain.workspace.nested_workspaces_enabled", lambda: True)
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda name: hermes_home / "profiles" / name,
    )
    monkeypatch.setattr(
        "app.domain.workspace.profile_workspace_dir",
        lambda _home, access=None: pathom_ws,
    )

    access = UserAccess(
        multi_user_enabled=True,
        user_id="pathom_u@example.com",
        username="pathom_u@example.com",
        role="user",
        profile_name="admin",
        profile_names=("admin",),
    )
    token = set_request_user_access(access)
    try:
        resolved = resolve_trusted_workspace(str(admin_ws))
        assert resolved.resolve() == pathom_ws.resolve()
        entries = {p.name for p in resolved.iterdir()}
        assert "mine.txt" in entries
        assert "secret.txt" not in entries
    finally:
        clear_request_user_access(token)


def test_resolve_trusted_workspace_remaps_foreign_admin_for_admin_role(
    monkeypatch,
    tmp_path,
):
    """Admin accounts still use per-user workspace trees, not shared profile folders."""
    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    admin_ws.mkdir(parents=True)
    pathom_ws.mkdir(parents=True)
    (admin_ws / "secret.txt").write_text("nope", encoding="utf-8")
    (pathom_ws / "mine.txt").write_text("ok", encoding="utf-8")
    (hermes_home / "profiles" / "admin").mkdir(parents=True)
    (hermes_home / "profiles" / "pathom_u").mkdir(parents=True)

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setattr("app.domain.workspace.nested_workspaces_enabled", lambda: True)
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr("app.domain.profiles._DEFAULT_HERMES_HOME", hermes_home)
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda name: hermes_home / "profiles" / name,
    )
    monkeypatch.setattr(
        "app.domain.workspace.profile_workspace_dir",
        lambda _home, access=None: pathom_ws,
    )

    access = UserAccess(
        multi_user_enabled=True,
        user_id="pathom_u@example.com",
        username="pathom_u@example.com",
        role="admin",
        profile_name="admin",
        profile_names=("admin",),
    )
    token = set_request_user_access(access)
    try:
        resolved = resolve_trusted_workspace(str(admin_ws))
        assert resolved.resolve() == pathom_ws.resolve()
        entries = {p.name for p in resolved.iterdir()}
        assert "mine.txt" in entries
        assert "secret.txt" not in entries
    finally:
        clear_request_user_access(token)


def test_resolve_trusted_workspace_uses_account_slug_not_bound_profile(
    monkeypatch,
    tmp_path,
):
    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    admin_ws.mkdir(parents=True)
    pathom_ws.mkdir(parents=True)

    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(
        "app.domain.workspace._default_hermes_home",
        lambda: hermes_home,
    )
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda name: hermes_home / "profiles" / name,
    )
    monkeypatch.setattr(
        "app.domain.workspace.profile_workspace_dir",
        lambda _home, access=None: pathom_ws,
    )

    access = UserAccess(
        multi_user_enabled=True,
        user_id="pathom_u@example.com",
        username="pathom_u@example.com",
        role="user",
        profile_name="admin",
    )
    token = set_request_user_access(access)
    try:
        resolved = resolve_trusted_workspace(VIRTUAL_WORKSPACE_ROOT)
        assert resolved.resolve() == pathom_ws.resolve()
    finally:
        clear_request_user_access(token)
