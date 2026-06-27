"""เส้นทาง /jobs — แยก router นี้ไว้ก่อน documents_dynamic เพื่อไม่ให้ถูกแย่งโดย GET /{document_name}/{file_name}"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, WebSocket, WebSocketDisconnect

from app.document_api.api.v1.routes.job_common import (
    compute_queue_positions,
    filter_jobs_excluding_ingest_pending,
    job_to_status_response as _to_job_status_response,
    wait_any_events,
)
from app.document_api.api.v1.param_deps import get_job_errors_list_query, get_job_list_query
from app.document_api.api.v1.schemas import JobAcceptedResponse, JobErrorsListQuery, JobListQuery, JobStatusResponse
from app.document_api.services.job_manager import (
    cancel_job,
    clear_job_error,
    get_job,
    list_error_jobs,
    list_jobs,
    subscribe_all_jobs,
    subscribe_job,
    unsubscribe_all_jobs,
    unsubscribe_job,
)
from app.document_api.services.job_retry import JobRetryError, retry_job_as_new
from app.document_api.services.pending_ingest_catalog import subscribe_all_pending, unsubscribe_all_pending

http_router = APIRouter()
ws_router = APIRouter()


def _active_jobs_for_dashboard() -> list:
    return filter_jobs_excluding_ingest_pending(
        list_jobs(statuses={"queued", "running", "failed"})
    )


@http_router.get("/jobs/errors", response_model=list[JobStatusResponse], tags=["job"])
async def list_error_job_history(
    params: Annotated[JobErrorsListQuery, Depends(get_job_errors_list_query)],
):
    """
    ประวัติ job ที่ล้มเหลวหรือมี error ใน metadata (เช่น ``llm_summary_error``) — เก็บใน memory ต่อ process เท่านั้น.
    """
    pending = list_jobs(statuses={"queued", "running"})
    pos_map, waiting = compute_queue_positions(pending)
    jobs = list_error_jobs(limit=params.limit, kind=params.kind)

    def _one(j):
        qp = pos_map.get(j.id) if j.status == "queued" else None
        return _to_job_status_response(j, queue_position=qp, queue_waiting_total=waiting)

    return [_one(job) for job in jobs]


@http_router.post("/jobs/{job_id}/cancel", response_model=JobStatusResponse, tags=["job"])
async def cancel_document_job(
    job_id: str,
):
    """Cancel a queued or running job immediately (status becomes ``cancelled``)."""
    jid = job_id.strip()
    job = cancel_job(jid)
    if not job:
        existing = get_job(jid)
        if not existing:
            raise HTTPException(status_code=404, detail="job not found")
        raise HTTPException(
            status_code=409,
            detail=f"Job cannot be cancelled — current status is {existing.status}",
        )
    pending = list_jobs(statuses={"queued", "running"})
    pos_map, waiting = compute_queue_positions(pending)
    return _to_job_status_response(job, queue_position=None, queue_waiting_total=waiting)


@http_router.post("/jobs/{job_id}/clear-error", response_model=JobStatusResponse, tags=["job"])
async def clear_document_job_error(
    job_id: str,
):
    """Dismiss error state on a failed or soft-errored job (clears error metadata; failed → cancelled)."""
    jid = job_id.strip()
    job = clear_job_error(jid)
    if not job:
        existing = get_job(jid)
        if not existing:
            raise HTTPException(status_code=404, detail="job not found")
        if existing.status in {"queued", "running"}:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot clear error while job is {existing.status}",
            )
        raise HTTPException(status_code=409, detail="Job has no error to clear")
    pending = list_jobs(statuses={"queued", "running"})
    pos_map, waiting = compute_queue_positions(pending)
    return _to_job_status_response(job, queue_position=None, queue_waiting_total=waiting)


@http_router.post("/jobs/{job_id}/retry", response_model=JobAcceptedResponse, tags=["job"])
async def retry_document_job(
    job_id: str,
    background_tasks: BackgroundTasks,
):
    """Re-run a failed/cancelled job (or completed with errors) as a new background job."""
    jid = job_id.strip()
    try:
        new_job, runner = retry_job_as_new(jid, actor_email=None)
    except LookupError:
        raise HTTPException(status_code=404, detail="job not found") from None
    except JobRetryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    background_tasks.add_task(runner)
    meta = new_job.metadata or {}
    doc_name = str(meta.get("document_name") or "")
    tname = str(meta.get("name") or meta.get("transcript_name") or "")
    return JobAcceptedResponse(
        job_id=new_job.id,
        status=new_job.status,
        message=f"Retry job accepted (from {jid[:8]}…)",
        status_url=f"/api/v1/jobs/{new_job.id}",
        document_name=doc_name,
        name=tname,
        total_files=new_job.total_items,
        hint="Poll status_url for running/completed/cancelled/failed.",
    )


@http_router.get("/jobs/{job_id}", response_model=JobStatusResponse, tags=["job"])
async def get_document_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    pending = list_jobs(statuses={"queued", "running"})
    pos_map, waiting = compute_queue_positions(pending)
    qp = pos_map.get(job_id) if job.status == "queued" else None
    return _to_job_status_response(job, queue_position=qp, queue_waiting_total=waiting)


@http_router.get("/jobs", response_model=list[JobStatusResponse], tags=["job"])
async def list_document_jobs(
    params: Annotated[JobListQuery, Depends(get_job_list_query)],
):
    only_pending = params.only_pending
    include_completed = params.include_completed
    include_failed = params.include_failed
    limit = params.limit
    if include_completed or include_failed:
        jobs = list_jobs()
        if not include_completed:
            jobs = [j for j in jobs if j.status not in ("completed", "cancelled")]
        if not include_failed:
            jobs = [j for j in jobs if j.status != "failed"]
    else:
        jobs = _active_jobs_for_dashboard()
    pending = _active_jobs_for_dashboard()
    pos_map, waiting = compute_queue_positions(pending)
    jobs_sorted = sorted(jobs, key=lambda item: item.created_at, reverse=True)[:limit]

    def _one(j):
        qp = pos_map.get(j.id) if j.status == "queued" else None
        return _to_job_status_response(j, queue_position=qp, queue_waiting_total=waiting)

    return [_one(job) for job in jobs_sorted]


def _jobs_ws_signature(jobs_sorted: list) -> tuple[tuple[str, int, str, str, str, str, str, int, int], ...]:
    """Fingerprint status + string progress labels so clients receive token stream updates."""
    sig: list[tuple[str, int, str, str, str, str, str, int, int]] = []
    for job in jobs_sorted:
        prog = (job.metadata or {}).get("progress") or {}
        meta = job.metadata or {}
        summary = prog.get("summary") if isinstance(prog.get("summary"), str) else ""
        llm_chunks = prog.get("llm_chunks") if isinstance(prog.get("llm_chunks"), str) else ""
        export_images = prog.get("export_images") if isinstance(prog.get("export_images"), str) else ""
        active_n = len(meta.get("active_slots") or meta.get("active_items") or [])
        pending_n = len(meta.get("pending_slots") or meta.get("pending_items") or [])
        sig.append(
            (
                job.id,
                int(getattr(job, "revision", 0)),
                job.status,
                summary,
                llm_chunks,
                export_images,
                str(job.detail or ""),
                active_n,
                pending_n,
            )
        )
    return tuple(sig)


async def _wait_job_notify(event: asyncio.Event, *, timeout: float = 1.0) -> None:
    if event.is_set():
        event.clear()
        return
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    event.clear()


def _jobs_ws_items(
    jobs_sorted: list,
    *,
    pos_map: dict[str, int],
    waiting: int,
) -> list[dict]:
    return [
        _to_job_status_response(
            j,
            queue_position=pos_map.get(j.id) if j.status == "queued" else None,
            queue_waiting_total=waiting,
        ).model_dump(mode="json")
        for j in jobs_sorted
    ]


async def _push_jobs_ws_snapshot(
    websocket: WebSocket,
    *,
    jobs_sorted: list,
    pos_map: dict[str, int],
    waiting: int,
    last_signature: tuple[tuple[str, int, str, str, str, str, str, int, int], ...] | None,
    last_ids: set[str],
) -> tuple[tuple[tuple[str, int, str, str, str, str, str], ...], set[str]]:
    sig = _jobs_ws_signature(jobs_sorted)
    current_ids = {j.id for j in jobs_sorted}
    removed_ids = sorted(last_ids - current_ids)
    if sig != last_signature or removed_ids:
        payload: dict = {
            "type": "jobs",
            "items": _jobs_ws_items(jobs_sorted, pos_map=pos_map, waiting=waiting),
        }
        if removed_ids:
            payload["removed_job_ids"] = removed_ids
        await websocket.send_json(payload)
        return sig, current_ids
    return last_signature or sig, last_ids


@ws_router.websocket("/jobs/ws")
@ws_router.websocket("/jobs")
async def jobs_ws(
    websocket: WebSocket,
):
    await websocket.accept()
    last_signature: tuple[tuple[str, int, str, str, str, str, str, int, int], ...] | None = None
    last_ids: set[str] = set()
    notify_jobs = subscribe_all_jobs()
    notify_pending = subscribe_all_pending()
    try:
        while True:
            jobs = _active_jobs_for_dashboard()
            pos_map, waiting = compute_queue_positions(jobs)
            jobs_sorted = sorted(jobs, key=lambda item: item.created_at, reverse=True)
            last_signature, last_ids = await _push_jobs_ws_snapshot(
                websocket,
                jobs_sorted=jobs_sorted,
                pos_map=pos_map,
                waiting=waiting,
                last_signature=last_signature,
                last_ids=last_ids,
            )
            await wait_any_events(notify_jobs, notify_pending, timeout=0.5 if jobs_sorted else 1.0)
    except WebSocketDisconnect:
        return
    finally:
        unsubscribe_all_jobs(notify_jobs)
        unsubscribe_all_pending(notify_pending)


@ws_router.websocket("/jobs/{job_id}/ws")
@ws_router.websocket("/jobs/{job_id}")
async def job_detail_ws(
    websocket: WebSocket,
    job_id: str,
):
    await websocket.accept()
    last_revision: int | None = None
    last_summary = ""
    last_llm_chunks = ""
    last_detail = ""
    notify = subscribe_job(job_id)
    try:
        while True:
            job = get_job(job_id)
            if not job:
                await websocket.send_json({"type": "job", "job_id": job_id, "error": "job not found"})
                last_revision = None
                await _wait_job_notify(notify, timeout=0.5)
                continue
            prog = (job.metadata or {}).get("progress") or {}
            summary = prog.get("summary") if isinstance(prog.get("summary"), str) else ""
            llm_chunks = prog.get("llm_chunks") if isinstance(prog.get("llm_chunks"), str) else ""
            rev = int(getattr(job, "revision", 0))
            terminal = job.status in ("completed", "cancelled", "failed")
            detail = str(job.detail or "")
            if (
                rev != last_revision
                or summary != last_summary
                or llm_chunks != last_llm_chunks
                or detail != last_detail
            ):
                pending = list_jobs(statuses={"queued", "running"})
                pos_map, waiting = compute_queue_positions(pending)
                qp = pos_map.get(job_id) if job.status == "queued" else None
                payload = {
                    "type": "job",
                    "item": _to_job_status_response(
                        job, queue_position=qp, queue_waiting_total=waiting
                    ).model_dump(mode="json"),
                }
                await websocket.send_json(payload)
                last_revision = rev
                last_summary = summary
                last_llm_chunks = llm_chunks
                last_detail = detail
            if terminal:
                await websocket.send_json({"type": "job_removed", "job_id": job_id, "status": job.status})
                return
            await _wait_job_notify(notify, timeout=0.5)
    except WebSocketDisconnect:
        return
    finally:
        unsubscribe_job(job_id, notify)
