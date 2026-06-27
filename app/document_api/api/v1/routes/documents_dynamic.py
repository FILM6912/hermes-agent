from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.document_api.api.v1.routes.ingest import ingest_document_bytes
from app.document_api.api.v1.routes.job_common import (
    DOCUMENT_INGEST_STAGE_KEYS as _STAGE_KEYS,
    INGEST_STAGE_MAP,
    UPLOAD_PENDING_STAGE_MAP,
    apply_commit_pending_stage_progress,
    apply_document_ingest_stage_progress,
    empty_commit_pending_progress,
    empty_document_progress as _empty_progress,
    empty_upload_pending_progress,
    file_stage_total_for_ingest as _file_stage_total,
)
from app.document_api.api.v1.schemas import (
    ChunkContentCreateRequest,
    ChunkContentDeleteResponse,
    ChunkContentDetail,
    ChunkContentListResponse,
    ChunkContentMutationResponse,
    ChunkContentSummary,
    ChunkContentUpdateRequest,
    DocumentDetail,
    DocumentFileEntry,
    DocumentSetEntry,
    DocumentSetMutationResponse,
    CommitPendingBatchRequest,
    JobAcceptedResponse,
    PendingIngestEntry,
    PendingIngestRejectResponse,
    RenameDocumentRequest,
    RenameFileRequest,
)
from app.document_api.services.chunk_content import (
    create_chunk,
    delete_chunk,
    get_chunk_by_id,
    list_chunks_for_file,
    update_chunk,
)
from app.document_api.services.document_catalog import (
    delete_document,
    delete_documents_by_folder,
    get_document,
    rename_document_file,
    rename_document_set,
)
from app.document_api.services.document_pipeline import (
    PgConfig,
    SupabaseConfig,
    _safe_storage_name,
    commit_pending_ingest_to_supabase,
)
from app.document_api.services.embeddings import build_embeddings
from app.document_api.services.folder_catalog import file_exists_in_folder, list_file_records_by_folder
from app.document_api.services.job_manager import (
    advance_job,
    complete_job,
    create_job,
    fail_job,
    get_job,
    init_job_ingest_queue,
    is_job_cancelled,
    register_job_active_item,
    register_job_task,
    release_job_ingest_file,
    start_job,
    update_job_metadata,
)
from app.document_api.core.config import get_settings

router = APIRouter()
settings = get_settings()


def _to_file_entries(rows: list[dict]) -> list[DocumentFileEntry]:
    return [DocumentFileEntry(**row) for row in rows]



def _document_id(document_name: str) -> str:
    digest = hashlib.md5(document_name.encode("utf-8")).hexdigest()[:12]
    return f"doc_{digest}"


def _resolve_file_name(folder: str, file_name_or_storage_name: str) -> str | None:
    raw_name = file_name_or_storage_name.strip()
    if not raw_name:
        return None
    if file_exists_in_folder(folder, raw_name):
        return raw_name
    for row in list_file_records_by_folder(folder):
        file_name = str(row.get("file_name") or "")
        if _safe_storage_name(file_name) == raw_name:
            return file_name
    return None


@router.get(
    "/ingest-pending",
    response_model=list[PendingIngestEntry],
    tags=["documents"],
)
async def list_all_document_ingest_pending():
    """รายการนำเข้าที่รอ admin commit — admin เห็นทุกแผนก, สมาชิกแผนกเดียวกันเห็นร่วมกัน"""
    from app.document_api.rag_department_scope import list_scoped_pending_ingest, resolve_rag_department_scope

    scope = resolve_rag_department_scope()
    rows = list_scoped_pending_ingest(scope)
    return [PendingIngestEntry(**r) for r in rows]


def _uses_upload_pending_progress(*, enable_supabase: bool) -> bool:
    return bool(enable_supabase and get_settings().ingest_defer_vector_until_admin)


def _initial_ingest_progress(*, enable_supabase: bool) -> dict:
    if _uses_upload_pending_progress(enable_supabase=enable_supabase):
        return empty_upload_pending_progress()
    return _empty_progress()


def _ingest_progress_profile(*, enable_supabase: bool) -> str:
    return "upload_pending" if _uses_upload_pending_progress(enable_supabase=enable_supabase) else "full"


def _ingest_max_parallel_files() -> int:
    try:
        n = int(get_settings().ingest_max_parallel_files)
    except (TypeError, ValueError):
        n = 5
    return max(1, min(n, 32))


def _ingest_file_skip_reason(filename: str) -> str | None:
    base = os.path.basename(filename.replace("\\", "/"))
    if not base:
        return "empty filename"
    if base.startswith("~$"):
        return "Microsoft Office temporary lock file"
    if base in {".DS_Store", "Thumbs.db", "desktop.ini"}:
        return "system metadata file"
    return None


def _format_ingest_file_error(exc: BaseException) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            msg = detail.get("message")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
            return f"ingest failed (http {exc.status_code})"
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        return f"ingest failed (http {exc.status_code})"
    text = str(exc).strip()
    return text or "ingest failed"


def _empty_ingest_file_row(file_name: str) -> dict:
    return {
        "file": file_name,
        "chunks": 0,
        "images": 0,
        "embedding": None,
        "errors": 0,
        "toc_issues": 0,
        "rearrange_notes": 0,
        "rearrange_llm_raw_chars": 0,
        "rearrange_llm_raw_preview": "",
        "pending_ingest_id": None,
        "awaiting_admin_commit": False,
        "llm_summary": "",
    }


def _ingest_file_results_payload(
    ok_rows: list[dict],
    failed_rows: list[dict],
    skipped_rows: list[dict],
) -> dict:
    return {
        "ingest_accepted_files": [str(r.get("file") or "") for r in ok_rows if r.get("file")],
        "ingest_skipped_files": [
            {"file": str(r.get("file") or ""), "reason": str(r.get("skip_reason") or "skipped")}
            for r in skipped_rows
            if r.get("file")
        ],
        "ingest_failed_files": [
            {"file": str(r.get("file") or ""), "error": str(r.get("ingest_error") or "ingest failed")}
            for r in failed_rows
            if r.get("file")
        ],
    }


def _ingest_file_row_from_result(ingest_result) -> dict:
    from app.document_api.api.v1.schemas import upload_summary_as_dict

    u = upload_summary_as_dict(ingest_result.upload)
    _raw = u.get("rearrange_llm_raw") or ""
    _raw_s = str(_raw)
    return {
        "file": ingest_result.source_filename,
        "chunks": int(u.get("chunks_uploaded") or 0),
        "images": int(u.get("images_uploaded") or 0),
        "embedding": u.get("embedding_used"),
        "errors": int(u.get("errors_total") or 0),
        "toc_issues": int(u.get("toc_errors_total") or 0),
        "rearrange_notes": int(u.get("rearrange_notes_total") or 0),
        "rearrange_llm_raw_chars": int(u.get("rearrange_llm_raw_chars") or len(_raw_s)),
        "rearrange_llm_raw_preview": _raw_s[:800] if _raw_s else "",
        "pending_ingest_id": u.get("pending_ingest_id"),
        "awaiting_admin_commit": u.get("status") == "pending_approval",
        "llm_summary": (u.get("llm_summary") or "")[:2000],
    }


def _resolve_pending_commit_items(pending_ids: list[str]) -> list[tuple[str, str, str]]:
    """คืน (pending_id, source_filename, document_name) ไม่ซ้ำ ตามลำดับที่ส่งมา"""
    from app.document_api.rag_department_scope import assert_row_accessible, resolve_rag_department_scope
    from app.document_api.services.pending_ingest_catalog import get_pending_by_id

    scope = resolve_rag_department_scope()
    items: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for raw in pending_ids:
        pid = (raw or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        row = get_pending_by_id(pid)
        if not row:
            raise HTTPException(status_code=404, detail=f"No pending ingest found for id {pid}")
        assert_row_accessible(scope, row.get("department_id"), created_by=row.get("created_by"))
        status = str(row.get("status") or "").strip().lower()
        if status and status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Pending ingest {pid} is not commitable (status={row.get('status')})",
            )
        src = (row.get("source_filename") or "").strip() or pid[:8]
        doc = (row.get("document_name") or "unknown").strip() or "unknown"
        items.append((pid, src, doc))
    if not items:
        raise HTTPException(status_code=400, detail="pending_ids must contain at least one id")
    return items


def _resolve_commit_actor() -> str | None:
    from app.document_api.rag_department_scope import resolve_rag_actor_context

    actor_email, _department = resolve_rag_actor_context()
    return (actor_email or "").strip() or None


def _enqueue_commit_pending_job(
    *,
    items: list[tuple[str, str, str]],
    actor_email: str | None,
):
    pending_ids = [pid for pid, _, _ in items]
    file_names = [src for _, src, _ in items]
    doc_name = items[0][2]
    job = create_job(
        kind="commit_pending",
        total_items=len(items),
        metadata={
            "pending_ingest_id": pending_ids[0],
            "pending_ingest_ids": pending_ids,
            "document_name": doc_name,
            "source_filename": file_names[0] if len(file_names) == 1 else "",
            "files": file_names,
            "progress_profile": "commit_pending",
            "progress": empty_commit_pending_progress(),
            "actor_email": actor_email,
        },
    )
    task = asyncio.create_task(
        asyncio.to_thread(_run_commit_pending_batch_job, job.id, items, actor_email),
    )
    register_job_task(job.id, task)
    from app.document_api.services.pending_ingest_catalog import notify_pending_ingest_changed

    for pid, _, _ in items:
        notify_pending_ingest_changed(pid)
    return job


def _run_commit_pending_batch_job(
    job_id: str,
    items: list[tuple[str, str, str]],
    actor_email: str,
) -> None:
    if is_job_cancelled(job_id):
        return
    from app.document_api.services.document_pipeline import PgConfig, SupabaseConfig, commit_pending_ingest_to_supabase

    s = get_settings()
    embeddings = build_embeddings(s)
    pg = PgConfig(
        host=s.pg_host,
        port=s.pg_port,
        database=s.pg_database,
        user=s.pg_user,
        password=s.pg_password,
        sslmode=s.pg_sslmode,
    )
    sb = SupabaseConfig(
        url=s.supabase_url,
        service_key=s.supabase_service_key,
        storage_bucket=s.supabase_storage_bucket,
        transcript_bucket=s.supabase_transcript_bucket,
        table_name=s.supabase_table_name,
        query_name=s.supabase_query_name,
    )
    total = len(items)
    parallel_limit = _ingest_max_parallel_files()
    slots = [(pending_id, src) for pending_id, src, _ in items]
    start_job(job_id, detail=f"committing {total} file(s)…")
    init_job_ingest_queue(job_id, slots)
    update_job_metadata(
        job_id,
        {
            "ingest_parallel_limit": parallel_limit,
            "progress_profile": "commit_pending",
        },
    )
    file_rows: list[dict] = []
    rows_lock = threading.Lock()
    completed_lock = threading.Lock()
    completed_count = 0
    failed_event = threading.Event()
    last_progress: dict = empty_commit_pending_progress()

    def _commit_one(idx: int, pending_id: str, src_name: str, _doc: str) -> None:
        nonlocal completed_count, last_progress
        if failed_event.is_set() or is_job_cancelled(job_id):
            return

        register_job_active_item(
            job_id,
            pending_id,
            file_name=src_name,
            detail=f"committing {idx}/{total}: {src_name}",
        )
        try:
            progress = empty_commit_pending_progress()
            advance_job(
                job_id,
                current_item=src_name,
                detail=f"committing {idx}/{total}: {src_name}",
            )

            def _progress(
                stage: str,
                percent: int,
                detail: str | None = None,
                *,
                _idx: int = idx,
                _src: str = src_name,
                _slot: str = pending_id,
            ) -> None:
                nonlocal last_progress
                apply_commit_pending_stage_progress(
                    job_id,
                    progress,
                    stage=stage,
                    percent=percent,
                    detail=detail,
                    file_index=_idx,
                    total_files=total,
                    current_file=_src,
                    slot_id=_slot,
                )
                last_progress = dict(progress)

            out = commit_pending_ingest_to_supabase(
                pending_id=pending_id,
                pg=pg,
                sb=sb,
                embeddings=embeddings,
                progress_callback=_progress,
                actor_username=actor_email,
            )
            if out.get("status") == "error":
                failed_event.set()
                fail_job(job_id, error=str(out.get("errors") or ["unknown error"]))
                return
            expected_images = int(out.get("images_expected") or 0)
            uploaded_images = int(out.get("images_uploaded") or 0)
            if expected_images > 0 and uploaded_images < expected_images:
                failed_event.set()
                fail_job(
                    job_id,
                    error=f"image upload incomplete: {uploaded_images}/{expected_images}",
                )
                return
            errs = list(out.get("errors") or [])
            chunks = int(out.get("chunks_uploaded") or 0)
            row = {
                "file": out.get("source_filename") or src_name,
                "pending_ingest_id": pending_id,
                "chunks": chunks,
                "errors": len(errs),
            }
            if errs and chunks == 0:
                failed_event.set()
                fail_job(job_id, error="; ".join(errs[:5]))
                return
            with rows_lock:
                file_rows.append(row)
            with completed_lock:
                completed_count += 1
                done = completed_count
            advance_job(
                job_id,
                completed_items=done,
                current_item=src_name,
                detail=f"committed {done}/{total}: {src_name}",
            )
        finally:
            release_job_ingest_file(job_id, pending_id)

    try:
        with ThreadPoolExecutor(max_workers=parallel_limit) as pool:
            futures = [
                pool.submit(_commit_one, idx, pending_id, src_name, doc)
                for idx, (pending_id, src_name, doc) in enumerate(items, start=1)
            ]
            for future in as_completed(futures):
                if failed_event.is_set():
                    break
                future.result()

        if failed_event.is_set() or is_job_cancelled(job_id):
            return
        if len(file_rows) != total:
            fail_job(job_id, error="commit batch incomplete")
            return

        progress = last_progress
        img_label = progress.get("export_images")
        if not (isinstance(img_label, str) and img_label.startswith("images ")):
            from app.document_api.services.document_pipeline import format_export_images_progress_label

            img_label = format_export_images_progress_label(done=1, total=1)
        done_progress = {
            **empty_commit_pending_progress(),
            "total": 100,
            "export_images": img_label,
            "embedding": 100,
            "import_db": 100,
        }
        llm_label = progress.get("llm_chunks")
        if isinstance(llm_label, str) and llm_label.strip():
            done_progress["llm_chunks"] = llm_label
        update_job_metadata(
            job_id,
            {
                "commit_file_summaries": file_rows,
                "progress": done_progress,
            },
        )
        if total == 1:
            one = file_rows[0]
            complete_job(
                job_id,
                detail=f"committed {one['file']} ({one['chunks']} chunks)",
            )
        else:
            total_chunks = sum(int(r.get("chunks") or 0) for r in file_rows)
            complete_job(job_id, detail=f"committed {total} file(s) ({total_chunks} chunks)")
    except Exception as exc:
        fail_job(job_id, error=str(exc))


def _run_commit_pending_job(
    job_id: str,
    pending_id: str,
    actor_email: str,
) -> None:
    from app.document_api.services.pending_ingest_catalog import get_pending_by_id

    row = get_pending_by_id(pending_id)
    src = (row.get("source_filename") or "").strip() if row else pending_id[:8]
    doc = (row.get("document_name") or "unknown").strip() if row else "unknown"
    _run_commit_pending_batch_job(job_id, [(pending_id, src or pending_id[:8], doc)], actor_email)


@router.post(
    "/ingest-pending/commit-batch",
    response_model=JobAcceptedResponse,
    tags=["documents"],
)
async def commit_document_ingest_pending_batch(
    body: CommitPendingBatchRequest,
):
    """Commit หลาย pending ใน job เดียว — ใช้แทนการยิง commit ทีละ id เมื่อมีหลายไฟล์ในชุดเดียวกัน"""
    items = _resolve_pending_commit_items(body.pending_ids)
    actor_email = _resolve_commit_actor()
    job = _enqueue_commit_pending_job(items=items, actor_email=actor_email)
    names = [src for _, src, _ in items]
    return JobAcceptedResponse(
        job_id=job.id,
        status=job.status,
        message=f"Commit job queued for {len(names)} file(s)",
        status_url=f"/api/v1/jobs/{job.id}",
        document_name=items[0][2],
        total_files=len(names),
        hint="Poll status_url; files lists every filename in this job.",
    )


@router.post(
    "/ingest-pending/{pending_id}/commit",
    response_model=JobAcceptedResponse,
    tags=["documents"],
)
async def commit_document_ingest_pending(
    pending_id: str,
):
    """Commit pending ingest to vector DB — รันเบื้องหลัง, ตอบ job_id ทันที"""
    from app.document_api.services.pending_ingest_catalog import get_pending_by_id

    pid = pending_id.strip()
    row = get_pending_by_id(pid)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="No pending ingest found for this id",
        )

    items = [(pid, (row.get("source_filename") or "").strip() or pid[:8], (row.get("document_name") or "unknown").strip())]
    actor_email = _resolve_commit_actor()
    job = _enqueue_commit_pending_job(items=items, actor_email=actor_email)
    src_name = items[0][1]
    doc_name = items[0][2]

    return JobAcceptedResponse(
        job_id=job.id,
        status="queued",
        message=f"Commit job queued for {src_name}",
        status_url=f"/api/v1/jobs/{job.id}",
        document_name=doc_name,
        total_files=1,
        hint="Poll status_url for embedding/import progress.",
    )


@router.post(
    "/ingest-pending/{pending_id}/reject",
    response_model=PendingIngestRejectResponse,
    tags=["documents"],
)
async def reject_document_ingest_pending(
    pending_id: str,
):
    """ปฏิเสธ pending ingest — ไม่ commit ลง vector DB"""
    from app.document_api.services.pending_ingest_catalog import reject_pending_ingest

    pid = pending_id.strip()
    actor_email = _resolve_commit_actor()
    try:
        out = reject_pending_ingest(pid, updated_by=actor_email)
    except LookupError:
        raise HTTPException(status_code=404, detail="No pending ingest found for this id") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PendingIngestRejectResponse(**out)


@router.post(
    "/{document_name}",
    response_model=JobAcceptedResponse,
    tags=["documents"],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                                "description": "Upload files",
                            },
                            "enable_supabase": {"type": "boolean", "default": True},
                            "on_duplicate": {"type": "string", "default": "replace"},
                            "include_metadata": {"type": "boolean", "default": True},
                            "chunk_size": {"type": "integer", "default": settings.chunk_size},
                        },
                    }
                }
            },
        }
    },
)
async def create_document_set(
    document_name: str,
    files: Annotated[list[UploadFile], File(..., description="Upload files")],
    background_tasks: BackgroundTasks,
    enable_supabase: bool = Form(default=True),
    on_duplicate: str = Form(default="replace"),
    include_metadata: bool = Form(default=True),
    chunk_size: int = Form(default=settings.chunk_size),
):
    folder = document_name.strip()
    if not folder:
        raise HTTPException(status_code=400, detail="document_name is required")

    payload_files: list[tuple[str, bytes]] = []
    for uploaded_file in files:
        file_name = (uploaded_file.filename or "").strip()
        if not file_name:
            raise HTTPException(status_code=400, detail="Every file must have a file name")
        payload_files.append((file_name, await uploaded_file.read()))

    job = create_job(
        kind="document_ingest",
        total_items=len(payload_files),
        metadata={
            "document_name": folder,
            "files": [name for name, _ in payload_files],
            "progress_profile": _ingest_progress_profile(enable_supabase=enable_supabase),
            "progress": _initial_ingest_progress(enable_supabase=enable_supabase),
            "actor_email": None,
            "retry": {
                "enable_supabase": enable_supabase,
                "on_duplicate": on_duplicate,
                "include_metadata": include_metadata,
                "chunk_size": chunk_size,
            },
        },
    )

    background_tasks.add_task(
        _run_document_ingest_job,
        job.id,
        folder,
        payload_files,
        enable_supabase=enable_supabase,
        on_duplicate=on_duplicate,
        include_metadata=include_metadata,
        chunk_size=chunk_size,
        stream_queue=None,
        actor_username=None,
    )
    return JobAcceptedResponse(
        job_id=job.id,
        status=job.status,
        message="job accepted",
        status_url=f"/api/v1/jobs/{job.id}",
        document_name=folder,
        total_files=len(payload_files),
    )


async def _run_document_ingest_job(
    job_id: str,
    folder: str,
    payload_files: list[tuple[str, bytes]],
    *,
    enable_supabase: bool,
    on_duplicate: str,
    include_metadata: bool,
    chunk_size: int,
    stream_queue: asyncio.Queue[dict | None] | None = None,
    actor_username: str | None = None,
) -> None:
    if is_job_cancelled(job_id):
        return
    loop = asyncio.get_running_loop()
    progress_profile = _ingest_progress_profile(enable_supabase=enable_supabase)
    upload_pending = progress_profile == "upload_pending"

    def push_stream(payload: dict) -> None:
        if stream_queue is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(stream_queue.put(payload), loop)
        except RuntimeError:
            pass

    start_job(job_id, detail="starting document ingest")
    total_files = len(payload_files)
    parallel_limit = _ingest_max_parallel_files()
    ingest_slots = [(f"ingest:{idx}", name) for idx, (name, _) in enumerate(payload_files, start=1)]
    init_job_ingest_queue(job_id, ingest_slots)
    file_rows: list[dict | None] = [None] * total_files
    completed_lock = asyncio.Lock()
    completed_count = 0
    last_progress: dict = _initial_ingest_progress(enable_supabase=enable_supabase)
    semaphore = asyncio.Semaphore(parallel_limit)

    async def _mark_file_done(*, idx: int, file_name: str, progress: dict) -> int:
        nonlocal completed_count
        async with completed_lock:
            completed_count += 1
            done = completed_count
        advance_job(
            job_id,
            completed_items=done,
            current_item=file_name,
            detail=f"completed file {done}/{total_files}",
        )
        if stream_queue is not None:
            await stream_queue.put(
                _ingest_sse_payload(
                    event_type="file_done",
                    job_id=job_id,
                    document_name=folder,
                    total_files=total_files,
                    status="running",
                    file_index=idx,
                    file_name=file_name,
                    current_item=file_name,
                    progress=dict(progress),
                    progress_profile=progress_profile,
                )
            )
        return done

    async def process_file(idx: int, file_name: str, file_bytes: bytes) -> None:
        slot_id = f"ingest:{idx}"
        slot = idx - 1
        if is_job_cancelled(job_id):
            return

        skip_reason = _ingest_file_skip_reason(file_name)
        if skip_reason:
            row = _empty_ingest_file_row(file_name)
            row["skipped"] = True
            row["skip_reason"] = skip_reason
            file_rows[slot] = row
            progress = _initial_ingest_progress(enable_supabase=enable_supabase)
            if stream_queue is not None:
                await stream_queue.put(
                    _ingest_sse_payload(
                        event_type="file_skipped",
                        job_id=job_id,
                        document_name=folder,
                        total_files=total_files,
                        status="running",
                        file_index=idx,
                        file_name=file_name,
                        current_item=file_name,
                        detail=skip_reason,
                        progress=dict(progress),
                        progress_profile=progress_profile,
                        skip_reason=skip_reason,
                    )
                )
            await _mark_file_done(idx=idx, file_name=file_name, progress=progress)
            release_job_ingest_file(job_id, slot_id)
            return

        async with semaphore:
            if is_job_cancelled(job_id):
                return

            register_job_active_item(
                job_id,
                slot_id,
                file_name=file_name,
                detail=f"processing file {idx}/{total_files}",
            )
            try:
                progress = _initial_ingest_progress(enable_supabase=enable_supabase)
                _llm_detail_advance_at = 0.0
                advance_job(
                    job_id,
                    current_item=file_name,
                    detail=f"processing file {idx}/{total_files}",
                )
                if stream_queue is not None:
                    await stream_queue.put(
                        _ingest_sse_payload(
                            event_type="file_start",
                            job_id=job_id,
                            document_name=folder,
                            total_files=total_files,
                            status="running",
                            file_index=idx,
                            file_name=file_name,
                            current_item=file_name,
                            progress=dict(progress),
                            progress_profile=progress_profile,
                        )
                    )

                def progress_callback(stage: str, percent: int, detail: str | None = None) -> None:
                    nonlocal _llm_detail_advance_at, last_progress
                    if is_job_cancelled(job_id):
                        raise RuntimeError("job cancelled")
                    _llm_detail_advance_at = apply_document_ingest_stage_progress(
                        job_id,
                        progress,
                        stage=stage,
                        percent=percent,
                        detail=detail,
                        file_index=idx,
                        total_files=total_files,
                        current_file=file_name,
                        slot_id=slot_id,
                        llm_detail_throttle_at=_llm_detail_advance_at,
                        profile=progress_profile,
                    )
                    last_progress = dict(progress)
                    if stream_queue is not None:
                        stage_map = UPLOAD_PENDING_STAGE_MAP if upload_pending else INGEST_STAGE_MAP
                        mapped = stage_map.get(stage)
                        if mapped:
                            push_stream(
                                _ingest_sse_payload(
                                    event_type="progress",
                                    job_id=job_id,
                                    document_name=folder,
                                    total_files=total_files,
                                    status="running",
                                    file_index=idx,
                                    file_name=file_name,
                                    current_item=file_name,
                                    stage=stage,
                                    percent=int(percent),
                                    detail=detail,
                                    progress=dict(progress),
                                    progress_profile=progress_profile,
                                )
                            )

                try:
                    ingest_result = await asyncio.to_thread(
                        ingest_document_bytes,
                        source_filename=file_name,
                        source_file_bytes=file_bytes,
                        folder_name=folder,
                        enable_supabase=enable_supabase,
                        on_duplicate=on_duplicate,
                        include_metadata=include_metadata,
                        chunk_size=chunk_size,
                        progress_callback=progress_callback,
                        rearrange_stream_callback=None,
                        actor_username=actor_username,
                        job_id=job_id,
                        file_index=idx,
                        total_files=total_files,
                    )
                    file_rows[slot] = _ingest_file_row_from_result(ingest_result)
                except Exception as exc:
                    if is_job_cancelled(job_id) or str(exc).strip().lower() == "job cancelled":
                        return
                    err_msg = _format_ingest_file_error(exc)
                    row = _empty_ingest_file_row(file_name)
                    row["ingest_error"] = err_msg
                    file_rows[slot] = row
                    if stream_queue is not None:
                        await stream_queue.put(
                            _ingest_sse_payload(
                                event_type="file_failed",
                                job_id=job_id,
                                document_name=folder,
                                total_files=total_files,
                                status="running",
                                file_index=idx,
                                file_name=file_name,
                                current_item=file_name,
                                error=err_msg,
                                progress=dict(progress),
                                progress_profile=progress_profile,
                            )
                        )

                await _mark_file_done(idx=idx, file_name=file_name, progress=progress)
            finally:
                release_job_ingest_file(job_id, slot_id)

    try:
        update_job_metadata(
            job_id,
            {
                "ingest_parallel_limit": parallel_limit,
                "progress_profile": progress_profile,
            },
        )
        await asyncio.gather(
            *[
                process_file(idx, file_name, file_bytes)
                for idx, (file_name, file_bytes) in enumerate(payload_files, start=1)
            ]
        )
        if is_job_cancelled(job_id):
            return

        ordered_rows = [row for row in file_rows if row is not None]
        ok_rows = [r for r in ordered_rows if not r.get("ingest_error") and not r.get("skipped")]
        failed_rows = [r for r in ordered_rows if r.get("ingest_error")]
        skipped_rows = [r for r in ordered_rows if r.get("skipped")]

        if upload_pending:
            from app.document_api.services.document_pipeline import format_summary_progress_label

            last_summary = (ok_rows[-1].get("llm_summary") or "") if ok_rows else ""
            final_progress = {
                **empty_upload_pending_progress(),
                "total": 100,
                "converter_files": 100,
                "summary": format_summary_progress_label(
                    file_index=total_files,
                    total_files=total_files,
                    llm_text=last_summary,
                ),
            }
        else:
            img_label = last_progress.get("export_images")
            if not (isinstance(img_label, str) and img_label.startswith("images ")):
                from app.document_api.services.document_pipeline import format_export_images_progress_label

                img_label = format_export_images_progress_label(done=1, total=1)
            final_progress = {
                **_empty_progress(),
                "total": 100,
                "converter_files": 100,
                "export_images": img_label,
                "embedding": 100,
                "import_db": 100,
            }
            if isinstance(last_progress.get("llm_chunks"), str) and last_progress.get("llm_chunks"):
                final_progress["llm_chunks"] = last_progress["llm_chunks"]

        meta_updates: dict = {
            "ingest_file_summaries": ordered_rows,
            "progress_profile": progress_profile,
            "progress": final_progress,
            "ingest_parallel_limit": parallel_limit,
        }
        if failed_rows:
            meta_updates["ingest_failed_files"] = [
                {"file": r.get("file"), "error": r.get("ingest_error")} for r in failed_rows
            ]
        if skipped_rows:
            meta_updates["ingest_skipped_files"] = [
                {"file": r.get("file"), "reason": r.get("skip_reason")} for r in skipped_rows
            ]
        update_job_metadata(job_id, meta_updates)

        ok_count = len(ok_rows)
        fail_count = len(failed_rows)
        skip_count = len(skipped_rows)
        if ok_count > 0:
            detail_parts = [f"ingested {ok_count}/{total_files} file(s)"]
            if fail_count:
                detail_parts.append(f"{fail_count} failed")
            if skip_count:
                detail_parts.append(f"{skip_count} skipped")
            detail = ", ".join(detail_parts)
            complete_job(job_id, detail=detail)
            done_message = detail
            done_status = "completed"
        elif fail_count > 0:
            first_err = str(failed_rows[0].get("ingest_error") or "ingest failed")
            fail_job(job_id, error=first_err, detail=f"all {fail_count} file(s) failed")
            done_message = first_err
            done_status = "failed"
        else:
            detail = f"skipped {skip_count} file(s)"
            complete_job(job_id, detail=detail)
            done_message = detail
            done_status = "completed"

        file_results_payload = _ingest_file_results_payload(ok_rows, failed_rows, skipped_rows)
        if stream_queue is not None:
            if done_status == "completed":
                await stream_queue.put(
                    _ingest_sse_payload(
                        event_type="done",
                        job_id=job_id,
                        document_name=folder,
                        total_files=total_files,
                        status="completed",
                        message=done_message,
                        progress=final_progress,
                        progress_profile=progress_profile,
                        **file_results_payload,
                    )
                )
            else:
                await stream_queue.put(
                    _ingest_sse_payload(
                        event_type="failed",
                        job_id=job_id,
                        document_name=folder,
                        total_files=total_files,
                        status="failed",
                        message="ingest failed",
                        detail=done_message,
                        error=done_message,
                        progress_profile=progress_profile,
                        **file_results_payload,
                    )
                )
    except Exception as exc:
        if is_job_cancelled(job_id) or str(exc).strip().lower() == "job cancelled":
            return
        error_message = _format_ingest_file_error(exc)
        error_meta: dict | None = None
        if isinstance(exc, HTTPException):
            error_meta = {"http_status": exc.status_code, "detail": exc.detail}
        meta_updates = {}
        if error_meta is not None:
            meta_updates["last_error"] = error_meta
        if meta_updates:
            update_job_metadata(job_id, meta_updates)
        fail_job(job_id, error=error_message, detail="ingest failed")
        if stream_queue is not None:
            await stream_queue.put(
                _ingest_sse_payload(
                    event_type="failed",
                    job_id=job_id,
                    document_name=folder,
                    total_files=total_files,
                    status="failed",
                    message="ingest failed",
                    detail=error_message,
                    error=error_message,
                    progress_profile=progress_profile,
                )
            )
    finally:
        if stream_queue is not None:
            await stream_queue.put(None)


@router.put(
    "/{document_name}",
    response_model=DocumentSetMutationResponse,
    tags=["documents"],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                                "description": "Upload files",
                            },
                            "enable_supabase": {"type": "boolean", "default": True},
                            "on_duplicate": {"type": "string", "default": "replace"},
                            "include_metadata": {"type": "boolean", "default": True},
                            "chunk_size": {"type": "integer", "default": settings.chunk_size},
                        },
                    }
                }
            },
        }
    },
)
async def update_document_set(
    document_name: str,
    files: Annotated[list[UploadFile], File(..., description="Upload files")],
    enable_supabase: bool = Form(default=True),
    on_duplicate: str = Form(default="replace"),
    include_metadata: bool = Form(default=True),
    chunk_size: int = Form(default=settings.chunk_size),
):
    folder = document_name.strip()
    actor = None
    for uploaded_file in files:
        file_name = (uploaded_file.filename or "upload.bin").strip() or "upload.bin"
        file_bytes = await uploaded_file.read()
        ingest_document_bytes(
            source_filename=file_name,
            source_file_bytes=file_bytes,
            folder_name=folder,
            enable_supabase=enable_supabase,
            on_duplicate=on_duplicate,
            include_metadata=include_metadata,
            chunk_size=chunk_size,
            actor_username=actor,
        )
    file_records = _to_file_entries(list_file_records_by_folder(folder))
    return DocumentSetMutationResponse(
        message=f"document set updated with {len(files)} file(s)",
        id=_document_id(folder),
        document_name=folder,
        files=file_records,
    )


@router.get("/{document_name}/files", response_model=DocumentSetEntry, tags=["FILES"])
async def list_document_files(document_name: str):
    try:
        folder = document_name.strip()
        return DocumentSetEntry(
            id=_document_id(folder),
            document_name=folder,
            files=_to_file_entries(list_file_records_by_folder(folder)),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot list files: {e}")


@router.patch("/rename/document", response_model=DocumentSetMutationResponse, tags=["documents"])
async def rename_document(payload: RenameDocumentRequest):
    try:
        old_name = payload.document_name.strip()
        new_name = payload.new_document_name.strip()
        files_before = list_file_records_by_folder(old_name)
        if not files_before:
            raise HTTPException(status_code=404, detail="document set not found")
        out = rename_document_set(old_name, new_name)
        if not out.get("updated"):
            raise HTTPException(status_code=400, detail="cannot rename document set")
        files_after = _to_file_entries(list_file_records_by_folder(new_name))
        return DocumentSetMutationResponse(
            message="document set renamed",
            id=_document_id(new_name),
            document_name=new_name,
            files=files_after,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot rename document set: {e}")


@router.delete("/{document_name}", response_model=DocumentSetMutationResponse, tags=["documents"])
async def delete_document_set(
    document_name: str,
):
    try:
        folder = document_name.strip()
        files_before = list_file_records_by_folder(folder)
        if not files_before:
            raise HTTPException(status_code=404, detail="document set not found")
        deleted = delete_documents_by_folder(folder)
        return DocumentSetMutationResponse(
            message=(
                "document set deleted "
                f"(documents={deleted['deleted_documents']}, chunks={deleted['deleted_chunks']}, images={deleted['deleted_images']})"
            ),
            id=_document_id(folder),
            document_name=folder,
            files=[],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot delete document set: {e}")


def _sse_event(data: dict) -> bytes:
    line = json.dumps(data, ensure_ascii=False, default=str, sort_keys=True)
    return f"data: {line}\n\n".encode("utf-8")


def _ingest_parallel_snapshot(job_id: str) -> tuple[list[str], list[str], list[str], dict[str, dict]]:
    job = get_job(job_id)
    if not job:
        return [], [], [], {}
    from app.document_api.api.v1.routes.job_common import parallel_queue_from_meta

    queue = parallel_queue_from_meta(job.metadata or {})
    return (
        list(queue.get("active_items") or []),
        list(queue.get("pending_items") or []),
        list(queue.get("completed_files") or []),
        dict(queue.get("file_activity") or {}),
    )


def _ingest_sse_payload(
    *,
    event_type: str,
    job_id: str,
    document_name: str,
    total_files: int,
    progress: dict | None = None,
    progress_profile: str = "full",
    status: str | None = None,
    message: str | None = None,
    file_index: int | None = None,
    file_name: str | None = None,
    current_item: str | None = None,
    stage: str | None = None,
    percent: int | None = None,
    detail: str | None = None,
    error: str | None = None,
    llm_summary: str | None = None,
    skip_reason: str | None = None,
    ingest_accepted_files: list[str] | None = None,
    ingest_skipped_files: list[dict] | None = None,
    ingest_failed_files: list[dict] | None = None,
) -> dict:
    merged = empty_upload_pending_progress() if progress_profile == "upload_pending" else _empty_progress()
    if progress:
        for k in merged:
            if k in progress:
                merged[k] = progress[k]
    resolved_current = current_item
    if resolved_current is None and file_name is not None:
        resolved_current = file_name
    active_items, pending_items, completed_files, file_activity = _ingest_parallel_snapshot(job_id)
    return {
        "type": event_type,
        "job_id": job_id,
        "document_name": document_name,
        "total_files": total_files,
        "status_url": f"/api/v1/jobs/{job_id}",
        "status": status,
        "message": message,
        "file_index": file_index,
        "file_name": file_name,
        "current_item": resolved_current,
        "active_items": active_items,
        "pending_items": pending_items,
        "completed_files": completed_files,
        "file_activity": file_activity,
        "stage": stage,
        "percent": percent,
        "detail": detail,
        "progress": merged,
        "error": error,
        "llm_summary": llm_summary,
        "skip_reason": skip_reason,
        "ingest_accepted_files": ingest_accepted_files,
        "ingest_skipped_files": ingest_skipped_files,
        "ingest_failed_files": ingest_failed_files,
    }


async def _document_ingest_sse(
    job_id: str,
    folder: str,
    payload_files: list[tuple[str, bytes]],
    *,
    enable_supabase: bool,
    on_duplicate: str,
    include_metadata: bool,
    chunk_size: int,
    actor_username: str | None = None,
) -> AsyncIterator[bytes]:
    job = get_job(job_id)
    status = job.status if job else "queued"
    progress_profile = _ingest_progress_profile(enable_supabase=enable_supabase)
    progress0 = (job.metadata.get("progress") if job else None) or _initial_ingest_progress(
        enable_supabase=enable_supabase
    )
    yield _sse_event(
        _ingest_sse_payload(
            event_type="accepted",
            job_id=job_id,
            document_name=folder,
            total_files=len(payload_files),
            status=status,
            message="job accepted",
            progress=progress0,
            progress_profile=progress_profile,
        )
    )
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    task = asyncio.create_task(
        _run_document_ingest_job(
            job_id,
            folder,
            payload_files,
            enable_supabase=enable_supabase,
            on_duplicate=on_duplicate,
            include_metadata=include_metadata,
            chunk_size=chunk_size,
            stream_queue=queue,
            actor_username=actor_username,
        )
    )
    register_job_task(job_id, task)
    while True:
        item = await queue.get()
        if item is None:
            break
        yield _sse_event(item)
    await task


@router.post(
    "/{document_name}/stream",
    tags=["documents"],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                                "description": "Upload files",
                            },
                            "enable_supabase": {"type": "boolean", "default": True},
                            "on_duplicate": {"type": "string", "default": "replace"},
                            "include_metadata": {"type": "boolean", "default": True},
                            "chunk_size": {"type": "integer", "default": settings.chunk_size},
                        },
                    }
                }
            },
        }
    },
)
async def create_document_set_stream(
    document_name: str,
    files: Annotated[list[UploadFile], File(..., description="Upload files")],
    enable_supabase: bool = Form(default=True),
    on_duplicate: str = Form(default="replace"),
    include_metadata: bool = Form(default=True),
    chunk_size: int = Form(default=settings.chunk_size),
):
    folder = document_name.strip()
    if not folder:
        raise HTTPException(status_code=400, detail="document_name is required")

    payload_files: list[tuple[str, bytes]] = []
    for uploaded_file in files:
        file_name = (uploaded_file.filename or "").strip()
        if not file_name:
            raise HTTPException(status_code=400, detail="Every file must have a file name")
        payload_files.append((file_name, await uploaded_file.read()))

    job = create_job(
        kind="document_ingest",
        total_items=len(payload_files),
        metadata={
            "document_name": folder,
            "files": [name for name, _ in payload_files],
            "progress_profile": _ingest_progress_profile(enable_supabase=enable_supabase),
            "progress": _initial_ingest_progress(enable_supabase=enable_supabase),
            "actor_email": None,
            "retry": {
                "enable_supabase": enable_supabase,
                "on_duplicate": on_duplicate,
                "include_metadata": include_metadata,
                "chunk_size": chunk_size,
            },
        },
    )

    return StreamingResponse(
        _document_ingest_sse(
            job.id,
            folder,
            payload_files,
            enable_supabase=enable_supabase,
            on_duplicate=on_duplicate,
            include_metadata=include_metadata,
            chunk_size=chunk_size,
            actor_username=None,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{document_name}/ingest-pending",
    response_model=list[PendingIngestEntry],
    tags=["documents"],
)
async def list_document_ingest_pending(
    document_name: str,
):
    from app.document_api.api.v1.routes.job_common import list_dashboard_pending_for_document
    from app.document_api.rag_department_scope import filter_rows_by_department_scope, resolve_rag_department_scope

    scope = resolve_rag_department_scope()
    rows = list_dashboard_pending_for_document(document_name.strip())
    rows = filter_rows_by_department_scope(rows, scope)
    return [PendingIngestEntry(**r) for r in rows]





def _resolve_source_in_folder(document_name: str, file_name: str) -> str:
    folder = document_name.strip()
    resolved = _resolve_file_name(folder, file_name)
    source = resolved or file_name.strip()
    if not source or not file_exists_in_folder(folder, source):
        raise HTTPException(status_code=404, detail="file not found in document folder")
    return source


@router.get(
    "/{document_name}/{file_name}/chunks",
    response_model=ChunkContentListResponse,
    tags=["content"],
)
async def list_file_chunks(document_name: str, file_name: str):
    try:
        folder = document_name.strip()
        source = _resolve_source_in_folder(document_name, file_name)
        rows = list_chunks_for_file(source, document_name=folder)
        return ChunkContentListResponse(
            source_filename=source,
            document_name=folder,
            chunks=[ChunkContentSummary(**r) for r in rows],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot list chunks: {e}")


@router.get(
    "/{document_name}/{file_name}/chunks/{chunk_id}",
    response_model=ChunkContentDetail,
    tags=["content"],
)
async def get_file_chunk(document_name: str, file_name: str, chunk_id: str):
    try:
        folder = document_name.strip()
        source = _resolve_source_in_folder(document_name, file_name)
        row = get_chunk_by_id(chunk_id, source_filename=source, document_name=folder)
        if not row:
            raise HTTPException(status_code=404, detail="chunk not found")
        return ChunkContentDetail(**row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot read chunk: {e}")


@router.post(
    "/{document_name}/{file_name}/chunks",
    response_model=ChunkContentMutationResponse,
    tags=["content"],
)
async def create_file_chunk(
    document_name: str,
    file_name: str,
    payload: ChunkContentCreateRequest,
):
    try:
        folder = document_name.strip()
        source = _resolve_source_in_folder(document_name, file_name)
        emb = build_embeddings(settings) if payload.re_embed else None
        out = create_chunk(
            source_filename=source,
            document_name=folder,
            content=payload.content,
            chunk_index=payload.chunk_index,
            re_embed=payload.re_embed,
            embeddings=emb,
            actor_username=None,
        )
        return ChunkContentMutationResponse(
            message="chunk created",
            id=out["id"],
            chunk_index=out.get("chunk_index"),
            token_count=int(out.get("token_count") or 0),
            embedding_applied=bool(out.get("embedding_applied")),
            embedding_error=out.get("embedding_error"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot create chunk: {e}")


@router.patch(
    "/{document_name}/{file_name}/chunks/{chunk_id}",
    response_model=ChunkContentMutationResponse,
    tags=["content"],
)
async def update_file_chunk(
    document_name: str,
    file_name: str,
    chunk_id: str,
    payload: ChunkContentUpdateRequest,
):
    try:
        folder = document_name.strip()
        source = _resolve_source_in_folder(document_name, file_name)
        fields_set = payload.model_fields_set
        content = payload.content if "content" in fields_set else None
        if "re_embed" in fields_set:
            re_embed = payload.re_embed
        elif "content" in fields_set:
            re_embed = True
        else:
            re_embed = False
        emb = build_embeddings(settings) if re_embed else None
        out = update_chunk(
            chunk_id=chunk_id,
            source_filename=source,
            document_name=folder,
            content=content,
            re_embed=re_embed,
            embeddings=emb,
            actor_username=None,
        )
        if not out:
            raise HTTPException(status_code=404, detail="chunk not found")
        return ChunkContentMutationResponse(
            message="chunk updated",
            id=out["id"],
            chunk_index=out.get("chunk_index"),
            token_count=int(out.get("token_count") or 0),
            embedding_applied=bool(out.get("embedding_applied")),
            embedding_error=out.get("embedding_error"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot update chunk: {e}")


@router.delete(
    "/{document_name}/{file_name}/chunks/{chunk_id}",
    response_model=ChunkContentDeleteResponse,
    tags=["content"],
)
async def delete_file_chunk(
    document_name: str,
    file_name: str,
    chunk_id: str,
):
    try:
        folder = document_name.strip()
        source = _resolve_source_in_folder(document_name, file_name)
        ok = delete_chunk(chunk_id=chunk_id, source_filename=source, document_name=folder)
        if not ok:
            raise HTTPException(status_code=404, detail="chunk not found")
        return ChunkContentDeleteResponse(message="chunk deleted", id=chunk_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot delete chunk: {e}")


@router.get("/{document_name}/{file_name}", response_model=DocumentDetail, tags=["FILES"])
async def get_document_file(document_name: str, file_name: str):
    try:
        folder = document_name.strip()
        source = file_name.strip()
        if not file_exists_in_folder(folder, source):
            raise HTTPException(status_code=404, detail="file not found in document folder")
        detail = get_document(source, document_name=folder)
        if not detail:
            raise HTTPException(status_code=404, detail="document not found")
        return DocumentDetail(**detail)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot read document file: {e}")


@router.put("/{document_name}/{file_name}", response_model=DocumentSetMutationResponse, tags=["FILES"])
async def update_document_file(
    document_name: str,
    file_name: str,
    file: Annotated[UploadFile, File(..., description="New file to replace old one")],
    enable_supabase: bool = Form(default=True),
    on_duplicate: str = Form(default="replace"),
    include_metadata: bool = Form(default=True),
    chunk_size: int = Form(default=settings.chunk_size),
):
    try:
        folder = document_name.strip()
        old_source = file_name.strip()
        if not file_exists_in_folder(folder, old_source):
            raise HTTPException(status_code=404, detail="file not found in document folder")

        file_bytes = await file.read()
        upload_name = (file.filename or "upload.bin").strip() or "upload.bin"
        ingest_document_bytes(
            source_filename=upload_name,
            source_file_bytes=file_bytes,
            folder_name=folder,
            enable_supabase=enable_supabase,
            on_duplicate=on_duplicate,
            include_metadata=include_metadata,
            chunk_size=chunk_size,
            actor_username=None,
        )

        new_source = (file.filename or "").strip()
        if new_source and new_source != old_source:
            delete_document(old_source, document_name=folder)

        files = _to_file_entries(list_file_records_by_folder(folder))
        return DocumentSetMutationResponse(
            message="file updated in document folder",
            id=_document_id(folder),
            document_name=folder,
            files=files,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot update document file: {e}")


@router.patch("/rename/file", response_model=DocumentSetMutationResponse, tags=["FILES"])
async def rename_file(payload: RenameFileRequest):
    try:
        folder = payload.document_name.strip()
        old_name = _resolve_file_name(folder, payload.file_name)
        if not old_name:
            raise HTTPException(status_code=404, detail="file not found in document folder")
        out = rename_document_file(folder, old_name, payload.new_file_name)
        if not out.get("updated"):
            raise HTTPException(status_code=400, detail="cannot rename file")
        files = _to_file_entries(list_file_records_by_folder(folder))
        return DocumentSetMutationResponse(
            message="file renamed",
            id=_document_id(folder),
            document_name=folder,
            files=files,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot rename file: {e}")


@router.delete("/{document_name}/{file_name}", response_model=DocumentSetMutationResponse, tags=["FILES"])
async def delete_document_file(
    document_name: str,
    file_name: str,
):
    try:
        folder = document_name.strip()
        source = file_name.strip()
        if not file_exists_in_folder(folder, source):
            raise HTTPException(status_code=404, detail="file not found in document folder")
        out = delete_document(source, document_name=folder)
        if out.get("deleted_chunks", 0) == 0:
            raise HTTPException(status_code=404, detail="document not found")
        files = _to_file_entries(list_file_records_by_folder(folder))
        return DocumentSetMutationResponse(
            message="file deleted from document folder",
            id=_document_id(folder),
            document_name=folder,
            files=files,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cannot delete document file: {e}")
