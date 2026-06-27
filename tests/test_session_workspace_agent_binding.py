"""Agent runs must stay bound to the session-selected workspace.

Hermes file/terminal tools read process-global ``TERMINAL_CWD``. After
``_run_agent_streaming`` releases ``_ENV_LOCK``, a concurrent session can
clobber that value; tool execution must re-pin the active session workspace.
"""
from __future__ import annotations

import os
import pathlib
from pathlib import Path

import pytest


def test_pin_process_agent_env_overrides_stale_terminal_cwd(tmp_path, monkeypatch):
    from app.domain.streaming import (
        _ENV_LOCK,
        _build_agent_thread_env,
        _pin_process_agent_env,
    )

    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()

    thread_env = _build_agent_thread_env(
        {"TERMINAL_CWD": "/profile/config/cwd", "TERMINAL_ENV": "local"},
        str(workspace_a),
        "session-a",
        str(tmp_path / "home-a"),
    )

    monkeypatch.setenv("TERMINAL_CWD", str(workspace_b))

    _pin_process_agent_env(thread_env)
    assert os.environ["TERMINAL_CWD"] == str(workspace_a.resolve())

    # Another concurrent session clobbered process env mid-run.
    with _ENV_LOCK:
        os.environ["TERMINAL_CWD"] = str(workspace_b)

    _pin_process_agent_env(thread_env)
    assert os.environ["TERMINAL_CWD"] == str(workspace_a.resolve())


def test_tool_start_reapplies_session_workspace_env():
    src = Path("app/domain/streaming.py").read_text(encoding="utf-8")
    start = src.index("def on_tool_start(tool_call_id, name, args):")
    end = src.index("\n            def on_tool_complete", start)
    block = src[start:end]
    assert "_pin_process_agent_env(_thread_env)" in block, (
        "on_tool_start must re-pin TERMINAL_CWD before Hermes tools execute"
    )


def test_run_agent_streaming_resolves_trusted_workspace_for_session(monkeypatch, tmp_path):
    from app.domain.streaming import _resolve_agent_session_workspace

    workspace = tmp_path / "project-x"
    workspace.mkdir()

    def fake_resolve(value):
        assert value == str(workspace)
        return workspace.resolve()

    monkeypatch.setattr(
        "app.domain.workspace.resolve_trusted_workspace",
        fake_resolve,
    )

    assert _resolve_agent_session_workspace(str(workspace)) == str(workspace.resolve())


def test_agent_workspace_resolves_admin_virtual_path_without_user_access(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admin default workspace: agent TERMINAL_CWD must match file sidebar ``.uploads/``."""
    from app.domain.streaming import _resolve_agent_session_workspace
    from app.domain.workspace import list_dir

    hermes_home = tmp_path / ".hermes"
    shared_root = hermes_home / "workspace"
    admin_dir = shared_root / "admin"
    uploads = admin_dir / ".uploads"
    uploads.mkdir(parents=True)
    image = uploads / "fp4_compare.png"
    image.write_bytes(b"png-bytes")

    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_ADMIN_USER", "admin@aitech.co.th")
    monkeypatch.setenv("HERMES_WEBUI_DEFAULT_WORKSPACE", str(shared_root))
    monkeypatch.delenv("HERMES_WEBUI_PROFILE_WORKSPACE", raising=False)
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr("app.domain.profiles._DEFAULT_HERMES_HOME", hermes_home)
    monkeypatch.setattr("app.domain.workspace._BOOT_DEFAULT_WORKSPACE", str(shared_root))

    resolved = Path(
        _resolve_agent_session_workspace(
            "/workspace",
            profile="default",
            profile_home=hermes_home,
        )
    )
    assert resolved == admin_dir.resolve()

    entries = list_dir(resolved, ".uploads")
    names = {entry["name"] for entry in entries}
    assert "fp4_compare.png" in names


def test_agent_workspace_matches_file_list_for_admin_uploads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """File list API and agent workspace must share the same ``.uploads/`` tree."""
    from app.domain.streaming import _resolve_agent_session_workspace
    from app.domain.users import UserAccess
    from app.domain.workspace import (
        clear_request_user_access,
        list_dir,
        resolve_trusted_workspace,
        set_request_user_access,
    )

    hermes_home = tmp_path / ".hermes"
    shared_root = hermes_home / "workspace"
    admin_dir = shared_root / "admin"
    uploads = admin_dir / ".uploads"
    uploads.mkdir(parents=True)
    (uploads / "fp4_compare.png").write_bytes(b"png")

    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_ADMIN_USER", "admin@aitech.co.th")
    monkeypatch.setenv("HERMES_WEBUI_DEFAULT_WORKSPACE", str(shared_root))
    monkeypatch.delenv("HERMES_WEBUI_PROFILE_WORKSPACE", raising=False)
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr("app.domain.profiles._DEFAULT_HERMES_HOME", hermes_home)
    monkeypatch.setattr("app.domain.workspace._BOOT_DEFAULT_WORKSPACE", str(shared_root))

    access = UserAccess(
        multi_user_enabled=True,
        user_id="admin@aitech.co.th",
        username="admin@aitech.co.th",
        role="admin",
        profile_name=None,
    )
    token = set_request_user_access(access)
    try:
        list_root = resolve_trusted_workspace("/workspace")
    finally:
        clear_request_user_access(token)

    agent_root = Path(
        _resolve_agent_session_workspace(
            "/workspace",
            profile="default",
            profile_home=hermes_home,
        )
    )
    assert agent_root == list_root.resolve()
    assert {e["name"] for e in list_dir(agent_root, ".uploads")} == {"fp4_compare.png"}
