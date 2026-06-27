"""Settings and workspace manifest repository for webui_state files."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.config import SETTINGS_FILE, load_settings, save_settings
from app.domain.workspace import _state_dir_for_profile_home, load_workspaces, save_workspaces


class SettingsRepository:
    """Read/write settings.json and workspaces.json under the active state dir."""

    @staticmethod
    def settings_path(profile_home: Path | None = None) -> Path:
        if profile_home is None:
            return SETTINGS_FILE
        return _state_dir_for_profile_home(profile_home) / "settings.json"

    @staticmethod
    def workspaces_path(profile_home: Path | None = None) -> Path:
        if profile_home is None:
            from app.domain.workspace import _workspaces_file

            return _workspaces_file()
        return _state_dir_for_profile_home(profile_home) / "workspaces.json"

    def load_settings(self) -> dict:
        return load_settings()

    def save_settings(self, settings: dict) -> dict:
        return save_settings(settings)

    def load_workspaces(self) -> list:
        return load_workspaces()

    def save_workspaces(self, workspaces: list) -> None:
        save_workspaces(workspaces)

    def read_json(self, path: Path) -> dict | list | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def write_json(self, path: Path, payload: dict | list) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
