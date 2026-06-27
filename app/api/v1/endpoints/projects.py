"""Native FastAPI project endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.services.projects import ProjectService

router = APIRouter(tags=["projects"])
_service = ProjectService()


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    color: str | None = None


class ProjectRenameRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_id: str | None = None
    name: str | None = None
    color: str | None = None


class ProjectDeleteRequest(BaseModel):
    project_id: str | None = None


@router.get("/projects")
def list_projects(all_profiles: str | None = Query(default=None)) -> dict[str, Any]:
    return _service.list_projects(all_profiles_raw=all_profiles)


@router.post("/projects/create")
def create_project(body: ProjectCreateRequest) -> JSONResponse:
    payload, status_code = _service.create_project(name=body.name, color=body.color)
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)


@router.post("/projects/rename")
def rename_project(body: ProjectRenameRequest) -> JSONResponse:
    payload, status_code = _service.rename_project(
        project_id=body.project_id,
        name=body.name,
        color=body.color,
    )
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)


@router.post("/projects/delete")
def delete_project(body: ProjectDeleteRequest) -> JSONResponse:
    payload, status_code = _service.delete_project(project_id=body.project_id)
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)
