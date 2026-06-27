"""Browser CSP reports and sanitized client SSE diagnostic events (c3 PR1).

Owns rate limiting, payload sanitization, and logging for:
- ``POST /api/csp-report`` (legacy; stays outside ``/api/v1`` normalizer)
- ``POST /api/client-events/log`` and ``POST /api/v1/client-events/log``

Legacy ``routes.handle_post`` delegates here; native v1 uses
``process_client_event_log`` via ``SystemRepository.log_client_event``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import urlsplit

_CSP_REPORT_LOGGER = logging.getLogger("csp_report")
_CSP_REPORT_RATE_LIMIT: dict[str, list[float]] = {}
_CSP_REPORT_RATE_LIMIT_LOCK = threading.Lock()
_CSP_REPORT_RATE_LIMIT_WINDOW_SECONDS = 60
_CSP_REPORT_RATE_LIMIT_MAX = 100
_CSP_REPORT_MAX_BODY_BYTES = 64 * 1024

_CLIENT_EVENT_LOGGER = logging.getLogger("client_event")
_CLIENT_EVENT_RATE_LIMIT: dict[str, list[float]] = {}
_CLIENT_EVENT_RATE_LIMIT_LOCK = threading.Lock()
_CLIENT_EVENT_RATE_LIMIT_WINDOW_SECONDS = 60
_CLIENT_EVENT_RATE_LIMIT_MAX = 30
_CLIENT_EVENT_MAX_BODY_BYTES = 4 * 1024
_CLIENT_EVENT_ALLOWED_FIELDS = {
    "event": 64,
    "source": 80,
    "session_id": 128,
    "stream_id": 128,
    "visibility_state": 32,
    "url_path": 256,
    "reason": 160,
}


def _client_ip_for_rate_limit(handler) -> str:
    try:
        address = getattr(handler, "client_address", None)
        if address:
            return str(address[0])
    except Exception:
        pass
    return "unknown"


def _client_ip_from_host(client_host: str | None) -> str:
    text = str(client_host or "").strip()
    return text if text else "unknown"


def _csp_report_rate_limited(handler, *, now: float | None = None) -> bool:
    return _csp_report_rate_limited_for_ip(_client_ip_for_rate_limit(handler), now=now)


def _effective_csp_rate_limit_max() -> int:
    """Honor ``routes._CSP_REPORT_RATE_LIMIT_MAX`` overrides used in tests."""
    try:
        from app.domain import routes

        return int(getattr(routes, "_CSP_REPORT_RATE_LIMIT_MAX", _CSP_REPORT_RATE_LIMIT_MAX))
    except Exception:
        return _CSP_REPORT_RATE_LIMIT_MAX


def _csp_report_rate_limited_for_ip(client_ip: str, *, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    key = client_ip
    cutoff = now - _CSP_REPORT_RATE_LIMIT_WINDOW_SECONDS
    limit_max = _effective_csp_rate_limit_max()
    with _CSP_REPORT_RATE_LIMIT_LOCK:
        timestamps = [ts for ts in _CSP_REPORT_RATE_LIMIT.get(key, []) if ts >= cutoff]
        if len(timestamps) >= limit_max:
            _CSP_REPORT_RATE_LIMIT[key] = timestamps
            return True
        timestamps.append(now)
        _CSP_REPORT_RATE_LIMIT[key] = timestamps
    return False


def _client_event_rate_limited(handler, *, now: float | None = None) -> bool:
    return _client_event_rate_limited_for_ip(_client_ip_for_rate_limit(handler), now=now)


def _effective_client_event_rate_limit_max() -> int:
    try:
        from app.domain import routes

        return int(
            getattr(routes, "_CLIENT_EVENT_RATE_LIMIT_MAX", _CLIENT_EVENT_RATE_LIMIT_MAX)
        )
    except Exception:
        return _CLIENT_EVENT_RATE_LIMIT_MAX


def _client_event_rate_limited_for_ip(client_ip: str, *, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    key = client_ip
    cutoff = now - _CLIENT_EVENT_RATE_LIMIT_WINDOW_SECONDS
    limit_max = _effective_client_event_rate_limit_max()
    with _CLIENT_EVENT_RATE_LIMIT_LOCK:
        timestamps = [ts for ts in _CLIENT_EVENT_RATE_LIMIT.get(key, []) if ts >= cutoff]
        if len(timestamps) >= limit_max:
            _CLIENT_EVENT_RATE_LIMIT[key] = timestamps
            return True
        timestamps.append(now)
        _CLIENT_EVENT_RATE_LIMIT[key] = timestamps
    return False


def _send_no_content(handler, status: int = 204) -> bool:
    handler.send_response(status)
    handler.send_header("Content-Length", "0")
    handler.end_headers()
    return True


def _read_csp_report_payload(handler):
    try:
        length = int(handler.headers.get("Content-Length", 0))
    except Exception:
        length = 0
    if length > _CSP_REPORT_MAX_BODY_BYTES:
        try:
            handler.rfile.read(_CSP_REPORT_MAX_BODY_BYTES)
        except Exception:
            pass
        return {"discarded": "body_too_large", "bytes": length}
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {"invalid": True, "bytes": len(raw)}


def handle_csp_report(handler) -> bool:
    """Collect browser CSP report-only violations without requiring auth."""
    client_ip = _client_ip_for_rate_limit(handler)
    if _csp_report_rate_limited_for_ip(client_ip):
        _CSP_REPORT_LOGGER.warning(
            "Dropped CSP report from %s: rate limit exceeded",
            client_ip,
        )
        return _send_no_content(handler)

    payload = _read_csp_report_payload(handler)
    _CSP_REPORT_LOGGER.info("CSP report from %s: %s", client_ip, payload)
    return _send_no_content(handler)


def _bounded_client_event_string(value, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def _sanitize_client_event_url_path(value) -> str | None:
    text = _bounded_client_event_string(value, 1024)
    if not text:
        return None
    try:
        parsed = urlsplit(text)
        path = parsed.path or "/"
    except Exception:
        path = text.split("?", 1)[0] or "/"
    if not path.startswith("/"):
        path = "/" + path.lstrip("/")
    return path[: _CLIENT_EVENT_ALLOWED_FIELDS["url_path"]]


def sanitize_client_event_payload(payload: dict | None) -> dict:
    """Whitelist tiny browser diagnostic events and discard sensitive content."""
    if not isinstance(payload, dict):
        return {"event": "unknown"}
    sanitized: dict[str, object] = {}
    for field, limit in _CLIENT_EVENT_ALLOWED_FIELDS.items():
        if field == "url_path":
            value = _sanitize_client_event_url_path(payload.get(field))
        else:
            value = _bounded_client_event_string(payload.get(field), limit)
        if value is not None:
            sanitized[field] = value
    ready_state = payload.get("ready_state")
    if isinstance(ready_state, bool):
        pass
    elif isinstance(ready_state, int) and 0 <= ready_state <= 3:
        sanitized["ready_state"] = ready_state
    online = payload.get("online")
    if isinstance(online, bool):
        sanitized["online"] = online
    elif isinstance(online, str):
        lowered = online.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            sanitized["online"] = True
        elif lowered in {"false", "0", "no", "off"}:
            sanitized["online"] = False
    if "event" not in sanitized:
        sanitized["event"] = "unknown"
    return sanitized


def read_client_event_payload(handler) -> dict:
    try:
        length = int(handler.headers.get("Content-Length", 0))
    except Exception:
        length = 0
    if length > _CLIENT_EVENT_MAX_BODY_BYTES:
        try:
            handler.rfile.read(_CLIENT_EVENT_MAX_BODY_BYTES)
        except Exception:
            pass
        try:
            handler.close_connection = True
        except Exception:
            pass
        return {"event": "discarded", "reason": "body_too_large"}
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        decoded = raw.decode("utf-8")
        payload = json.loads(decoded)
    except Exception:
        return {"event": "invalid", "reason": "invalid_json"}
    return payload if isinstance(payload, dict) else {"event": "invalid", "reason": "not_object"}


def process_client_event_log(client_ip: str, body: dict) -> tuple[dict, int]:
    """Core client-event logging; returns ``(json_body, http_status)``."""
    if _client_event_rate_limited_for_ip(client_ip):
        _CLIENT_EVENT_LOGGER.warning(
            "Dropped client event from %s: rate limit exceeded",
            client_ip,
        )
        return {"ok": False, "error": "rate_limited"}, 429
    payload = sanitize_client_event_payload(body)
    _CLIENT_EVENT_LOGGER.info("Client event from %s: %s", client_ip, payload)
    return {"ok": True, "event": payload.get("event")}, 200


def handle_client_event_log(handler, body: dict) -> bool:
    """Legacy HTTP handler entry; JSON framing uses ``routes.j`` for test seams."""
    from app.domain.routes import j

    result, status = process_client_event_log(_client_ip_for_rate_limit(handler), body)
    return j(handler, result, status=status) or True
