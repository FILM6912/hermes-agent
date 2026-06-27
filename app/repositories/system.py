"""System/admin repository — wraps api.system_health, api.agent_health, and api.routes helpers."""

from __future__ import annotations

import datetime
import json
import os
import signal
import threading
import time
from typing import Any
from urllib.parse import urlencode

from starlette.responses import Response

from app.core.legacy_handler import (
    LegacyHTTPHandler,
    _HeaderProxy,
    _build_response,
    run_legacy_dispatch_sync,
)


def _json_from_legacy_response(response: Response) -> tuple[Any, int]:
    body = response.body
    if not body:
        return {}, response.status_code
    encoding = ""
    for key, value in response.headers.items():
        if key.lower() == "content-encoding":
            encoding = str(value).lower()
            break
    if encoding == "gzip":
        import gzip

        body = gzip.decompress(body)
    return json.loads(body), response.status_code


def _legacy_auth_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Forward session auth to legacy handlers (cookie and Bearer fallback)."""
    if not headers:
        return {}
    out: dict[str, str] = {}
    cookie = headers.get("cookie") or headers.get("Cookie")
    if cookie:
        out["Cookie"] = cookie
    authorization = headers.get("authorization") or headers.get("Authorization")
    if authorization:
        out["Authorization"] = authorization
    return out


class SystemRepository:
    def get_system_health(self) -> dict[str, Any]:
        from app.domain.system_health import build_system_health_payload

        return build_system_health_payload()

    def get_agent_health(self) -> dict[str, Any]:
        from app.domain.agent_health import build_agent_health_payload

        return build_agent_health_payload()

    def get_plugins(self) -> dict[str, Any]:
        from app.domain.routes import (
            _PLUGIN_VISIBILITY_HOOKS,
            _plugin_visibility_payload,
        )

        try:
            return _plugin_visibility_payload()
        except Exception:
            return {
                "plugins": [],
                "empty": True,
                "supported_hooks": list(_PLUGIN_VISIBILITY_HOOKS),
                "read_only": True,
                "unavailable": True,
            }

    def get_wiki_status(self) -> dict[str, Any]:
        from app.domain.routes import _build_llm_wiki_status

        return _build_llm_wiki_status()

    def get_gateway_status(self) -> dict[str, Any]:
        from app.domain.agent_health import build_agent_health_payload
        from app.domain.routes import (
            _gateway_session_metadata_path,
            _load_gateway_session_identity_map,
            _normalize_messaging_source,
        )

        identity_map = _load_gateway_session_identity_map()
        sessions_path = _gateway_session_metadata_path()

        health = build_agent_health_payload()
        alive = health.get("alive")
        if alive is True:
            running = True
            configured = True
        elif alive is False:
            running = False
            configured = True
        else:
            running = bool(identity_map)
            configured = bool(identity_map)

        platforms_set: set[str] = set()
        for meta in identity_map.values():
            raw = meta.get("raw_source") or meta.get("platform") or ""
            norm = _normalize_messaging_source(raw)
            if norm:
                platforms_set.add(norm)
        platform_labels = {
            "telegram": "Telegram",
            "discord": "Discord",
            "slack": "Slack",
            "email": "Email",
            "web": "Web",
            "api": "API",
        }
        platforms = sorted(
            [{"name": p, "label": platform_labels.get(p, p.title())} for p in platforms_set],
            key=lambda item: item["label"],
        )
        last_active = ""
        if running and sessions_path.exists():
            try:
                mtime = sessions_path.stat().st_mtime
                last_active = datetime.datetime.fromtimestamp(mtime).isoformat()
            except Exception:
                pass
        return {
            "running": running,
            "configured": configured,
            "platforms": platforms,
            "last_active": last_active,
            "session_count": len(identity_map),
        }

    def get_logs(
        self,
        *,
        file_key: str | None = None,
        tail: str | None = None,
        profile: str | None = None,
        username: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], int | None]:
        from app.domain.routes import _handle_logs

        query: dict[str, str] = {}
        if file_key is not None:
            query["file"] = file_key
        if tail is not None:
            query["tail"] = tail
        if profile:
            query["profile"] = profile
        if username:
            query["username"] = username
        path = "/api/logs"
        if query:
            path = f"{path}?{urlencode(query)}"
        response = run_legacy_dispatch_sync(
            method="GET",
            path=path,
            headers=_legacy_auth_headers(headers),
            dispatch=lambda handler, parsed: _handle_logs(handler, parsed),
        )
        payload, status = _json_from_legacy_response(response)
        return payload, status if status != 200 else None

    def get_insights(
        self,
        *,
        days: int = 30,
        profile: str | None = None,
        username: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        from app.domain.routes import _handle_insights

        query: dict[str, str] = {"days": str(days)}
        if profile:
            query["profile"] = profile
        if username:
            query["username"] = username
        response = run_legacy_dispatch_sync(
            method="GET",
            path=f"/api/insights?{urlencode(query)}",
            headers=_legacy_auth_headers(headers),
            dispatch=lambda handler, parsed: _handle_insights(handler, parsed),
        )
        payload, status = _json_from_legacy_response(response)
        if status != 200:
            from fastapi import HTTPException

            detail = payload.get("error") if isinstance(payload, dict) else payload
            raise HTTPException(status_code=status, detail=detail)
        return payload

    def shutdown(self) -> dict[str, str]:
        def _do_shutdown() -> None:
            time.sleep(0.3)
            os.kill(os.getpid(), signal.SIGINT)

        threading.Thread(target=_do_shutdown, daemon=True).start()
        return {"status": "shutting_down"}

    def admin_reload(self) -> dict[str, str]:
        import importlib

        from app.domain import models as models_module

        importlib.reload(models_module)
        import app.domain.routes as routes_module

        routes_module.get_session = models_module.get_session
        routes_module.Session = models_module.Session
        routes_module.compact = models_module.compact
        return {"status": "ok", "reloaded": "app.domain.models"}

    def transcribe(self, *, headers: dict[str, str], body: bytes) -> Response:
        from app.domain.upload import handle_transcribe

        return run_legacy_dispatch_sync(
            method="POST",
            path="/api/transcribe",
            headers=headers,
            body=body,
            dispatch=lambda handler, parsed: handle_transcribe(handler),
        )

    def log_client_event(
        self,
        *,
        body: bytes,
        headers: dict[str, str],
        client_host: str,
        client_port: int = 0,
    ) -> tuple[dict[str, Any], int | None]:
        del headers, client_port  # parity with legacy dispatch signature
        from app.domain.handlers.client_diagnostics import process_client_event_log

        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            payload = {"event": "invalid", "reason": "invalid_json"}
        if not isinstance(payload, dict):
            payload = {"event": "invalid", "reason": "not_object"}
        result, status = process_client_event_log(client_host, payload)
        return result, status if status != 200 else None
