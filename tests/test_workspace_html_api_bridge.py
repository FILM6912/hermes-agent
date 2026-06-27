"""Workspace HTML API bridge and agent guidance for live dashboard data."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.domain.workspace as workspace_mod


def test_inline_relative_workspace_script(tmp_path: Path) -> None:
    ws = tmp_path / "admin"
    ws.mkdir()
    (ws / "ProjectMonitor.js").write_text("window.PROJECT = true;\n", encoding="utf-8")
    html = '<html><head></head><body><script src="ProjectMonitor.js"></script></body></html>'
    out = workspace_mod._inline_workspace_relative_scripts(
        html,
        workspace_root=ws,
        html_disk_path=ws / "index.html",
    )
    assert 'src="ProjectMonitor.js"' not in out
    assert "window.PROJECT = true" in out


def test_resolve_broken_api_file_script_path() -> None:
    rel = workspace_mod._workspace_relative_asset_path(
        "/api/v1/file/ProjectMonitor.js",
        workspace_root=Path("/tmp/ws"),
        html_disk_path=Path("/tmp/ws/index.html"),
    )
    assert rel == "ProjectMonitor.js"


def test_inject_workspace_html_bridge_adds_hermes_helpers() -> None:
    raw = b"<!DOCTYPE html><html><head></head><body><h1>Dash</h1></body></html>"
    out = workspace_mod.inject_workspace_html_preview_enhancements(
        raw,
        workspace_virtual="/workspace",
    ).decode("utf-8")
    assert "hermesLoadText" in out
    assert "hermesLoadJson" in out
    assert '"/workspace"' in out
    assert "<base target" in out
    assert "patchStorage" in out
    assert out.index("patchStorage") < out.index("hermesLoadText")


def test_inject_skips_bridge_without_virtual_workspace() -> None:
    raw = b"<html><body>hi</body></html>"
    out = workspace_mod.inject_workspace_html_preview_enhancements(raw).decode("utf-8")
    assert "hermesLoadText" not in out
    assert "<base target" in out
    assert "patchStorage" in out


def test_system_message_documents_workspace_api_and_hermes_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home = tmp_path / ".hermes"
    profile_home = hermes_home / "profiles" / "admin"
    disk = hermes_home / "workspace" / "admin"
    disk.mkdir(parents=True)
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("TERMINAL_CWD", str(disk))
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace")
    workspace_mod.clear_request_user_access(workspace_mod.set_request_user_access(None))

    message = workspace_mod.build_workspace_agent_system_message(
        disk,
        profile_home=profile_home,
    )
    assert "/api/v1/list?workspace=/workspace" in message
    assert "hermesLoadText" in message
    assert "hermesLoadJson" in message
