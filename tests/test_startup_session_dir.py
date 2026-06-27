"""Regression: run_startup must not shadow module-level SESSION_DIR."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core.startup import run_startup

REPO = Path(__file__).resolve().parents[1]
STARTUP_SOURCE = (REPO / "app" / "core" / "startup.py").read_text(encoding="utf-8")


def _run_startup_function_body() -> ast.FunctionDef:
    tree = ast.parse(STARTUP_SOURCE)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run_startup":
            return node
    raise AssertionError("run_startup not found")


def test_run_startup_does_not_reimport_session_dir_inside_function():
    """Inner import shadowed module-level SESSION_DIR and caused UnboundLocalError at mkdir."""
    fn = _run_startup_function_body()
    inner_imports = [
        child
        for child in ast.walk(fn)
        if isinstance(child, ast.ImportFrom)
        and child.module == "app.domain.models"
        and any(alias.name == "SESSION_DIR" for alias in child.names)
    ]
    assert inner_imports == []


def test_run_startup_mkdirs_session_dir_without_unbound_local_error(
    tmp_path, monkeypatch
):
    session_dir = tmp_path / "sessions"
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    monkeypatch.setattr("app.core.startup.SESSION_DIR", session_dir)
    monkeypatch.setattr("app.core.startup.STATE_DIR", state_dir)
    monkeypatch.setattr("app.core.startup.DEFAULT_WORKSPACE", workspace)

    app = SimpleNamespace(state=SimpleNamespace())

    with (
        patch("app.core.startup._within_container", return_value=True),
        patch("app.domain.config.print_startup_config"),
        patch("app.core.startup.fix_credential_permissions"),
        patch("app.core.startup.threading.Thread"),
        patch("app.domain.users.bootstrap_default_admin"),
        patch("app.domain.auth.is_auth_enabled", return_value=True),
        patch(
            "app.storage.schema.init_storage",
            return_value={
                "local_backend": "json",
                "supabase_enabled": False,
                "schema_version": 1,
            },
        ),
        patch("app.storage.migrate.run_storage_migrations", return_value={"json": {}}),
        patch("app.domain.auth.bootstrap_auth_sessions"),
        patch("app.storage.repositories.sessions.ensure_sessions_migrated"),
        patch(
            "app.storage.repositories.chat_sessions.get_chat_sessions_repository",
            return_value=MagicMock(enabled=lambda: False),
        ),
        patch("app.domain.gateway_watcher.start_watcher"),
    ):
        run_startup(app)  # type: ignore[arg-type]

    assert session_dir.is_dir()
