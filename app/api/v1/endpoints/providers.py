"""Native FastAPI provider endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.services.providers import ProviderService

router = APIRouter(tags=["providers"])
_service = ProviderService()


class ProviderKeyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str | None = None
    api_key: str | None = None


class ProviderDeleteRequest(BaseModel):
    provider: str | None = None


@router.get("/providers")
def list_providers() -> dict[str, Any]:
    return _service.list_providers()


@router.get("/provider/quota")
def provider_quota(
    provider: str | None = Query(default=None),
    refresh: str | None = Query(default=None),
) -> dict[str, Any]:
    refresh_flag = (refresh or "").strip().lower() in {"1", "true", "yes", "on"}
    provider_id = (provider or "").strip() or None
    return _service.get_provider_quota(provider_id, refresh=refresh_flag)


@router.get("/provider/cost-history")
def provider_cost_history(
    provider: str | None = Query(default=None),
    days: str | None = Query(default="7"),
) -> dict[str, Any]:
    provider_id = (provider or "").strip() or None
    return _service.get_cost_history(provider_id, days=days)


@router.post("/providers")
def set_provider_key(body: ProviderKeyRequest) -> JSONResponse:
    """Set or clear a provider API key."""
    payload, status_code = _service.set_provider_key(body.provider, body.api_key)
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)


@router.post("/providers/delete")
def delete_provider_key(body: ProviderDeleteRequest) -> JSONResponse:
    """Remove a provider API key."""
    payload, status_code = _service.remove_provider_key(body.provider)
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)
