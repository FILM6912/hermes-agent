from __future__ import annotations

import asyncio
import logging
import re
import time

from app.document_api.api.v1.schemas import JobStatusResponse

logger = logging.getLogger(__name__)

DOCUMENT_INGEST_STAGE_KEYS = ("converter_files", "export_images", "llm_chunks", "embedding", "import_db")
UPLOAD_PENDING_STAGE_KEYS = ("converter_files", "summary")
COMMIT_PENDING_STAGE_KEYS = ("export_images", "llm_chunks", "embedding", "import_db")
STRING_PROGRESS_KEYS = frozenset({"summary", "llm_chunks", "export_images"})

INGEST_STAGE_MAP = {
    "convert": "converter_files",
    "images": "export_images",
    "llm_chunks": "llm_chunks",
    "embedding": "embedding",
    "db": "import_db",
    "summary": "summary",
}

UPLOAD_PENDING_STAGE_MAP = {
    "convert": "converter_files",
    "summary": "summary",
}

COMMIT_STAGE_MAP = {
    "images": "export_images",
    "llm_chunks": "llm_chunks",
    "embedding": "embedding",
    "db": "import_db",
}


def _as_percent(value: object) -> int:
    if isinstance(value, str):
        return 0
    return max(0, min(100, int(value or 0)))


def _label_fraction(label: str, *, kind: str) -> int:
    if not isinstance(label, str) or not label.strip():
        return 0
    if kind == "llm_chunks":
        match = re.search(r"chunks\s+(\d+)/(\d+)", label)
        if not match:
            return 0
        done, total = int(match.group(1)), int(match.group(2))
        if total <= 0:
            return 100
        return int((done / total) * 100)
    if kind == "export_images":
        match = re.search(r"images\s+(\d+)/(\d+)", label)
        if not match:
            return 0
        done, total = int(match.group(1)), int(match.group(2))
        if total <= 0:
            return 100
        return int((done / total) * 100)
    if kind == "summary":
        match = re.search(r"tokens\s+(\d+)", label)
        return 100 if match and int(match.group(1)) > 0 else 0
    return 0


def _log_progress_label(job_id: str, stage: str, label: str) -> None:
    short = (job_id or "")[:8]
    logger.info("job %s progress %s: %s", short, stage, label)


def apply_document_ingest_stage_progress(
    job_id: str,
    progress: dict,
    *,
    stage: str,
    percent: int,
    detail: str | None,
    file_index: int,
    total_files: int,
    current_file: str,
    slot_id: str | None = None,
    llm_detail_throttle_at: float | None = None,
    llm_detail_throttle_sec: float = 0.85,
    profile: str = "full",
) -> float | None:
    """Update in-memory job progress for document ingest; returns updated LLM detail throttle time."""
    from app.document_api.services.job_manager import advance_job, update_job_file_activity, update_job_metadata

    stage_maps = {
        "upload_pending": UPLOAD_PENDING_STAGE_MAP,
        "full": INGEST_STAGE_MAP,
    }
    stage_map = stage_maps.get(profile, INGEST_STAGE_MAP)
    mapped = stage_map.get(stage)
    if not mapped:
        return llm_detail_throttle_at
    label_updated: str | None = None
    if mapped in STRING_PROGRESS_KEYS:
        if detail is not None:
            detail_s = str(detail)
            if mapped == "summary" and detail_s.startswith("files "):
                progress[mapped] = detail_s
                label_updated = detail_s
            elif mapped == "llm_chunks" and detail_s.startswith("chunks "):
                progress[mapped] = detail_s
                label_updated = detail_s
            elif mapped == "export_images" and detail_s.startswith("images "):
                progress[mapped] = detail_s
                label_updated = detail_s
    else:
        progress[mapped] = max(0, min(100, int(percent)))
    if profile == "upload_pending":
        file_total = file_stage_total_for_upload_pending(progress)
    else:
        file_total = file_stage_total_for_ingest(progress)
    progress["total"] = int((((file_index - 1) + (file_total / 100)) / max(total_files, 1)) * 100)
    update_job_metadata(job_id, {"progress": dict(progress)})
    activity_key = (slot_id or current_file or "").strip()
    if label_updated:
        _log_progress_label(job_id, mapped, label_updated)
        advance_job(job_id, detail=label_updated, current_item=current_file)
        if activity_key:
            update_job_file_activity(
                job_id,
                activity_key,
                detail=label_updated,
                percent=file_total,
                file_name=current_file,
            )
        return llm_detail_throttle_at

    if not detail:
        return llm_detail_throttle_at

    bump_detail = True
    throttle_at = llm_detail_throttle_at
    if mapped == "llm_chunks" and not label_updated:
        now_m = time.monotonic()
        if throttle_at is not None and now_m - throttle_at < llm_detail_throttle_sec:
            bump_detail = False
        else:
            throttle_at = now_m
    if bump_detail:
        advance_job(job_id, detail=detail, current_item=current_file)
        if activity_key:
            update_job_file_activity(
                job_id,
                activity_key,
                detail=detail,
                percent=file_total,
                file_name=current_file,
            )
    return throttle_at


def apply_commit_pending_stage_progress(
    job_id: str,
    progress: dict,
    *,
    stage: str,
    percent: int,
    detail: str | None,
    file_index: int = 1,
    total_files: int = 1,
    current_file: str | None = None,
    slot_id: str | None = None,
) -> None:
    from app.document_api.services.job_manager import advance_job, update_job_file_activity, update_job_metadata

    mapped = COMMIT_STAGE_MAP.get(stage)
    if not mapped:
        return
    label_updated: str | None = None
    if mapped in STRING_PROGRESS_KEYS:
        if detail is not None:
            detail_s = str(detail)
            if mapped == "summary" and detail_s.startswith("files "):
                progress[mapped] = detail_s
                label_updated = detail_s
            elif mapped == "llm_chunks" and detail_s.startswith("chunks "):
                progress[mapped] = detail_s
                label_updated = detail_s
            elif mapped == "export_images" and detail_s.startswith("images "):
                progress[mapped] = detail_s
                label_updated = detail_s
    else:
        progress[mapped] = max(0, min(100, int(percent)))
    file_total = file_stage_total_for_commit_pending(progress)
    progress["total"] = int((((file_index - 1) + (file_total / 100)) / max(total_files, 1)) * 100)
    activity_key = (slot_id or current_file or "").strip()
    meta = {"progress": dict(progress)}
    if label_updated:
        _log_progress_label(job_id, mapped, label_updated)
        update_job_metadata(job_id, meta)
        advance_job(job_id, detail=label_updated, current_item=current_file)
        if activity_key:
            update_job_file_activity(
                job_id,
                activity_key,
                detail=label_updated,
                percent=file_total,
                file_name=current_file,
            )
        return
    update_job_metadata(job_id, meta)
    if detail:
        advance_job(job_id, detail=detail, current_item=current_file)
        if activity_key:
            update_job_file_activity(
                job_id,
                activity_key,
                detail=detail,
                percent=file_total,
                file_name=current_file,
            )


def empty_document_progress() -> dict:
    return {
        "converter_files": 0,
        "export_images": "",
        "llm_chunks": "",
        "embedding": 0,
        "import_db": 0,
        "total": 0,
    }


def empty_upload_pending_progress() -> dict:
    return {
        "converter_files": 0,
        "summary": "",
        "total": 0,
    }


def empty_commit_pending_progress() -> dict:
    return {
        "export_images": "",
        "llm_chunks": "",
        "embedding": 0,
        "import_db": 0,
        "total": 0,
    }


def empty_audio_progress() -> dict:
    return {
        "upload_storage": 0,
        "import_db": 0,
        "asr": 0,
        "total": 0,
    }


def file_stage_total_for_ingest(progress: dict) -> int:
    values: list[int] = []
    for stage in DOCUMENT_INGEST_STAGE_KEYS:
        raw = progress.get(stage, 0)
        if stage == "llm_chunks" and isinstance(raw, str):
            values.append(_label_fraction(raw, kind="llm_chunks"))
        elif stage == "export_images" and isinstance(raw, str):
            values.append(_label_fraction(raw, kind="export_images"))
        else:
            values.append(_as_percent(raw))
    if not values:
        return 0
    return int(sum(values) / len(values))


def file_stage_total_for_upload_pending(progress: dict) -> int:
    conv = _as_percent(progress.get("converter_files"))
    summary_raw = progress.get("summary", "")
    summary_part = _label_fraction(summary_raw, kind="summary") if isinstance(summary_raw, str) else _as_percent(summary_raw)
    return int(conv * 0.5 + summary_part * 0.5)


def file_stage_total_for_commit_pending(progress: dict) -> int:
    values: list[int] = []
    for stage in COMMIT_PENDING_STAGE_KEYS:
        raw = progress.get(stage, 0)
        if stage == "llm_chunks" and isinstance(raw, str):
            values.append(_label_fraction(raw, kind="llm_chunks"))
        elif stage == "export_images" and isinstance(raw, str):
            values.append(_label_fraction(raw, kind="export_images"))
        else:
            values.append(_as_percent(raw))
    if not values:
        return 0
    return int(sum(values) / len(values))


def extract_job_files(metadata: dict | None) -> list[str]:
    """ชื่อไฟล์ทั้งหมดในงาน — จาก metadata.files หรือ ingest_file_summaries / source_filename."""
    meta = metadata or {}
    raw = meta.get("files")
    if isinstance(raw, list):
        names = [str(x).strip() for x in raw if str(x).strip()]
        if names:
            return names
    for key in ("ingest_file_summaries", "commit_file_summaries"):
        summaries = meta.get(key)
        if isinstance(summaries, list):
            names = []
            for row in summaries:
                if isinstance(row, dict):
                    fn = str(row.get("file") or row.get("source_filename") or "").strip()
                    if fn:
                        names.append(fn)
            if names:
                return names
    src = str(meta.get("source_filename") or "").strip()
    if src:
        return [src]
    return []


def extract_job_document_name(metadata: dict | None) -> str | None:
    meta = metadata or {}
    name = str(meta.get("document_name") or "").strip()
    return name or None


def compute_queue_positions(pending_jobs: list) -> tuple[dict[str, int], int]:
    """
    จากงาน queued+running — คืน (แมป job_id -> ลำดับคิว 1..n สำหรับแค่ queued, จำนวน queued ทั้งหมด).
    คิวเรียง FIFO ตาม ``created_at`` (เก่าสุด = ลำดับ 1).
    """
    queued = sorted((j for j in pending_jobs if getattr(j, "status", None) == "queued"), key=lambda j: j.created_at)
    n = len(queued)
    positions = {j.id: i + 1 for i, j in enumerate(queued)}
    return positions, n


def _string_list_no_dedupe(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item or "").strip() for item in raw if str(item or "").strip()]


def _slot_labels_from_meta(meta: dict) -> dict[str, str]:
    raw = meta.get("slot_labels")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        slot_id = str(key or "").strip()
        label = str(value or "").strip()
        if slot_id and label:
            out[slot_id] = label
    return out


def parallel_queue_from_meta(meta: dict) -> dict[str, object]:
    """Build API-facing parallel queue fields from job metadata."""
    labels = _slot_labels_from_meta(meta)
    if "pending_slots" in meta or "active_slots" in meta or "completed_slots" in meta:
        active_slot_ids = _string_list_no_dedupe(meta.get("active_slots"))
        pending_slot_ids = _string_list_no_dedupe(meta.get("pending_slots"))
        completed_slot_ids = _string_list_no_dedupe(meta.get("completed_slots"))
        active_items = [labels.get(slot_id, slot_id) for slot_id in active_slot_ids]
        pending_items = [labels.get(slot_id, slot_id) for slot_id in pending_slot_ids]
        completed_files = [labels.get(slot_id, slot_id) for slot_id in completed_slot_ids]
        raw_activity = meta.get("file_activity")
        file_activity: dict[str, dict] = {}
        if isinstance(raw_activity, dict):
            for slot_id, value in raw_activity.items():
                sid = str(slot_id or "").strip()
                if not sid or not isinstance(value, dict):
                    continue
                entry = dict(value)
                entry.setdefault("file_name", labels.get(sid, sid))
                file_activity[sid] = entry
        return {
            "active_slot_ids": active_slot_ids,
            "pending_slot_ids": pending_slot_ids,
            "completed_slot_ids": completed_slot_ids,
            "active_items": active_items,
            "pending_items": pending_items,
            "completed_files": completed_files,
            "file_activity": file_activity,
        }

    active_items = _string_list_no_dedupe(meta.get("active_items"))
    pending_items = _string_list_no_dedupe(meta.get("pending_items"))
    completed_files = _string_list_no_dedupe(meta.get("completed_files"))
    raw_activity = meta.get("file_activity")
    file_activity = dict(raw_activity) if isinstance(raw_activity, dict) else {}
    return {
        "active_slot_ids": [],
        "pending_slot_ids": [],
        "completed_slot_ids": [],
        "active_items": active_items,
        "pending_items": pending_items,
        "completed_files": completed_files,
        "file_activity": file_activity,
    }


def _normalize_job_active_items(raw: object) -> list[str]:
    return _string_list_no_dedupe(raw)


def job_to_status_response(
    job,
    *,
    queue_position: int | None = None,
    queue_waiting_total: int | None = None,
) -> JobStatusResponse:
    meta = job.metadata or {}
    if job.kind == "transcript_audio":
        default_prog = empty_audio_progress()
    elif meta.get("progress_profile") == "commit_pending":
        default_prog = empty_commit_pending_progress()
    elif meta.get("progress_profile") == "upload_pending":
        default_prog = empty_upload_pending_progress()
    else:
        default_prog = empty_document_progress()
    raw_prog = meta.get("progress")
    progress_out = dict(raw_prog) if isinstance(raw_prog, dict) else dict(default_prog)
    files_out = extract_job_files(meta)
    doc_name = extract_job_document_name(meta)
    raw_activity = meta.get("file_activity")
    file_activity_out = dict(raw_activity) if isinstance(raw_activity, dict) else {}
    queue = parallel_queue_from_meta(meta)
    file_activity_out = dict(queue.get("file_activity") or file_activity_out)
    return JobStatusResponse(
        job_id=job.id,
        kind=job.kind,
        status=job.status,
        revision=getattr(job, "revision", 0),
        document_name=doc_name,
        files=files_out,
        detail=job.detail,
        error=job.error,
        total_items=job.total_items,
        completed_items=job.completed_items,
        current_item=job.current_item,
        active_items=list(queue.get("active_items") or []),
        pending_items=list(queue.get("pending_items") or []),
        completed_files=list(queue.get("completed_files") or []),
        active_slot_ids=list(queue.get("active_slot_ids") or []),
        pending_slot_ids=list(queue.get("pending_slot_ids") or []),
        completed_slot_ids=list(queue.get("completed_slot_ids") or []),
        file_activity=file_activity_out,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        metadata=dict(meta),
        progress=progress_out,
        llm_summary=meta.get("llm_summary"),
        llm_summary_error=meta.get("llm_summary_error"),
        queue_position=queue_position,
        queue_waiting_total=queue_waiting_total,
    )


def active_commit_pending_ingest_ids() -> frozenset[str]:
    """Pending rows currently being committed — show only under /jobs, not ingest-pending."""
    from app.document_api.services.job_manager import list_jobs

    ids: set[str] = set()
    for job in list_jobs(statuses={"queued", "running"}):
        if job.kind != "commit_pending":
            continue
        meta = job.metadata or {}
        batch = meta.get("pending_ingest_ids")
        if isinstance(batch, list):
            for raw in batch:
                pid = str(raw or "").strip()
                if pid:
                    ids.add(pid)
        pid = str(meta.get("pending_ingest_id") or "").strip()
        if pid:
            ids.add(pid)
    return frozenset(ids)


def filter_jobs_excluding_ingest_pending(jobs: list) -> list:
    from app.document_api.services.pending_ingest_catalog import list_upload_job_ids_awaiting_admin

    blocked = list_upload_job_ids_awaiting_admin()
    if not blocked:
        return jobs
    return [job for job in jobs if job.id not in blocked]


def filter_ingest_pending_rows(rows: list[dict]) -> list[dict]:
    committing = active_commit_pending_ingest_ids()
    ready_rows = [row for row in rows if row.get("summary_ready", True)]
    if not committing:
        return ready_rows
    return [row for row in ready_rows if str(row.get("id") or "") not in committing]


def list_dashboard_pending_ingest(*, created_by: str | None = None, department_id: str | None = None) -> list[dict]:
    from app.document_api.services.pending_ingest_catalog import list_all_pending_ingest

    return filter_ingest_pending_rows(
        list_all_pending_ingest(created_by=created_by, department_id=department_id)
    )


def list_dashboard_pending_for_document(document_name: str) -> list[dict]:
    from app.document_api.services.pending_ingest_catalog import list_pending_for_document

    return filter_ingest_pending_rows(list_pending_for_document(document_name))


async def wait_any_events(*events: asyncio.Event, timeout: float = 0.5) -> bool:
    """Block until one event fires or timeout. Returns True when woken by a notify."""
    if not events:
        return False
    if any(ev.is_set() for ev in events):
        for ev in events:
            ev.clear()
        return True
    tasks = [asyncio.create_task(ev.wait()) for ev in events]
    notified = False
    try:
        done, _pending = await asyncio.wait(
            tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        notified = any(task.done() and not task.cancelled() for task in done)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
    for ev in events:
        ev.clear()
    return notified
