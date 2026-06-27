from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

try:
    import asyncio
except ImportError:  # pragma: no cover
    asyncio = None  # type: ignore[assignment]

from collections import defaultdict

_JOB_WATCHERS: dict[str, list[Any]] = defaultdict(list)
_ALL_JOBS_WATCHERS: list[Any] = []
_WATCH_LOOP: Any = None


def _capture_watch_loop() -> None:
    global _WATCH_LOOP
    if asyncio is None:
        return
    try:
        _WATCH_LOOP = asyncio.get_running_loop()
    except RuntimeError:
        pass


def _signal_asyncio_event(event: Any) -> None:
    """Thread-safe wake for asyncio.Event watchers (jobs may update from worker threads)."""
    if asyncio is None:
        return
    loop = _WATCH_LOOP
    if loop is None:
        try:
            event.set()
        except Exception:
            pass
        return
    try:
        if asyncio.get_running_loop() is loop:
            event.set()
            return
    except RuntimeError:
        pass
    try:
        loop.call_soon_threadsafe(event.set)
    except Exception:
        try:
            event.set()
        except Exception:
            pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slot_id_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item or "").strip() for item in raw if str(item or "").strip()]


def _slot_labels_dict(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        slot_id = str(key or "").strip()
        label = str(value or "").strip()
        if slot_id and label:
            out[slot_id] = label
    return out


def _clear_parallel_file_activity(meta: dict[str, Any]) -> None:
    for key in (
        "active_items",
        "pending_items",
        "completed_files",
        "active_slots",
        "pending_slots",
        "completed_slots",
        "slot_labels",
        "file_activity",
    ):
        meta.pop(key, None)


@dataclass
class JobRecord:
    id: str
    kind: str
    status: str
    total_items: int
    completed_items: int = 0
    current_item: str | None = None
    detail: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=_utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    revision: int = 0


def _bump_revision(job: JobRecord) -> None:
    job.revision += 1


def _notify_after_change(job_id: str | None) -> None:
    if job_id:
        _notify_job_changed(job_id)


def notify_job_watchers(job_id: str | None = None) -> None:
    """Public hook to wake /jobs WebSocket listeners without mutating job state."""
    _notify_after_change(job_id)


def subscribe_job(job_id: str) -> Any:
    """Return an asyncio.Event notified when this job revision/metadata changes."""
    if asyncio is None:
        raise RuntimeError("asyncio is required for job subscriptions")
    _capture_watch_loop()
    ev = asyncio.Event()
    with _LOCK:
        _JOB_WATCHERS[job_id].append(ev)
    return ev


def unsubscribe_job(job_id: str, event: Any) -> None:
    with _LOCK:
        lst = _JOB_WATCHERS.get(job_id)
        if lst and event in lst:
            lst.remove(event)


def subscribe_all_jobs() -> Any:
    if asyncio is None:
        raise RuntimeError("asyncio is required for job subscriptions")
    _capture_watch_loop()
    ev = asyncio.Event()
    with _LOCK:
        _ALL_JOBS_WATCHERS.append(ev)
    return ev


def unsubscribe_all_jobs(event: Any) -> None:
    with _LOCK:
        if event in _ALL_JOBS_WATCHERS:
            _ALL_JOBS_WATCHERS.remove(event)


def _notify_job_changed(job_id: str) -> None:
    events: list[Any] = []
    with _LOCK:
        events.extend(_JOB_WATCHERS.get(job_id, []))
        events.extend(_ALL_JOBS_WATCHERS)
    for ev in events:
        _signal_asyncio_event(ev)


_JOBS: dict[str, JobRecord] = {}
_JOB_TASKS: dict[str, Any] = {}
_LOCK = Lock()


def create_job(*, kind: str, total_items: int, metadata: dict[str, Any] | None = None) -> JobRecord:
    job = JobRecord(
        id=str(uuid4()),
        kind=kind,
        status="queued",
        total_items=max(total_items, 0),
        metadata=metadata or {},
    )
    with _LOCK:
        _JOBS[job.id] = job
    return job


def start_job(job_id: str, detail: str | None = None) -> JobRecord | None:
    out: JobRecord | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        job.status = "running"
        job.started_at = job.started_at or _utc_now()
        job.detail = detail
        _bump_revision(job)
        out = job
    _notify_after_change(out.id if out else None)
    return out


def advance_job(
    job_id: str,
    *,
    completed_items: int | None = None,
    current_item: str | None = None,
    detail: str | None = None,
) -> JobRecord | None:
    out: JobRecord | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if completed_items is not None:
            job.completed_items = max(0, min(completed_items, job.total_items))
        if current_item is not None:
            job.current_item = current_item
        if detail is not None:
            job.detail = detail
        _bump_revision(job)
        out = job
    _notify_after_change(out.id if out else None)
    return out


def complete_job(job_id: str, detail: str | None = None) -> JobRecord | None:
    out: JobRecord | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        job.status = "completed"
        job.completed_items = job.total_items
        job.current_item = None
        job.detail = detail or "job completed"
        job.finished_at = _utc_now()
        meta = dict(job.metadata or {})
        _clear_parallel_file_activity(meta)
        job.metadata = meta
        _bump_revision(job)
        out = job
    _notify_after_change(out.id if out else None)
    return out


def fail_job(job_id: str, error: str, detail: str | None = None) -> JobRecord | None:
    out: JobRecord | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        job.status = "failed"
        job.error = error
        job.detail = detail or "job failed"
        job.finished_at = _utc_now()
        meta = dict(job.metadata or {})
        _clear_parallel_file_activity(meta)
        job.metadata = meta
        _bump_revision(job)
        out = job
    _notify_after_change(out.id if out else None)
    return out


def cancel_job(job_id: str, *, detail: str | None = None) -> JobRecord | None:
    """Mark job cancelled immediately. Returns None if missing or not queued/running."""
    task_to_cancel = None
    notify_id: str | None = None
    out: JobRecord | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if job.status not in {"queued", "running"}:
            return None
        job.status = "cancelled"
        job.current_item = None
        job.detail = detail or "job cancelled"
        job.finished_at = _utc_now()
        meta = dict(job.metadata or {})
        _clear_parallel_file_activity(meta)
        job.metadata = meta
        _bump_revision(job)
        notify_id = job.id
        out = job
        task_to_cancel = _JOB_TASKS.pop(job_id, None)
    _notify_after_change(notify_id)
    if task_to_cancel is not None and asyncio is not None:
        try:
            if hasattr(task_to_cancel, "done") and not task_to_cancel.done():
                task_to_cancel.cancel()
        except Exception:
            pass
    return out


def register_job_task(job_id: str, task: Any) -> None:
    """Register asyncio Task (or compatible) so cancel can interrupt promptly."""
    with _LOCK:
        _JOB_TASKS[job_id] = task

    def _cleanup(_t: Any) -> None:
        with _LOCK:
            if _JOB_TASKS.get(job_id) is _t:
                _JOB_TASKS.pop(job_id, None)

    if hasattr(task, "add_done_callback"):
        try:
            task.add_done_callback(_cleanup)
        except Exception:
            pass


def is_job_cancelled(job_id: str) -> bool:
    with _LOCK:
        job = _JOBS.get(job_id)
        return job is not None and job.status == "cancelled"


def get_job(job_id: str) -> JobRecord | None:
    with _LOCK:
        return _JOBS.get(job_id)


def clear_jobs_for_testing() -> None:
    """Clear in-memory job store (tests only)."""
    with _LOCK:
        _JOBS.clear()
        _JOB_TASKS.clear()


def list_jobs(statuses: set[str] | None = None) -> list[JobRecord]:
    with _LOCK:
        jobs = list(_JOBS.values())
    if statuses is None:
        return jobs
    return [job for job in jobs if job.status in statuses]


def job_has_recorded_error(job: JobRecord) -> bool:
    """True if the job failed or carries a soft error in metadata (e.g. LLM summary)."""
    if job.status == "failed":
        return True
    if job.error:
        return True
    meta = job.metadata or {}
    if meta.get("llm_summary_error"):
        return True
    le = meta.get("last_error")
    if isinstance(le, dict) and (le.get("message") or le.get("error")):
        return True
    if isinstance(le, str) and le.strip():
        return True
    return False


def clear_job_error(job_id: str, *, detail: str | None = None) -> JobRecord | None:
    """
    Clear recorded errors from a terminal job (failed/completed/cancelled).

    Returns None when the job is missing, still active (queued/running), or has no
    recorded error. Failed jobs become ``cancelled`` so they drop off the dashboard.
    """
    out: JobRecord | None = None
    notify_id: str | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if job.status in {"queued", "running"}:
            return None
        if not job_has_recorded_error(job):
            return None

        job.error = None
        meta = dict(job.metadata or {})
        meta.pop("llm_summary_error", None)
        meta.pop("last_error", None)
        job.metadata = meta

        if job.status == "failed":
            job.status = "cancelled"
            job.current_item = None
            job.detail = detail or "error cleared"
            job.finished_at = job.finished_at or _utc_now()
        elif detail:
            job.detail = detail

        _bump_revision(job)
        notify_id = job.id
        out = job
    _notify_after_change(notify_id)
    return out


def list_error_jobs(*, limit: int = 100, kind: str | None = None) -> list[JobRecord]:
    """Newest first; same in-memory store as ``list_jobs`` (this process only)."""
    with _LOCK:
        jobs = list(_JOBS.values())
    filtered = [j for j in jobs if job_has_recorded_error(j)]
    if kind is not None and (k := kind.strip()):
        filtered = [j for j in filtered if j.kind == k]
    filtered.sort(key=lambda j: j.created_at, reverse=True)
    cap = min(max(limit, 1), 500)
    return filtered[:cap]


def update_job_metadata(job_id: str, updates: dict[str, Any]) -> JobRecord | None:
    out: JobRecord | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        merged = dict(job.metadata)
        merged.update(updates)
        job.metadata = merged
        _bump_revision(job)
        out = job
    _notify_after_change(out.id if out else None)
    return out


def init_job_ingest_queue(job_id: str, slots: list[tuple[str, str]]) -> None:
    """Initialize parallel ingest queue tracking (all slots start as pending).

    Each slot is ``(slot_id, display_file_name)``. Duplicate display names are
    allowed — each slot is tracked independently.
    """
    pending: list[str] = []
    labels: dict[str, str] = {}
    for slot_id, file_name in slots:
        sid = (slot_id or "").strip()
        label = (file_name or "").strip()
        if not sid or not label:
            continue
        pending.append(sid)
        labels[sid] = label
    notify_id: str | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        meta = dict(job.metadata or {})
        meta["pending_slots"] = pending
        meta["active_slots"] = []
        meta["completed_slots"] = []
        meta["slot_labels"] = labels
        meta["file_activity"] = {}
        meta.pop("pending_items", None)
        meta.pop("active_items", None)
        meta.pop("completed_files", None)
        job.metadata = meta
        _bump_revision(job)
        notify_id = job_id
    _notify_after_change(notify_id)


def register_job_active_item(
    job_id: str,
    slot_id: str,
    *,
    file_name: str | None = None,
    detail: str | None = None,
) -> None:
    """Mark a queue slot as actively processing."""
    sid = (slot_id or "").strip()
    if not sid:
        return
    notify_id: str | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        meta = dict(job.metadata or {})
        active = _slot_id_list(meta.get("active_slots"))
        if sid not in active:
            active.append(sid)
        meta["active_slots"] = active
        pending = _slot_id_list(meta.get("pending_slots"))
        if sid in pending:
            pending.remove(sid)
        meta["pending_slots"] = pending
        labels = _slot_labels_dict(meta.get("slot_labels"))
        label = (file_name or labels.get(sid) or sid).strip()
        if label:
            labels[sid] = label
        meta["slot_labels"] = labels
        activity = dict(meta.get("file_activity") or {})
        entry = dict(activity.get(sid) or {})
        if detail is not None:
            entry["detail"] = detail
        if label:
            entry["file_name"] = label
        activity[sid] = entry
        meta["file_activity"] = activity
        job.metadata = meta
        _bump_revision(job)
        notify_id = job_id
    _notify_after_change(notify_id)


def update_job_file_activity(
    job_id: str,
    slot_id: str,
    *,
    detail: str | None = None,
    percent: int | None = None,
    file_name: str | None = None,
) -> None:
    """Update live step text / percent for an active slot without changing the active set."""
    sid = (slot_id or "").strip()
    if not sid:
        return
    notify_id: str | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        meta = dict(job.metadata or {})
        active = _slot_id_list(meta.get("active_slots"))
        if sid not in active:
            return
        labels = _slot_labels_dict(meta.get("slot_labels"))
        activity = dict(meta.get("file_activity") or {})
        entry = dict(activity.get(sid) or {})
        if detail is not None:
            entry["detail"] = detail
        if percent is not None:
            entry["percent"] = max(0, min(100, int(percent)))
        label = (file_name or labels.get(sid) or entry.get("file_name") or sid)
        if label:
            entry["file_name"] = str(label).strip()
        activity[sid] = entry
        meta["file_activity"] = activity
        job.metadata = meta
        _bump_revision(job)
        notify_id = job_id
    _notify_after_change(notify_id)


def unregister_job_active_item(job_id: str, slot_id: str) -> None:
    """Remove a slot from the active parallel ingest set."""
    sid = (slot_id or "").strip()
    if not sid:
        return
    notify_id: str | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        meta = dict(job.metadata or {})
        active = [item for item in _slot_id_list(meta.get("active_slots")) if item != sid]
        meta["active_slots"] = active
        activity = dict(meta.get("file_activity") or {})
        activity.pop(sid, None)
        meta["file_activity"] = activity
        job.metadata = meta
        _bump_revision(job)
        notify_id = job_id
    _notify_after_change(notify_id)


def release_job_ingest_file(job_id: str, slot_id: str) -> None:
    """Mark a slot finished: drop from active/pending and append to completed_slots."""
    sid = (slot_id or "").strip()
    if not sid:
        return
    notify_id: str | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        meta = dict(job.metadata or {})
        active = [item for item in _slot_id_list(meta.get("active_slots")) if item != sid]
        pending = [item for item in _slot_id_list(meta.get("pending_slots")) if item != sid]
        completed = _slot_id_list(meta.get("completed_slots"))
        if sid not in completed:
            completed.append(sid)
        activity = dict(meta.get("file_activity") or {})
        activity.pop(sid, None)
        meta["active_slots"] = active
        meta["pending_slots"] = pending
        meta["completed_slots"] = completed
        meta["file_activity"] = activity
        job.metadata = meta
        _bump_revision(job)
        notify_id = job_id
    _notify_after_change(notify_id)


def clear_job_active_items(job_id: str) -> None:
    notify_id: str | None = None
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        meta = dict(job.metadata or {})
        if not any(
            key in meta
            for key in (
                "active_items",
                "pending_items",
                "completed_files",
                "active_slots",
                "pending_slots",
                "completed_slots",
                "slot_labels",
                "file_activity",
            )
        ):
            return
        _clear_parallel_file_activity(meta)
        job.metadata = meta
        _bump_revision(job)
        notify_id = job_id
    _notify_after_change(notify_id)
