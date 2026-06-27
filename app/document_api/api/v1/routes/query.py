from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.document_api.api.v1.param_deps import get_documents_list_query, get_query_request
from app.document_api.api.v1.schemas import (
    DocumentListItem,
    DocumentListResponse,
    DocumentsListQuery,
    QueryRequest,
    QueryResponse,
    QueryResultRow,
)
from app.document_api.core.config import default_mcp_km_number_of_results, get_settings
from app.document_api.services.document_catalog import build_source_file_url, list_documents as list_catalog_documents
from app.document_api.services.document_pipeline import PgConfig, SupabaseConfig, query_documents
from app.document_api.services.embeddings import build_embeddings, build_reranker
from app.document_api.services.folder_catalog import ensure_folder_table, list_files_by_folder, list_folder_files

router = APIRouter()
settings = get_settings()


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    operation_id="search_documents_list",
    tags=["search"],
)
async def list_documents_with_summaries(
    params: Annotated[DocumentsListQuery, Depends(get_documents_list_query)],
):
    """รายการเอกสารพร้อม LLM summary (แถวละไฟล์) — tag เดียวกับ POST /search"""
    docs = params.docs
    try:
        ensure_folder_table()
        chunk_rows = {r["source_filename"]: r for r in list_catalog_documents()}
        filtered_docs = {name.strip() for name in (docs or []) if name and name.strip()}
        items: list[DocumentListItem] = []
        from app.document_api.rag_department_scope import list_committed_folder_files

        for row in list_committed_folder_files():
            folder_name = str(row.get("folder_name") or "")
            if filtered_docs and folder_name not in filtered_docs:
                continue
            file_name = str(row.get("file_name") or "")
            chunk = chunk_rows.get(file_name) or {}
            items.append(
                DocumentListItem(
                    document_name=folder_name,
                    source_filename=file_name,
                    llm_summary=str(row.get("llm_summary") or ""),
                    source_file_url=build_source_file_url(folder_name, file_name),
                    chunk_count=int(chunk.get("chunk_count") or 0),
                    created_by=row.get("created_by"),
                    approved_by=row.get("approved_by"),
                    approved_at=row.get("approved_at"),
                )
            )
        return DocumentListResponse(total=len(items), items=items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot list documents: {e}") from e


@router.post("", response_model=QueryResponse, operation_id="search_documents")
async def query(
    params: Annotated[QueryRequest, Depends(get_query_request)],
):
    query_text = params.query_text
    query_mode = params.query_mode
    number_of_results = default_mcp_km_number_of_results()
    docs = params.docs
    rrf_k = params.rrf_k
    try:
        embeddings = build_embeddings(settings)
        reranker = build_reranker(settings) if params.use_reranker else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pg = PgConfig(
        host=settings.pg_host,
        port=settings.pg_port,
        database=settings.pg_database,
        user=settings.pg_user,
        password=settings.pg_password,
        sslmode=settings.pg_sslmode,
    )
    sb = SupabaseConfig(
        url=settings.supabase_url,
        service_key=settings.supabase_service_key,
        storage_bucket=settings.supabase_storage_bucket,
        transcript_bucket=settings.supabase_transcript_bucket,
        table_name=settings.supabase_table_name,
        query_name=settings.supabase_query_name,
    )

    filter_filenames: list[str] = []
    if docs:
        for document_name in docs:
            for file_name in list_files_by_folder(document_name.strip()):
                filter_filenames.append(file_name)
        filter_filenames = list(dict.fromkeys(filter_filenames))

    rows = query_documents(
        query_text=query_text,
        mode=query_mode,
        pg=pg,
        sb=sb,
        number_of_results=number_of_results,
        rrf_k=rrf_k,
        filter_docs=filter_filenames,
        embeddings=embeddings,
        reranker=reranker,
        rerank_candidates=settings.reranker_candidates,
    )

    parts = []
    for i, row in enumerate(rows, 1):
        score_field = (
            "rerank_score"
            if row.get("rerank_score") is not None
            else "hybrid_score"
            if "hybrid_score" in row
            else "similarity"
            if "similarity" in row
            else "rank"
        )
        score_val = float(row.get(score_field, 0.0) or 0.0)
        parts.append(
            f"[{i}] {row.get('source_filename', '')} "
            f"(chunk {row.get('chunk_index', '?')}, score={score_val:.4f})\n{row.get('content', '')}"
        )

    return QueryResponse(
        query=query_text,
        mode=query_mode,
        total=len(rows),
        results=[QueryResultRow.model_validate(row) for row in rows],
        results_text="\n\n---\n\n".join(parts),
    )

