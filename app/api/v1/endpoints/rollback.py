"""Native FastAPI rollback endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.domain.users import resolve_request_user_access
from app.services.rollback import RollbackService

router = APIRouter(tags=["rollback"])
_service = RollbackService()


class RollbackRestoreRequest(BaseModel):
    workspace: str | None = None
    checkpoint: str | None = None


@router.get("/rollback/list")
def rollback_list(
    request: Request,
    workspace: str | None = Query(default=None),
) -> JSONResponse:
    access = resolve_request_user_access(request)
    payload, status_code = _service.list_checkpoints(workspace, access=access)
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)


@router.get("/rollback/diff")
def rollback_diff(
    request: Request,
    workspace: str | None = Query(default=None),
    checkpoint: str | None = Query(default=None),
) -> JSONResponse:
    access = resolve_request_user_access(request)
    payload, status_code = _service.get_checkpoint_diff(
        workspace,
        checkpoint,
        access=access,
    )
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)


@router.post("/rollback/restore")
def rollback_restore(request: Request, body: RollbackRestoreRequest) -> JSONResponse:
    access = resolve_request_user_access(request)
    payload, status_code = _service.restore_checkpoint(
        workspace=body.workspace,
        checkpoint=body.checkpoint,
        access=access,
    )
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)
