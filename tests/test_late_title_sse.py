"""Regression: background title SSE must arrive after stream_end."""

from __future__ import annotations

import json
import queue
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CHAT_STREAMING = (REPO / "app" / "domain" / "chat_streaming.py").read_text(encoding="utf-8")
STREAMING = (REPO / "app" / "domain" / "streaming.py").read_text(encoding="utf-8")
FRONTEND_CHAT = (REPO / "frontend" / "src" / "services" / "hermes" / "chat.ts").read_text(
    encoding="utf-8"
)


def test_chat_sse_keeps_stream_open_after_stream_end_for_title():
    assert '"stream_end"' not in CHAT_STREAMING.split("_TERMINAL_SSE_EVENTS")[1].split(")")[0]
    assert "stream_close" in CHAT_STREAMING


def test_background_title_threads_emit_stream_close():
    for fn_name in ("_run_background_title_update", "_run_background_title_refresh"):
        start = STREAMING.index(f"def {fn_name}")
        next_def = STREAMING.find("\ndef ", start + 1)
        body = STREAMING[start:next_def]
        assert "_put_stream_close(put_event, session_id)" in body, fn_name


def test_stream_end_without_background_title_emits_stream_close():
    window = STREAMING.split("put('stream_end', {'session_id': session_id})")[1][:600]
    assert "put('stream_close', {'session_id': session_id})" in window


def test_frontend_keeps_sse_open_for_late_title():
    assert "schedulePostStreamEndClose" in FRONTEND_CHAT
    assert "addEventListener(\"stream_close\"" in FRONTEND_CHAT
    stream_end_block = FRONTEND_CHAT.split("const handleStreamEnd")[1].split("const handleStreamClose")[0]
    assert "close();" not in stream_end_block


def test_frontend_stream_chat_waits_for_stream_close():
    stream_chat = (REPO / "frontend" / "src" / "services" / "hermes" / "streamChat.ts").read_text(
        encoding="utf-8"
    )
    assert "onStreamClose:" in stream_chat
    assert "state.finished = true" in stream_chat.split("onStreamClose:")[1].split("onError:")[0]
    stream_end_block = stream_chat.split("onStreamEnd:")[1].split("onStreamClose:")[0]
    assert "state.finished = true" not in stream_end_block
    assert 'type: "turn_end"' in stream_end_block


def test_iter_live_chat_stream_delivers_title_after_stream_end():
    from app.domain.chat_streaming import format_sse_event, iter_live_chat_stream_bytes
    from app.domain.config import STREAMS, STREAMS_LOCK, create_stream_channel

    stream_id = "test-late-title-stream"
    channel = create_stream_channel()
    with STREAMS_LOCK:
        STREAMS[stream_id] = channel

    try:
        channel.put_nowait(("stream_end", {"session_id": "sess-1"}))
        channel.put_nowait(("title", {"session_id": "sess-1", "title": "การทักทายเริ่มต้น"}))
        channel.put_nowait(("stream_close", {"session_id": "sess-1"}))

        frames = list(iter_live_chat_stream_bytes(stream_id))
        events = []
        for frame in frames:
            text = frame.decode("utf-8")
            for line in text.splitlines():
                if line.startswith("event: "):
                    events.append(line.split(": ", 1)[1])

        assert "stream_end" in events
        assert "title" in events
        assert events.index("title") > events.index("stream_end")
        assert events[-1] == "stream_close"
    finally:
        with STREAMS_LOCK:
            STREAMS.pop(stream_id, None)
