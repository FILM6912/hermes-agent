"""Native FastAPI slash-command endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.services.commands import CommandsService

router = APIRouter(tags=["commands"])
_service = CommandsService()


class CommandExecRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    command: str = ""


@router.get("/commands")
def list_commands() -> dict[str, Any]:
    return _service.list_commands()


@router.post("/commands/exec")
def exec_command(body: CommandExecRequest) -> JSONResponse:
    payload, status_code = _service.exec_command(body.command)
    return JSONResponse(content=payload, status_code=status_code)
