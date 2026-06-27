from __future__ import annotations

import asyncio
import json
import logging
import queue
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.document_api.api.dependencies import require_asr_enabled
from app.document_api.api.v1.routes.job_common import empty_audio_progress
from app.document_api.api.v1.schemas import (
    TranscriptAudioIndexResponse,
    TranscriptAudioDocumentEntry,
    TranscriptAudioListResponse,
    TranscriptAudioProcessRequest,
    TranscriptAudioRecord,
    TranscriptAudioTranscriptSetEntry,
    TranscriptReportJobAcceptedResponse,
)
from app.document_api.core.config import Settings, get_settings
from app.document_api.lm_engine.asr_engine import transcribe_audio_path_streaming, transcribe_audio_path_to_text
from app.document_api.schemas.asr import normalize_asr_payload_for_metadata
from app.document_api.services.job_manager import (
    advance_job,
    complete_job,
    create_job,
    fail_job,
    start_job,
    update_job_metadata,
)
from app.document_api.services.transcript_summary import (
    generate_transcript_audio_report_llm,
    generate_transcript_audio_summary_llm,
)
from app.document_api.services.transcript_catalog import (
    delete_transcript_row,
    download_transcript_audio_bytes,
    get_transcript_row_scoped,
    list_audio_transcripts,
    list_transcript_audio_groups,
    transcript_upload_audio_file,
    update_transcript_audio_llm_report,
    update_transcript_audio_llm_summary,
    update_transcript_content,
    validate_transcript_ids_for_process,
)
from app.document_api.rag_department_scope import (
    assert_transcript_row_accessible,
    filter_transcript_rows_by_scope,
    resolve_rag_department_scope,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _resolve_transcript_actor() -> str | None:
    from app.document_api.rag_department_scope import resolve_rag_actor_context

    actor_email, _department = resolve_rag_actor_context()
    return (actor_email or "").strip() or None


def _row_to_record(row: dict) -> TranscriptAudioRecord:
    """Map DB row (document_name column) to API ``transcript_group`` field."""
    return TranscriptAudioRecord(
        id=str(row.get("id") or ""),
        transcript_group=str(row.get("document_name") or ""),
        transcript_name=str(row.get("transcript_name") or ""),
        content=row.get("content"),
        files=row.get("files") if isinstance(row.get("files"), list) else [],
        segments=row.get("segments") if isinstance(row.get("segments"), list) else [],
        audio_llm_summary=row.get("audio_llm_summary"),
        audio_llm_report=row.get("audio_llm_report"),
        created_by=row.get("created_by"),
        updated_by=row.get("updated_by"),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        source_filename=row.get("source_filename"),
    )


def _store_transcript_llm_artifacts(
    *,
    transcript_id: str,
    transcript_text: str,
    document_name: str,
    transcript_name: str,
    source_filename: str,
    updated_by: str | None,
    settings: Settings | None = None,
    run_summary: bool = True,
    run_report: bool = True,
) -> dict:
    """สรุป + รายงาน LLM แล้วเขียนลง transcript row — คืน key สำหรับ job metadata"""
    st = settings or get_settings()
    out: dict = {}
    body = (transcript_text or "").strip()
    if not body or not st.llm_enabled:
        return out
    tid = str(transcript_id)

    if run_summary:
        summ, err = generate_transcript_audio_summary_llm(
            transcript_text=body,
            document_name=document_name,
            transcript_name=transcript_name,
            source_filename=source_filename,
            settings=st,
        )
        if err:
            out["audio_llm_summary_error"] = err
        elif summ:
            update_transcript_audio_llm_summary(tid, summ, updated_by=updated_by)
            out["audio_llm_summary"] = summ

    if run_report:
        report, err = generate_transcript_audio_report_llm(
            transcript_text=body,
            document_name=document_name,
            transcript_name=transcript_name,
            source_filename=source_filename,
            settings=st,
        )
        if err:
            out["audio_llm_report_error"] = err
        elif report:
            update_transcript_audio_llm_report(tid, report, updated_by=updated_by)
            out["audio_llm_report"] = report

    return out


def _normalize_pg_uuid_list(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if x is not None]
    return [str(raw)]


def _terminal_failure_message_transcript_rows(
    file_rows: list[dict],
    *,
    llm_summary_error: str | None,
) -> str | None:
    """
    รวมข้อความ error จากแต่ละไฟล์/id (ASR / not found / ฯลฯ) และ LLM summary error.
    คืน None เมื่อไม่มีความล้มเหลว — ใช้ตัดสินใจ ``fail_job`` vs ``complete_job``.
    """
    parts: list[str] = []
    if llm_summary_error and str(llm_summary_error).strip():
        parts.append(str(llm_summary_error).strip())
    for fr in file_rows:
        if fr.get("skipped"):
            continue
        if fr.get("audio_llm_summary_error"):
            continue
        if fr.get("audio_llm_report_error"):
            continue
        tid = str(fr.get("transcript_id") or fr.get("source_filename") or "?")
        e = fr.get("error")
        if e:
            parts.append(f"{tid}: {e}")
            continue
        asr = fr.get("asr")
        if isinstance(asr, dict) and asr.get("error"):
            parts.append(f"{tid}: ASR {asr['error']}")
            continue
        if fr.get("audio_llm_report_error"):
            parts.append(f"{tid}: report {fr['audio_llm_report_error']}")
    merged = "; ".join(p for p in parts if p)
    return merged if merged else None


@router.get(
    "",
    response_model=TranscriptAudioIndexResponse,
)
async def list_transcript_audio_index():
    """
    Transcript index grouped by ``transcript_group`` with ``transcript_sets``.
    Each set: ``transcript_name``, ``transcript_id`` (newest row), ``processing``
    (true when the **newest** row in that set has non-empty ``content`` — no need to process again unless ``force_reprocess``).

    URL: ``GET /api/v1/transcript-report``. Department-scoped when multi-user RBAC is active (admin sees all).
    """
    scope = resolve_rag_department_scope()
    rows = await asyncio.to_thread(list_transcript_audio_groups, scope=scope)
    buckets: OrderedDict[str, list[TranscriptAudioTranscriptSetEntry]] = OrderedDict()
    for r in rows:
        group = str(r.get("document_name") or "").strip()
        tn = str(r.get("transcript_name") or "").strip()
        ids = _normalize_pg_uuid_list(r.get("transcript_ids"))
        transcript_id = ids[0] if ids else ""
        newest_content = r.get("newest_content")
        processing = bool((newest_content if newest_content is not None else "").strip())
        entry = TranscriptAudioTranscriptSetEntry(
            transcript_name=tn,
            transcript_id=transcript_id,
            processing=processing,
        )
        buckets.setdefault(group, []).append(entry)

    transcript_groups = [
        TranscriptAudioDocumentEntry(transcript_group=group_name, transcript_sets=sets_list)
        for group_name, sets_list in buckets.items()
    ]
    total_sets = sum(len(g.transcript_sets) for g in transcript_groups)
    return TranscriptAudioIndexResponse(
        total=total_sets,
        transcript_group_count=len(transcript_groups),
        transcript_groups=transcript_groups,
    )


def _asr_sse_line(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False, default=str)}\n\n"


async def _asr_stream_sse(tmp_path: str, asr_prompt: str):
    """SSE: หลายบรรทัด ``type=token`` แล้วจบด้วย ``type=done`` หรือ ``type=error``"""
    holder: dict = {}
    sync_q: queue.Queue[dict | None] = queue.Queue()

    def on_token(chunk: str) -> None:
        if chunk:
            sync_q.put({"type": "token", "text": chunk})

    def worker() -> None:
        try:
            st = get_settings()
            ap = (asr_prompt or "").strip() or None
            holder["payload"] = transcribe_audio_path_streaming(
                st,
                tmp_path,
                prompt=ap,
                on_token=on_token,
            )
        except Exception as e:
            holder["error"] = str(e).strip() or "asr stream failed"
        finally:
            sync_q.put(None)

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    try:
        while True:
            item = await asyncio.to_thread(sync_q.get)
            if item is None:
                break
            yield _asr_sse_line(item)
        if holder.get("error"):
            yield _asr_sse_line({"type": "error", "message": holder["error"]})
        else:
            pay = holder.get("payload") or {}
            done: dict = {**pay, "type": "done"}
            yield _asr_sse_line(done)
    finally:
        th.join(timeout=7200)
        Path(tmp_path).unlink(missing_ok=True)


_TRANSCRIPT_AUDIO_STREAM_OPENAPI_EXTRA: dict = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {"type": "string", "format": "binary", "description": "ไฟล์เสียง 1 ไฟล์"},
                        "asr_prompt": {
                            "type": "string",
                            "description": "Prompt ถอดเสียง (ทับ ASR_PROMPT ใน .env)",
                            "default": "",
                        },
                    },
                }
            }
        },
    },
}


@router.post(
    "/stream",
    openapi_extra=_TRANSCRIPT_AUDIO_STREAM_OPENAPI_EXTRA,
)
async def asr_stream_only(
    _settings: Annotated[Settings, Depends(require_asr_enabled)],
    file: Annotated[UploadFile, File(..., description="ไฟล์เสียง")],
    asr_prompt: str = Form(default=""),
):
    """
    ถอดเสียงแบบ **SSE** เท่านั้น — ส่งไฟล์เสียงมาประมวลผล ไม่เขียน DB / Storage.

    URL: ``POST /api/v1/transcript-report/stream`` — Response: ``text/event-stream``.
    """
    base_name = (file.filename or "").strip()
    if not base_name:
        raise HTTPException(status_code=400, detail="File name is required")
    body = await file.read()
    suffix = Path(base_name).suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        tf.write(body)
        tmp_path = tf.name
    return StreamingResponse(
        _asr_stream_sse(tmp_path, asr_prompt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


_TRANSCRIPT_AUDIO_OPENAPI_EXTRA: dict = {
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
                            "description": "ไฟล์เสียง (หลายไฟล์ได้)",
                        },
                        "content": {
                            "type": "string",
                            "description": "ข้อความ transcript ล่วงหน้า — ใช้กับทุกไฟล์; ถ้ามีจะไม่รัน ASR",
                            "default": "",
                        },
                        "run_asr": {
                            "type": "boolean",
                            "default": False,
                            "description": "ถ้า True ถอดเสียงทันทีหลังอัปโหลด; ค่าเริ่มต้น False = อัปโหลดก่อน แล้วค่อย POST .../process",
                        },
                        "asr_prompt": {
                            "type": "string",
                            "description": "Prompt ต่อการถอด (ทับค่า ASR_PROMPT ใน .env)",
                            "default": "",
                        },
                        "enable_supabase": {"type": "boolean", "default": True},
                    },
                }
            }
        },
    },
}


@router.get(
    "/{transcript_group}/{transcript_name}",
    response_model=TranscriptAudioListResponse,
)
async def list_transcript_audio_rows(
    transcript_group: str,
    transcript_name: str,
    limit: int = Query(default=50, ge=1, le=500, description="จำนวนแถวสูงสุด"),
):
    """
    ดึงรายการ transcript ที่บันทึกจาก audio ใต้ ``transcript_group`` + ``transcript_name`` (เรียงใหม่สุดก่อน)

    URL: ``GET /api/v1/transcript-report/{transcript_group}/{transcript_name}``. Rows are limited to the caller's department unless admin.
    """
    folder = transcript_group.strip()
    tname = transcript_name.strip()
    if not folder:
        raise HTTPException(status_code=400, detail="transcript_group is required")
    if not tname:
        raise HTTPException(status_code=400, detail="transcript_name is required")
    scope = resolve_rag_department_scope()
    rows = await asyncio.to_thread(list_audio_transcripts, folder, tname, limit=limit)
    rows = filter_transcript_rows_by_scope(rows, scope)
    items = [_row_to_record(r) for r in rows]
    return TranscriptAudioListResponse(
        transcript_group=folder,
        transcript_name=tname,
        total=len(items),
        items=items,
    )


@router.post(
    "/{transcript_group}/{transcript_name}/process",
    response_model=TranscriptReportJobAcceptedResponse,
)
async def create_transcript_audio_process_job(
    transcript_group: str,
    transcript_name: str,
    background_tasks: BackgroundTasks,
    body: TranscriptAudioProcessRequest,
):
    """
    ขั้นถัดไปหลังอัปโหลด: ดึงไฟล์จาก Supabase transcript bucket → ถอดเสียง (เมื่อ ``ASR_ENABLED``)
    → เขียน ``content``/``segments`` → สรุป LLM + รายงาน LLM (เมื่อ ``LLM_ENABLED``).

    ตรวจสอบ id / ASR / Supabase / LLM **ก่อนสร้าง job** — ถ้าไม่ผ่านได้ HTTP 400 พร้อม ``errors`` ไม่สร้างคิว

    URL: ``POST /api/v1/transcript-report/{transcript_group}/{transcript_name}/process`` — body: ``transcript_ids`` จาก ``GET`` รายการแถว
    """
    folder = transcript_group.strip()
    if not folder:
        raise HTTPException(status_code=400, detail="transcript_group is required")
    tname = transcript_name.strip()
    if not tname:
        raise HTTPException(status_code=400, detail="transcript_name is required")

    ids_unique: list[str] = []
    for raw in body.transcript_ids:
        tid = (raw or "").strip()
        if tid and tid not in ids_unique:
            ids_unique.append(tid)
    if not ids_unique:
        raise HTTPException(status_code=400, detail="transcript_ids must contain at least one id")

    scope = resolve_rag_department_scope()

    pre_errors = await asyncio.to_thread(
        validate_transcript_ids_for_process,
        ids_unique,
        document_name=folder,
        transcript_name=tname,
        force_reprocess=body.force_reprocess,
        scope=scope,
    )
    if pre_errors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Process preflight failed — fix errors and submit again",
                "errors": pre_errors,
            },
        )

    actor_email = _resolve_transcript_actor()

    job = create_job(
        kind="transcript_audio",
        total_items=len(ids_unique),
        metadata={
            "document_name": folder,
            "name": tname,
            "transcript_name": tname,
            "transcript_ids": ids_unique,
            "phase": "process",
            "progress": empty_audio_progress(),
            "actor_email": actor_email,
            "retry": {
                "phase": "process",
                "asr_prompt": body.asr_prompt,
                "force_reprocess": body.force_reprocess,
            },
        },
    )

    background_tasks.add_task(
        _guarded_run_transcript_audio_process_job,
        job.id,
        folder,
        tname,
        ids_unique,
        asr_prompt=body.asr_prompt,
        force_reprocess=body.force_reprocess,
        updated_by=actor_email,
    )
    return TranscriptReportJobAcceptedResponse(
        job_id=job.id,
        status=job.status,
        message="transcript audio process job accepted",
        status_url=f"/api/v1/jobs/{job.id}",
        transcript_group=folder,
        transcript_name=tname,
        total_files=len(ids_unique),
        hint=(
            "The status field above is only the initial accept state (usually queued). "
            "GET status_url for running/completed/failed. Rows with transcript text will not re-run ASR "
            "unless you send force_reprocess: true in the body."
        ),
    )


@router.delete(
    "/{transcript_group}/{transcript_name}/{transcript_id}",
)
async def delete_transcript_audio_row(
    transcript_group: str,
    transcript_name: str,
    transcript_id: str,
):
    """
    ลบแถว transcript หนึ่งรายการ (และไฟล์เสียงใน storage ถ้ามี).
    ต้องมี ``transcript-report:delete`` และอยู่แผนกเดียวกับ ``created_by`` (admin ลบได้ทุกแผนก).
    """
    folder = transcript_group.strip()
    tname = transcript_name.strip()
    tid = transcript_id.strip()
    if not folder or not tname or not tid:
        raise HTTPException(
            status_code=400,
            detail="transcript_group, transcript_name, and transcript_id are required",
        )

    scope = resolve_rag_department_scope()
    row = await asyncio.to_thread(
        get_transcript_row_scoped,
        tid,
        document_name=folder,
        transcript_name=tname,
    )
    if not row:
        raise HTTPException(status_code=404, detail="transcript row not found")
    assert_transcript_row_accessible(scope, created_by=row.get("created_by"))

    actor_email = _resolve_transcript_actor()
    ok = await asyncio.to_thread(
        delete_transcript_row,
        tid,
        document_name=folder,
        transcript_name=tname,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="transcript row not found")
    return {
        "ok": True,
        "transcript_id": tid,
        "transcript_group": folder,
        "transcript_name": tname,
        "deleted_by": actor_email,
    }


@router.post(
    "/{transcript_group}/{transcript_name}",
    response_model=TranscriptReportJobAcceptedResponse,
    openapi_extra=_TRANSCRIPT_AUDIO_OPENAPI_EXTRA,
)
async def create_transcript_audio_job(
    transcript_group: str,
    transcript_name: str,
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(..., description="Upload audio files")],
    content: str = Form(default=""),
    run_asr: bool = Form(default=False),
    asr_prompt: str = Form(default=""),
    enable_supabase: bool = Form(default=True),
):
    """
    อัปโหลดเสียงเป็นคิวงาน — เก็บใน bucket **transcript** และตาราง **transcript**.
    ``created_by`` / ``updated_by`` มาจากผู้ใช้ที่ล็อกอิน (ไม่รับจากฟอร์ม)
    ค่าเริ่มต้น ``run_asr=false`` = อัปโหลดก่อนเท่านั้น แล้วให้เรียก ``POST .../process`` พร้อม ``transcript_ids``
    เพื่อถอดเสียงและสรุป

    ถ้าต้องการถอดทันทีหลังอัปโหลด (เดิม): ส่ง ``run_asr=true`` และต้องเปิด ``ASR_ENABLED``
    (ถอดเสียงผ่าน ``app.lm_engine.asr_engine`` เมื่อไม่ส่ง ``content``)

    URL: ``POST /api/v1/transcript-report/{transcript_group}/{transcript_name}``.
    """
    folder = transcript_group.strip()
    if not folder:
        raise HTTPException(status_code=400, detail="transcript_group is required")
    tname = transcript_name.strip()
    if not tname:
        raise HTTPException(status_code=400, detail="transcript_name is required")

    payload_files: list[tuple[str, bytes]] = []
    for uploaded_file in files:
        file_name = (uploaded_file.filename or "").strip()
        if not file_name:
            raise HTTPException(status_code=400, detail="Every file must have a file name")
        payload_files.append((file_name, await uploaded_file.read()))

    actor_email = _resolve_transcript_actor()

    job = create_job(
        kind="transcript_audio",
        total_items=len(payload_files),
        metadata={
            "document_name": folder,
            "name": tname,
            "transcript_name": tname,
            "files": [name for name, _ in payload_files],
            "progress": empty_audio_progress(),
            "actor_email": actor_email,
        },
    )

    background_tasks.add_task(
        _guarded_run_transcript_audio_upload_job,
        job.id,
        folder,
        tname,
        payload_files,
        content=content,
        run_asr=run_asr,
        asr_prompt=asr_prompt,
        enable_supabase=enable_supabase,
        created_by=actor_email,
        updated_by=actor_email,
    )
    return TranscriptReportJobAcceptedResponse(
        job_id=job.id,
        status=job.status,
        message="transcript audio job accepted",
        status_url=f"/api/v1/jobs/{job.id}",
        transcript_group=folder,
        transcript_name=tname,
        total_files=len(payload_files),
        hint="The status above is only on accept — GET status_url for real progress.",
    )


async def _guarded_run_transcript_audio_process_job(
    job_id: str,
    folder: str,
    tname: str,
    ids_unique: list[str],
    *,
    asr_prompt: str,
    force_reprocess: bool,
    updated_by: str | None,
) -> None:
    try:
        await _run_transcript_audio_process_job(
            job_id,
            folder,
            tname,
            ids_unique,
            asr_prompt=asr_prompt,
            force_reprocess=force_reprocess,
            updated_by=updated_by,
        )
    except asyncio.CancelledError:
        fail_job(job_id, error="cancelled", detail="transcript process job cancelled")
        raise
    except BaseException as exc:
        err = str(exc).strip() or type(exc).__name__
        logger.exception("transcript process job %s: unhandled error", job_id)
        update_job_metadata(job_id, {"last_error": {"message": err}})
        fail_job(job_id, error=err, detail="transcript process job crashed")


async def _guarded_run_transcript_audio_upload_job(
    job_id: str,
    folder: str,
    transcript_name: str,
    payload_files: list[tuple[str, bytes]],
    *,
    content: str,
    run_asr: bool,
    asr_prompt: str,
    enable_supabase: bool,
    created_by: str | None,
    updated_by: str | None,
) -> None:
    try:
        await _run_transcript_audio_job(
            job_id,
            folder,
            transcript_name,
            payload_files,
            content=content,
            run_asr=run_asr,
            asr_prompt=asr_prompt,
            enable_supabase=enable_supabase,
            created_by=created_by,
            updated_by=updated_by,
        )
    except asyncio.CancelledError:
        fail_job(job_id, error="cancelled", detail="transcript upload job cancelled")
        raise
    except BaseException as exc:
        err = str(exc).strip() or type(exc).__name__
        logger.exception("transcript upload job %s: unhandled error", job_id)
        update_job_metadata(job_id, {"last_error": {"message": err}})
        fail_job(job_id, error=err, detail="transcript audio job crashed")


async def _run_transcript_audio_job(
    job_id: str,
    folder: str,
    transcript_name: str,
    payload_files: list[tuple[str, bytes]],
    *,
    content: str,
    run_asr: bool,
    asr_prompt: str,
    enable_supabase: bool,
    created_by: str | None,
    updated_by: str | None,
) -> None:
    start_job(job_id, detail="starting transcript audio upload")
    logger.info(
        "transcript audio upload job %s started (%d file(s) document=%s transcript=%s)",
        job_id,
        len(payload_files),
        folder,
        transcript_name,
    )
    file_rows: list[dict] = []
    n = len(payload_files)
    try:
        for idx, (file_name, file_bytes) in enumerate(payload_files, start=1):
            st = get_settings()
            want_asr = bool(run_asr) and st.asr_enabled and not (content or "").strip()
            progress = {
                "upload_storage": 0,
                "import_db": 0,
                "asr": 0 if want_asr else 100,
                "total": int(((idx - 1) / n) * 100) if n else 100,
            }
            update_job_metadata(job_id, {"progress": progress})
            advance_job(
                job_id,
                completed_items=idx - 1,
                current_item=file_name,
                detail=f"processing audio {idx}/{n}",
            )
            result = await asyncio.to_thread(
                transcript_upload_audio_file,
                document_name=folder,
                transcript_name=transcript_name,
                file_name=file_name,
                file_bytes=file_bytes,
                content=content,
                enable_supabase=enable_supabase,
                created_by=created_by,
                updated_by=updated_by,
            )

            if want_asr and result.get("transcript_id"):

                def _run_asr() -> dict:
                    tid = result.get("transcript_id")
                    try:
                        suffix = Path(file_name).suffix or ".wav"
                        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                            tf.write(file_bytes)
                            tmp_path = tf.name
                        try:
                            ap = (asr_prompt or "").strip() or None
                            out = transcribe_audio_path_to_text(
                                get_settings(),
                                tmp_path,
                                prompt=ap,
                            )
                            txt = out.get("text") or ""
                            update_transcript_content(
                                str(tid),
                                txt,
                                segments=out.get("segments"),
                                updated_by=updated_by,
                            )
                            meta = normalize_asr_payload_for_metadata(out)
                            meta["text"] = txt
                            return meta
                        finally:
                            Path(tmp_path).unlink(missing_ok=True)
                    except Exception as e:
                        return {"error": str(e)}

                advance_job(job_id, detail=f"ASR transcribing {file_name}")
                progress["asr"] = 30
                update_job_metadata(job_id, {"progress": dict(progress)})
                asr_meta = await asyncio.to_thread(_run_asr)
                result["asr"] = asr_meta

            tid = result.get("transcript_id")
            final_text_for_summary = ""
            if want_asr and tid:
                asr_meta = result.get("asr") or {}
                if not asr_meta.get("error"):
                    final_text_for_summary = (asr_meta.get("text") or "").strip()
            elif tid:
                final_text_for_summary = (content or "").strip()

            if tid and final_text_for_summary and st.llm_enabled:
                llm_out = await asyncio.to_thread(
                    _store_transcript_llm_artifacts,
                    transcript_id=str(tid),
                    transcript_text=final_text_for_summary,
                    document_name=folder,
                    transcript_name=transcript_name,
                    source_filename=file_name,
                    updated_by=updated_by,
                    settings=st,
                )
                if llm_out.get("audio_llm_summary_error"):
                    result["audio_llm_summary_error"] = llm_out["audio_llm_summary_error"]
                elif llm_out.get("audio_llm_summary"):
                    result["audio_llm_summary"] = llm_out["audio_llm_summary"]
                if llm_out.get("audio_llm_report_error"):
                    result["audio_llm_report_error"] = llm_out["audio_llm_report_error"]
                elif llm_out.get("audio_llm_report"):
                    result["audio_llm_report"] = llm_out["audio_llm_report"]

            progress = {
                "upload_storage": 100,
                "import_db": 100,
                "asr": 100,
                "total": int((idx / n) * 100) if n else 100,
            }
            update_job_metadata(job_id, {"progress": progress})
            file_rows.append(result)
            advance_job(
                job_id,
                completed_items=idx,
                current_item=file_name,
                detail=f"saved transcript row {idx}/{n}",
            )

        final_progress = {"upload_storage": 100, "import_db": 100, "asr": 100, "total": 100}
        err_items = [
            {
                "transcript_id": str(fr.get("transcript_id") or fr.get("source_filename") or ""),
                "detail": str(fr["audio_llm_summary_error"]),
            }
            for fr in file_rows
            if fr.get("audio_llm_summary_error")
        ]
        err_items.extend(
            {
                "transcript_id": str(fr.get("transcript_id") or fr.get("source_filename") or ""),
                "detail": str(fr["audio_llm_report_error"]),
            }
            for fr in file_rows
            if fr.get("audio_llm_report_error")
        )
        first_summ = next((fr.get("audio_llm_summary") for fr in file_rows if fr.get("audio_llm_summary")), None)
        first_report = next((fr.get("audio_llm_report") for fr in file_rows if fr.get("audio_llm_report")), None)
        meta_fin: dict = {
            "transcript_file_summaries": file_rows,
            "progress": final_progress,
        }
        if err_items:
            meta_fin["transcript_llm_errors"] = err_items
            meta_fin["llm_summary_error"] = "; ".join(f'{e["transcript_id"]}: {e["detail"]}' for e in err_items)
        if first_summ:
            meta_fin["llm_summary"] = (first_summ[:4000] + "…") if len(first_summ) > 4000 else first_summ
        if first_report:
            meta_fin["llm_report"] = (first_report[:4000] + "…") if len(first_report) > 4000 else first_report
        update_job_metadata(job_id, meta_fin)
        fail_msg = _terminal_failure_message_transcript_rows(
            file_rows,
            llm_summary_error=meta_fin.get("llm_summary_error"),
        )
        if fail_msg:
            fail_job(
                job_id,
                error=fail_msg[:8000],
                detail="transcript audio: finished with errors",
            )
        else:
            complete_job(job_id, detail=f"transcript audio: inserted {n} row(s)")
    except Exception as exc:
        error_message = str(exc).strip() or "transcript upload failed"
        update_job_metadata(job_id, {"last_error": {"message": error_message}})
        fail_job(job_id, error=error_message, detail="transcript audio job failed")


async def _run_transcript_audio_process_job(
    job_id: str,
    folder: str,
    transcript_name: str,
    transcript_ids: list[str],
    *,
    asr_prompt: str,
    force_reprocess: bool,
    updated_by: str | None,
) -> None:
    start_job(job_id, detail="transcript process: ASR + summary")
    tname = transcript_name
    logger.info(
        "transcript audio process job %s started (%d id(s) document=%s transcript=%s force_reprocess=%s)",
        job_id,
        len(transcript_ids),
        folder,
        tname,
        force_reprocess,
    )
    file_rows: list[dict] = []
    n = len(transcript_ids)
    try:
        for idx, tid in enumerate(transcript_ids, start=1):
            st = get_settings()
            progress = {
                "upload_storage": 100,
                "import_db": 100,
                "asr": 0,
                "total": int(((idx - 1) / n) * 100) if n else 100,
            }
            update_job_metadata(job_id, {"progress": progress})
            advance_job(
                job_id,
                completed_items=idx - 1,
                current_item=tid,
                detail=f"process transcript {idx}/{n}",
            )

            row = await asyncio.to_thread(
                get_transcript_row_scoped,
                tid,
                document_name=folder,
                transcript_name=tname,
            )
            if not row:
                file_rows.append({"transcript_id": tid, "error": "not found or folder mismatch"})
                update_job_metadata(
                    job_id,
                    {
                        "progress": {
                            "upload_storage": 100,
                            "import_db": 100,
                            "asr": 100,
                            "total": int((idx / n) * 100) if n else 100,
                        }
                    },
                )
                advance_job(
                    job_id,
                    completed_items=idx,
                    current_item=tid,
                    detail=f"transcript not found {idx}/{n}",
                )
                continue

            content = (row.get("content") or "").strip()
            summary_full = (row.get("audio_llm_summary") or "").strip()
            report_full = (row.get("audio_llm_report") or "").strip()
            files = row.get("files") or []
            if not isinstance(files, list):
                files = []
            source_fn = (row.get("source_filename") or "").strip() or "audio"

            if not force_reprocess and content:
                progress = {
                    "upload_storage": 100,
                    "import_db": 100,
                    "asr": 100,
                    "total": int((idx / n) * 100) if n else 100,
                }
                update_job_metadata(job_id, {"progress": progress})
                file_rows.append({"transcript_id": tid, "skipped": True})
                advance_job(
                    job_id,
                    completed_items=idx,
                    current_item=tid,
                    detail=f"skipped (already has content) {idx}/{n}",
                )
                continue

            want_asr = force_reprocess or not content
            final_text = content
            asr_meta: dict | None = None

            if not want_asr:
                progress["asr"] = 100
                update_job_metadata(job_id, {"progress": dict(progress)})

            if want_asr:
                if not st.asr_enabled:
                    file_rows.append(
                        {
                            "transcript_id": tid,
                            "error": "ASR is disabled — set ASR_ENABLED=true",
                        }
                    )
                    update_job_metadata(
                        job_id,
                        {
                            "progress": {
                                "upload_storage": 100,
                                "import_db": 100,
                                "asr": 100,
                                "total": int((idx / n) * 100) if n else 100,
                            }
                        },
                    )
                    advance_job(
                        job_id,
                        completed_items=idx,
                        current_item=tid,
                        detail=f"ASR disabled {idx}/{n}",
                    )
                    continue
                try:
                    audio_bytes, stor_name = await asyncio.to_thread(download_transcript_audio_bytes, files)
                except ValueError as e:
                    file_rows.append({"transcript_id": tid, "error": str(e)})
                    update_job_metadata(
                        job_id,
                        {
                            "progress": {
                                "upload_storage": 100,
                                "import_db": 100,
                                "asr": 100,
                                "total": int((idx / n) * 100) if n else 100,
                            }
                        },
                    )
                    advance_job(
                        job_id,
                        completed_items=idx,
                        current_item=tid,
                        detail=f"download failed {idx}/{n}",
                    )
                    continue

                def _run_asr() -> dict:
                    try:
                        suffix = Path(stor_name).suffix or ".wav"
                        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                            tf.write(audio_bytes)
                            tmp_path = tf.name
                        try:
                            ap = (asr_prompt or "").strip() or None
                            out = transcribe_audio_path_to_text(
                                get_settings(),
                                tmp_path,
                                prompt=ap,
                            )
                            txt = out.get("text") or ""
                            update_transcript_content(
                                str(tid),
                                txt,
                                segments=out.get("segments"),
                                updated_by=updated_by,
                            )
                            meta = normalize_asr_payload_for_metadata(out)
                            meta["text"] = txt
                            return meta
                        finally:
                            Path(tmp_path).unlink(missing_ok=True)
                    except Exception as e:
                        return {"error": str(e)}

                advance_job(job_id, detail=f"ASR transcribing {stor_name}")
                progress["asr"] = 30
                update_job_metadata(job_id, {"progress": dict(progress)})
                asr_meta = await asyncio.to_thread(_run_asr)
                if asr_meta.get("error"):
                    file_rows.append({"transcript_id": tid, "error": asr_meta["error"], "asr": asr_meta})
                    update_job_metadata(
                        job_id,
                        {
                            "progress": {
                                "upload_storage": 100,
                                "import_db": 100,
                                "asr": 100,
                                "total": int((idx / n) * 100) if n else 100,
                            }
                        },
                    )
                    advance_job(
                        job_id,
                        completed_items=idx,
                        current_item=tid,
                        detail=f"ASR failed {idx}/{n}",
                    )
                    continue
                final_text = (asr_meta.get("text") or "").strip()

            llm_summ: str | None = None
            llm_err: str | None = None
            llm_report: str | None = None
            llm_report_err: str | None = None
            if tid and final_text and st.llm_enabled:
                need_summary = force_reprocess or not summary_full
                need_report = force_reprocess or not report_full
                if need_summary or need_report:
                    llm_out = await asyncio.to_thread(
                        _store_transcript_llm_artifacts,
                        transcript_id=str(tid),
                        transcript_text=final_text,
                        document_name=folder,
                        transcript_name=tname,
                        source_filename=source_fn,
                        updated_by=updated_by,
                        settings=st,
                        run_summary=need_summary,
                        run_report=need_report,
                    )
                    if llm_out.get("audio_llm_summary_error"):
                        llm_err = llm_out["audio_llm_summary_error"]
                    elif llm_out.get("audio_llm_summary"):
                        llm_summ = llm_out["audio_llm_summary"]
                    if llm_out.get("audio_llm_report_error"):
                        llm_report_err = llm_out["audio_llm_report_error"]
                    elif llm_out.get("audio_llm_report"):
                        llm_report = llm_out["audio_llm_report"]

            progress = {
                "upload_storage": 100,
                "import_db": 100,
                "asr": 100,
                "total": int((idx / n) * 100) if n else 100,
            }
            update_job_metadata(job_id, {"progress": progress})
            out_row: dict = {"transcript_id": tid}
            if asr_meta is not None:
                out_row["asr"] = asr_meta
            if llm_err:
                out_row["audio_llm_summary_error"] = llm_err
            elif llm_summ:
                out_row["audio_llm_summary"] = llm_summ
            if llm_report_err:
                out_row["audio_llm_report_error"] = llm_report_err
            elif llm_report:
                out_row["audio_llm_report"] = llm_report
            file_rows.append(out_row)
            advance_job(
                job_id,
                completed_items=idx,
                current_item=tid,
                detail=f"processed transcript {idx}/{n}",
            )

        final_progress = {"upload_storage": 100, "import_db": 100, "asr": 100, "total": 100}
        err_items = [
            {
                "transcript_id": str(fr.get("transcript_id") or ""),
                "detail": str(fr["audio_llm_summary_error"]),
            }
            for fr in file_rows
            if fr.get("audio_llm_summary_error")
        ]
        err_items.extend(
            {
                "transcript_id": str(fr.get("transcript_id") or ""),
                "detail": str(fr["audio_llm_report_error"]),
            }
            for fr in file_rows
            if fr.get("audio_llm_report_error")
        )
        first_summ = next((fr.get("audio_llm_summary") for fr in file_rows if fr.get("audio_llm_summary")), None)
        first_report = next((fr.get("audio_llm_report") for fr in file_rows if fr.get("audio_llm_report")), None)
        meta_proc: dict = {
            "transcript_process_results": file_rows,
            "progress": final_progress,
        }
        if err_items:
            meta_proc["transcript_llm_errors"] = err_items
            meta_proc["llm_summary_error"] = "; ".join(f'{e["transcript_id"]}: {e["detail"]}' for e in err_items)
        if first_summ:
            meta_proc["llm_summary"] = (first_summ[:4000] + "…") if len(first_summ) > 4000 else first_summ
        if first_report:
            meta_proc["llm_report"] = (first_report[:4000] + "…") if len(first_report) > 4000 else first_report
        update_job_metadata(job_id, meta_proc)
        fail_msg = _terminal_failure_message_transcript_rows(
            file_rows,
            llm_summary_error=meta_proc.get("llm_summary_error"),
        )
        if fail_msg:
            fail_job(
                job_id,
                error=fail_msg[:8000],
                detail="transcript process: finished with errors",
            )
        else:
            complete_job(job_id, detail=f"transcript process: {n} id(s)")
    except Exception as exc:
        error_message = str(exc).strip() or "transcript process failed"
        update_job_metadata(job_id, {"last_error": {"message": error_message}})
        fail_job(job_id, error=error_message, detail="transcript process job failed")
