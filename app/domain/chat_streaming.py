"""WebUI-owned chat streaming seam (architecture c1).

Single external interface for chat SSE delivery, stream registration, cancel,
and lifecycle status. The agent producer remains in ``app.domain.streaming``
(``_run_agent_streaming``, ``cancel_stream``); this module owns orchestration
glue and byte-level SSE framing for ``/api/v1/chat/*`` and legacy ``/api/chat/*``.

Invariants (PR1 — no HTTP contract changes):
- ``GET /api/v1/chat/stream`` and legacy ``/api/chat/stream`` emit the same SSE
  frames, heartbeats, terminal events, and journal replay semantics.
- ``GET /api/v1/chat/cancel`` and legacy cancel paths delegate to
  ``streaming.cancel_stream`` (or the runtime adapter when enabled).
- Stream registration uses ``STREAMS`` / ``STREAMS_LOCK`` from ``config``; only
  one live channel per ``stream_id``.
- Journal replay reads ``run_journal`` summaries; dead streams may synthesize
  stale-interrupted terminal events.
- Non-chat SSE (approval, clarify, gateway, terminal) stays outside this module.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import queue
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

logger = logging.getLogger(__name__)

SSE_HEARTBEAT_INTERVAL_SECONDS = 5

SSE_RESPONSE_HEADERS: list[tuple[str, str]] = [
    ("Content-Type", "text/event-stream; charset=utf-8"),
    ("Cache-Control", "no-cache"),
    ("X-Accel-Buffering", "no"),
    ("Connection", "close"),
]

# ``stream_end`` ends the assistant turn but the SSE channel may stay open for
# late ``title`` / ``title_status`` events from background title generation.
_TERMINAL_SSE_EVENTS = frozenset({"stream_close", "error", "cancel"})


# ── SSE framing ─────────────────────────────────────────────────────────────


def format_sse_event(event: str, data: Any, event_id: str | None = None) -> bytes:
    """Format one SSE frame as UTF-8 bytes."""
    parts: list[str] = []
    if event_id:
        parts.append(f"id: {event_id}\n")
    parts.append(f"event: {event}\n")
    parts.append(f"data: {json.dumps(data, ensure_ascii=False)}\n\n")
    return "".join(parts).encode("utf-8")


def parse_after_seq(raw: str | None) -> int | None:
    """Parse ``after_seq`` query param for journal replay cursors."""
    if raw in (None, ""):
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


# ── Run journal replay ────────────────────────────────────────────────────────


def _find_run_summary(stream_id: str):
    from app.domain.run_journal import find_run_summary

    return find_run_summary(stream_id)


def _read_run_events(session_id: str, stream_id: str, *, after_seq: int | None):
    from app.domain.run_journal import read_run_events

    return read_run_events(session_id, stream_id, after_seq=after_seq)


def _stale_interrupted_event(session_id: str, stream_id: str, *, after_seq: int | None):
    from app.domain.run_journal import stale_interrupted_event

    return stale_interrupted_event(session_id, stream_id, after_seq=after_seq)


def journal_replay_available(stream_id: str) -> bool:
    if not stream_id:
        return False
    try:
        return bool(_find_run_summary(stream_id))
    except Exception:
        return False


def run_journal_status_payload(summary: dict, *, active: bool = False) -> dict:
    """Shape run-journal summary for ``/api/chat/stream/status`` responses."""
    terminal = bool(summary.get("terminal"))
    terminal_state = summary.get("terminal_state")
    if not active and not terminal:
        terminal_state = "lost-worker-bookkeeping"
    return {
        "session_id": summary.get("session_id"),
        "run_id": summary.get("run_id"),
        "last_seq": summary.get("last_seq"),
        "last_event_id": summary.get("last_event_id"),
        "last_event": summary.get("last_event"),
        "terminal": terminal,
        "terminal_state": terminal_state,
    }


def iter_journal_replay_bytes(stream_id: str, after_seq: int | None) -> Iterator[bytes]:
    """Replay journaled SSE events for a dead or completed stream."""
    summary = _find_run_summary(stream_id)
    if not summary:
        return

    journal = _read_run_events(
        str(summary.get("session_id") or ""),
        stream_id,
        after_seq=after_seq,
    )
    for entry in journal.get("events") or []:
        yield format_sse_event(
            entry.get("event") or entry.get("type") or "message",
            entry.get("payload"),
            entry.get("event_id"),
        )

    if not summary.get("terminal"):
        stale = _stale_interrupted_event(
            str(summary.get("session_id") or ""),
            stream_id,
            after_seq=after_seq,
        )
        if stale:
            yield format_sse_event(
                stale["event"],
                stale["payload"],
                stale.get("event_id"),
            )


def replay_run_journal_to_handler(
    handler,
    stream_id: str,
    after_seq: int | None,
) -> bool:
    """Write journaled SSE bytes to a legacy handler; return False if unavailable."""
    if not journal_replay_available(stream_id):
        return False
    for chunk in iter_journal_replay_bytes(stream_id, after_seq):
        handler.wfile.write(chunk)
        handler.wfile.flush()
    return True


# ── Live stream subscription ─────────────────────────────────────────────────


def _get_live_stream(stream_id: str):
    from app.domain.config import STREAMS

    return STREAMS.get(stream_id)


def is_stream_active(stream_id: str) -> bool:
    from app.domain.config import STREAMS

    return bool(stream_id) and stream_id in STREAMS


def iter_live_chat_stream_bytes(stream_id: str) -> Iterator[bytes]:
    """Subscribe to an in-memory chat stream and yield SSE bytes until terminal."""
    from app.domain.config import STREAM_LAST_EVENT_ID

    stream = _get_live_stream(stream_id)
    if stream is None:
        return

    subscriber = stream.subscribe() if hasattr(stream, "subscribe") else stream
    try:
        while True:
            try:
                event, data = subscriber.get(timeout=SSE_HEARTBEAT_INTERVAL_SECONDS)
            except queue.Empty:
                yield b": heartbeat\n\n"
                continue

            event_id = STREAM_LAST_EVENT_ID.get(stream_id)
            yield format_sse_event(event, data, event_id)
            if event in _TERMINAL_SSE_EVENTS:
                break
    finally:
        if subscriber is not stream and hasattr(stream, "unsubscribe"):
            with contextlib.suppress(Exception):
                stream.unsubscribe(subscriber)


async def iter_chat_sse_bytes(
    stream_id: str,
    *,
    after_seq: int | None = None,
    request: Request | None = None,
) -> AsyncIterator[bytes]:
    """Async SSE byte generator for an active or replayable chat stream."""
    stream = _get_live_stream(stream_id)
    if stream is None:
        if not journal_replay_available(stream_id):
            return
        for chunk in iter_journal_replay_bytes(stream_id, after_seq):
            yield chunk
        return

    from app.domain.config import STREAM_LAST_EVENT_ID

    subscriber = stream.subscribe() if hasattr(stream, "subscribe") else stream
    loop = asyncio.get_running_loop()
    try:
        while True:
            if request is not None and await request.is_disconnected():
                break

            try:
                event, data = await loop.run_in_executor(
                    None,
                    lambda: subscriber.get(timeout=SSE_HEARTBEAT_INTERVAL_SECONDS),
                )
            except queue.Empty:
                yield b": heartbeat\n\n"
                continue

            event_id = STREAM_LAST_EVENT_ID.get(stream_id)
            yield format_sse_event(event, data, event_id)
            if event in _TERMINAL_SSE_EVENTS:
                break
    finally:
        if subscriber is not stream and hasattr(stream, "unsubscribe"):
            with contextlib.suppress(Exception):
                stream.unsubscribe(subscriber)


def build_chat_stream_response(
    *,
    stream_id: str,
    after_seq: int | None = None,
    request: Request | None = None,
) -> Response:
    """Return a JSON error or ``StreamingResponse`` for chat SSE."""
    if not stream_id:
        return JSONResponse({"error": "stream not found"}, status_code=404)

    stream = _get_live_stream(stream_id)
    if stream is None and not journal_replay_available(stream_id):
        return JSONResponse({"error": "stream not found"}, status_code=404)

    async def _body() -> AsyncIterator[bytes]:
        async for chunk in iter_chat_sse_bytes(
            stream_id,
            after_seq=after_seq,
            request=request,
        ):
            yield chunk

    response = StreamingResponse(
        _body(),
        status_code=200,
        media_type="text/event-stream; charset=utf-8",
    )
    for key, value in SSE_RESPONSE_HEADERS:
        if key.lower() != "content-type":
            response.headers[key] = value
    return response


def write_legacy_chat_sse_stream(handler, parsed, *, disconnect_errors: tuple[type, ...]) -> bool:
    """Write chat SSE through a legacy ``BaseHTTPRequestHandler``-shim handler."""
    from urllib.parse import parse_qs

    qs = parse_qs(parsed.query)
    stream_id = qs.get("stream_id", [""])[0]
    after_seq = parse_after_seq(qs.get("after_seq", [None])[0])

    stream = _get_live_stream(stream_id)
    if stream is None:
        if not journal_replay_available(stream_id):
            from app.domain.helpers import j

            j(handler, {"error": "stream not found"}, status=404)
            return True

        handler.send_response(200)
        for key, value in SSE_RESPONSE_HEADERS:
            handler.send_header(key, value)
        handler.end_headers()
        try:
            for chunk in iter_journal_replay_bytes(stream_id, after_seq):
                handler.wfile.write(chunk)
                handler.wfile.flush()
        except disconnect_errors:
            pass
        return True

    handler.send_response(200)
    for key, value in SSE_RESPONSE_HEADERS:
        handler.send_header(key, value)
    handler.end_headers()
    try:
        for chunk in iter_live_chat_stream_bytes(stream_id):
            handler.wfile.write(chunk)
            handler.wfile.flush()
    except disconnect_errors:
        pass
    return True


# ── Cancel and status ─────────────────────────────────────────────────────────


def cancel_chat_stream(stream_id: str) -> tuple[dict[str, Any], int]:
    """Cancel an in-flight chat stream (shared by v1 and legacy routes)."""
    stream_id = str(stream_id or "").strip()
    if not stream_id:
        return {"error": "stream_id required"}, 400

    from app.domain.runtime_adapter import LegacyJournalRuntimeAdapter, runtime_adapter_enabled
    from app.domain.streaming import cancel_stream

    if runtime_adapter_enabled():
        adapter = LegacyJournalRuntimeAdapter(cancel_delegate=cancel_stream)
        cancelled = adapter.cancel_run(stream_id).accepted
    else:
        cancelled = cancel_stream(stream_id)

    return {
        "ok": True,
        "cancelled": cancelled,
        "stream_id": stream_id,
    }, 200


def chat_stream_status_payload(stream_id: str) -> dict[str, Any]:
    """Poll chat stream lifecycle state (``/api/v1/chat/stream/status``)."""
    from app.domain.run_journal import find_run_summary

    stream_id = str(stream_id or "")
    active = is_stream_active(stream_id)
    payload: dict[str, Any] = {
        "active": active,
        "stream_id": stream_id,
        "replay_available": False,
    }
    try:
        journal = find_run_summary(stream_id) if stream_id else None
    except Exception:
        journal = None
    if journal:
        payload["replay_available"] = True
        payload["journal"] = run_journal_status_payload(journal, active=active)
    return payload


# ── Stream registration and worker start ──────────────────────────────────────


def new_chat_stream_id() -> str:
    return uuid.uuid4().hex


def register_chat_stream_channel(stream_id: str, *, goal_related: bool = False):
    """Create an in-memory SSE channel and register it under ``stream_id``."""
    from app.domain.config import STREAMS, STREAMS_LOCK, STREAM_GOAL_RELATED, create_stream_channel

    stream = create_stream_channel()
    with STREAMS_LOCK:
        STREAMS[stream_id] = stream
    if goal_related:
        STREAM_GOAL_RELATED[stream_id] = True
    return stream


def run_agent_streaming_in_request_context(fn) -> None:
    """Run an agent worker callable with the caller's contextvars (profile/user access)."""
    contextvars.copy_context().run(fn)


def start_chat_agent_worker(
    session_id: str,
    msg: str,
    model: str,
    workspace: str,
    stream_id: str,
    attachments,
    *,
    model_provider=None,
    goal_related: bool = False,
    ephemeral: bool = False,
) -> threading.Thread:
    """Spawn the background producer thread for a chat stream."""
    from app.domain.streaming import _run_agent_streaming

    ctx = contextvars.copy_context()

    def _run() -> None:
        _run_agent_streaming(
            session_id,
            msg,
            model,
            workspace,
            stream_id,
            attachments,
            model_provider=model_provider,
            goal_related=goal_related,
            ephemeral=ephemeral,
        )

    thr = threading.Thread(target=ctx.run, args=(_run,), daemon=True)
    thr.start()
    return thr


def session_has_live_active_stream(session) -> tuple[bool, str | None]:
    """Return whether ``session`` has a stream id still registered in ``STREAMS``."""
    from app.domain.config import STREAMS, STREAMS_LOCK

    current_stream_id = getattr(session, "active_stream_id", None)
    if not current_stream_id:
        return False, None
    with STREAMS_LOCK:
        return current_stream_id in STREAMS, current_stream_id
