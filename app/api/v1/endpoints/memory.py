"""Native FastAPI memory endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.core.security import (
    AgentSoulAccessError,
    ensure_agent_soul_access,
    filter_memory_payload_for_user,
    get_current_user,
)
from app.services.memory import MemoryService

router = APIRouter(tags=["memory"])
_service = MemoryService()


class MemoryWriteRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    section: str | None = None
    content: str | None = None


@router.get("/memory")
def read_memory(request: Request) -> dict[str, Any]:
    user = get_current_user(request)
    payload = _service.read_memory()
    return filter_memory_payload_for_user(payload, user)


@router.post("/memory/write")
def write_memory(body: MemoryWriteRequest, request: Request) -> JSONResponse:
    user = get_current_user(request)
    if body.section == "soul":
        try:
            ensure_agent_soul_access(user)
        except AgentSoulAccessError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    payload, status_code = _service.write_memory(
        section=body.section,
        content=body.content,
    )
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)
