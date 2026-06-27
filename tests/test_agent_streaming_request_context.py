"""Agent streaming threads inherit request contextvars (profile/user access)."""

from __future__ import annotations

from pathlib import Path


def test_start_chat_agent_worker_uses_request_context() -> None:
    src = Path("app/domain/chat_streaming.py").read_text(encoding="utf-8")
    assert "contextvars.copy_context()" in src
    assert "def run_agent_streaming_in_request_context" in src
    start = src.index("def start_chat_agent_worker(")
    end = src.index("\n\ndef session_has_live_active_stream", start)
    block = src[start:end]
    assert "ctx.run" in block
