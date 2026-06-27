"""Regression coverage for #749 profile creation model/provider selection."""

from pathlib import Path

import pytest
import yaml

import app.domain.profiles as profiles


REPO = Path(__file__).resolve().parent.parent
PANELS_JS = (REPO / "static-legacy" / "panels.js").read_text(encoding="utf-8")
ROUTES_PY = (REPO / "app" / "domain" / "routes.py").read_text(encoding="utf-8")


def test_profile_create_form_is_name_only():
    form_start = PANELS_JS.find("function _renderProfileForm(){")
    assert form_start != -1
    form_body = PANELS_JS[form_start : PANELS_JS.find("\nfunction cancelProfileForm()", form_start)]
    assert 'id="profileFormName"' in form_body
    assert 'id="profileFormModel"' not in form_body
    assert 'id="profileFormBaseUrl"' not in form_body
    assert 'id="profileFormApiKey"' not in form_body
    assert "profile_clone_label" in form_body


def test_profile_create_payload_is_name_only():
    fn_start = PANELS_JS.find("async function saveProfileForm()")
    assert fn_start != -1
    fn_body = PANELS_JS[fn_start : PANELS_JS.find("\n}", fn_start) + 2]
    assert "JSON.stringify({ name })" in fn_body
    assert "profileFormModel" not in fn_body
    assert "payload.default_model" not in fn_body


def test_profile_create_route_passes_model_fields_to_profile_api():
    route_start = ROUTES_PY.find('if parsed.path == "/api/profile/create":')
    assert route_start != -1
    route_body = ROUTES_PY[route_start : ROUTES_PY.find('if parsed.path == "/api/profile/delete":', route_start)]
    assert 'default_model = body.get("default_model"' in route_body
    assert 'model_provider = body.get("model_provider"' in route_body
    assert "default_model=default_model" in route_body
    assert "model_provider=model_provider" in route_body


def test_profile_model_config_writer_persists_default_and_provider(tmp_path):
    profile_dir = tmp_path / "profiles" / "research"
    profile_dir.mkdir(parents=True)

    profiles._write_model_defaults_to_config(
        profile_dir,
        default_model="anthropic/claude-opus-4.6",
        model_provider="nous",
    )

    saved = yaml.safe_load((profile_dir / "config.yaml").read_text(encoding="utf-8"))
    assert saved["model"]["default"] == "anthropic/claude-opus-4.6"
    assert saved["model"]["provider"] == "nous"


def test_profile_model_config_writer_preserves_existing_model_settings(tmp_path):
    profile_dir = tmp_path / "profiles" / "research"
    profile_dir.mkdir(parents=True)
    (profile_dir / "config.yaml").write_text(
        "model:\n  base_url: https://gateway.example/v1\n",
        encoding="utf-8",
    )

    profiles._write_model_defaults_to_config(
        profile_dir,
        default_model="gpt-5.5",
        model_provider="openai-codex",
    )

    saved = yaml.safe_load((profile_dir / "config.yaml").read_text(encoding="utf-8"))
    assert saved["model"]["base_url"] == "https://gateway.example/v1"
    assert saved["model"]["default"] == "gpt-5.5"
    assert saved["model"]["provider"] == "openai-codex"


def test_profile_model_selection_accepts_catalog_model_with_provider():
    catalog = {
        "groups": [
            {
                "provider": "OpenAI Codex",
                "provider_id": "openai-codex",
                "models": [{"id": "gpt-5.5", "label": "GPT-5.5"}],
            }
        ]
    }

    profiles._validate_profile_model_selection(
        "gpt-5.5",
        "openai-codex",
        available_models=catalog,
    )


def test_profile_model_selection_accepts_provider_qualified_picker_value():
    catalog = {
        "groups": [
            {
                "provider": "Research Gateway",
                "provider_id": "custom:research-gateway",
                "models": [
                    {
                        "id": "@custom:research-gateway:claude-opus-4.6",
                        "label": "claude-opus-4.6",
                    }
                ],
            }
        ]
    }

    default_model, model_provider = profiles._split_webui_provider_model_value(
        "@custom:research-gateway:claude-opus-4.6",
        "custom:research-gateway",
    )

    profiles._validate_profile_model_selection(
        default_model,
        model_provider,
        available_models=catalog,
    )


def test_profile_model_selection_rejects_unknown_model_provider_pair():
    catalog = {
        "groups": [
            {
                "provider": "OpenAI Codex",
                "provider_id": "openai-codex",
                "models": [{"id": "gpt-5.5", "label": "GPT-5.5"}],
            }
        ]
    }

    with pytest.raises(ValueError, match="not available for provider"):
        profiles._validate_profile_model_selection(
            "missing-model",
            "openai-codex",
            available_models=catalog,
        )


def test_profile_create_rejects_unknown_model_before_creating_profile(monkeypatch):
    calls = []

    monkeypatch.setattr(
        profiles,
        "_get_available_models_for_profile_validation",
        lambda: {
            "groups": [
                {
                    "provider": "OpenAI Codex",
                    "provider_id": "openai-codex",
                    "models": [{"id": "gpt-5.5", "label": "GPT-5.5"}],
                }
            ]
        },
    )
    monkeypatch.setattr(
        profiles,
        "_create_profile_fallback",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(ValueError, match="Selected model 'missing-model'"):
        profiles.create_profile_api(
            "research",
            default_model="missing-model",
            model_provider="openai-codex",
        )

    assert calls == []
