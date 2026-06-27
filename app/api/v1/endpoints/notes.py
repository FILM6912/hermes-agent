"""Native FastAPI notes endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.services.notes import NotesService

router = APIRouter(tags=["notes"])
_service = NotesService()


@router.get("/notes/sources")
def notes_sources(request: Request) -> Response:
    return _service.list_sources(headers=dict(request.headers))


@router.get("/notes/search")
def notes_search(request: Request) -> Response:
    return _service.search(
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )


@router.get("/notes/item")
def notes_item(request: Request) -> Response:
    return _service.get_item(
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )
