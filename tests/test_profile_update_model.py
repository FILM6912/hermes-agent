"""POST /api/v1/profile/update — per-profile default model."""

from pathlib import Path

import pytest
import yaml

import app.domain.profiles as profiles


def test_update_profile_model_api_writes_config(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    profile_dir = hermes_home / "profiles" / "user1"
    profile_dir.mkdir(parents=True)
    (profile_dir / "config.yaml").write_text(
        "model:\n  default: old-model\n  provider: lmstudio\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(profiles, "_DEFAULT_HERMES_HOME", hermes_home)

    catalog = {
        "groups": [
            {
                "provider": "LM Studio",
                "provider_id": "lmstudio",
                "models": [{"id": "qwen3.5-9b", "label": "Qwen 3.5 9B"}],
            }
        ]
    }

    def fake_list():
        return [
            {
                "name": "user1",
                "path": str(profile_dir),
                "is_default": False,
                "is_active": False,
                "gateway_running": False,
                "model": "old-model",
                "provider": "lmstudio",
                "has_env": False,
                "skill_count": 0,
            }
        ]

    monkeypatch.setattr(profiles, "list_profiles_api", fake_list)
    monkeypatch.setattr(
        profiles,
        "_validate_profile_model_selection",
        lambda default_model, model_provider, available_models=None: None,
    )

    result = profiles.update_profile_model_api(
        "user1",
        default_model="qwen3.5-9b",
        model_provider="lmstudio",
    )

    assert result["ok"] is True
    saved = yaml.safe_load((profile_dir / "config.yaml").read_text(encoding="utf-8"))
    assert saved["model"]["default"] == "qwen3.5-9b"
    assert saved["model"]["provider"] == "lmstudio"
