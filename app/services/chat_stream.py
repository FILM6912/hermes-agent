"""Chat SSE service shim — delegates to ``app.domain.chat_streaming``.

Kept for import stability (FastAPI phase 3 paths and tests). New code should
import from ``app.domain.chat_streaming`` directly.
"""

from __future__ import annotations

from app.domain.chat_streaming import (  # noqa: F401
    SSE_HEARTBEAT_INTERVAL_SECONDS,
    SSE_RESPONSE_HEADERS,
    _TERMINAL_SSE_EVENTS,
    _find_run_summary,
    _read_run_events,
    _stale_interrupted_event,
    build_chat_stream_response,
    format_sse_event,
    iter_chat_sse_bytes,
    iter_journal_replay_bytes,
    iter_live_chat_stream_bytes,
    journal_replay_available,
    parse_after_seq,
    write_legacy_chat_sse_stream,
)

__all__ = [
    "SSE_HEARTBEAT_INTERVAL_SECONDS",
    "SSE_RESPONSE_HEADERS",
    "_TERMINAL_SSE_EVENTS",
    "_find_run_summary",
    "_read_run_events",
    "_stale_interrupted_event",
    "build_chat_stream_response",
    "format_sse_event",
    "iter_chat_sse_bytes",
    "iter_journal_replay_bytes",
    "iter_live_chat_stream_bytes",
    "journal_replay_available",
    "parse_after_seq",
    "write_legacy_chat_sse_stream",
]
