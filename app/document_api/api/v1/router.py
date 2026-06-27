from __future__ import annotations

from fastapi import APIRouter

from app.document_api.api.v1.routes import documents_dynamic, ingest, ingest_pending, jobs, query, transcript_audio

api_router = APIRouter()

# /jobs และ /ingest-pending ต้องอยู่ก่อน documents_dynamic
api_router.include_router(jobs.ws_router)
api_router.include_router(ingest_pending.ws_router)
api_router.include_router(jobs.http_router)
api_router.include_router(ingest.router, prefix="/documents", tags=["documents"])
api_router.include_router(query.router, prefix="/search", tags=["search"])
api_router.include_router(transcript_audio.router, prefix="/transcript-report", tags=["transcript-report"])
api_router.include_router(documents_dynamic.router)
