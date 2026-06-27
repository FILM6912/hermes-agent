"""Partial create/update must not reset unrelated config fields."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from app.domain import dashboard_probe
from app.domain.config import set_auxiliary_model, set_hermes_default_model


def test_save_dashboard_config_preserves_url_when_only_enabled_sent(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "webui": {
                    "dashboard": {
                        "enabled": "auto",
                        "url": "http://127.0.0.1:3000/",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.domain.config._get_config_path", lambda: config_path)
    monkeypatch.setattr(
        "app.domain.config._load_yaml_config_file",
        lambda _path: yaml.safe_load(config_path.read_text(encoding="utf-8")),
    )

    saved: dict = {}

    def capture_save(_path, data):
        saved.update(data)
        config_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    monkeypatch.setattr("app.domain.config._save_yaml_config_file", capture_save)
    monkeypatch.setattr("app.domain.config.reload_config", lambda: None)

    out = dashboard_probe.save_dashboard_config({"enabled": "always"})
    assert out["enabled"] == "always"
    assert saved["webui"]["dashboard"]["url"] == "http://127.0.0.1:3000/"


def test_set_hermes_default_model_preserves_provider_and_base_url(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "model": {
                    "provider": "custom:a.i.tech",
                    "default": "glm/glm-4.7",
                    "base_url": "http://192.168.99.1:4000/v1",
                },
                "custom_providers": [{"name": "A.I.Tech", "base_url": "http://192.168.99.1:4000/v1"}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("app.domain.config._get_config_path", lambda: config_path)
    monkeypatch.setattr("app.domain.config.reload_config", lambda: None)
    monkeypatch.setattr("app.domain.config.invalidate_models_cache", lambda: None)
    monkeypatch.setattr(
        "app.domain.config.resolve_model_provider",
        lambda _model: ("glm/glm-5.2", "custom:a.i.tech", "http://192.168.99.1:4000/v1"),
    )

    set_hermes_default_model("glm/glm-5.2")
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["model"]["default"] == "glm/glm-5.2"
    assert saved["model"]["provider"] == "custom:a.i.tech"
    assert saved["model"]["base_url"] == "http://192.168.99.1:4000/v1"
    assert saved["custom_providers"]


def test_set_auxiliary_model_partial_update_preserves_provider(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "auxiliary": {
                    "title_generation": {
                        "provider": "custom:a.i.tech",
                        "model": "glm/glm-4.7",
                        "base_url": "http://192.168.99.1:4000/v1",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.domain.config._get_config_path", lambda: config_path)
    monkeypatch.setattr("app.domain.config.reload_config", lambda: None)

    set_auxiliary_model(
        "title_generation",
        model="glm/glm-5.2",
        update_provider=False,
        update_model=True,
    )
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    slot = saved["auxiliary"]["title_generation"]
    assert slot["model"] == "glm/glm-5.2"
    assert slot["provider"] == "custom:a.i.tech"
    assert slot["base_url"] == "http://192.168.99.1:4000/v1"


def test_session_update_service_ignores_unset_model_provider():
    from app.services.sessions import SessionService

    session = MagicMock()
    session.workspace = "/workspace"
    session.model = "glm/glm-4.7"
    session.model_provider = "custom:a.i.tech"
    session.messages = []
    session.compact.return_value = {"session_id": "s1", "model": "glm/glm-5.2"}

    service = SessionService(repository=MagicMock())
    service._repo.get.return_value = session

    with (
        patch("app.domain.routes._get_session_agent_lock"),
        patch("app.domain.routes._session_model_state_from_request", return_value=("glm/glm-5.2", "custom:a.i.tech")),
        patch("app.domain.routes._resolve_context_length_for_session_model", return_value=128000),
        patch("app.domain.config._evict_session_agent"),
        patch("app.domain.workspace.resolve_trusted_workspace", side_effect=lambda value: value),
        patch("app.domain.workspace.set_last_workspace"),
    ):
        service.update_session(
            session_id="s1",
            body={"session_id": "s1", "model": "glm/glm-5.2"},
        )

    assert session.model == "glm/glm-5.2"
    assert session.model_provider == "custom:a.i.tech"
