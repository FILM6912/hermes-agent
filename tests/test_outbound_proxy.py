"""Outbound HTTP proxy and API proxy env helpers."""

from __future__ import annotations

import pathlib
import urllib.request

import pytest

from app.core.outbound_proxy import (
    apply_outbound_proxy_env,
    build_url_opener,
    outbound_proxy_configured,
    outbound_proxy_settings,
)

REPO = pathlib.Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_proxy_cache(monkeypatch):
    outbound_proxy_settings.cache_clear()
    yield
    outbound_proxy_settings.cache_clear()


def test_outbound_proxy_prefers_hermes_env(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://fallback:1")
    monkeypatch.setenv("HERMES_WEBUI_HTTP_PROXY", "http://hermes:8080")
    monkeypatch.setenv("HERMES_WEBUI_HTTPS_PROXY", "http://hermes-tls:8443")
    monkeypatch.setenv("HERMES_WEBUI_NO_PROXY", "localhost,127.0.0.1")

    settings = outbound_proxy_settings()
    assert settings["http"] == "http://hermes:8080"
    assert settings["https"] == "http://hermes-tls:8443"
    assert settings["no_proxy"] == "localhost,127.0.0.1"
    assert outbound_proxy_configured() is True


def test_apply_outbound_proxy_env_injects_standard_names(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_HTTP_PROXY", "http://corp:3128")
    monkeypatch.setenv("HERMES_WEBUI_HTTPS_PROXY", "http://corp:3128")
    monkeypatch.setenv("HERMES_WEBUI_NO_PROXY", "localhost")

    env = apply_outbound_proxy_env({"PATH": "/bin"})
    assert env["HTTP_PROXY"] == "http://corp:3128"
    assert env["HTTPS_PROXY"] == "http://corp:3128"
    assert env["NO_PROXY"] == "localhost"
    assert env["PATH"] == "/bin"


def test_build_url_opener_uses_proxy_handler(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_HTTP_PROXY", "http://corp:3128")
    opener = build_url_opener()
    handler_types = {type(h).__name__ for h in opener.handlers}
    assert "ProxyHandler" in handler_types


def test_streaming_agent_env_applies_outbound_proxy():
    src = read("app/domain/streaming.py")
    assert "apply_outbound_proxy_env" in src
