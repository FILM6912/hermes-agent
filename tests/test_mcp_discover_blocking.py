"""Regression: MCP discover must not block the whole WebUI API surface.

Root cause (2026-06): ``_run_mcp_discovery`` held ``_ENV_LOCK`` across slow MCP
network I/O (~60s/server), serializing every other env-mutation path. The native
``POST /api/v1/mcp/discover`` handler was ``async def`` but called blocking
legacy dispatch on the event loop, freezing profiles/list/workspaces until
discover finished. Auto ``discoverMcpServers()`` on MCP tab / chat panel mount
triggered this on every app load when a broken HTTP MCP server was configured.
"""

from __future__ import annotations

import ast
import inspect
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTES_PY = ROOT / "app" / "domain" / "routes.py"


def _discover_call_lines_in_run_mcp_discovery() -> list[int]:
    source = ROUTES_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_run_mcp_discovery":
            continue
        lines: list[int] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Name) and func.id == "discover_profile_mcp_tools":
                    lines.append(child.lineno)
        return sorted(lines)
    raise AssertionError("_run_mcp_discovery not found in routes.py")


def _env_lock_with_block_lines(func_name: str) -> list[tuple[int, int]]:
    """Return (start, end) line ranges for ``with _ENV_LOCK:`` bodies in *func_name*."""
    source = ROUTES_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != func_name:
            continue
        ranges: list[tuple[int, int]] = []
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.With):
                continue
            if not any(
                isinstance(item.context_expr, ast.Name)
                and item.context_expr.id == "_ENV_LOCK"
                for item in stmt.items
            ):
                continue
            start = stmt.lineno
            end = max(getattr(n, "lineno", start) for n in ast.walk(stmt))
            ranges.append((start, end))
        return ranges
    raise AssertionError(f"{func_name} not found in routes.py")


def test_discover_profile_mcp_tools_outside_env_lock_in_routes():
    """``discover_profile_mcp_tools()`` must not run inside ``with _ENV_LOCK:``."""
    discover_lines = _discover_call_lines_in_run_mcp_discovery()
    assert discover_lines, "expected discover_profile_mcp_tools() in _run_mcp_discovery"
    lock_ranges = _env_lock_with_block_lines("_run_mcp_discovery")
    assert lock_ranges, "expected at least one with _ENV_LOCK block"
    for call_line in discover_lines:
        for start, end in lock_ranges:
            assert not (start <= call_line <= end), (
                f"discover_profile_mcp_tools() at line {call_line} is inside "
                f"_ENV_LOCK body ({start}-{end}); release the lock before slow MCP I/O"
            )


def test_mcp_discover_endpoint_runs_in_threadpool():
    """Blocking MCP handlers must be sync ``def`` so Starlette runs them off-loop."""
    from app.api.v1.endpoints import mcp as mcp_module

    discover = mcp_module.discover_mcp_servers
    assert not inspect.iscoroutinefunction(discover), (
        "discover_mcp_servers must be a sync def (threadpool), not async def blocking the loop"
    )


@pytest.fixture
def fake_hermes_home(tmp_path, monkeypatch):
    import yaml

    import app.domain.mcp_runtime as mcp_runtime_mod
    import app.domain.profiles as profiles_mod

    fake_home = tmp_path / ".hermes"
    fake_home.mkdir(parents=True)
    (fake_home / "config.yaml").write_text(
        yaml.safe_dump({"mcp_servers": {"slow-srv": {"command": "echo"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_BASE_HOME", str(fake_home))
    monkeypatch.setattr(profiles_mod, "_DEFAULT_HERMES_HOME", fake_home)
    monkeypatch.setattr(profiles_mod, "_active_profile", "default")
    mcp_runtime_mod._MCP_LAST_PROFILE_HOME = None
    return fake_home


def test_run_mcp_discovery_releases_env_lock_during_slow_connect(fake_hermes_home):
    """While MCP connect runs, other threads must be able to acquire ``_ENV_LOCK``."""
    from app.domain.routes import _run_mcp_discovery
    from app.domain.streaming import _ENV_LOCK

    lock_acquired_during_discover = threading.Event()
    discover_started = threading.Event()

    def slow_discover(_home: str) -> list[str]:
        discover_started.set()
        time.sleep(0.4)
        return []

    def try_acquire_lock() -> None:
        assert discover_started.wait(timeout=2.0)
        if _ENV_LOCK.acquire(timeout=0.5):
            lock_acquired_during_discover.set()
            _ENV_LOCK.release()

    with patch("app.domain.routes.shutil.which", return_value="/usr/bin/python3"), patch(
        "tools.mcp_tool.get_mcp_status",
        return_value=[],
    ), patch(
        "app.domain.mcp_runtime.discover_profile_mcp_tools",
        side_effect=slow_discover,
    ):
        waiter = threading.Thread(target=try_acquire_lock, daemon=True)
        waiter.start()
        _run_mcp_discovery("")
        waiter.join(timeout=2.0)

    assert lock_acquired_during_discover.is_set(), (
        "_ENV_LOCK was still held during slow MCP discovery — other API paths would stall"
    )
