"""Native async terminal SSE stream service (FastAPI phase 3)."""

from __future__ import annotations

import asyncio
import queue
from collections.abc import AsyncIterator

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from app.services.chat_stream import (
    SSE_HEARTBEAT_INTERVAL_SECONDS,
    SSE_RESPONSE_HEADERS,
    format_sse_event,
)

_TERMINAL_SSE_EVENTS = frozenset({"terminal_closed", "terminal_error"})


async def iter_terminal_sse_bytes(
    session_id: str,
    *,
    request: Request | None = None,
) -> AsyncIterator[bytes]:
    """Async SSE byte generator for embedded terminal output."""
    from app.domain.terminal import get_terminal

    term = get_terminal(session_id)
    if term is None:
        return

    loop = asyncio.get_running_loop()
    while True:
        if request is not None and await request.is_disconnected():
            break

        try:
            event, data = await loop.run_in_executor(
                None,
                lambda: term.output.get(timeout=SSE_HEARTBEAT_INTERVAL_SECONDS),
            )
        except queue.Empty:
            yield b": terminal heartbeat\n\n"
            if term.closed.is_set() and term.output.empty():
                yield format_sse_event(
                    "terminal_closed",
                    {"exit_code": term.proc.poll()},
                )
                break
            continue

        yield format_sse_event(event, data)
        if event in _TERMINAL_SSE_EVENTS:
            break


def build_terminal_output_stream_response(
    *,
    session_id: str,
    request: Request | None = None,
) -> Response:
    """Return a JSON error or ``StreamingResponse`` for terminal SSE."""
    if not session_id:
        return JSONResponse({"error": "session_id required"}, status_code=400)

    from app.domain.terminal import get_terminal

    if get_terminal(session_id) is None:
        return JSONResponse({"error": "terminal not running"}, status_code=404)

    async def _body() -> AsyncIterator[bytes]:
        async for chunk in iter_terminal_sse_bytes(session_id, request=request):
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
