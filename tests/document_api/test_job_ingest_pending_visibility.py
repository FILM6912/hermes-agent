"""Jobs vs ingest-pending lifecycle: upload on /jobs, ready on ingest-pending, commit on /jobs."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.document_api.api.v1.routes import jobs as jobs_routes
from app.document_api.api.v1.routes.job_common import (
    filter_ingest_pending_rows,
    filter_jobs_excluding_ingest_pending,
    list_dashboard_pending_ingest,
)
from app.document_api.services.job_manager import clear_jobs_for_testing, create_job, start_job


def _jobs_client() -> TestClient:
    app = FastAPI()
    app.include_router(jobs_routes.http_router, prefix="/api/v1")
    return TestClient(app)


def test_jobs_still_show_upload_while_summary_not_ready(monkeypatch):
    clear_jobs_for_testing()
    job = create_job(kind="document_ingest", total_items=1)
    start_job(job.id)

    monkeypatch.setattr(
        "app.services.pending_ingest_catalog.list_upload_job_ids_awaiting_admin",
        lambda: frozenset(),
    )

    res = _jobs_client().get("/api/v1/jobs")

    assert res.status_code == 200
    assert res.json()[0]["job_id"] == job.id


def test_jobs_hide_upload_when_all_pending_summaries_ready(monkeypatch):
    clear_jobs_for_testing()
    job = create_job(kind="document_ingest", total_items=1)
    start_job(job.id)

    monkeypatch.setattr(
        "app.services.pending_ingest_catalog.list_upload_job_ids_awaiting_admin",
        lambda: frozenset({job.id}),
    )

    res = _jobs_client().get("/api/v1/jobs")

    assert res.status_code == 200
    assert res.json() == []


def test_filter_jobs_excluding_ingest_pending(monkeypatch):
    clear_jobs_for_testing()
    blocked = create_job(kind="document_ingest", total_items=1)
    visible = create_job(kind="commit_pending", total_items=1)
    start_job(blocked.id)
    start_job(visible.id)

    monkeypatch.setattr(
        "app.services.pending_ingest_catalog.list_upload_job_ids_awaiting_admin",
        lambda: frozenset({blocked.id}),
    )

    filtered = filter_jobs_excluding_ingest_pending([blocked, visible])

    assert [j.id for j in filtered] == [visible.id]


def test_filter_ingest_pending_rows_only_ready_and_not_committing():
    clear_jobs_for_testing()
    create_job(
        kind="commit_pending",
        total_items=1,
        metadata={"pending_ingest_id": "pending-a"},
    )
    rows = [
        {"id": "pending-a", "job_id": "upload-1", "summary_ready": True},
        {"id": "pending-b", "job_id": "upload-2", "summary_ready": True},
        {"id": "pending-c", "job_id": "upload-2", "summary_ready": False},
    ]

    filtered = filter_ingest_pending_rows(rows)

    assert [r["id"] for r in filtered] == ["pending-b"]


def test_filter_ingest_pending_rows_hides_committing_items_with_active_commit():
    clear_jobs_for_testing()
    create_job(
        kind="commit_pending",
        total_items=1,
        metadata={"pending_ingest_id": "pending-a"},
    )
    rows = [
        {"id": "pending-a", "job_id": "upload-1", "summary_ready": True},
        {"id": "pending-b", "job_id": "upload-2", "summary_ready": True},
    ]

    filtered = filter_ingest_pending_rows(rows)

    assert [r["id"] for r in filtered] == ["pending-b"]


def test_list_dashboard_pending_ingest_uses_filters(monkeypatch):
    monkeypatch.setattr(
        "app.services.pending_ingest_catalog.list_all_pending_ingest",
        lambda created_by=None, admin_ready_only=True: [
            {
                "id": "pending-a",
                "job_id": "upload-1",
                "document_name": "d",
                "source_filename": "f.pdf",
                "status": "pending",
                "summary_ready": True,
            },
        ],
    )
    monkeypatch.setattr(
        "app.api.v1.routes.job_common.active_commit_pending_ingest_ids",
        lambda: frozenset({"pending-a"}),
    )

    assert list_dashboard_pending_ingest() == []
