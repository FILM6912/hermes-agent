"""Agent workspace system prompt clarifies shell paths in nested mode."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.domain.workspace as workspace_mod


def test_nested_mode_shows_virtual_workspace_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home = tmp_path / ".hermes"
    profile_home = hermes_home / "profiles" / "user1"
    disk = hermes_home / "workspace" / "user1" / "test"
    disk.mkdir(parents=True)
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("TERMINAL_CWD", str(disk))
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace/test")
    monkeypatch.setattr(workspace_mod, "_default_hermes_home", lambda: hermes_home)
    workspace_mod.clear_request_user_access(workspace_mod.set_request_user_access(None))

    message = workspace_mod.build_workspace_agent_system_message(
        disk,
        profile_home=profile_home,
    )

    assert "Active workspace: /workspace/test" in message
    assert str(disk.resolve()) not in message
    assert "Never use host paths" in message
    assert "Do not emit ``MEDIA:`` tokens" in message
    assert "present_files" in message


def test_legacy_mode_keeps_workspace_tag_authority(tmp_path: Path) -> None:
    disk = tmp_path / "projects" / "demo"
    disk.mkdir(parents=True)

    message = workspace_mod.build_workspace_agent_system_message(disk)

    assert str(disk.resolve()) in message
    assert "[Workspace::v1: ...]" in message
    assert "Never use host paths" not in message
