"""FastAPI Depends helpers — รวม query params เป็น Pydantic models สำหรับ docs."""

from __future__ import annotations

from typing import Literal

from fastapi import Query

from app.document_api.api.v1.schemas import (
    DocumentsListQuery,
    JobErrorsListQuery,
    JobListQuery,
    QueryRequest,
)
def get_query_request(
    query_text: str = Query(..., description="ข้อความที่ต้องการค้นหา"),
    query_mode: Literal["hybrid", "semantic", "keyword"] = Query(default="hybrid"),
    docs: list[str] = Query(default=[], description="document_name list"),
    rrf_k: int = Query(default=60, ge=1),
    use_reranker: bool = Query(
        default=True,
        description="ใช้ Qwen3-VL-Reranker จัดอันดับผลลัพธ์ (hybrid/semantic)",
    ),
) -> QueryRequest:
    return QueryRequest(
        query_text=query_text,
        query_mode=query_mode,
        docs=docs,
        rrf_k=rrf_k,
        use_reranker=use_reranker,
    )


def get_documents_list_query(
    docs: list[str] | None = Query(
        default=None,
        description="document_name list (ไม่ส่งค่า = เลือกทั้งหมด)",
        examples=[["invoice", "report"]],
    ),
) -> DocumentsListQuery:
    return DocumentsListQuery(docs=docs)


def get_job_list_query(
    only_pending: bool = Query(
        default=False,
        description="If true, only queued/running jobs (excludes ingest-pending rows)",
    ),
    include_completed: bool = Query(
        default=False,
        description="If true, include completed jobs in the list (newest first). Default false — finished jobs drop off the dashboard.",
    ),
    include_failed: bool = Query(
        default=False,
        description="If true, include status=failed in the list; default false so failed jobs only appear under GET /jobs/errors",
    ),
    limit: int = Query(default=100, ge=1, le=500, description="Maximum number of jobs to return"),
) -> JobListQuery:
    return JobListQuery(
        only_pending=only_pending,
        include_completed=include_completed,
        include_failed=include_failed,
        limit=limit,
    )


def get_job_errors_list_query(
    limit: int = Query(default=100, ge=1, le=500, description="Max jobs to return (newest first)"),
    kind: str | None = Query(
        default=None,
        description="If set, only this job kind (e.g. transcript_audio, document_ingest)",
    ),
) -> JobErrorsListQuery:
    return JobErrorsListQuery(limit=limit, kind=kind)
