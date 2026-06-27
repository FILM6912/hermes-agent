"""Native FastAPI onboarding endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.services.onboarding import OnboardingService

router = APIRouter(tags=["onboarding"])
_service = OnboardingService()

_NO_STORE = {"Cache-Control": "no-store"}


class OnboardingSetupRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class OnboardingProbeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class OnboardingOAuthStartRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    provider: str | None = None


class OnboardingOAuthCancelRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    flow_id: str | None = None
    provider: str | None = None


def _client_network(request: Request) -> tuple[str, str, str]:
    client_host = request.client.host if request.client else ""
    return (
        client_host,
        request.headers.get("X-Forwarded-For", ""),
        request.headers.get("X-Real-IP", ""),
    )


def _json(payload: dict[str, Any], *, status_code: int = 200, extra_headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status_code, headers=dict(extra_headers or {}))


@router.get("/onboarding/status")
def onboarding_status() -> dict[str, Any]:
    return _service.get_status()


@router.get("/onboarding/oauth/poll")
def onboarding_oauth_poll(flow_id: str | None = Query(default=None)) -> JSONResponse:
    payload, status_code = _service.oauth_poll(str(flow_id or ""))
    if status_code is not None:
        return _json(payload, status_code=status_code, extra_headers=_NO_STORE)
    return _json(payload, extra_headers=_NO_STORE)


@router.post("/onboarding/oauth/start")
def onboarding_oauth_start(body: OnboardingOAuthStartRequest, request: Request) -> JSONResponse:
    client_host, xff, xri = _client_network(request)
    payload, status_code = _service.oauth_start(
        body.model_dump(exclude_unset=False),
        client_host=client_host,
        x_forwarded_for=xff,
        x_real_ip=xri,
    )
    if status_code is not None:
        return _json(payload, status_code=status_code, extra_headers=_NO_STORE)
    return _json(payload, extra_headers=_NO_STORE)


@router.post("/onboarding/oauth/cancel")
def onboarding_oauth_cancel(body: OnboardingOAuthCancelRequest) -> JSONResponse:
    payload, status_code = _service.oauth_cancel(body.model_dump(exclude_unset=False))
    if status_code is not None:
        return _json(payload, status_code=status_code, extra_headers=_NO_STORE)
    return _json(payload, extra_headers=_NO_STORE)


@router.post("/onboarding/setup")
def onboarding_setup(body: OnboardingSetupRequest, request: Request) -> JSONResponse:
    client_host, xff, xri = _client_network(request)
    payload, status_code = _service.apply_setup(
        body.model_dump(exclude_unset=False),
        client_host=client_host,
        x_forwarded_for=xff,
        x_real_ip=xri,
    )
    if status_code is not None:
        return _json(payload, status_code=status_code)
    return _json(payload)


@router.post("/onboarding/complete")
def onboarding_complete() -> dict[str, Any]:
    return _service.complete()


@router.post("/onboarding/probe")
def onboarding_probe(body: OnboardingProbeRequest, request: Request) -> JSONResponse:
    client_host, xff, xri = _client_network(request)
    payload, status_code = _service.probe(
        body.model_dump(exclude_unset=False),
        client_host=client_host,
        x_forwarded_for=xff,
        x_real_ip=xri,
    )
    if status_code is not None:
        return _json(payload, status_code=status_code)
    return _json(payload)
