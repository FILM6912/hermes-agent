"""Native FastAPI dashboard probe endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.services.dashboard import DashboardService

router = APIRouter(tags=["dashboard"])
_service = DashboardService()
logger = logging.getLogger(__name__)


class DashboardConfigSaveRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: str | None = None
    url: str | None = None


@router.get("/dashboard/status")
def dashboard_status() -> dict[str, Any]:
    return _service.get_status()


@router.get("/dashboard/config")
def dashboard_config() -> dict[str, Any]:
    return _service.get_config()


@router.post("/dashboard/config")
def save_dashboard_config(body: DashboardConfigSaveRequest) -> JSONResponse:
    try:
        payload = _service.save_config(body.model_dump(exclude_unset=True))
        return JSONResponse(content=payload)
    except ValueError as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=400)
    except Exception:
        logger.exception("dashboard config save failed")
        return JSONResponse(content={"error": "dashboard config save failed"}, status_code=500)
