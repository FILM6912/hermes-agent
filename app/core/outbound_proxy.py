"""Outbound HTTP(S) proxy configuration for WebUI server-side API calls."""

from __future__ import annotations

import os
import urllib.request
from functools import lru_cache
from typing import Any


def _clean_env_value(name: str) -> str:
    return (os.getenv(name) or "").strip()


@lru_cache(maxsize=1)
def outbound_proxy_settings() -> dict[str, str]:
    """Resolve outbound proxy env vars (HERMES_WEBUI_* overrides standard names)."""
    http_proxy = (
        _clean_env_value("HERMES_WEBUI_HTTP_PROXY")
        or _clean_env_value("HTTP_PROXY")
        or _clean_env_value("http_proxy")
    )
    https_proxy = (
        _clean_env_value("HERMES_WEBUI_HTTPS_PROXY")
        or _clean_env_value("HTTPS_PROXY")
        or _clean_env_value("https_proxy")
        or http_proxy
    )
    no_proxy = (
        _clean_env_value("HERMES_WEBUI_NO_PROXY")
        or _clean_env_value("NO_PROXY")
        or _clean_env_value("no_proxy")
    )
    result: dict[str, str] = {}
    if http_proxy:
        result["http"] = http_proxy
    if https_proxy:
        result["https"] = https_proxy
    if no_proxy:
        result["no_proxy"] = no_proxy
    return result


def outbound_proxy_configured() -> bool:
    settings = outbound_proxy_settings()
    return bool(settings.get("http") or settings.get("https"))


def apply_outbound_proxy_env(env: dict[str, Any] | None) -> dict[str, Any]:
    """Inject HTTP(S)_PROXY / NO_PROXY into a subprocess env dict when configured."""
    merged = dict(env or {})
    settings = outbound_proxy_settings()
    if settings.get("http"):
        merged.setdefault("HTTP_PROXY", settings["http"])
        merged.setdefault("http_proxy", settings["http"])
    if settings.get("https"):
        merged.setdefault("HTTPS_PROXY", settings["https"])
        merged.setdefault("https_proxy", settings["https"])
    if settings.get("no_proxy"):
        merged.setdefault("NO_PROXY", settings["no_proxy"])
        merged.setdefault("no_proxy", settings["no_proxy"])
    return merged


def build_url_opener(
    *,
    redirect_handler: urllib.request.BaseHandler | None = None,
) -> urllib.request.OpenerDirector:
    """Build a urllib opener that honors outbound proxy env when set."""
    handlers: list[urllib.request.BaseHandler] = []
    settings = outbound_proxy_settings()
    if settings.get("http") or settings.get("https"):
        handlers.append(
            urllib.request.ProxyHandler(
                {
                    "http": settings.get("http", ""),
                    "https": settings.get("https", settings.get("http", "")),
                }
            )
        )
    if redirect_handler is not None:
        handlers.append(redirect_handler)
    if not handlers:
        return urllib.request.build_opener()
    return urllib.request.build_opener(*handlers)


