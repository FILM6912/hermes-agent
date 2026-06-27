"""FastAPI v1 chat streaming endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.domain.chat_streaming import build_chat_stream_response, parse_after_seq
from app.services.chat_control import ChatControlService

router = APIRouter(tags=["chat"])
_service = ChatControlService()


async def _parse_json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


@router.post("/chat")
async def chat(request: Request) -> Response:
    """Synchronous chat alias (POST /api/v1/chat, legacy /api/chat)."""
    body = await _parse_json_body(request)
    return _service.chat_sync(body, headers=dict(request.headers))


@router.post("/chat/start")
async def chat_start(request: Request) -> Response:
    """Start a streaming chat turn (POST /api/v1/chat/start)."""
    body = await _parse_json_body(request)
    return _service.start_chat(body, headers=dict(request.headers))


@router.get("/chat/cancel")
def chat_cancel(stream_id: str = Query(default="")) -> Response:
    """Cancel an in-flight chat stream (GET /api/v1/chat/cancel?stream_id=...)."""
    payload, status = _service.cancel_chat(stream_id)
    return JSONResponse(content=payload, status_code=status)


@router.get("/chat/stream/status")
def chat_stream_status(stream_id: str = Query(default="")) -> dict[str, Any]:
    """Poll chat stream lifecycle state (GET /api/v1/chat/stream/status)."""
    return _service.stream_status(stream_id)


@router.post("/chat/steer")
async def chat_steer(request: Request) -> Response:
    """Inject mid-turn steer text into the active agent (POST /api/v1/chat/steer)."""
    body = await _parse_json_body(request)
    return _service.steer_chat(body, headers=dict(request.headers))


@router.get("/chat/stream", include_in_schema=False)
async def chat_stream(request: Request) -> Response:
    """SSE stream for an active chat run (GET /api/v1/chat/stream?stream_id=...)."""
    stream_id = request.query_params.get("stream_id", "")
    after_seq = parse_after_seq(request.query_params.get("after_seq"))
    return build_chat_stream_response(
        stream_id=stream_id,
        after_seq=after_seq,
        request=request,
    )
