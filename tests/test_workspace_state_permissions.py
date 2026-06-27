"""Hermes home traversal must not crash workspace APIs."""
from __future__ import annotations

import os
import pathlib

import pytest

from app.domain import workspace as workspace_mod


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX only")
def test_load_workspaces_survives_unreadable_hermes_home(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    other_uid = os.getuid() + 1 if os.getuid() < 65534 else max(os.getuid() - 1, 1)
    try:
        os.chown(hermes_home, other_uid, os.getgid())
        os.chmod(hermes_home, 0o700)
    except PermissionError:
        pytest.skip("test user cannot chown directories for permission simulation")

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    profile_home = hermes_home / "profiles" / "default"
    profile_home.mkdir(parents=True)

    # Runtime user cannot traverse hermes_home; load must degrade to empty list.
    assert workspace_mod.load_workspaces_for_profile(profile_home) == []


def test_resolve_state_dir_does_not_mkdir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    profile_home = hermes_home / "profiles" / "default"
    profile_home.mkdir(parents=True)

    state_dir = workspace_mod._resolve_state_dir_for_profile_home(profile_home)
    assert state_dir == hermes_home / "users" / "webui_state" or state_dir.name == "webui_state"
    assert not state_dir.exists()
