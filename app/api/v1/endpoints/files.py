"""Native FastAPI file endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.services.files import FileService

router = APIRouter(tags=["files"])
_service = FileService()


async def _parse_json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


@router.get("/file")
def read_file(request: Request) -> Response:
    return _service.read_file(
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )


@router.get("/file/raw")
def read_file_raw(request: Request) -> Response:
    return _service.read_file_raw(
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )


@router.get("/file/view")
def view_file(request: Request) -> Response:
    return _service.view_file(
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )


@router.get("/folder/download")
def folder_download(request: Request) -> Response:
    return _service.folder_download(
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )


@router.get("/media")
def media(request: Request) -> Response:
    return _service.media(
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )




@router.post("/file/read")
async def read_file_post(request: Request) -> Response:
    """Legacy alias: POST body {path, session_id?} -> GET /api/file semantics."""
    body = await _parse_json_body(request)
    query_params = {}
    for key in ("path", "session_id"):
        if key in body and body[key] is not None:
            query_params[key] = str(body[key])
    return _service.read_file(
        query_params=query_params,
        headers=dict(request.headers),
    )

@router.post("/file/save")
async def save_file(request: Request) -> Response:
    return _service.save_file(
        body=await _parse_json_body(request),
        headers=dict(request.headers),
    )


@router.post("/file/delete")
async def delete_file(request: Request) -> Response:
    return _service.delete_file(
        body=await _parse_json_body(request),
        headers=dict(request.headers),
    )


@router.post("/file/create")
async def create_file(request: Request) -> Response:
    return _service.create_file(
        body=await _parse_json_body(request),
        headers=dict(request.headers),
    )


@router.post("/file/rename")
async def rename_file(request: Request) -> Response:
    return _service.rename_file(
        body=await _parse_json_body(request),
        headers=dict(request.headers),
    )


@router.post("/file/move")
async def move_file(request: Request) -> Response:
    return _service.move_file(
        body=await _parse_json_body(request),
        headers=dict(request.headers),
    )


@router.post("/file/create-dir")
async def create_dir(request: Request) -> Response:
    return _service.create_dir(
        body=await _parse_json_body(request),
        headers=dict(request.headers),
    )


@router.post("/file/reveal")
async def reveal_file(request: Request) -> Response:
    return _service.reveal_file(
        body=await _parse_json_body(request),
        headers=dict(request.headers),
    )


@router.post("/file/path")
async def file_path(request: Request) -> Response:
    return _service.file_path(
        body=await _parse_json_body(request),
        headers=dict(request.headers),
    )


@router.post("/file/open-vscode")
async def open_vscode(request: Request) -> Response:
    return _service.open_vscode(
        body=await _parse_json_body(request),
        headers=dict(request.headers),
    )
