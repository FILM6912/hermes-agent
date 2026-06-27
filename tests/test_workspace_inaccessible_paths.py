import json
from pathlib import Path

import pytest

from app.domain import workspace


def test_load_workspaces_normalizes_to_single_profile_workspace(tmp_path, monkeypatch):
    """Legacy multi-entry workspace lists are normalized to one auto workspace."""
    import app.domain.profiles as profiles_mod

    profile_home = tmp_path / "hermes"
    profile_home.mkdir()
    state_dir = profile_home / "webui_state"
    state_dir.mkdir()
    existing = tmp_path / "existing"
    existing.mkdir()
    unavailable = tmp_path / "missing-or-inaccessible"
    ws_file = state_dir / "workspaces.json"
    raw = [
        {"path": str(existing), "name": "Existing"},
        {"path": str(unavailable), "name": "Unavailable"},
    ]
    ws_file.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(profiles_mod, "get_active_hermes_home", lambda: profile_home)
    monkeypatch.setattr(profiles_mod, "get_active_profile_name", lambda: "default")
    monkeypatch.setattr(workspace, "_workspaces_file", lambda: ws_file)

    loaded = workspace.load_workspaces()

    canonical = workspace.profile_workspace_rel()
    assert loaded == [{"path": canonical, "name": "Home"}]
    assert json.loads(ws_file.read_text(encoding="utf-8")) == loaded


def test_clean_workspace_list_still_renames_default_without_dropping_missing(tmp_path):
    missing = tmp_path / "temporarily-unavailable"

    cleaned = workspace._clean_workspace_list([
        {"path": str(missing), "name": "default"},
    ])

    assert cleaned == [{"path": str(missing.resolve()), "name": "Home"}]


def test_validate_workspace_to_add_distinguishes_permission_denied(monkeypatch, tmp_path):
    candidate = tmp_path / "Documents"
    candidate.mkdir()

    target = str(candidate.resolve())
    original_stat = Path.stat

    def fake_stat(self):
        if str(self) == target:
            raise PermissionError("Operation not permitted")
        return original_stat(self)

    monkeypatch.setattr(Path, "stat", fake_stat)

    with pytest.raises(ValueError) as excinfo:
        workspace.validate_workspace_to_add(str(candidate))

    message = str(excinfo.value)
    assert "Cannot access path" in message
    assert "Operation not permitted" in message
    assert "macOS" in message
    assert "Full Disk Access" in message


def test_resolve_trusted_workspace_distinguishes_missing_from_permission_denied(monkeypatch, tmp_path):
    candidate = tmp_path / "Documents"
    candidate.mkdir()

    target = str(candidate.resolve())
    original_stat = Path.stat

    def fake_stat(self):
        if str(self) == target:
            raise PermissionError("Operation not permitted")
        return original_stat(self)

    monkeypatch.setattr(Path, "stat", fake_stat)

    with pytest.raises(ValueError) as excinfo:
        workspace.resolve_trusted_workspace(str(candidate))

    assert "Cannot access path" in str(excinfo.value)
    assert "Path does not exist" not in str(excinfo.value)
