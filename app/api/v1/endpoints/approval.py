"""Native FastAPI approval/clarify endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response

from app.services.approval import ApprovalService
from app.services.sse_streams import (
    build_approval_stream_response,
    build_clarify_stream_response,
)

router = APIRouter(tags=["approval"])
_service = ApprovalService()


class ApprovalRespondRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str = ""
    choice: str = "deny"
    approval_id: str = ""


class ClarifyRespondRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str = ""
    response: str | None = None
    answer: str | None = None
    choice: str | None = None
    clarify_id: str = ""


@router.get("/approval/pending")
def approval_pending(session_id: str = Query(default="")) -> dict:
    return _service.get_pending(session_id)


@router.get("/approval/stream", include_in_schema=False)
async def approval_stream(request: Request) -> Response:
    """SSE stream for approval notifications."""
    session_id = request.query_params.get("session_id", "")
    return build_approval_stream_response(session_id=session_id, request=request)


@router.get("/approval/inject_test", include_in_schema=False)
def approval_inject_test(
    request: Request,
    session_id: str = Query(default=""),
    pattern_key: str = Query(default="test_pattern"),
    command: str = Query(default="rm -rf /tmp/test"),
) -> JSONResponse:
    client_host = request.client.host if request.client else ""
    if client_host != "127.0.0.1":
        return JSONResponse(content={"error": "not found"}, status_code=404)
    payload, status = _service.inject_test(
        session_id=session_id,
        pattern_key=pattern_key,
        command=command,
    )
    return JSONResponse(content=payload, status_code=status)


@router.post("/approval/respond")
def approval_respond(body: ApprovalRespondRequest) -> JSONResponse:
    payload, status = _service.respond(
        session_id=body.session_id,
        choice=body.choice,
        approval_id=body.approval_id,
    )
    return JSONResponse(content=payload, status_code=status)


@router.get("/clarify/pending")
def clarify_pending(session_id: str = Query(default="")) -> dict:
    return _service.get_clarify_pending(session_id)


@router.get("/clarify/stream", include_in_schema=False)
async def clarify_stream(request: Request) -> Response:
    """SSE stream for clarify notifications."""
    session_id = request.query_params.get("session_id", "")
    return build_clarify_stream_response(session_id=session_id, request=request)


@router.get("/clarify/inject_test", include_in_schema=False)
def clarify_inject_test(
    request: Request,
    session_id: str = Query(default=""),
    question: str = Query(default="Which option?"),
    choices: list[str] = Query(default=[]),
) -> JSONResponse:
    client_host = request.client.host if request.client else ""
    if client_host != "127.0.0.1":
        return JSONResponse(content={"error": "not found"}, status_code=404)
    payload, status = _service.inject_clarify_test(
        session_id=session_id,
        question=question,
        choices=choices,
    )
    return JSONResponse(content=payload, status_code=status)


@router.post("/clarify/respond")
def clarify_respond(body: ClarifyRespondRequest) -> JSONResponse:
    payload, status = _service.clarify_respond(
        session_id=body.session_id,
        response=body.response,
        answer=body.answer,
        choice=body.choice,
        clarify_id=body.clarify_id,
    )
    return JSONResponse(content=payload, status_code=status)
