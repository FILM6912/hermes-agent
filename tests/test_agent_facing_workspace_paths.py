"""Agent-facing workspace paths stay virtual; containment avoids quoted-root false positives."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.domain.profiles as profiles_mod
import app.domain.workspace as workspace_mod
from app.domain.streaming import _sanitize_messages_for_api, _workspace_context_prefix


def _bind_nested_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    hermes_home = tmp_path / ".hermes"
    profile_home = hermes_home / "profiles" / "admin"
    account_root = hermes_home / "workspace" / "admin"
    nested = account_root / "test"
    nested.mkdir(parents=True)
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT", str(account_root))
    monkeypatch.setenv("TERMINAL_CWD", str(nested))
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace/test")
    profiles_mod._DEFAULT_HERMES_HOME = hermes_home
    workspace_mod.clear_request_user_access(workspace_mod.set_request_user_access(None))
    return profile_home, account_root, nested


def test_agent_facing_workspace_path_maps_disk_to_virtual(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_home, account_root, nested = _bind_nested_workspace(tmp_path, monkeypatch)
    assert workspace_mod.agent_facing_workspace_path(
        nested,
        profile_home=profile_home,
        active_workspace_virtual="/workspace/test",
    ) == "/workspace/test"
    assert workspace_mod.agent_facing_workspace_path(
        account_root,
        profile_home=profile_home,
    ) == "/workspace"


def test_workspace_prefix_uses_virtual_path_not_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_home, account_root, nested = _bind_nested_workspace(tmp_path, monkeypatch)
    prefix = _workspace_context_prefix(
        str(nested),
        profile_home=profile_home,
        active_workspace_virtual="/workspace/test",
    )
    assert prefix.startswith("[Workspace::v1: /workspace/test]")
    assert str(nested) not in prefix
    assert str(account_root) not in prefix


def test_nested_system_message_hides_disk_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_home, account_root, nested = _bind_nested_workspace(tmp_path, monkeypatch)
    message = workspace_mod.build_workspace_agent_system_message(
        nested,
        profile_home=profile_home,
    )
    assert "Active workspace: /workspace/test" in message
    assert str(account_root) not in message
    assert str(nested) not in message
    assert "Never use host paths" in message


def test_execute_code_rewrites_workspace_csv_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_home, account_root, _nested = _bind_nested_workspace(tmp_path, monkeypatch)
    code = (
        "import pandas as pd\n"
        "df = pd.read_csv('/workspace/MR011x_2026.01.12_ProjectMonitor_V01_2026.csv')\n"
    )
    rewritten = workspace_mod.rewrite_virtual_paths_in_shell_command(
        code,
        profile_home=profile_home,
    )
    assert "'/workspace/MR011x" not in rewritten
    assert str(account_root / "MR011x_2026.01.12_ProjectMonitor_V01_2026.csv") in rewritten


def test_execute_code_allows_quoted_root_separator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_nested_workspace(tmp_path, monkeypatch)
    code = 'parts = "a/b/c".split("/")\npath = "/" + name'
    rewritten = workspace_mod.rewrite_virtual_paths_in_shell_command(code)
    assert rewritten == code


def test_shell_still_blocks_unquoted_cd_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_nested_workspace(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="filesystem root"):
        workspace_mod.rewrite_virtual_paths_in_shell_command("cd /")


def test_sanitize_messages_rewrites_tool_result_disk_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_home, account_root, nested = _bind_nested_workspace(tmp_path, monkeypatch)
    disk_file = str(nested / "report.csv")
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "tc1", "function": {"name": "search_files", "arguments": "{}"}}]},
        {
            "role": "tool",
            "tool_call_id": "tc1",
            "name": "search_files",
            "content": f'{{"files": ["{disk_file}"]}}',
        },
    ]
    clean = _sanitize_messages_for_api(messages)
    assert disk_file not in clean[1]["content"]
    assert "/workspace/test/report.csv" in clean[1]["content"]


def test_rewrite_agent_visible_workspace_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_home, account_root, _nested = _bind_nested_workspace(tmp_path, monkeypatch)
    tagged = f"[Workspace::v1: {account_root}]\nhello"
    rewritten = workspace_mod.rewrite_agent_visible_workspace_tags(
        tagged,
        profile_home=profile_home,
    )
    assert rewritten.startswith("[Workspace::v1: /workspace]")
    assert str(account_root) not in rewritten
