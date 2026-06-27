"""Multi-user workspace resolution must not probe foreign profile homes."""

from __future__ import annotations

import os
import pathlib

import pytest

import app.domain.workspace as workspace_mod
from app.domain.users import UserAccess


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX only")
def test_owning_profile_homes_skips_unreadable_foreign_profile(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home = tmp_path / ".hermes"
    admin_profile = hermes_home / "profiles" / "admin"
    pathom_profile = hermes_home / "profiles" / "pathom_u"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    admin_profile.mkdir(parents=True)
    pathom_profile.mkdir(parents=True)
    admin_ws.mkdir(parents=True)
    pathom_ws.mkdir(parents=True)

    other_uid = os.getuid() + 1 if os.getuid() < 65534 else max(os.getuid() - 1, 1)
    try:
        os.chown(admin_profile, other_uid, os.getgid())
        os.chmod(admin_profile, 0o700)
    except PermissionError:
        pytest.skip("test user cannot chown directories for permission simulation")

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

    access = UserAccess(
        multi_user_enabled=True,
        user_id="pathom_u@example.com",
        username="pathom_u@example.com",
        role="user",
        profile_name="admin",
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        homes = workspace_mod._owning_profile_homes_for_workspace(admin_ws)
        assert pathom_profile.resolve() in homes
        assert admin_profile.resolve() not in homes
    finally:
        workspace_mod.clear_request_user_access(token)


def test_resolve_trusted_workspace_remaps_foreign_admin_disk_path_for_admin_role(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    admin_ws.mkdir(parents=True)
    pathom_ws.mkdir(parents=True)
    (hermes_home / "profiles" / "admin").mkdir(parents=True)
    (hermes_home / "profiles" / "pathom_u").mkdir(parents=True)

    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(
        "app.domain.workspace._default_hermes_home",
        lambda: hermes_home,
    )
    monkeypatch.setattr("app.domain.profiles._DEFAULT_HERMES_HOME", hermes_home)
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda name: hermes_home / "profiles" / name,
    )
    monkeypatch.setattr(
        "app.domain.workspace.profile_workspace_dir",
        lambda _home, access=None: pathom_ws,
    )
    monkeypatch.setattr(
        workspace_mod,
        "_BOOT_DEFAULT_WORKSPACE",
        str(hermes_home / "workspace"),
    )

    access = UserAccess(
        multi_user_enabled=True,
        user_id="pathom_u@example.com",
        username="pathom_u@example.com",
        role="admin",
        profile_name="admin",
        profile_names=("admin",),
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        resolved = workspace_mod.resolve_trusted_workspace(str(admin_ws))
        assert resolved.resolve() == pathom_ws.resolve()
    finally:
        workspace_mod.clear_request_user_access(token)


def test_resolve_trusted_workspace_remaps_foreign_admin_disk_path(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    monkeypatch.setattr(
        workspace_mod,
        "_BOOT_DEFAULT_WORKSPACE",
        str(hermes_home / "workspace"),
    )

    access = UserAccess(
        multi_user_enabled=True,
        user_id="pathom_u@example.com",
        username="pathom_u@example.com",
        role="user",
        profile_name="admin",
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        resolved = workspace_mod.resolve_trusted_workspace(str(admin_ws))
        assert resolved.resolve() == pathom_ws.resolve()
    finally:
        workspace_mod.clear_request_user_access(token)


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX only")
def test_resolve_trusted_workspace_survives_unreadable_foreign_profile_home(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home = tmp_path / ".hermes"
    admin_profile = hermes_home / "profiles" / "admin"
    pathom_profile = hermes_home / "profiles" / "pathom_u"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    admin_profile.mkdir(parents=True)
    pathom_profile.mkdir(parents=True)
    admin_ws.mkdir(parents=True)
    pathom_ws.mkdir(parents=True)

    other_uid = os.getuid() + 1 if os.getuid() < 65534 else max(os.getuid() - 1, 1)
    try:
        os.chown(admin_profile, other_uid, os.getgid())
        os.chmod(admin_profile, 0o700)
    except PermissionError:
        pytest.skip("test user cannot chown directories for permission simulation")

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
    monkeypatch.setattr(
        workspace_mod,
        "_BOOT_DEFAULT_WORKSPACE",
        str(hermes_home / "workspace"),
    )

    access = UserAccess(
        multi_user_enabled=True,
        user_id="pathom_u@example.com",
        username="pathom_u@example.com",
        role="user",
        profile_name="admin",
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        resolved = workspace_mod.resolve_trusted_workspace(str(admin_ws))
        assert resolved.resolve() == pathom_ws.resolve()
    finally:
        workspace_mod.clear_request_user_access(token)
