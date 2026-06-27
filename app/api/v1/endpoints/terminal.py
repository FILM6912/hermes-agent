"""Native FastAPI terminal endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse, Response

from app.services.terminal import TerminalService
from app.services.terminal_stream import build_terminal_output_stream_response

router = APIRouter(tags=["terminal"])
_service = TerminalService()


class TerminalStartRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str = ""
    rows: int = 24
    cols: int = 80
    restart: bool = False


class TerminalSessionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str = ""


class TerminalInputRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str = ""
    data: str = ""


class TerminalResizeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str = ""
    rows: int = 24
    cols: int = 80


@router.get("/terminal/output", include_in_schema=False)
async def terminal_output(request: Request) -> Response:
    """SSE stream for embedded terminal output."""
    session_id = request.query_params.get("session_id", "")
    return build_terminal_output_stream_response(
        session_id=session_id,
        request=request,
    )


@router.post("/terminal/start")
def terminal_start(body: TerminalStartRequest) -> JSONResponse:
    payload, status = _service.start(
        session_id=body.session_id,
        rows=body.rows,
        cols=body.cols,
        restart=body.restart,
    )
    return JSONResponse(content=payload, status_code=status)


@router.post("/terminal/input")
def terminal_input(body: TerminalInputRequest) -> JSONResponse:
    payload, status = _service.write_input(session_id=body.session_id, data=body.data)
    return JSONResponse(content=payload, status_code=status)


@router.post("/terminal/resize")
def terminal_resize(body: TerminalResizeRequest) -> JSONResponse:
    payload, status = _service.resize(
        session_id=body.session_id,
        rows=body.rows,
        cols=body.cols,
    )
    return JSONResponse(content=payload, status_code=status)


@router.post("/terminal/close")
def terminal_close(body: TerminalSessionRequest) -> JSONResponse:
    payload, status = _service.close(session_id=body.session_id)
    return JSONResponse(content=payload, status_code=status)
