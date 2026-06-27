"""Multi-user virtual /workspace maps to workspace/<account-slug>/ for every account."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.domain.profiles as profiles_mod
import app.domain.workspace as workspace_mod
from app.domain.users import UserAccess


def _bind_multi_user_workspace_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    hermes_home = tmp_path / ".hermes"
    shared_root = hermes_home / "workspace"
    admin_dir = shared_root / "admin"
    user_dir = shared_root / "user"
    shared_root.mkdir(parents=True)
    admin_dir.mkdir()
    user_dir.mkdir()
    (shared_root / "sensor_data.csv").write_text("ok", encoding="utf-8")

    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_DEFAULT_WORKSPACE", str(shared_root))
    monkeypatch.delenv("HERMES_WEBUI_PROFILE_WORKSPACE", raising=False)
    monkeypatch.setattr(workspace_mod, "_BOOT_DEFAULT_WORKSPACE", str(shared_root))
    profiles_mod._DEFAULT_HERMES_HOME = hermes_home
    return hermes_home, admin_dir, user_dir


def test_admin_virtual_workspace_root_uses_account_slug_subdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home, admin_dir, _user_dir = _bind_multi_user_workspace_layout(
        tmp_path,
        monkeypatch,
    )
    profile_home = hermes_home / "profiles" / "default"
    profile_home.mkdir(parents=True)

    access = UserAccess(
        multi_user_enabled=True,
        user_id="admin@example.com",
        username="admin@example.com",
        role="admin",
        profile_name="admin",
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        disk = workspace_mod.virtual_path_to_disk("/workspace", profile_home)
        assert disk.resolve() == admin_dir.resolve()
        assert (
            workspace_mod.resolve_trusted_workspace("/workspace").resolve()
            == admin_dir.resolve()
        )
        rewritten = workspace_mod.rewrite_virtual_path_in_file_arg(
            "/workspace/sensor_data.csv",
            profile_home=profile_home,
        )
        assert rewritten == str((admin_dir / "sensor_data.csv").resolve())
    finally:
        workspace_mod.clear_request_user_access(token)


def test_user_virtual_workspace_root_uses_account_slug_subdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home, _admin_dir, user_dir = _bind_multi_user_workspace_layout(
        tmp_path,
        monkeypatch,
    )
    profile_home = hermes_home / "users" / "user"
    profile_home.mkdir(parents=True)

    access = UserAccess(
        multi_user_enabled=True,
        user_id="user@example.com",
        username="user@example.com",
        role="user",
        profile_name="user",
        profile_names=("user",),
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        disk = workspace_mod.virtual_path_to_disk("/workspace", profile_home)
        assert disk.resolve() == user_dir.resolve()
        assert (
            workspace_mod.resolve_trusted_workspace("/workspace").resolve()
            == user_dir.resolve()
        )
    finally:
        workspace_mod.clear_request_user_access(token)
