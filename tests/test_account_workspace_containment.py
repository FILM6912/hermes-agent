"""Strict per-account workspace containment for agent tools."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.domain.profiles as profiles_mod
import app.domain.workspace as workspace_mod
from app.domain.profiles import patch_account_workspace_containment
from app.domain.users import UserAccess


def _bind_admin_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    hermes_home = tmp_path / ".hermes"
    profile_home = hermes_home / "profiles" / "admin"
    account_root = hermes_home / "workspace" / "admin"
    nested = account_root / "test"
    other = hermes_home / "workspace" / "other" / "secret"
    nested.mkdir(parents=True)
    other.mkdir(parents=True)
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT", str(account_root))
    monkeypatch.setenv("TERMINAL_CWD", str(nested))
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace/test")
    monkeypatch.delenv("HERMES_WEBUI_DEFAULT_WORKSPACE", raising=False)
    profiles_mod._DEFAULT_HERMES_HOME = hermes_home
    return account_root, nested, other


def test_resolve_trusted_workspace_rejects_other_account_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_root, nested, other = _bind_admin_workspace(tmp_path, monkeypatch)
    access = UserAccess(
        multi_user_enabled=True,
        user_id="admin@example.com",
        username="admin@example.com",
        role="admin",
        profile_name="admin",
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        allowed = workspace_mod.resolve_trusted_workspace(nested)
        assert allowed.resolve() == nested.resolve()
        remapped = workspace_mod.resolve_trusted_workspace(other)
        assert remapped.resolve() == account_root.resolve()
    finally:
        workspace_mod.clear_request_user_access(token)


def test_resolve_trusted_workspace_ignores_stale_terminal_cwd_pollution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UI file polling must not inherit a concurrent agent's TERMINAL_CWD=/app pin."""
    account_root, _nested, _other = _bind_admin_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("TERMINAL_CWD", "/app")
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace")
    access = UserAccess(
        multi_user_enabled=True,
        user_id="admin@example.com",
        username="admin@example.com",
        role="admin",
        profile_name="admin",
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        resolved = workspace_mod.resolve_trusted_workspace("/workspace")
        assert resolved.resolve() == account_root.resolve()
    finally:
        workspace_mod.clear_request_user_access(token)


def test_rewrite_allows_webui_venv_python_in_shell_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_admin_workspace(tmp_path, monkeypatch)
    venv_root = tmp_path / "venv"
    bin_dir = venv_root / "bin"
    bin_dir.mkdir(parents=True)
    (venv_root / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    python = bin_dir / "python3"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)
    monkeypatch.setenv("HERMES_WEBUI_VIRTUAL_ENV", str(venv_root))

    command = f"{python} -m pip install pandas"
    rewritten = workspace_mod.rewrite_virtual_paths_in_shell_command(
        command,
        terminal_cwd=str(tmp_path / ".hermes" / "workspace" / "admin" / "test"),
        active_workspace_virtual="/workspace/test",
    )
    assert rewritten == command


def test_rewrite_blocks_absolute_path_outside_account_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_root, nested, other = _bind_admin_workspace(tmp_path, monkeypatch)
    command = f"cat {other / 'secret.txt'}"
    with pytest.raises(ValueError, match="outside"):
        workspace_mod.rewrite_virtual_paths_in_shell_command(
            command,
            terminal_cwd=str(nested),
            active_workspace_virtual="/workspace/test",
        )


def test_rewrite_allows_hermes_home_config_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_root, nested, _other = _bind_admin_workspace(tmp_path, monkeypatch)
    hermes_home = tmp_path / ".hermes"
    config_path = hermes_home / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("model: test\n", encoding="utf-8")
    profile_config = hermes_home / "profiles" / "admin" / "config.yaml"
    profile_config.parent.mkdir(parents=True, exist_ok=True)
    profile_config.write_text("model: admin\n", encoding="utf-8")
    state_dir = tmp_path / "webui-state"
    state_dir.mkdir()
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state_dir))

    for target in (config_path, profile_config, state_dir / "settings.json"):
        command = f"cat {target}"
        rewritten = workspace_mod.rewrite_virtual_paths_in_shell_command(
            command,
            terminal_cwd=str(nested),
            active_workspace_virtual="/workspace/test",
        )
        assert rewritten == command


def test_file_tool_allows_hermes_home_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_root, nested, _other = _bind_admin_workspace(tmp_path, monkeypatch)
    hermes_home = tmp_path / ".hermes"
    config_path = hermes_home / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("model: test\n", encoding="utf-8")
    calls: list[str] = []

    class FakeFileToolsModule:
        @staticmethod
        def _resolve_path_for_task(filepath: str, task_id: str = "default") -> Path:
            p = Path(filepath).expanduser()
            if not p.is_absolute():
                import os

                p = Path(os.environ.get("TERMINAL_CWD", os.getcwd())) / p
            return p.resolve()

        @staticmethod
        def read_file_tool(path: str, offset: int = 1, limit: int = 500, task_id: str = "default") -> str:
            calls.append(path)
            return "ok"

    import sys

    sys.modules["tools.file_tools"] = FakeFileToolsModule()
    patch_account_workspace_containment()

    from tools.file_tools import read_file_tool

    read_file_tool(str(config_path))
    assert calls == [str(config_path.resolve())]


def test_rewrite_still_blocks_arbitrary_host_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_root, nested, _other = _bind_admin_workspace(tmp_path, monkeypatch)
    outside = tmp_path / "etc" / "passwd"
    outside.parent.mkdir(parents=True)
    outside.write_text("root:x:0:0:root:/root:/bin/bash\n", encoding="utf-8")
    command = f"cat {outside}"
    with pytest.raises(ValueError, match="outside"):
        workspace_mod.rewrite_virtual_paths_in_shell_command(
            command,
            terminal_cwd=str(nested),
            active_workspace_virtual="/workspace/test",
        )


def test_file_tool_patch_blocks_outside_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_root, nested, other = _bind_admin_workspace(tmp_path, monkeypatch)
    calls: list[str] = []

    class FakeFileToolsModule:
        @staticmethod
        def _resolve_path_for_task(filepath: str, task_id: str = "default") -> Path:
            p = Path(filepath).expanduser()
            if not p.is_absolute():
                import os

                p = Path(os.environ.get("TERMINAL_CWD", os.getcwd())) / p
            return p.resolve()

        @staticmethod
        def read_file_tool(path: str, offset: int = 1, limit: int = 500, task_id: str = "default") -> str:
            calls.append(path)
            return "ok"

    import sys

    sys.modules["tools.file_tools"] = FakeFileToolsModule()
    patch_account_workspace_containment()

    from tools.file_tools import read_file_tool

    read_file_tool("report.txt")
    assert calls == ["report.txt"]

    with pytest.raises(ValueError, match="outside"):
        read_file_tool(str(other / "secret.txt"))


def test_file_tool_patch_rewrites_virtual_path_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_root, nested, _other = _bind_admin_workspace(tmp_path, monkeypatch)
    target = nested / "report.txt"
    target.write_text("hello", encoding="utf-8")
    calls: list[str] = []

    class FakeFileToolsModule:
        @staticmethod
        def _resolve_path_for_task(filepath: str, task_id: str = "default") -> Path:
            p = Path(filepath).expanduser()
            if not p.is_absolute():
                import os

                p = Path(os.environ.get("TERMINAL_CWD", os.getcwd())) / p
            return p.resolve()

        @staticmethod
        def read_file_tool(path: str, offset: int = 1, limit: int = 500, task_id: str = "default") -> str:
            calls.append(path)
            return "ok"

    import sys

    sys.modules["tools.file_tools"] = FakeFileToolsModule()
    patch_account_workspace_containment()

    from tools.file_tools import read_file_tool

    read_file_tool("/workspace/test/report.txt")
    assert calls == [str(target.resolve())]


def _bind_admin_and_pathom_workspaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    admin_ws.mkdir(parents=True)
    pathom_ws.mkdir(parents=True)
    (hermes_home / "profiles" / "admin").mkdir(parents=True)
    (hermes_home / "profiles" / "pathom_u").mkdir(parents=True)
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr(profiles_mod, "_DEFAULT_HERMES_HOME", hermes_home)
    workspace_mod._BOOT_DEFAULT_WORKSPACE = str(hermes_home / "workspace")
    return admin_ws, pathom_ws


def test_admin_containment_ignores_foreign_account_workspace_root_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admin UI must not inherit another account's agent workspace root pin."""
    admin_ws, pathom_ws = _bind_admin_and_pathom_workspaces(tmp_path, monkeypatch)
    monkeypatch.setenv("HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT", str(pathom_ws))

    access = UserAccess(
        multi_user_enabled=True,
        user_id="admin@example.com",
        username="admin@example.com",
        role="admin",
        profile_name="admin",
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        containment = workspace_mod.account_workspace_containment_root(access=access)
        resolved = workspace_mod.resolve_trusted_workspace("/workspace")
        assert containment.resolve() == admin_ws.resolve()
        assert resolved.resolve() == admin_ws.resolve()
    finally:
        workspace_mod.clear_request_user_access(token)


def test_admin_containment_ignores_foreign_terminal_cwd_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admin UI must not inherit another account's TERMINAL_CWD workspace pin."""
    admin_ws, pathom_ws = _bind_admin_and_pathom_workspaces(tmp_path, monkeypatch)
    nested = pathom_ws / "project"
    nested.mkdir()
    monkeypatch.setenv("TERMINAL_CWD", str(nested))
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace/project")

    access = UserAccess(
        multi_user_enabled=True,
        user_id="admin@example.com",
        username="admin@example.com",
        role="admin",
        profile_name="admin",
    )
    token = workspace_mod.set_request_user_access(access)
    try:
        containment = workspace_mod.account_workspace_containment_root(access=access)
        resolved = workspace_mod.resolve_trusted_workspace("/workspace")
        assert containment.resolve() == admin_ws.resolve()
        assert resolved.resolve() == admin_ws.resolve()
    finally:
        workspace_mod.clear_request_user_access(token)
