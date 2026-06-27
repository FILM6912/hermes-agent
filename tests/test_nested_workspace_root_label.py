"""Nested workspace root picker label uses the signed-in account slug."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.domain.workspace as workspace_mod


def test_nested_root_display_name_uses_account_slug(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home = tmp_path / ".hermes"
    admin_home = hermes_home / "profiles" / "admin"
    admin_home.mkdir(parents=True)
    (hermes_home / "workspace" / "admin").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_WORKSPACE_NAME", "Home")

    from app.domain.users import UserAccess

    access = UserAccess(
        multi_user_enabled=True,
        role="admin",
        user_id="admin@example.com",
        username="admin@example.com",
        profile_name="admin",
        profile_names=("admin",),
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        state_dir = hermes_home / "users" / "admin" / "webui_state"
        state_dir.mkdir(parents=True)
        ws_file = state_dir / "workspaces.json"
        ws_file.write_text(
            json.dumps([{"path": "/workspace", "name": "user"}], ensure_ascii=False),
            encoding="utf-8",
        )

        loaded = workspace_mod.load_workspaces_for_profile(admin_home)
        root = next(row for row in loaded if row["path"] == "/workspace")
        assert root["name"] == "admin"
    finally:
        workspace_mod.clear_request_user_access(token)
