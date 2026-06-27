"""Stateless document pipeline test API — /api/v1/test/*."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.document_api.core.config import get_settings
from app.document_api.services import pipeline_test as svc

router = APIRouter(prefix="/test", tags=["pipeline-test"])


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    dimensions: int
    count: int
    persisted: bool = False


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(min_length=1)
    top_n: int | None = None


class RerankResultRow(BaseModel):
    index: int
    score: float
    document: str


class RerankResponse(BaseModel):
    query: str
    results: list[RerankResultRow]
    persisted: bool = False


class OrganizeRequest(BaseModel):
    text: str
    model: str | None = None


class OrganizeResponse(BaseModel):
    text: str
    model: str
    persisted: bool = False
    error: str | None = None


class ConvertResponse(BaseModel):
    markdown: str
    source_filename: str
    metadata: dict
    image_count: int
    persisted: bool = False


class PipelineRequest(BaseModel):
    text: str | None = None
    query: str | None = None
    documents: list[str] | None = None
    run_organize: bool = True
    run_embed: bool = False
    run_rerank: bool = False


@router.post("/convert", response_model=ConvertResponse)
async def convert_file(file: Annotated[UploadFile, File(...)]) -> ConvertResponse:
    if not (file.filename or "").strip():
        raise HTTPException(status_code=400, detail="file is required")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        result = svc.convert_uploaded_bytes(filename=file.filename or "upload.bin", content=content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ConvertResponse(**result)


@router.post("/embed", response_model=EmbedResponse)
async def embed(body: EmbedRequest) -> EmbedResponse:
    try:
        result = svc.embed_texts(texts=body.texts, settings=get_settings())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EmbedResponse(**result)


@router.post("/rerank", response_model=RerankResponse)
async def rerank(body: RerankRequest) -> RerankResponse:
    try:
        result = svc.rerank_texts(
            query=body.query,
            documents=body.documents,
            top_n=body.top_n,
            settings=get_settings(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RerankResponse(**result)


@router.post("/organize", response_model=OrganizeResponse)
async def organize(body: OrganizeRequest) -> OrganizeResponse:
    try:
        result = svc.organize_text(
            text=body.text,
            settings=get_settings(),
            model=body.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return OrganizeResponse(**result)


@router.post("/pipeline")
async def pipeline(body: PipelineRequest) -> dict:
    try:
        return svc.run_test_pipeline(
            text=body.text,
            query=body.query,
            rerank_documents=body.documents,
            run_organize=body.run_organize,
            run_embed=body.run_embed,
            run_rerank=body.run_rerank,
            settings=get_settings(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
