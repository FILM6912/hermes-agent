"""Regression: custom provider must not send Ollama ``think`` to LiteLLM/vLLM/RunPod."""

from __future__ import annotations

from types import SimpleNamespace

from app.domain.profiles import (
    _custom_endpoint_supports_ollama_think,
    _strip_non_ollama_think_param,
    apply_agent_runtime_patches,
    patch_custom_provider_think_param,
)


def test_custom_endpoint_supports_ollama_think_detects_ollama_port():
    assert _custom_endpoint_supports_ollama_think("http://localhost:11434/v1")
    assert _custom_endpoint_supports_ollama_think("https://api.ollama.com/v1")


def test_custom_endpoint_supports_ollama_think_rejects_litellm_and_runpod():
    assert not _custom_endpoint_supports_ollama_think("http://192.168.99.1:4000/v1")
    assert not _custom_endpoint_supports_ollama_think(
        "https://ede5590xgywyz1-1234.proxy.runpod.net/v1"
    )


def test_strip_non_ollama_think_param_removes_think_for_litellm():
    kwargs = {
        "model": "Qwen/Qwen3.6-35B-A3B",
        "messages": [],
        "extra_body": {"think": False},
    }
    cleaned = _strip_non_ollama_think_param(kwargs, "http://192.168.99.1:4000/v1")
    assert "extra_body" not in cleaned


def test_strip_non_ollama_think_param_preserves_ollama_think():
    kwargs = {"extra_body": {"think": False, "options": {"num_ctx": 8192}}}
    kept = _strip_non_ollama_think_param(kwargs, "http://127.0.0.1:11434/v1")
    assert kept["extra_body"]["think"] is False
    assert kept["extra_body"]["options"]["num_ctx"] == 8192


def test_build_api_kwargs_patch_strips_think_for_custom_litellm(monkeypatch):
    import agent.chat_completion_helpers as chat_helpers

    calls: list[str] = []

    def fake_build(agent, api_messages):
        calls.append(getattr(agent, "base_url", ""))
        return {
            "model": agent.model,
            "messages": api_messages,
            "extra_body": {"think": False},
        }

    monkeypatch.setattr(chat_helpers, "build_api_kwargs", fake_build)
    patch_custom_provider_think_param()

    agent = SimpleNamespace(
        provider="custom",
        base_url="http://192.168.99.1:4000/v1",
        model="Qwen/Qwen3.6-35B-A3B",
    )
    kwargs = chat_helpers.build_api_kwargs(agent, [{"role": "user", "content": "hi"}])
    assert calls == ["http://192.168.99.1:4000/v1"]
    assert "extra_body" not in kwargs

    # Idempotent re-patch
    patch_custom_provider_think_param()


def test_apply_agent_runtime_patches_installs_think_gate(monkeypatch):
    import agent.chat_completion_helpers as chat_helpers

    original = chat_helpers.build_api_kwargs
    monkeypatch.setattr(
        chat_helpers,
        "build_api_kwargs",
        original,
        raising=False,
    )
    apply_agent_runtime_patches()
    assert getattr(chat_helpers.build_api_kwargs, "_hermes_webui_think_gated", False)
