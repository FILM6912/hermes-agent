from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from threading import Lock
from typing import Any

from app.document_api.core.config import get_settings
from app.document_api.services.job_manager import _capture_watch_loop, _signal_asyncio_event

_PENDING_WATCHERS: dict[str, list[Any]] = defaultdict(list)
_ALL_PENDING_WATCHERS: list[Any] = []
_WATCH_LOCK = Lock()


def subscribe_pending(pending_id: str) -> Any:
    _capture_watch_loop()
    ev = asyncio.Event()
    with _WATCH_LOCK:
        _PENDING_WATCHERS[pending_id.strip()].append(ev)
    return ev


def unsubscribe_pending(pending_id: str, event: Any) -> None:
    with _WATCH_LOCK:
        lst = _PENDING_WATCHERS.get(pending_id.strip())
        if lst and event in lst:
            lst.remove(event)


def subscribe_all_pending() -> Any:
    _capture_watch_loop()
    ev = asyncio.Event()
    with _WATCH_LOCK:
        _ALL_PENDING_WATCHERS.append(ev)
    return ev


def unsubscribe_all_pending(event: Any) -> None:
    with _WATCH_LOCK:
        if event in _ALL_PENDING_WATCHERS:
            _ALL_PENDING_WATCHERS.remove(event)


def _notify_pending_changed(pending_id: str | None = None) -> None:
    events: list[Any] = []
    pid = (pending_id or "").strip()
    with _WATCH_LOCK:
        if pid:
            events.extend(_PENDING_WATCHERS.get(pid, []))
        events.extend(_ALL_PENDING_WATCHERS)
    for ev in events:
        _signal_asyncio_event(ev)


def notify_pending_ingest_changed(pending_id: str | None = None) -> None:
    """Public hook for routes/services to wake ingest-pending WebSocket listeners."""
    _notify_pending_changed(pending_id)


def is_valid_pending_id(pending_id: str) -> bool:
    pid = (pending_id or "").strip()
    if not pid:
        return False
    try:
        uuid.UUID(pid)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _pg_conn():
    import psycopg2

    s = get_settings()
    return psycopg2.connect(
        host=s.pg_host,
        port=s.pg_port,
        dbname=s.pg_database,
        user=s.pg_user,
        password=s.pg_password,
        sslmode=s.pg_sslmode,
    )


_SUMMARY_READY_ENSURED = False


def _ensure_department_id_column() -> None:
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE document_ingest_pending "
                "ADD COLUMN IF NOT EXISTS department_id TEXT"
            )
        conn.commit()


def _ensure_summary_ready_column() -> None:
    global _SUMMARY_READY_ENSURED
    if _SUMMARY_READY_ENSURED:
        return
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE document_ingest_pending "
                "ADD COLUMN IF NOT EXISTS summary_ready BOOLEAN NOT NULL DEFAULT false"
            )
            cur.execute(
                "ALTER TABLE document_ingest_pending "
                "ADD COLUMN IF NOT EXISTS department_id TEXT"
            )
            cur.execute(
                """
                UPDATE document_ingest_pending
                SET summary_ready = true
                WHERE status = 'pending'
                  AND summary_ready = false
                  AND llm_summary IS NOT NULL
                  AND length(trim(llm_summary)) > 0
                """
            )
        conn.commit()
    _SUMMARY_READY_ENSURED = True


def replace_pending_ingest(
    *,
    document_name: str,
    source_filename: str,
    markdown_text: str,
    bucket_url: str | None,
    source_file_storage_path: str | None,
    source_file_url: str | None,
    converter_metadata: dict[str, Any] | None,
    rearrange_notes: list[str],
    rearrange_llm_raw: str,
    chunk_size: int,
    chunk_overlap: int,
    split_text: str,
    on_duplicate: str,
    job_id: str | None,
    created_by: str | None,
    department_id: str | None = None,
) -> str:
    """ลบ pending เดิมของคู่ (document_name, source_filename) แล้วแทรกแถวใหม่ — คืน id เป็น string"""
    doc = (document_name or "").strip()
    src = (source_filename or "").strip()
    meta = converter_metadata if isinstance(converter_metadata, dict) else {}
    notes_json = json.dumps(rearrange_notes or [], ensure_ascii=False)
    meta_json = json.dumps(meta, ensure_ascii=False, default=str)
    pending_id = str(uuid.uuid4())
    dept = (department_id or "").strip().lower() or None
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM document_ingest_pending
                WHERE document_name = %s AND source_filename = %s AND status = 'pending'
                """,
                (doc, src),
            )
            cur.execute(
                """
                INSERT INTO document_ingest_pending (
                    id, document_name, source_filename, markdown_text,
                    bucket_url, source_file_storage_path, source_file_url,
                    converter_metadata, rearrange_notes, rearrange_llm_raw,
                    chunk_size, chunk_overlap, split_text, on_duplicate,
                    status, job_id, created_by, updated_by, department_id, updated_at
                )
                VALUES (
                    %s::uuid, %s, %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s,
                    %s, %s, %s, %s,
                    'pending', %s, %s, %s, %s, NOW()
                )
                """,
                (
                    pending_id,
                    doc,
                    src,
                    markdown_text,
                    bucket_url,
                    source_file_storage_path,
                    source_file_url,
                    meta_json,
                    notes_json,
                    rearrange_llm_raw or "",
                    chunk_size,
                    chunk_overlap,
                    split_text,
                    on_duplicate,
                    job_id,
                    created_by,
                    created_by,
                    dept,
                ),
            )
        conn.commit()
    _notify_pending_changed(pending_id)
    jid = (job_id or "").strip()
    if jid:
        from app.document_api.services.job_manager import notify_job_watchers

        notify_job_watchers(jid)
    return pending_id


def update_pending_llm_summary(pending_id: str, summary: str) -> None:
    pid = (pending_id or "").strip()
    if not pid:
        return
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE document_ingest_pending
                SET llm_summary = %s, updated_at = NOW()
                WHERE id = %s::uuid AND status = 'pending'
                """,
                (summary, pid),
            )
        conn.commit()
    _notify_pending_changed(pid)


def mark_pending_summary_ready(pending_id: str) -> None:
    """Mark LLM summary complete — row becomes visible on /ingest-pending and upload job may leave /jobs."""
    _ensure_summary_ready_column()
    pid = (pending_id or "").strip()
    if not is_valid_pending_id(pid):
        return
    job_id: str | None = None
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE document_ingest_pending
                SET summary_ready = true, updated_at = NOW()
                WHERE id = %s::uuid AND status = 'pending'
                RETURNING job_id
                """,
                (pid,),
            )
            row = cur.fetchone()
        conn.commit()
    if row:
        job_id = str(row[0] or "").strip() or None
    _notify_pending_changed(pid)
    if job_id:
        from app.document_api.services.job_manager import notify_job_watchers

        notify_job_watchers(job_id)


def get_pending_by_id(pending_id: str) -> dict[str, Any] | None:
    pid = (pending_id or "").strip()
    if not is_valid_pending_id(pid):
        return None
    _ensure_summary_ready_column()
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text, document_name, source_filename, markdown_text,
                       bucket_url, source_file_storage_path, source_file_url,
                       converter_metadata, rearrange_notes,                        rearrange_llm_raw,
                       llm_summary,
                       chunk_size, chunk_overlap, split_text, on_duplicate,
                       status, job_id, created_by, updated_by, department_id,
                       created_at::text, updated_at::text, summary_ready
                FROM document_ingest_pending
                WHERE id = %s::uuid
                """,
                (pid,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "document_name": row[1],
        "source_filename": row[2],
        "markdown_text": row[3],
        "bucket_url": row[4],
        "source_file_storage_path": row[5],
        "source_file_url": row[6],
        "converter_metadata": row[7] if isinstance(row[7], dict) else {},
        "rearrange_notes": row[8] if isinstance(row[8], list) else [],
        "rearrange_llm_raw": row[9] or "",
        "llm_summary": row[10] or "",
        "chunk_size": int(row[11] or 1500),
        "chunk_overlap": int(row[12] or 200),
        "split_text": row[13] or "\n\n",
        "on_duplicate": row[14] or "replace",
        "status": row[15],
        "job_id": row[16],
        "created_by": row[17],
        "updated_by": row[18],
        "department_id": row[19],
        "created_at": row[20],
        "updated_at": row[21],
        "summary_ready": bool(row[22]),
    }


def _pending_list_row(r: tuple) -> dict[str, Any]:
    return {
        "id": r[0],
        "document_name": r[1],
        "source_filename": r[2],
        "llm_summary": r[3] or "",
        "status": r[4],
        "job_id": r[5],
        "created_by": r[6],
        "updated_by": r[7],
        "created_at": r[8],
        "updated_at": r[9],
        "markdown_length": int(r[10] or 0),
        "summary_ready": bool(r[11]),
        "department_id": r[12] if len(r) > 12 else None,
    }


def list_pending_for_document(document_name: str, *, admin_ready_only: bool = True) -> list[dict[str, Any]]:
    _ensure_summary_ready_column()
    doc = (document_name or "").strip()
    ready_clause = " AND summary_ready = true" if admin_ready_only else ""
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id::text, document_name, source_filename,
                       llm_summary, status, job_id, created_by, updated_by,
                       created_at::text, updated_at::text,
                       length(markdown_text)::int, summary_ready, department_id
                FROM document_ingest_pending
                WHERE document_name = %s AND status = 'pending'{ready_clause}
                ORDER BY created_at ASC
                """,
                (doc,),
            )
            rows = cur.fetchall()
    return [_pending_list_row(r) for r in rows]


def list_all_pending_ingest(
    *,
    created_by: str | None = None,
    department_id: str | None = None,
    admin_ready_only: bool = True,
) -> list[dict[str, Any]]:
    _ensure_summary_ready_column()
    creator = (created_by or "").strip()
    dept = (department_id or "").strip().lower()
    ready_clause = " AND summary_ready = true" if admin_ready_only else ""
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            if creator:
                cur.execute(
                    f"""
                    SELECT id::text, document_name, source_filename,
                           llm_summary, status, job_id, created_by, updated_by,
                           created_at::text, updated_at::text,
                           length(markdown_text)::int, summary_ready, department_id
                    FROM document_ingest_pending
                    WHERE status = 'pending' AND created_by = %s{ready_clause}
                    ORDER BY created_at ASC
                    """,
                    (creator,),
                )
            elif dept:
                cur.execute(
                    f"""
                    SELECT id::text, document_name, source_filename,
                           llm_summary, status, job_id, created_by, updated_by,
                           created_at::text, updated_at::text,
                           length(markdown_text)::int, summary_ready, department_id
                    FROM document_ingest_pending
                    WHERE status = 'pending' AND department_id = %s{ready_clause}
                    ORDER BY created_at ASC
                    """,
                    (dept,),
                )
            else:
                cur.execute(
                    f"""
                    SELECT id::text, document_name, source_filename,
                           llm_summary, status, job_id, created_by, updated_by,
                           created_at::text, updated_at::text,
                           length(markdown_text)::int, summary_ready, department_id
                    FROM document_ingest_pending
                    WHERE status = 'pending'{ready_clause}
                    ORDER BY created_at ASC
                    """
                )
            rows = cur.fetchall()
    return [_pending_list_row(r) for r in rows]


def lookup_created_by_for_job_id(job_id: str) -> str:
    jid = (job_id or "").strip()
    if not jid:
        return ""
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT created_by
                FROM document_ingest_pending
                WHERE job_id = %s AND status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (jid,),
            )
            row = cur.fetchone()
    if not row or not row[0]:
        return ""
    return str(row[0]).strip()


def list_upload_job_ids_awaiting_admin() -> frozenset[str]:
    """Upload job ids whose pending files are all summarized — hide from /jobs, show on ingest-pending."""
    _ensure_summary_ready_column()
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id
                FROM document_ingest_pending
                WHERE status = 'pending'
                  AND job_id IS NOT NULL
                  AND job_id <> ''
                GROUP BY job_id
                HAVING bool_and(summary_ready)
                """
            )
            rows = cur.fetchall()
    return frozenset(str(r[0]).strip() for r in rows if r and r[0])


def list_pending_ingest_job_ids() -> frozenset[str]:
    """Backward-compatible alias — only jobs fully awaiting admin approval."""
    return list_upload_job_ids_awaiting_admin()


def reject_pending_ingest(pending_id: str, *, updated_by: str | None = None) -> dict[str, Any]:
    """ปฏิเสธ pending ingest — ตั้ง status เป็น rejected (ไม่ commit ลง vector DB)"""
    pid = (pending_id or "").strip()
    if not pid:
        raise LookupError("Pending ingest not found")
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE document_ingest_pending
                SET status = 'rejected', updated_by = %s, updated_at = NOW()
                WHERE id = %s::uuid AND status = 'pending'
                RETURNING id::text, document_name, source_filename
                """,
                (updated_by, pid),
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        existing = get_pending_by_id(pid)
        if not existing:
            raise LookupError("Pending ingest not found")
        raise ValueError(f"Cannot reject: status is {existing.get('status')}")
    _notify_pending_changed(row[0])
    return {
        "message": "Pending ingest rejected",
        "pending_ingest_id": row[0],
        "document_name": row[1],
        "source_filename": row[2],
        "status": "rejected",
    }


def delete_pending_row(pending_id: str) -> None:
    pid = (pending_id or "").strip()
    if not pid:
        return
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM document_ingest_pending WHERE id = %s::uuid",
                (pid,),
            )
        conn.commit()
    _notify_pending_changed(pid)
