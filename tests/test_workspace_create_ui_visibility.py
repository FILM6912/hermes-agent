"""Workspace create UI is available to user and admin when nested workspaces are on."""

from __future__ import annotations

import pathlib
import py_compile
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PANELS_JS = (ROOT / "static-legacy" / "panels.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
ROLLBACK_PY = ROOT / "app" / "domain" / "rollback.py"


def test_rollback_py_compiles():
    py_compile.compile(str(ROLLBACK_PY), doraise=True)
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", str(ROLLBACK_PY)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_workspace_create_button_not_gated_on_profile_management():
    assert "function _syncWorkspaceCreateButtonVisibility()" in PANELS_JS
    assert "_nestedWorkspacesEnabled ? '' : 'none'" in PANELS_JS
    assert "btnAddWorkspace" in INDEX_HTML
    create_fn = PANELS_JS.split("function openWorkspaceCreate()", 1)[1].split("function ", 1)[0]
    assert "_canManageProfiles" not in create_fn
    sync_fn = PANELS_JS.split("function _syncWorkspaceCreateButtonVisibility()", 1)[1].split(
        "function ", 1
    )[0]
    assert "_canManageProfiles" not in sync_fn
