"""Unit tests for native GitService."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "app.services.git",
    ROOT / "app" / "services" / "git.py",
)
_git_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["app.services.git"] = _git_mod
_spec.loader.exec_module(_git_mod)
GitService = _git_mod.GitService


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        shell=False,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "hermes-tests@example.invalid")
    _git(path, "config", "user.name", "Hermes Tests")
    return path


def _commit_all(path: Path, message: str = "initial") -> None:
    _git(path, "add", ".")
    _git(path, "commit", "-m", message)


@pytest.fixture
def git_service() -> GitService:
    return GitService()


def test_git_status_requires_session_id(git_service: GitService):
    payload, status = git_service.git_status("")
    assert status == 400
    assert "session_id" in payload["error"]


def test_git_stage_requires_session_id(git_service: GitService):
    payload, status = git_service.git_stage({"paths": ["README.md"]})
    assert status == 400
    assert "session_id" in payload["error"].lower()


def test_git_diff_requires_path(git_service: GitService, tmp_path: Path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    session = SimpleNamespace(workspace=str(repo))

    monkeypatch.setattr(
        _git_mod,
        "get_session",
        lambda session_id: session,
    )

    payload, status = git_service.git_diff(session_id="sid-1", path="")
    assert status == 400
    assert payload["error"] == "path required"


def test_git_info_non_git_workspace(git_service: GitService, tmp_path: Path, monkeypatch):
    non_git = tmp_path / "not-a-repo"
    non_git.mkdir()
    session = SimpleNamespace(workspace=str(non_git))

    monkeypatch.setattr(
        _git_mod,
        "get_session",
        lambda session_id: session,
    )

    payload, status = git_service.git_info("sid-1")
    assert status is None
    assert payload["git"] is None


def test_git_status_and_stage_in_git_repo(
    git_service: GitService,
    tmp_path: Path,
    monkeypatch,
):
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
    _commit_all(repo)
    session = SimpleNamespace(workspace=str(repo), active_stream_id=None)

    monkeypatch.setattr(
        _git_mod,
        "get_session",
        lambda session_id: session,
    )
    monkeypatch.setenv("HERMES_WEBUI_WORKSPACE_GIT_DESTRUCTIVE", "1")
    (repo / "tracked.txt").write_text("one\ntwo\n", encoding="utf-8")

    status_payload, status_code = git_service.git_status("sid-1")
    assert status_code is None
    assert status_payload["git"]["totals"]["unstaged"] == 1

    staged_payload, staged_code = git_service.git_stage(
        {"session_id": "sid-1", "paths": ["tracked.txt"]}
    )
    assert staged_code is None
    assert staged_payload["ok"] is True
    assert staged_payload["git"]["totals"]["staged"] == 1
