"""Native FastAPI background/goal/btw endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.services.agent_actions import AgentActionsService

router = APIRouter(tags=["agent"])
_service = AgentActionsService()


@router.get("/background/status")
def background_status(
    session_id: str = Query(default=""),
) -> JSONResponse:
    payload, status_code = _service.background_status(session_id)
    return JSONResponse(content=payload, status_code=status_code)


async def _parse_json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


@router.post("/background")
async def background_run(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.run_background(body, headers=dict(request.headers))


@router.post("/goal")
async def goal_run(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.run_goal(body, headers=dict(request.headers))


@router.post("/btw")
async def btw_run(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.run_btw(body, headers=dict(request.headers))
