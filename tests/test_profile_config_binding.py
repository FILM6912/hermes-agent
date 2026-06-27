"""Regression tests: chat streaming must use the session profile's config.yaml.

Per-client profile switches (cookie-scoped) do not mutate process-global cfg.
The streaming worker thread therefore must load profiles/<name>/config.yaml from
the session's stamped profile and pass it to resolve_model_provider(), not rely
on get_config() / module-level cfg (which still reflect the process default).
"""
from __future__ import annotations

import copy

import app.domain.config as config


class _RestoreCfg:
    def __enter__(self):
        self._snapshot = copy.deepcopy(config.cfg)
        return self

    def __exit__(self, *exc):
        config.cfg.clear()
        config.cfg.update(self._snapshot)


def test_resolve_model_provider_prefers_profile_config_over_global():
    """LM Studio base_url must come from the session profile, not process default."""
    with _RestoreCfg():
        config.cfg.clear()
        config.cfg.update(
            {
                "model": {
                    "provider": "lmstudio",
                    "base_url": "http://127.0.0.1:1234/v1",
                    "default": "global-model",
                },
            }
        )
        profile_cfg = {
            "model": {
                "provider": "lmstudio",
                "base_url": "http://192.168.99.1:1234/v1",
                "default": "user-model",
            },
        }

        model, provider, base_url = config.resolve_model_provider(
            "user-model",
            profile_cfg,
        )
        assert model == "user-model"
        assert provider == "lmstudio"
        assert base_url == "http://192.168.99.1:1234/v1"

        _, _, global_base = config.resolve_model_provider("global-model")
        assert global_base == "http://127.0.0.1:1234/v1"


def test_resolve_model_provider_at_lmstudio_uses_profile_config():
    with _RestoreCfg():
        config.cfg.clear()
        config.cfg.update(
            {
                "model": {
                    "provider": "lmstudio",
                    "base_url": "http://127.0.0.1:1234/v1",
                },
            }
        )
        profile_cfg = {
            "model": {
                "provider": "lm-studio",
                "base_url": "http://192.168.99.1:1234/v1",
            },
        }
        model, provider, base_url = config.resolve_model_provider(
            "@lmstudio:some-model",
            profile_cfg,
        )
        assert model == "some-model"
        assert provider == "lmstudio"
        assert base_url == "http://192.168.99.1:1234/v1"


def test_resolve_custom_provider_connection_honors_profile_config():
    profile_cfg = {
        "custom_providers": [
            {
                "name": "my-local",
                "base_url": "http://192.168.99.1:8080/v1",
                "api_key": "test-key",
            }
        ]
    }
    with _RestoreCfg():
        config.cfg.clear()
        config.cfg.update({"custom_providers": []})
        api_key, base_url = config.resolve_custom_provider_connection(
            "custom:my-local",
            profile_cfg,
        )
        assert api_key == "test-key"
        assert base_url == "http://192.168.99.1:8080/v1"
