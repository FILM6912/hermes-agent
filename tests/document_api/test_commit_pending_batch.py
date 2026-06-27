"""Batch commit pending — one job for multiple files."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.document_api.api.v1.routes import documents_dynamic
from app.document_api.services.job_manager import clear_jobs_for_testing, get_job


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(documents_dynamic.router, prefix="/api/v1")
    return TestClient(app)


def test_commit_batch_queues_single_job_with_all_files(monkeypatch):
    clear_jobs_for_testing()
    rows = {
        "p1": {
            "id": "p1",
            "document_name": "QR Code Station AMR",
            "source_filename": "a.docx",
            "status": "pending",
        },
        "p2": {
            "id": "p2",
            "document_name": "QR Code Station AMR",
            "source_filename": "b.docx",
            "status": "pending",
        },
        "p3": {
            "id": "p3",
            "document_name": "QR Code Station AMR",
            "source_filename": "c.docx",
            "status": "pending",
        },
    }

    def fake_get(pid: str):
        return rows.get(pid)

    monkeypatch.setattr(
        "app.api.v1.routes.documents_dynamic.get_pending_by_id",
        fake_get,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.pending_ingest_catalog.get_pending_by_id",
        fake_get,
    )

    def noop_notify(_pid: str) -> None:
        return None

    monkeypatch.setattr(
        "app.services.pending_ingest_catalog.notify_pending_ingest_changed",
        noop_notify,
    )

    enqueued: list = []

    def fake_enqueue(*, items, actor_email: str):
        from app.document_api.services.job_manager import create_job

        job = create_job(
            kind="commit_pending",
            total_items=len(items),
            metadata={
                "pending_ingest_ids": [pid for pid, _, _ in items],
                "files": [src for _, src, _ in items],
                "document_name": items[0][2],
            },
        )
        enqueued.append(items)
        return job

    monkeypatch.setattr(
        "app.api.v1.routes.documents_dynamic._enqueue_commit_pending_job",
        fake_enqueue,
    )

    res = _client().post(
        "/api/v1/ingest-pending/commit-batch",
        json={"pending_ids": ["p1", "p2", "p3"]},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["total_files"] == 3
    assert body["document_name"] == "QR Code Station AMR"
    job = get_job(body["job_id"])
    assert job is not None
    assert job.total_items == 3
    assert job.metadata["files"] == ["a.docx", "b.docx", "c.docx"]
    assert len(enqueued) == 1
    assert len(enqueued[0]) == 3


def test_active_commit_pending_collects_batch_ids():
    from app.document_api.api.v1.routes.job_common import active_commit_pending_ingest_ids
    from app.document_api.services.job_manager import create_job, start_job

    clear_jobs_for_testing()
    job = create_job(
        kind="commit_pending",
        total_items=3,
        metadata={"pending_ingest_ids": ["p1", "p2", "p3"]},
    )
    start_job(job.id)

    assert active_commit_pending_ingest_ids() == frozenset({"p1", "p2", "p3"})
