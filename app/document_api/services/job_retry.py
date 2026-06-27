from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.document_api.services.job_manager import create_job, get_job, job_has_recorded_error


class JobRetryError(Exception):
    """Retry blocked — message is safe for HTTP 409 detail."""


def can_retry_job(job) -> bool:
    if job.status in {"failed", "cancelled"}:
        return True
    if job.status == "completed" and job_has_recorded_error(job):
        return True
    return False


def retry_job_as_new(source_job_id: str, *, actor_email: str) -> tuple[Any, Callable[[], None]]:
    """
    Clone a retryable job into a new queued job and return a sync runner for background execution.
    Raises LookupError when the source job id is unknown; JobRetryError when retry is not allowed.
    """
    jid = (source_job_id or "").strip()
    source = get_job(jid)
    if not source:
        raise LookupError("job not found")
    if not can_retry_job(source):
        raise JobRetryError(f"Job cannot be retried — current status is {source.status}")

    meta = dict(source.metadata or {})
    kind = source.kind

    if kind == "commit_pending":
        from app.document_api.services.pending_ingest_catalog import get_pending_by_id

        raw_ids = meta.get("pending_ingest_ids")
        if isinstance(raw_ids, list) and raw_ids:
            pending_ids = [str(x).strip() for x in raw_ids if str(x).strip()]
        else:
            pid = (meta.get("pending_ingest_id") or "").strip()
            pending_ids = [pid] if pid else []
        if not pending_ids:
            raise JobRetryError("Missing pending_ingest_id(s) — cannot retry commit")

        meta_files = [str(x).strip() for x in (meta.get("files") or []) if str(x).strip()]
        items: list[tuple[str, str, str]] = []
        for i, pid in enumerate(pending_ids):
            row = get_pending_by_id(pid)
            src = ""
            doc = (meta.get("document_name") or "unknown").strip()
            if row:
                src = (row.get("source_filename") or "").strip()
                doc = (row.get("document_name") or doc).strip() or doc
            if not src and i < len(meta_files):
                src = meta_files[i]
            if not src:
                src = (meta.get("source_filename") or "").strip()
            items.append((pid, src or pid[:8], doc or "unknown"))
        doc_name = (meta.get("document_name") or items[0][2] or "unknown").strip()
        file_names = [src for _, src, _ in items]
        source_actor = str(meta.get("actor_email") or meta.get("actor_username") or actor_email or "").strip()
        new_job = create_job(
            kind=kind,
            total_items=len(items),
            metadata={
                "pending_ingest_id": pending_ids[0],
                "pending_ingest_ids": pending_ids,
                "document_name": doc_name,
                "source_filename": file_names[0] if len(file_names) == 1 else "",
                "files": file_names,
                "progress_profile": "commit_pending",
                "retried_from": jid,
                "actor_email": source_actor or actor_email,
            },
        )

        def _run() -> None:
            from app.document_api.api.v1.routes.documents_dynamic import _run_commit_pending_batch_job

            if get_job(new_job.id) and get_job(new_job.id).status == "cancelled":
                return
            _run_commit_pending_batch_job(new_job.id, items, actor_email)

        return new_job, _run

    if kind == "transcript_audio":
        folder = (meta.get("document_name") or "").strip()
        tname = (meta.get("transcript_name") or meta.get("name") or "").strip()
        ids = [str(x) for x in (meta.get("transcript_ids") or []) if str(x).strip()]
        retry = dict(meta.get("retry") or {})
        phase = (meta.get("phase") or retry.get("phase") or "process").strip()
        if phase != "process":
            raise JobRetryError("Only transcript process jobs can be retried — re-upload audio for a new job")
        if not folder or not tname:
            raise JobRetryError("Missing document_name or transcript name in job metadata")
        if not ids:
            raise JobRetryError("Missing transcript_ids — cannot retry")

        new_job = create_job(
            kind=kind,
            total_items=len(ids),
            metadata={
                "document_name": folder,
                "name": tname,
                "transcript_name": tname,
                "transcript_ids": ids,
                "phase": "process",
                "retry": {**retry, "force_reprocess": True},
                "retried_from": jid,
                "actor_email": str(meta.get("actor_email") or meta.get("actor_username") or actor_email or "").strip()
                or actor_email,
            },
        )
        asr_prompt = str(retry.get("asr_prompt") or meta.get("asr_prompt") or "")

        def _run() -> None:
            import asyncio

            from app.document_api.api.v1.routes.transcript_audio import _guarded_run_transcript_audio_process_job

            if get_job(new_job.id) and get_job(new_job.id).status == "cancelled":
                return
            asyncio.run(
                _guarded_run_transcript_audio_process_job(
                    new_job.id,
                    folder,
                    tname,
                    ids,
                    asr_prompt=asr_prompt,
                    force_reprocess=True,
                    updated_by=actor_email,
                )
            )

        return new_job, _run

    if kind == "document_ingest":
        folder = (meta.get("document_name") or "").strip()
        file_names = [str(x) for x in (meta.get("files") or []) if str(x).strip()]
        retry = dict(meta.get("retry") or {})
        if not folder or not file_names:
            raise JobRetryError("Missing document_name or files in job metadata")

        from app.document_api.services.document_pipeline import download_ingest_source_bytes

        payload_files: list[tuple[str, bytes]] = []
        for fn in file_names:
            try:
                payload_files.append((fn, download_ingest_source_bytes(folder, fn)))
            except Exception as exc:
                raise JobRetryError(
                    f"Cannot download {fn} from storage — upload the document again ({exc})"
                ) from exc

        source_actor = str(meta.get("actor_email") or meta.get("actor_username") or actor_email or "").strip()
        new_job = create_job(
            kind=kind,
            total_items=len(payload_files),
            metadata={
                "document_name": folder,
                "files": file_names,
                "retry": retry,
                "retried_from": jid,
                "progress": meta.get("progress") or {},
                "actor_email": source_actor or actor_email,
            },
        )

        def _run() -> None:
            import asyncio

            from app.document_api.api.v1.routes.documents_dynamic import _run_document_ingest_job

            if get_job(new_job.id) and get_job(new_job.id).status == "cancelled":
                return
            asyncio.run(
                _run_document_ingest_job(
                    new_job.id,
                    folder,
                    payload_files,
                    enable_supabase=bool(retry.get("enable_supabase", True)),
                    on_duplicate=str(retry.get("on_duplicate") or "replace"),
                    include_metadata=bool(retry.get("include_metadata", True)),
                    chunk_size=int(retry.get("chunk_size") or 1500),
                    stream_queue=None,
                    actor_username=actor_email,
                )
            )

        return new_job, _run

    raise JobRetryError(f"Unsupported job kind for retry: {kind}")
