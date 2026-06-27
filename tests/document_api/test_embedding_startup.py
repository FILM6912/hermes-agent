"""Startup warm-up when EMBEDDING_ENABLED=true."""

from __future__ import annotations

import pytest

from app.document_api.core.config import Settings


@pytest.mark.asyncio
async def test_startup_document_api_warms_embedding_when_enabled(monkeypatch):
    warmed: list[str] = []

    def _fake_warm(settings: Settings) -> bool:
        warmed.append(settings.embedding_model)
        return True

    monkeypatch.setattr(
        "app.document_api.lm_engine.qwen_vl_hf_embeddings.warm_embedding_model",
        _fake_warm,
    )
    monkeypatch.setattr(
        "app.document_api.integration.is_document_api_feature_requested",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.document_api.integration._load_document_api_router",
        lambda: object(),
    )
    monkeypatch.setattr(
        "app.document_api.services.document_pipeline.bootstrap_on_startup",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.document_api.core.logging_setup.configure_app_logging",
        lambda _level: None,
    )

    class _FakeSettings:
        supabase_url = "http://example.test"
        log_level = "INFO"
        embedding_enabled = True
        embedding_model = "Qwen/Qwen3-VL-Embedding-2B"
        reranker_enabled = False
        reranker_model = "Qwen/Qwen3-VL-Reranker-2B"
        asr_enabled = False

    monkeypatch.setattr(
        "app.document_api.core.config.get_settings",
        lambda: _FakeSettings(),
    )

    import app.document_api.integration as integration

    monkeypatch.setattr(integration, "_document_api_initialized", False)
    await integration.startup_document_api()

    assert warmed == ["Qwen/Qwen3-VL-Embedding-2B"]


@pytest.mark.asyncio
async def test_startup_document_api_skips_embedding_when_disabled(monkeypatch):
    called = False

    def _fake_warm(_settings: Settings) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(
        "app.document_api.lm_engine.qwen_vl_hf_embeddings.warm_embedding_model",
        _fake_warm,
    )
    monkeypatch.setattr(
        "app.document_api.integration.is_document_api_feature_requested",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.document_api.integration._load_document_api_router",
        lambda: object(),
    )
    monkeypatch.setattr(
        "app.document_api.services.document_pipeline.bootstrap_on_startup",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.document_api.core.logging_setup.configure_app_logging",
        lambda _level: None,
    )

    class _FakeSettings:
        supabase_url = "http://example.test"
        log_level = "INFO"
        embedding_enabled = False
        embedding_model = "Qwen/Qwen3-VL-Embedding-2B"
        reranker_enabled = False
        reranker_model = "Qwen/Qwen3-VL-Reranker-2B"
        asr_enabled = False

    monkeypatch.setattr(
        "app.document_api.core.config.get_settings",
        lambda: _FakeSettings(),
    )

    import app.document_api.integration as integration

    monkeypatch.setattr(integration, "_document_api_initialized", False)
    await integration.startup_document_api()

    assert called is False
