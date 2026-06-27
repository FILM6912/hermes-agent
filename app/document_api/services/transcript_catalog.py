from __future__ import annotations

import json
import mimetypes
from typing import Any

from app.document_api.core.config import get_settings
from app.document_api.core.storage_urls import public_storage_object_url
from app.document_api.services.document_pipeline import _ensure_bucket, _safe_storage_name


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


def _sb():
    from supabase.client import create_client

    s = get_settings()
    return create_client(s.supabase_url, supabase_key=s.supabase_service_key)


def transcript_upload_audio_file(
    *,
    document_name: str,
    transcript_name: str,
    file_name: str,
    file_bytes: bytes,
    content: str = "",
    enable_supabase: bool = True,
    created_by: str | None = None,
    updated_by: str | None = None,
) -> dict[str, Any]:
    """
    อัปโหลดไฟล์เสียงไป bucket transcript แล้ว INSERT แถวในตาราง transcript.
    คอลัมน์ files เป็น JSON array เช่น [{"path":"...","url":"..."}].
    object ใน storage: ``{document_safe}/{transcript_safe}/{file_safe}``.
    """
    folder = (document_name or "").strip()
    if not folder:
        raise ValueError("document_name is required")
    tn = (transcript_name or "").strip()
    if not tn:
        raise ValueError("transcript_name (name) is required")
    base_name = (file_name or "").strip()
    if not base_name:
        raise ValueError("file name is required")

    settings = get_settings()
    text = content or ""
    by = updated_by or created_by

    files_payload: list[dict[str, str]] = []
    if enable_supabase and (settings.supabase_url or "").strip() and (settings.supabase_service_key or "").strip():
        root = _safe_storage_name(folder)
        seg = _safe_storage_name(tn)
        object_path = f"{root}/{seg}/{_safe_storage_name(base_name)}"
        mime = mimetypes.guess_type(base_name)[0] or "application/octet-stream"
        client = _sb()
        bucket_name = settings.supabase_transcript_bucket
        _ensure_bucket(client, bucket_name)
        client.storage.from_(bucket_name).upload(
            path=object_path,
            file=file_bytes,
            file_options={"content-type": mime, "upsert": "true"},
        )
        pub = public_storage_object_url(bucket_name, object_path, settings)
        files_payload.append({"path": object_path, "url": pub})

    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO transcript (document_name, transcript_name, content, files, created_by, updated_by)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                RETURNING id::text
                """,
                (folder, tn, text, json.dumps(files_payload, ensure_ascii=False), created_by, by),
            )
            row = cur.fetchone()
        conn.commit()

    tid = row[0] if row else None
    return {
        "transcript_id": tid,
        "document_name": folder,
        "transcript_name": tn,
        "source_filename": base_name,
        "files": files_payload,
        "content_len": len(text),
        "storage_enabled": bool(files_payload),
    }


def _source_filename_from_files(files: Any) -> str | None:
    if not isinstance(files, list) or not files:
        return None
    first = files[0]
    if not isinstance(first, dict):
        return None
    p = first.get("path") or ""
    if not p:
        return None
    return str(p).rsplit("/", 1)[-1]


def _serialize_transcript_row(row: dict[str, Any]) -> dict[str, Any]:
    files = row.get("files")
    if isinstance(files, str):
        try:
            files = json.loads(files)
        except (json.JSONDecodeError, TypeError):
            files = []
    if not isinstance(files, list):
        files = []
    segments = row.get("segments")
    if isinstance(segments, str):
        try:
            segments = json.loads(segments)
        except (json.JSONDecodeError, TypeError):
            segments = []
    if not isinstance(segments, list):
        segments = []
    cid = row.get("id")
    ca = row.get("created_at")
    ua = row.get("updated_at")
    return {
        "id": str(cid) if cid is not None else "",
        "document_name": str(row.get("document_name") or ""),
        "transcript_name": str(row.get("transcript_name") or ""),
        "content": row.get("content"),
        "files": files,
        "segments": segments,
        "audio_llm_summary": row.get("audio_llm_summary"),
        "audio_llm_report": row.get("audio_llm_report"),
        "created_by": row.get("created_by"),
        "updated_by": row.get("updated_by"),
        "created_at": ca.isoformat() if hasattr(ca, "isoformat") else str(ca or ""),
        "updated_at": ua.isoformat() if hasattr(ua, "isoformat") else str(ua or ""),
        "source_filename": _source_filename_from_files(files),
    }


def list_audio_transcripts(
    document_name: str,
    transcript_name: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    folder = (document_name or "").strip()
    tn = (transcript_name or "").strip()
    if not folder or not tn:
        return []
    lim = max(1, min(int(limit or 100), 500))
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, document_name, transcript_name, content, files, segments, audio_llm_summary,
                       audio_llm_report, created_by, updated_by, created_at, updated_at
                FROM transcript
                WHERE document_name = %s AND transcript_name = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (folder, tn, lim),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, t)) for t in cur.fetchall()]
    return [_serialize_transcript_row(r) for r in rows]


def list_transcript_audio_groups(
    *,
    scope: Any | None = None,
) -> list[dict[str, Any]]:
    """คู่ (document_name, transcript_name) ทั้งหมดที่มีแถวในตาราง transcript พร้อมจำนวนแถวและแถวที่รอถอดเสียง"""
    from app.document_api.rag_department_scope import (
        RagDepartmentScope,
        transcript_row_visible,
    )

    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT document_name,
                       transcript_name,
                       COUNT(*)::int AS row_count,
                       COALESCE(
                           array_agg(id::text ORDER BY created_at DESC) FILTER (WHERE id IS NOT NULL),
                           ARRAY[]::text[]
                       ) AS transcript_ids,
                       COALESCE(
                           array_agg(created_by ORDER BY created_at DESC)
                               FILTER (WHERE created_by IS NOT NULL),
                           ARRAY[]::text[]
                       ) AS created_bys,
                       COUNT(*) FILTER (
                         WHERE COALESCE(TRIM(BOTH FROM content), '') = ''
                           AND jsonb_typeof(COALESCE(files, '[]'::jsonb)) = 'array'
                           AND jsonb_array_length(COALESCE(files, '[]'::jsonb)) > 0
                       )::int AS pending_process_count,
                       COALESCE((array_agg(content ORDER BY created_at DESC))[1], '') AS newest_content
                FROM transcript
                GROUP BY document_name, transcript_name
                ORDER BY document_name ASC, transcript_name ASC
                """
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, t)) for t in cur.fetchall()]

    if scope is None or not isinstance(scope, RagDepartmentScope) or scope.unrestricted:
        return rows

    visible: list[dict[str, Any]] = []
    for row in rows:
        created_bys = row.get("created_bys") or []
        if not isinstance(created_bys, list):
            created_bys = [created_bys]
        if any(transcript_row_visible(scope, created_by=cb) for cb in created_bys if cb):
            clean = dict(row)
            clean.pop("created_bys", None)
            visible.append(clean)
    return visible


def update_transcript_content(
    transcript_id: str,
    content: str,
    *,
    segments: list[dict[str, Any]] | None = None,
    updated_by: str | None = None,
) -> bool:
    if not (transcript_id or "").strip():
        return False
    tid = transcript_id.strip()
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            if segments is not None:
                cur.execute(
                    """
                    UPDATE transcript
                    SET content = %s,
                        segments = %s::jsonb,
                        updated_by = COALESCE(%s, updated_by),
                        updated_at = NOW()
                    WHERE id = %s::uuid
                    """,
                    (content, json.dumps(segments, ensure_ascii=False), updated_by, tid),
                )
            else:
                cur.execute(
                    """
                    UPDATE transcript
                    SET content = %s,
                        updated_by = COALESCE(%s, updated_by),
                        updated_at = NOW()
                    WHERE id = %s::uuid
                    """,
                    (content, updated_by, tid),
                )
            ok = cur.rowcount > 0
        conn.commit()
    return ok


def get_transcript_row_scoped(
    transcript_id: str,
    *,
    document_name: str,
    transcript_name: str,
) -> dict[str, Any] | None:
    """ดึงแถว transcript ตาม id โดยตรวจสอบ document_name + transcript_name (กันข้ามโฟลเดอร์)"""
    tid = (transcript_id or "").strip()
    folder = (document_name or "").strip()
    tn = (transcript_name or "").strip()
    if not tid or not folder or not tn:
        return None
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, document_name, transcript_name, content, files, segments, audio_llm_summary,
                       audio_llm_report, created_by, updated_by, created_at, updated_at
                FROM transcript
                WHERE id = %s::uuid AND document_name = %s AND transcript_name = %s
                """,
                (tid, folder, tn),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return _serialize_transcript_row(dict(zip(cols, row)))


def _object_path_from_transcript_files(files: list[Any]) -> tuple[str, str]:
    """
    ตรวจ ``files`` จากแถว transcript ว่ามี path ใน storage — คืน (object_path, ชื่อไฟล์ suffix).
    ยก ValueError ถ้าโครงสร้างไม่พร้อมดาวน์โหลด
    """
    if not isinstance(files, list) or not files:
        raise ValueError("Transcript row has no file in storage")
    first = files[0]
    if not isinstance(first, dict):
        raise ValueError("Invalid files JSON shape")
    path = (first.get("path") or "").strip()
    if not path:
        raise ValueError(
            "Missing storage object path on uploaded file — ensure Supabase upload succeeded"
        )
    base_name = path.rsplit("/", 1)[-1] or "audio"
    return path, base_name


def validate_transcript_ids_for_process(
    transcript_ids: list[str],
    *,
    document_name: str,
    transcript_name: str,
    force_reprocess: bool,
    scope: Any | None = None,
) -> list[dict[str, str]]:
    """
    ตรวจก่อน queue process: คืน ``[]`` ถ้าทุก id ผ่าน;
    ไม่งั้นรายการ ``{"transcript_id", "detail"}`` (อาจมีหลายแถว)
    """
    settings = get_settings()
    folder = (document_name or "").strip()
    tn = (transcript_name or "").strip()
    from app.document_api.rag_department_scope import RagDepartmentScope, transcript_row_visible

    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in transcript_ids:
        tid = (raw or "").strip()
        if not tid:
            errors.append({"transcript_id": str(raw), "detail": "transcript_id is empty after trim"})
            continue
        if tid in seen:
            continue
        seen.add(tid)
        row = get_transcript_row_scoped(tid, document_name=folder, transcript_name=tn)
        if not row:
            errors.append(
                {
                    "transcript_id": tid,
                    "detail": "Row not found or document_name / transcript_name does not match this row",
                }
            )
            continue
        if scope is not None and isinstance(scope, RagDepartmentScope) and not scope.unrestricted:
            if not transcript_row_visible(scope, created_by=row.get("created_by")):
                errors.append(
                    {
                        "transcript_id": tid,
                        "detail": "Department access denied for this transcript row",
                    }
                )
                continue
        content = (row.get("content") or "").strip()
        if not force_reprocess and content:
            errors.append(
                {
                    "transcript_id": tid,
                    "detail": "Row already has transcript content — send force_reprocess=true to re-run",
                }
            )
            continue
        want_asr = force_reprocess or not content
        files = row.get("files") or []
        if not isinstance(files, list):
            files = []
        if want_asr:
            if not settings.asr_enabled:
                errors.append(
                    {
                        "transcript_id": tid,
                        "detail": "ASR required but ASR_ENABLED=false — set in .env and restart",
                    }
                )
                continue
            try:
                _object_path_from_transcript_files(files)
            except ValueError as e:
                errors.append({"transcript_id": tid, "detail": str(e)})
                continue
            if not (settings.supabase_url or "").strip() or not (settings.supabase_service_key or "").strip():
                errors.append(
                    {
                        "transcript_id": tid,
                        "detail": "Supabase download required but supabase_url or service key is not configured",
                    }
                )
                continue
    return errors


def download_transcript_audio_bytes(files: list[Any]) -> tuple[bytes, str]:
    """
    ดาวน์โหลดไฟล์เสียงชิ้นแรกจาก Supabase transcript bucket.
    คืน (bytes, ชื่อไฟล์สำหรับ suffix) — ยก ValueError ถ้าไม่มี path หรือดาวน์โหลดไม่ได้
    """
    path, base_name = _object_path_from_transcript_files(files)
    settings = get_settings()
    if not (settings.supabase_url or "").strip() or not (settings.supabase_service_key or "").strip():
        raise ValueError("Supabase is not configured — cannot download audio for transcription")
    client = _sb()
    bucket_name = settings.supabase_transcript_bucket
    try:
        data = client.storage.from_(bucket_name).download(path)
    except Exception as e:
        raise ValueError(f"Storage download failed: {e}") from e
    if not data:
        raise ValueError("Storage download returned empty payload")
    return bytes(data), base_name


def delete_transcript_row(
    transcript_id: str,
    *,
    document_name: str,
    transcript_name: str,
) -> bool:
    """ลบแถว transcript และไฟล์เสียงชิ้นแรกใน storage (ถ้ามี)"""
    tid = (transcript_id or "").strip()
    folder = (document_name or "").strip()
    tn = (transcript_name or "").strip()
    if not tid or not folder or not tn:
        return False
    row = get_transcript_row_scoped(tid, document_name=folder, transcript_name=tn)
    if not row:
        return False
    files = row.get("files") or []
    settings = get_settings()
    if (
        isinstance(files, list)
        and files
        and (settings.supabase_url or "").strip()
        and (settings.supabase_service_key or "").strip()
    ):
        try:
            path, _ = _object_path_from_transcript_files(files)
            client = _sb()
            client.storage.from_(settings.supabase_transcript_bucket).remove([path])
        except Exception:
            pass
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM transcript
                WHERE id = %s::uuid AND document_name = %s AND transcript_name = %s
                """,
                (tid, folder, tn),
            )
            ok = cur.rowcount > 0
        conn.commit()
    return ok


def update_transcript_audio_llm_summary(
    transcript_id: str,
    audio_llm_summary: str,
    *,
    updated_by: str | None = None,
) -> bool:
    if not (transcript_id or "").strip():
        return False
    tid = transcript_id.strip()
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE transcript
                SET audio_llm_summary = %s,
                    updated_by = COALESCE(%s, updated_by),
                    updated_at = NOW()
                WHERE id = %s::uuid
                """,
                (audio_llm_summary, updated_by, tid),
            )
            ok = cur.rowcount > 0
        conn.commit()
    return ok


def update_transcript_audio_llm_report(
    transcript_id: str,
    audio_llm_report: str,
    *,
    updated_by: str | None = None,
) -> bool:
    if not (transcript_id or "").strip():
        return False
    tid = transcript_id.strip()
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE transcript
                SET audio_llm_report = %s,
                    updated_by = COALESCE(%s, updated_by),
                    updated_at = NOW()
                WHERE id = %s::uuid
                """,
                (audio_llm_report, updated_by, tid),
            )
            ok = cur.rowcount > 0
        conn.commit()
    return ok
