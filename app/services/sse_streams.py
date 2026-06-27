"""Native async SSE stream services for approval, clarify, and session events."""

from __future__ import annotations

import asyncio
import queue
from collections.abc import AsyncIterator, Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from app.services.chat_stream import (
    SSE_HEARTBEAT_INTERVAL_SECONDS,
    SSE_RESPONSE_HEADERS,
    format_sse_event,
)


def _streaming_sse_response(body: AsyncIterator[bytes]) -> StreamingResponse:
    response = StreamingResponse(
        body,
        status_code=200,
        media_type="text/event-stream; charset=utf-8",
    )
    for key, value in SSE_RESPONSE_HEADERS:
        if key.lower() != "content-type":
            response.headers[key] = value
    return response


async def _iter_queue_sse_bytes(
    q: queue.Queue,
    *,
    request: Request | None = None,
    heartbeat: bytes = b": keepalive\n\n",
    format_payload: Callable[[Any], tuple[str, Any] | None] | None = None,
) -> AsyncIterator[bytes]:
    loop = asyncio.get_running_loop()
    while True:
        if request is not None and await request.is_disconnected():
            break

        try:
            payload = await loop.run_in_executor(
                None,
                lambda: q.get(timeout=SSE_HEARTBEAT_INTERVAL_SECONDS),
            )
        except queue.Empty:
            yield heartbeat
            continue

        if payload is None:
            break

        if format_payload is not None:
            formatted = format_payload(payload)
            if formatted is None:
                continue
            event, data = formatted
            yield format_sse_event(event, data)


def _approval_subscribe_with_snapshot(session_id: str) -> tuple[queue.Queue, dict | None, int]:
    import queue as queue_module

    from app.domain.routes import (
        _approval_head_locked,
        _approval_sse_subscribers,
        _lock,
    )

    q: queue.Queue = queue_module.Queue(maxsize=16)
    initial_pending = None
    initial_count = 0
    with _lock:
        _approval_sse_subscribers.setdefault(session_id, []).append(q)
        initial_pending, initial_count = _approval_head_locked(session_id)
    return q, initial_pending, initial_count


def _approval_unsubscribe(session_id: str, q: queue.Queue) -> None:
    from app.domain.routes import _approval_sse_unsubscribe

    _approval_sse_unsubscribe(session_id, q)


async def iter_approval_sse_bytes(
    session_id: str,
    *,
    request: Request | None = None,
) -> AsyncIterator[bytes]:
    q, initial_pending, initial_count = _approval_subscribe_with_snapshot(session_id)
    try:
        yield format_sse_event(
            "initial",
            {"pending": initial_pending, "pending_count": initial_count},
        )
        async for chunk in _iter_queue_sse_bytes(
            q,
            request=request,
            format_payload=lambda payload: ("approval", payload),
        ):
            yield chunk
    finally:
        _approval_unsubscribe(session_id, q)


def build_approval_stream_response(
    *,
    session_id: str,
    request: Request | None = None,
) -> Response:
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    async def _body() -> AsyncIterator[bytes]:
        async for chunk in iter_approval_sse_bytes(session_id, request=request):
            yield chunk

    return _streaming_sse_response(_body())


def _clarify_subscribe_with_snapshot(session_id: str) -> tuple[queue.Queue, dict | None, int]:
    import queue as queue_module

    from app.domain.clarify import (
        _clarify_sse_subscribers,
        _gateway_queues,
        _lock as _clarify_lock,
        _pending as _clarify_pending,
    )

    q: queue.Queue = queue_module.Queue(maxsize=16)
    initial_pending = None
    initial_count = 0
    with _clarify_lock:
        _clarify_sse_subscribers.setdefault(session_id, []).append(q)
        gw_q = _gateway_queues.get(session_id) or []
        if gw_q:
            initial_pending = dict(gw_q[0].data)
            initial_count = len(gw_q)
        else:
            legacy = _clarify_pending.get(session_id)
            if legacy:
                initial_pending = dict(legacy)
                initial_count = 1
    return q, initial_pending, initial_count


def _clarify_unsubscribe(session_id: str, q: queue.Queue) -> None:
    from app.domain.clarify import sse_unsubscribe

    sse_unsubscribe(session_id, q)


async def iter_clarify_sse_bytes(
    session_id: str,
    *,
    request: Request | None = None,
) -> AsyncIterator[bytes]:
    q, initial_pending, initial_count = _clarify_subscribe_with_snapshot(session_id)
    try:
        yield format_sse_event(
            "initial",
            {"pending": initial_pending, "pending_count": initial_count},
        )
        async for chunk in _iter_queue_sse_bytes(
            q,
            request=request,
            format_payload=lambda payload: ("clarify", payload),
        ):
            yield chunk
    finally:
        _clarify_unsubscribe(session_id, q)


def build_clarify_stream_response(
    *,
    session_id: str,
    request: Request | None = None,
) -> Response:
    from app.domain.routes import clarify_sse_subscribe  # noqa: PLC0415

    if clarify_sse_subscribe is None:
        return JSONResponse({"error": "clarify SSE not available"}, status_code=400)

    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    async def _body() -> AsyncIterator[bytes]:
        async for chunk in iter_clarify_sse_bytes(session_id, request=request):
            yield chunk

    return _streaming_sse_response(_body())


async def iter_session_events_sse_bytes(
    *,
    request: Request | None = None,
) -> AsyncIterator[bytes]:
    from app.domain.session_events import subscribe_session_events, unsubscribe_session_events

    q = subscribe_session_events()
    try:
        async for chunk in _iter_queue_sse_bytes(
            q,
            request=request,
            format_payload=lambda event_data: (
                event_data.get("type", "sessions_changed"),
                event_data,
            ),
        ):
            yield chunk
    finally:
        unsubscribe_session_events(q)


def build_session_events_stream_response(
    *,
    request: Request | None = None,
) -> Response:
    async def _body() -> AsyncIterator[bytes]:
        async for chunk in iter_session_events_sse_bytes(request=request):
            yield chunk

    return _streaming_sse_response(_body())


def _gateway_sse_probe_payload(settings: dict, watcher) -> tuple[dict, int]:
    enabled = bool(settings.get("show_cli_sessions"))
    if watcher is None:
        watcher_alive = False
    elif hasattr(watcher, "is_alive") and callable(getattr(watcher, "is_alive")):
        watcher_alive = bool(watcher.is_alive())
    else:
        thread = getattr(watcher, "_thread", None)
        watcher_alive = thread is not None and thread.is_alive()
    payload = {
        "enabled": enabled,
        "fallback_poll_ms": 30000,
        "ok": enabled and watcher_alive,
        "watcher_running": watcher_alive,
    }
    if not enabled:
        payload["error"] = "agent sessions not enabled"
        return payload, 404
    if not watcher_alive:
        payload["error"] = "watcher not started"
        return payload, 503
    return payload, 200


async def iter_gateway_sse_bytes(
    *,
    request: Request | None = None,
) -> AsyncIterator[bytes]:
    from app.domain.gateway_watcher import get_watcher
    from app.domain.models import get_cli_sessions

    watcher = get_watcher()
    q = watcher.subscribe()
    try:
        initial = get_cli_sessions()
        yield format_sse_event("sessions_changed", {"sessions": initial})

        async for chunk in _iter_queue_sse_bytes(
            q,
            request=request,
            format_payload=lambda event_data: (
                event_data.get("type", "sessions_changed"),
                event_data,
            ),
        ):
            yield chunk
    finally:
        watcher.unsubscribe(q)


def build_gateway_stream_response(
    *,
    probe: bool = False,
    request: Request | None = None,
) -> Response:
    from app.domain.config import load_settings
    from app.domain.gateway_watcher import get_watcher

    settings = load_settings()
    watcher = get_watcher()

    if probe:
        payload, status = _gateway_sse_probe_payload(settings, watcher)
        return JSONResponse(payload, status_code=status)

    if not settings.get("show_cli_sessions"):
        return JSONResponse({"error": "agent sessions not enabled"}, status_code=404)

    probe_body, _probe_status = _gateway_sse_probe_payload(settings, watcher)
    if not probe_body["watcher_running"]:
        return JSONResponse({"error": "watcher not started"}, status_code=503)

    async def _body() -> AsyncIterator[bytes]:
        async for chunk in iter_gateway_sse_bytes(request=request):
            yield chunk

    return _streaming_sse_response(_body())

def _kanban_sse_parsed_query(request: Request):
    from urllib.parse import urlparse

    query = request.url.query
    legacy = "/api/kanban/events/stream"
    if query:
        legacy = f"{legacy}?{query}"
    return urlparse(legacy)


def _kanban_sse_initial_cursor(request: Request, parsed) -> int:
    from urllib.parse import parse_qs

    qs = parse_qs(parsed.query or "")
    since_raw = (qs.get("since") or [None])[0]
    if since_raw is None:
        since_raw = request.headers.get("last-event-id")
    try:
        cursor = int(since_raw) if since_raw is not None else 0
    except (TypeError, ValueError):
        cursor = 0
    return max(cursor, 0)


async def iter_kanban_sse_bytes(
    *,
    request: Request,
    board,
    parsed,
) -> AsyncIterator[bytes]:
    import asyncio
    import json
    import time

    from app.domain.kanban_bridge import (
        _KANBAN_SSE_HEARTBEAT_SECONDS,
        _KANBAN_SSE_POLL_SECONDS,
        _kanban_sse_fetch_new,
    )
    from app.domain.profiles import profile_request_context

    cursor = _kanban_sse_initial_cursor(request, parsed)
    yield format_sse_event("hello", {"cursor": cursor, "board": board})

    loop = asyncio.get_running_loop()
    last_heartbeat = time.monotonic()
    while True:
        if await request.is_disconnected():
            break

        def _fetch() -> tuple[int, list]:
            with profile_request_context():
                return _kanban_sse_fetch_new(board, cursor)

        cursor, events = await loop.run_in_executor(None, _fetch)
        if events:
            yield format_sse_event(
                "events",
                {"events": events, "cursor": cursor},
                event_id=str(cursor),
            )
            last_heartbeat = time.monotonic()
        elif (time.monotonic() - last_heartbeat) >= _KANBAN_SSE_HEARTBEAT_SECONDS:
            yield b": keepalive\n\n"
            last_heartbeat = time.monotonic()

        await asyncio.sleep(_KANBAN_SSE_POLL_SECONDS)


def build_kanban_stream_response(
    *,
    request: Request,
) -> Response:
    from app.domain.kanban_bridge import _resolve_board

    parsed = _kanban_sse_parsed_query(request)
    try:
        board = _resolve_board(parsed)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    async def _body() -> AsyncIterator[bytes]:
        async for chunk in iter_kanban_sse_bytes(
            request=request,
            board=board,
            parsed=parsed,
        ):
            yield chunk

    return _streaming_sse_response(_body())

