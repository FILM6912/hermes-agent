from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.document_api.api.v1.param_deps import get_documents_list_query
from app.document_api.api.v1.schemas import (
    DocumentFileEntry,
    DocumentSetEntry,
    DocumentsListQuery,
    IngestResponse,
)
from app.document_api.core.config import get_settings
from app.document_api.services.document_catalog import build_source_file_url
from app.document_api.services.document_pipeline import (
    PgConfig,
    SupabaseConfig,
    convert_file_to_markdown,
    ingest_to_supabase,
)
from app.document_api.services.embeddings import build_embeddings
from app.document_api.services.folder_catalog import (
    ensure_folder_table,
    insert_folder_files,
    list_folder_files,
    update_folder_file_summary,
)
from app.document_api.services.document_summary import generate_document_summary_llm

router = APIRouter()
settings = get_settings()


def _generate_and_persist_document_summary(
    *,
    markdown: str,
    document_name: str,
    source_filename: str,
    pending_id: str | None,
    progress_callback: Callable[[str, int, str | None], None] | None,
    file_index: int,
    total_files: int,
) -> tuple[str, str | None]:
    """Generate LLM summary; persist to pending row or return for document_folder insert."""
    from app.document_api.services.document_pipeline import make_summary_stream_emitter
    from app.document_api.services.pending_ingest_catalog import (
        mark_pending_summary_ready,
        update_pending_llm_summary,
    )

    stream_emit = None
    if progress_callback is not None:
        stream_emit = make_summary_stream_emitter(
            progress_callback,
            file_index=file_index,
            total_files=total_files,
        )
        progress_callback("summary", 1, "starting summary")

    summary, err = generate_document_summary_llm(
        markdown_text=markdown,
        document_name=document_name,
        source_filename=source_filename,
        stream_callback=stream_emit,
    )
    if progress_callback is not None:
        from app.document_api.services.document_pipeline import format_summary_progress_label

        progress_callback(
            "summary",
            100 if summary else 0,
            format_summary_progress_label(
                file_index=file_index,
                total_files=total_files,
                llm_text=summary,
            ),
        )

    pid = (pending_id or "").strip()
    if pid:
        if summary:
            update_pending_llm_summary(pid, summary)
        mark_pending_summary_ready(pid)
    return summary, err


def _document_id(document_name: str) -> str:
    digest = hashlib.md5(document_name.encode("utf-8")).hexdigest()[:12]
    return f"doc_{digest}"


async def ingest_document(
    file: UploadFile | None = File(default=None),
    folder_name: str | None = Form(default="default"),
    enable_supabase: bool = Form(default=True),
    on_duplicate: str = Form(default="replace"),
    include_metadata: bool = Form(default=True),
    chunk_size: int = Form(default=settings.chunk_size),
):
    actor_username, department_id = _resolve_ingest_actor()
    if file is None or not (file.filename or "").strip():
        raise HTTPException(status_code=400, detail="No file uploaded — attach a file in the 'file' field")
    source_file_bytes = await file.read()
    return ingest_document_bytes(
        source_filename=file.filename or "upload.bin",
        source_file_bytes=source_file_bytes,
        folder_name=folder_name,
        enable_supabase=enable_supabase,
        on_duplicate=on_duplicate,
        include_metadata=include_metadata,
        chunk_size=chunk_size,
        actor_username=actor_username,
        department_id=department_id,
    )


def _resolve_ingest_actor() -> tuple[str | None, str | None]:
    from app.document_api.rag_department_scope import resolve_rag_actor_context

    return resolve_rag_actor_context()


def ingest_document_bytes(
    *,
    source_filename: str,
    source_file_bytes: bytes,
    folder_name: str | None = "default",
    enable_supabase: bool = True,
    on_duplicate: str = "replace",
    include_metadata: bool = True,
    chunk_size: int = settings.chunk_size,
    progress_callback: Callable[[str, int, str | None], None] | None = None,
    rearrange_stream_callback: Callable[[str, str], None] | None = None,
    actor_username: str | None = None,
    department_id: str | None = None,
    defer_vector_commit: bool | None = None,
    job_id: str | None = None,
    file_index: int = 1,
    total_files: int = 1,
) -> IngestResponse:
    from app.domain.roles import role_has_full_access
    from app.domain.users import is_multi_user_enabled
    from app.domain.workspace import get_request_user_access

    if actor_username is None or department_id is None:
        resolved_actor, resolved_dept = _resolve_ingest_actor()
        actor_username = actor_username or resolved_actor
        department_id = department_id if department_id is not None else resolved_dept
    if is_multi_user_enabled():
        access = get_request_user_access()
        if access.multi_user_enabled and not role_has_full_access(access.role) and not department_id:
            raise HTTPException(
                status_code=400,
                detail="User must belong to a department before uploading RAG documents",
            )

    tmp_dir = Path(tempfile.mkdtemp(prefix="document_api_upload_"))
    try:
        embeddings = build_embeddings(settings)
        out_path = tmp_dir / Path(source_filename).name
        out_path.write_bytes(source_file_bytes)

        if progress_callback:
            progress_callback("convert", 0, "starting convert")
        conv = convert_file_to_markdown(out_path)
        if progress_callback:
            progress_callback("convert", 100, "convert completed")

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

        defer = settings.ingest_defer_vector_until_admin if defer_vector_commit is None else defer_vector_commit
        defer = bool(defer) and bool(enable_supabase) and bool((job_id or "").strip())

        upload = ingest_to_supabase(
            conv=conv,
            enable_supabase=enable_supabase,
            pg=pg,
            sb=sb,
            on_duplicate=on_duplicate,
            chunk_size=chunk_size,
            chunk_overlap=settings.chunk_overlap,
            split_text=settings.split_text,
            document_name=folder_name,
            source_file_bytes=source_file_bytes,
            embeddings=embeddings,
            progress_callback=progress_callback,
            rearrange_stream_callback=rearrange_stream_callback,
            actor_username=actor_username,
            department_id=department_id,
            defer_vector_commit=defer,
            job_id=job_id,
        )
        llm_summary_text: str | None = None
        llm_summary_error: str | None = None
        folder_name_clean = (folder_name or "default").strip() or "default"
        pending_id = upload.get("pending_ingest_id")
        if upload.get("status") == "pending_approval" and pending_id:
            llm_summary_text, llm_summary_error = _generate_and_persist_document_summary(
                markdown=conv.markdown or "",
                document_name=folder_name_clean,
                source_filename=conv.source_filename,
                pending_id=str(pending_id),
                progress_callback=progress_callback,
                file_index=file_index,
                total_files=total_files,
            )
        elif upload.get("status") != "pending_approval" and enable_supabase:
            llm_summary_text, llm_summary_error = _generate_and_persist_document_summary(
                markdown=conv.markdown or "",
                document_name=folder_name_clean,
                source_filename=conv.source_filename,
                pending_id=None,
                progress_callback=progress_callback,
                file_index=file_index,
                total_files=total_files,
            )
        expected_images = int(upload.get("images_expected") or 0)
        uploaded_images_count = int(upload.get("images_uploaded") or 0)
        if expected_images > 0 and uploaded_images_count < expected_images:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "image upload incomplete",
                    "upload": upload,
                },
            )
        st = upload.get("status")
        if st != "pending_approval" and (
            st in {"partial"} or (upload.get("errors") or [])
        ):
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "ingest to database failed",
                    "upload": upload,
                },
            )

        folder_saved = False
        if upload.get("status") != "pending_approval":
            ensure_folder_table()
            summary_map = (
                {(folder_name_clean, conv.source_filename): llm_summary_text}
                if llm_summary_text
                else None
            )
            inserted = insert_folder_files(
                [(folder_name_clean, conv.source_filename)],
                actor_username=actor_username,
                uploaded_by=actor_username,
                record_approval=True,
                llm_summaries=summary_map,
                department_id=department_id,
            )
            folder_saved = inserted > 0
            if llm_summary_text and not folder_saved:
                update_folder_file_summary(
                    folder_name_clean,
                    conv.source_filename,
                    llm_summary_text,
                    actor_username=actor_username,
                )

        images: list[dict] = []
        markdown_for_response = ""
        upload_summary = {
            "status": upload.get("status"),
            "source_filename": upload.get("source_filename"),
            "chunks_uploaded": upload.get("chunks_uploaded", 0),
            "images_uploaded": upload.get("images_uploaded", 0),
            "embedding_used": upload.get("embedding_used", False),
            "vector_dim": upload.get("vector_dim"),
            "table_name": upload.get("table_name"),
            "query_name": upload.get("query_name"),
            "bucket_url": upload.get("bucket_url"),
            "source_file_url": upload.get("source_file_url"),
            "source_file_storage_path": upload.get("source_file_storage_path"),
            "folder_name": folder_name_clean or None,
            "folder_saved": folder_saved,
            "errors": (upload.get("errors") or [])[:5],
            "errors_total": len(upload.get("errors") or []),
            "toc_errors": (upload.get("toc_errors") or [])[:5],
            "toc_errors_total": len(upload.get("toc_errors") or []),
            "rearrange_notes": (upload.get("rearrange_notes") or [])[:5],
            "rearrange_notes_total": len(upload.get("rearrange_notes") or []),
            "rearrange_llm_raw": upload.get("rearrange_llm_raw") or "",
            "rearrange_llm_raw_chars": int(upload.get("rearrange_llm_raw_chars") or 0),
            "pending_ingest_id": upload.get("pending_ingest_id"),
            "llm_summary": llm_summary_text or upload.get("llm_summary") or "",
            "llm_summary_error": llm_summary_error,
        }
        metadata = {}
        if include_metadata:
            metadata = {
                "source_filename": conv.source_filename,
                "image_count": len(conv.images),
                "markdown_length": len(conv.markdown),
                "converter_metadata": conv.metadata,
                "response_mode": "summary_only",
            }

        return IngestResponse(
            source_filename=conv.source_filename,
            markdown=markdown_for_response,
            images=images,
            metadata=metadata,
            upload=upload_summary,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.get("", response_model=list[DocumentSetEntry])
async def get_documents(
    params: Annotated[DocumentsListQuery, Depends(get_documents_list_query)],
):
    docs = params.docs
    try:
        from app.document_api.rag_department_scope import list_committed_folder_files

        ensure_folder_table()
        rows = list_committed_folder_files()
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            folder_name = row["folder_name"]
            grouped.setdefault(folder_name, []).append(
                {
                    "id": int(row["id"]),
                    "file_name": row["file_name"],
                    "created_by": row.get("created_by"),
                    "updated_by": row.get("updated_by"),
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                    "approved_by": row.get("approved_by"),
                    "approved_at": row.get("approved_at"),
                    "source_file_url": build_source_file_url(folder_name, row["file_name"]),
                    "llm_summary": row.get("llm_summary") or "",
                }
            )
        filtered_docs = {name.strip() for name in (docs or []) if name and name.strip()}
        return [
            DocumentSetEntry(
                id=_document_id(document_name),
                document_name=document_name,
                files=[DocumentFileEntry(**f) for f in files],
            )
            for document_name, files in grouped.items()
            if not filtered_docs or document_name in filtered_docs
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot list documents: {e}")


