"""Native FastAPI system/admin probe endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import InsightsReaderDep, LogsReaderDep, SettingsSystemDep
from app.schemas.users import BootstrapAdminRequest, BootstrapAdminResponse
from app.services.system import SystemService
from app.services.users import UsersService

router = APIRouter(tags=["system"])
_service = SystemService()
_users_service = UsersService()


@router.post("/shutdown")
def shutdown(_operator: SettingsSystemDep) -> dict[str, str]:
    return _service.shutdown()


@router.post("/admin/reload")
def admin_reload(_operator: SettingsSystemDep) -> dict[str, str]:
    return _service.admin_reload()


@router.post("/transcribe")
async def transcribe(request: Request) -> Response:
    body = await request.body()
    return _service.transcribe(headers=dict(request.headers), body=body)


@router.get("/plugins")
def list_plugins() -> dict[str, Any]:
    return _service.get_plugins()


@router.get("/gateway/status")
def gateway_status() -> dict[str, Any]:
    return _service.get_gateway_status()


@router.get("/wiki/status")
def wiki_status() -> dict[str, Any]:
    return _service.get_wiki_status()


@router.get("/insights")
def insights(
    request: Request,
    _reader: InsightsReaderDep,
    days: int = Query(default=30, ge=1, le=365),
    profile: str | None = Query(default=None),
    username: str | None = Query(default=None),
) -> dict[str, Any]:
    return _service.get_insights(
        days=days,
        profile=profile,
        username=username,
        headers=dict(request.headers),
    )


@router.get("/logs")
def logs(
    request: Request,
    _reader: LogsReaderDep,
    file: str | None = Query(default="agent"),
    tail: str | None = Query(default=None),
    profile: str | None = Query(default=None),
    username: str | None = Query(default=None),
) -> JSONResponse:
    payload, status_code = _service.get_logs(
        file_key=file,
        tail=tail,
        profile=profile,
        username=username,
        headers=dict(request.headers),
    )
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)


@router.post("/client-events/log")
async def client_events_log(request: Request) -> JSONResponse:
    body = await request.body()
    client = request.client
    payload, status_code = _service.log_client_event(
        body=body,
        headers=dict(request.headers),
        client_host=client.host if client else "unknown",
        client_port=client.port if client else 0,
    )
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)


@router.get("/system/health")
def system_health() -> dict[str, Any]:
    return _service.get_system_health()


@router.get("/health/agent")
def health_agent() -> dict[str, Any]:
    return _service.get_agent_health()


@router.post("/system/bootstrap-admin", response_model=BootstrapAdminResponse)
def bootstrap_admin(body: BootstrapAdminRequest) -> JSONResponse:
    """Promote a legacy install to multi-user by creating the first admin user."""
    payload, status_code = _users_service.promote_install(
        admin_email=body.admin_email,
        admin_password=body.admin_password,
        current_password=body.current_password,
    )
    return JSONResponse(
        content=BootstrapAdminResponse(**payload).model_dump(exclude_none=True),
        status_code=status_code,
    )
