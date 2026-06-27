"""Rewrite UI virtual /workspace paths in shell commands before tool execution."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.domain.profiles as profiles_mod
import app.domain.workspace as workspace_mod
from app.domain.profiles import (
    patch_execute_code_session_approval,
    patch_terminal_virtual_path_rewrite,
)


def _bind_nested_workspace_test_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    hermes_home = tmp_path / ".hermes"
    profile_home = hermes_home / "profiles" / "admin"
    disk_root = hermes_home / "workspace" / "admin"
    nested = disk_root / "test"
    nested.mkdir(parents=True)
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.delenv("HERMES_WEBUI_DEFAULT_WORKSPACE", raising=False)
    monkeypatch.delenv("HERMES_WEBUI_PROFILE_WORKSPACE", raising=False)
    profiles_mod._DEFAULT_HERMES_HOME = hermes_home
    return hermes_home, profile_home, nested


def test_rewrite_maps_nested_workspace_to_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hermes_home, profile_home, nested = _bind_nested_workspace_test_home(
        tmp_path,
        monkeypatch,
    )

    command = "cd /workspace/test && python3 -c 'print(1)'"
    rewritten = workspace_mod.rewrite_virtual_paths_in_shell_command(
        command,
        profile_home=profile_home,
        terminal_cwd=str(nested),
        active_workspace_virtual="/workspace/test",
    )

    assert "/workspace/test" not in rewritten
    assert str(nested.resolve()) in rewritten


def test_rewrite_leaves_legacy_mode_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HERMES_WEBUI_MULTI_USER", raising=False)
    command = "cd /workspace/test && ls"
    assert (
        workspace_mod.rewrite_virtual_paths_in_shell_command(command)
        == command
    )


def test_terminal_tool_patch_rewrites_command_before_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hermes_home, profile_home, nested = _bind_nested_workspace_test_home(
        tmp_path,
        monkeypatch,
    )

    captured: list[str] = []

    class FakeTerminalModule:
        @staticmethod
        def terminal_tool(command: str, **kwargs: object) -> str:
            captured.append(command)
            return "ok"

    import sys

    monkeypatch.setenv("TERMINAL_CWD", str(nested))
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace/test")
    sys.modules["tools.terminal_tool"] = FakeTerminalModule()
    patch_terminal_virtual_path_rewrite()

    from tools.terminal_tool import terminal_tool

    terminal_tool("cd /workspace/test && echo hi")

    assert captured == [f"cd {nested.resolve()} && echo hi"]


def test_rewrite_collapses_doubled_hermes_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hermes_home, profile_home, nested = _bind_nested_workspace_test_home(
        tmp_path,
        monkeypatch,
    )
    doubled = f"{_hermes_home.resolve()}/{str(_hermes_home.resolve()).lstrip('/')}/workspace/test"
    command = f"os.makedirs('{doubled}', exist_ok=True)"
    rewritten = workspace_mod.rewrite_virtual_paths_in_shell_command(
        command,
        profile_home=profile_home,
        terminal_cwd=str(nested),
        active_workspace_virtual="/workspace/test",
    )
    assert doubled not in rewritten
    assert str(nested.resolve()) in rewritten


def test_rewrite_fixes_shared_root_shortcut_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hermes_home, profile_home, nested = _bind_nested_workspace_test_home(
        tmp_path,
        monkeypatch,
    )
    wrong = _hermes_home / "workspace" / "test" / "random_data.xlsx"
    command = f"MEDIA:{wrong}"
    rewritten = workspace_mod.rewrite_virtual_paths_in_shell_command(
        command,
        profile_home=profile_home,
        terminal_cwd=str(nested),
        active_workspace_virtual="/workspace/test",
    )
    assert str(wrong) not in rewritten
    assert str(nested / "random_data.xlsx") in rewritten


def test_display_maps_disk_paths_to_virtual(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hermes_home, profile_home, nested = _bind_nested_workspace_test_home(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setenv("TERMINAL_CWD", str(nested))
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace/test")
    monkeypatch.setenv(
        "HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT",
        str(_hermes_home / "workspace" / "admin"),
    )

    disk_command = f"cd {nested.resolve()} && ls -la"
    displayed = workspace_mod.display_virtual_paths_in_shell_command(
        disk_command,
        profile_home=profile_home,
    )
    assert str(nested.resolve()) not in displayed
    assert "cd /workspace/test && ls -la" == displayed


def test_display_tool_args_rewrites_command_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hermes_home, profile_home, nested = _bind_nested_workspace_test_home(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setenv("TERMINAL_CWD", str(nested))
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace/test")

    args = {"command": f"python3 {nested / 'app.py'}"}
    displayed = workspace_mod.display_virtual_paths_in_tool_args(
        args,
        profile_home=profile_home,
    )
    assert str(nested / "app.py") not in displayed["command"]
    assert "/workspace/test/app.py" in displayed["command"]


def test_display_leaves_legacy_mode_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HERMES_WEBUI_MULTI_USER", raising=False)
    command = "cd /home/user/project && ls"
    assert (
        workspace_mod.display_virtual_paths_in_shell_command(command)
        == command
    )


def test_execute_code_guard_honors_session_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hermes_home, _profile_home, _nested = _bind_nested_workspace_test_home(
        tmp_path,
        monkeypatch,
    )
    calls: list[tuple[str, str]] = []

    class FakeApprovalModule:
        @staticmethod
        def get_current_session_key() -> str:
            return "sess-1"

        @staticmethod
        def is_approved(session_key: str, pattern_key: str) -> bool:
            return session_key == "sess-1" and pattern_key == "execute_code"

        @staticmethod
        def check_execute_code_guard(code: str, env_type: str) -> dict:
            calls.append((code, env_type))
            return {"approved": False, "message": "blocked"}

    import sys

    sys.modules["tools.approval"] = FakeApprovalModule()
    patch_execute_code_session_approval()

    from tools.approval import check_execute_code_guard

    result = check_execute_code_guard("print(1)", "local")
    assert result == {"approved": True, "message": None}
    assert calls == []


def test_rewrite_virtual_path_in_file_arg_maps_nested_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hermes_home, profile_home, nested = _bind_nested_workspace_test_home(
        tmp_path,
        monkeypatch,
    )
    rewritten = workspace_mod.rewrite_virtual_path_in_file_arg(
        "/workspace/test/report.txt",
        profile_home=profile_home,
        terminal_cwd=str(nested),
        active_workspace_virtual="/workspace/test",
    )
    assert rewritten == str((nested / "report.txt").resolve())


def test_rewrite_does_not_double_prefix_on_expanded_absolute_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: embedded ``.../.hermes/workspace/...`` must not re-expand /workspace."""
    hermes_home, profile_home, _nested = _bind_nested_workspace_test_home(
        tmp_path,
        monkeypatch,
    )
    disk_root = hermes_home / "workspace" / "admin"
    target = disk_root / "random_data.csv"
    doubled = (
        f"{hermes_home.resolve()}/"
        f"{str(hermes_home.resolve()).lstrip('/')}/"
        f"workspace/admin/admin/random_data.csv"
    )
    access = __import__(
        "app.domain.users", fromlist=["UserAccess"]
    ).UserAccess(
        multi_user_enabled=True,
        user_id="admin@example.com",
        username="admin@example.com",
        role="admin",
        profile_name="admin",
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        rewritten = workspace_mod.rewrite_virtual_paths_in_shell_command(
            f"open('{doubled}')",
            profile_home=profile_home,
            terminal_cwd=str(disk_root),
            active_workspace_virtual="/workspace",
        )
        assert "/home/" not in rewritten or doubled not in rewritten
        assert str(disk_root / "admin" / "random_data.csv") in rewritten
        workspace_mod.assert_account_workspace_text_paths(
            rewritten,
            tool_name="shell",
            root=disk_root,
        )
    finally:
        workspace_mod.clear_request_user_access(token)


def test_virtual_path_strips_redundant_account_slug(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home, profile_home, _nested = _bind_nested_workspace_test_home(
        tmp_path,
        monkeypatch,
    )
    disk_root = hermes_home / "workspace" / "admin"
    access = __import__(
        "app.domain.users", fromlist=["UserAccess"]
    ).UserAccess(
        multi_user_enabled=True,
        user_id="admin@example.com",
        username="admin@example.com",
        role="admin",
        profile_name="admin",
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        disk = workspace_mod.virtual_path_to_disk(
            "/workspace/admin/random_data.csv",
            profile_home,
        )
        assert disk.resolve() == (disk_root / "random_data.csv").resolve()
    finally:
        workspace_mod.clear_request_user_access(token)
