"""Native FastAPI personality endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.services.personalities import PersonalitiesService

router = APIRouter(tags=["personalities"])
_service = PersonalitiesService()


class PersonalitySetRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str
    name: str = ""


@router.get("/personalities")
def list_personalities() -> dict[str, Any]:
    return _service.list_personalities()


@router.post("/personality/set")
def set_personality(body: PersonalitySetRequest) -> JSONResponse:
    payload, status_code = _service.set_personality(
        session_id=body.session_id,
        name=body.name,
    )
    return JSONResponse(content=payload, status_code=status_code)
