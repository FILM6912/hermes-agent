"""Native FastAPI update endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.services.updates import UpdatesService

router = APIRouter(tags=["updates"])
_service = UpdatesService()


class UpdatesSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    updates: dict[str, Any] | None = None
    target: str | None = None


class UpdatesTargetRequest(BaseModel):
    target: str | None = None


@router.get("/updates/check")
def updates_check(
    request: Request,
    force: str | None = Query(default=None),
    simulate: str | None = Query(default=None),
) -> dict[str, Any]:
    force_flag = (force or "").strip() == "1"
    simulate_flag = (simulate or "").strip() == "1"
    client = request.client
    client_host = client.host if client else "127.0.0.1"
    return _service.check_for_updates(
        force=force_flag,
        simulate=simulate_flag,
        client_host=client_host,
    )


@router.post("/updates/summary")
def updates_summary(body: UpdatesSummaryRequest) -> dict[str, Any]:
    updates = body.updates if isinstance(body.updates, dict) else {}
    return _service.summarize_updates(updates, target=body.target)


@router.post("/updates/apply")
def updates_apply(body: UpdatesTargetRequest) -> JSONResponse:
    payload, status_code = _service.apply_update(body.target or "")
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)


@router.post("/updates/force")
def updates_force(body: UpdatesTargetRequest) -> JSONResponse:
    payload, status_code = _service.apply_force_update(body.target or "")
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)
