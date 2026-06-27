"""Native FastAPI Kanban endpoints (delegates to api.kanban_bridge)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.services.kanban import KanbanService
from app.services.sse_streams import build_kanban_stream_response

router = APIRouter(tags=["kanban"])
_service = KanbanService()


@router.get("/kanban/events/stream", include_in_schema=False)
async def kanban_events_stream(request: Request) -> Response:
    """SSE stream for Kanban task events."""
    return build_kanban_stream_response(request=request)


@router.api_route("/kanban/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
async def kanban_dispatch(request: Request, path: str) -> Response:
    subpath = path.strip("/")
    if request.method == "GET" and subpath == "events/stream":
        return build_kanban_stream_response(request=request)

    body: dict = {}
    raw = await request.body()
    if raw:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            body = parsed

    return _service.dispatch(
        method=request.method,
        subpath=subpath,
        query_params=dict(request.query_params),
        body=body,
        headers=dict(request.headers),
    )
