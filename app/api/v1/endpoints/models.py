"""Native FastAPI model catalog endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.services.models import ModelService

router = APIRouter(tags=["models"])
_service = ModelService()


class ModelSetRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    scope: str
    task: str | None = None
    provider: str | None = None
    model: str | None = None


class DefaultModelRequest(BaseModel):
    model: str | None = None


class ReasoningSetRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    display: str | None = None
    effort: str | None = None


@router.get("/models")
def list_models() -> dict[str, Any]:
    return _service.get_available_models()


@router.get("/models/live")
def list_live_models(
    provider: str | None = Query(default=None),
) -> JSONResponse:
    status_code, payload = _service.get_live_models(provider=provider)
    return JSONResponse(content=payload, status_code=status_code)


@router.get("/model/auxiliary")
def model_auxiliary() -> dict[str, Any]:
    return _service.get_auxiliary_models()


@router.get("/reasoning")
def reasoning_status(
    model: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    base_url: str | None = Query(default=None),
) -> dict[str, Any]:
    return _service.get_reasoning_status(
        model_id=(model or "").strip() or None,
        provider_id=(provider or "").strip() or None,
        base_url=(base_url or "").strip() or None,
    )


@router.post("/reasoning")
def reasoning_set(body: ReasoningSetRequest) -> JSONResponse:
    payload, status_code = _service.set_reasoning(
        display=body.display,
        effort=body.effort,
    )
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)


@router.post("/model/set")
def set_model(body: ModelSetRequest) -> JSONResponse:
    """Set main or auxiliary model routing."""
    patch = body.model_dump(exclude_unset=True)
    payload, status_code = _service.set_model(**patch)
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)


@router.post("/default-model")
def set_default_model(body: DefaultModelRequest) -> JSONResponse:
    payload, status_code = _service.set_default_model(body.model)
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)
