"""Native FastAPI upload endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.security import get_current_user, user_has_permission
from app.services.upload import UploadService

router = APIRouter(tags=["upload"])
_service = UploadService()


@router.post("/upload")
async def upload_file(request: Request) -> JSONResponse:
    user = get_current_user(request)
    if user is not None and not user_has_permission(user, "upload:file"):
        raise HTTPException(status_code=403, detail="Permission required: upload:file")
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    content_length = int(request.headers.get("content-length", "0") or 0)
    payload, status_code = _service.upload_multipart(
        body=body,
        content_type=content_type,
        content_length=content_length,
    )
    return JSONResponse(content=payload, status_code=status_code)


@router.post("/upload/extract")
async def upload_extract(request: Request) -> JSONResponse:
    user = get_current_user(request)
    if user is not None and not user_has_permission(user, "upload:file"):
        raise HTTPException(status_code=403, detail="Permission required: upload:file")
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    content_length = int(request.headers.get("content-length", "0") or 0)
    payload, status_code = _service.upload_extract_multipart(
        body=body,
        content_type=content_type,
        content_length=content_length,
    )
    return JSONResponse(content=payload, status_code=status_code)
