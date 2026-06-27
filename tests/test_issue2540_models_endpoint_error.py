import urllib.error
import urllib.request
from email.message import Message

from app.domain import config


class _ConfigState:
    def __enter__(self):
        self.old_cfg = config.cfg
        self.old_mtime = config._cfg_mtime
        self.old_cache = config._available_models_cache
        self.old_cache_ts = config._available_models_cache_ts
        self.old_cache_fp = config._available_models_cache_source_fingerprint
        config._cfg_mtime = 0.0
        config._available_models_cache = None
        config._available_models_cache_ts = 0.0
        config._available_models_cache_source_fingerprint = None
        return self

    def __exit__(self, exc_type, exc, tb):
        config.cfg = self.old_cfg
        config._cfg_mtime = self.old_mtime
        config._available_models_cache = self.old_cache
        config._available_models_cache_ts = self.old_cache_ts
        config._available_models_cache_source_fingerprint = self.old_cache_fp
        return False


def _configure_named_custom_provider(tmp_path, monkeypatch, *, model=None):
    monkeypatch.setattr(config, "_models_cache_path", tmp_path / "models_cache.json")
    monkeypatch.setattr(config, "_get_auth_store_path", lambda: tmp_path / "auth.json")
    entry = {
        "name": "Broken Proxy",
        "base_url": "https://broken.example/v1",
        "api_key": "bad-key",
    }
    if model:
        entry["model"] = model
    config.cfg = {
        "model": {"provider": "openai-codex", "default": "gpt-5.5"},
        "providers": {},
        "fallback_providers": [],
        "custom_providers": [entry],
    }


def _groups_by_provider(data):
    return {group["provider_id"]: group for group in data["groups"]}


def test_named_custom_provider_models_endpoint_401_hides_unreachable_models(monkeypatch, tmp_path):
    def fake_urlopen(req, timeout=10):
        raise urllib.error.HTTPError(
            getattr(req, "full_url", "https://broken.example/v1/models"),
            401,
            "Unauthorized",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with _ConfigState():
        _configure_named_custom_provider(tmp_path, monkeypatch, model="broken/manual")
        data = config.get_available_models()

    assert "custom:broken-proxy" not in _groups_by_provider(data)


def test_named_custom_provider_models_endpoint_network_error_omits_group(monkeypatch, tmp_path):
    def fake_urlopen(req, timeout=10):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with _ConfigState():
        _configure_named_custom_provider(tmp_path, monkeypatch)
        data = config.get_available_models()

    assert "custom:broken-proxy" not in _groups_by_provider(data)


def test_named_custom_provider_models_endpoint_5xx_omits_unreachable_group(monkeypatch, tmp_path):
    def fake_urlopen(req, timeout=10):
        raise urllib.error.HTTPError(
            getattr(req, "full_url", "https://broken.example/v1/models"),
            502,
            "Bad Gateway",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with _ConfigState():
        _configure_named_custom_provider(tmp_path, monkeypatch, model="broken/manual")
        data = config.get_available_models()

    assert "custom:broken-proxy" not in _groups_by_provider(data)


def test_frontend_model_picker_renders_provider_endpoint_hint():
    ui = open("static-legacy/ui.js", encoding="utf-8").read()
    css = open("static-legacy/style.css", encoding="utf-8").read()

    assert "models_endpoint_error" in ui
    assert "dataset.modelsEndpointError" in ui
    assert "model-provider-hint" in ui
    assert "entry.modelsEndpointError.message" in ui
    assert ".model-provider-hint" in css
