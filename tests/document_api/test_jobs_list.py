"""Integration-style tests for GET /api/v1/jobs listing behavior."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.document_api.api.v1.routes import jobs as jobs_routes
from app.document_api.services.job_manager import clear_jobs_for_testing, complete_job, create_job, fail_job, start_job


@pytest.fixture(autouse=True)
def _no_pending_admin_filter(monkeypatch):
    monkeypatch.setattr(
        "app.document_api.services.pending_ingest_catalog.list_upload_job_ids_awaiting_admin",
        lambda: frozenset(),
    )


def _jobs_client() -> TestClient:
    app = FastAPI()
    app.include_router(jobs_routes.http_router, prefix="/api/v1")
    return TestClient(app)


def test_completed_commit_pending_job_not_listed_by_default():
    clear_jobs_for_testing()
    job = create_job(kind="commit_pending", total_items=1, metadata={"document_name": "doc-a"})
    start_job(job.id)
    complete_job(job.id, detail="committed example.pdf (3 chunks)")

    res = _jobs_client().get("/api/v1/jobs")

    assert res.status_code == 200
    ids = [item["job_id"] for item in res.json()]
    assert job.id not in ids


def test_running_commit_pending_job_still_listed():
    clear_jobs_for_testing()
    job = create_job(kind="commit_pending", total_items=1)
    start_job(job.id, detail="committing…")

    res = _jobs_client().get("/api/v1/jobs")

    assert res.status_code == 200
    ids = [item["job_id"] for item in res.json()]
    assert job.id in ids


def test_completed_job_drops_from_active_list_before_post_complete_metadata():
    clear_jobs_for_testing()
    job = create_job(kind="document_ingest", total_items=1, metadata={"progress_profile": "upload_pending"})
    start_job(job.id)
    complete_job(job.id, detail="ingested 1 file(s)")

    res = _jobs_client().get("/api/v1/jobs")

    assert res.status_code == 200
    assert res.json() == []


def test_jobs_list_exposes_all_files_at_top_level():
    clear_jobs_for_testing()
    job = create_job(
        kind="document_ingest",
        total_items=3,
        metadata={
            "document_name": "invoice-set",
            "files": ["a.pdf", "b.docx", "c.pptx"],
            "progress_profile": "full",
        },
    )
    start_job(job.id, detail="processing file 1/3")
    from app.document_api.services.job_manager import advance_job

    advance_job(job.id, current_item="a.pdf")

    res = _jobs_client().get("/api/v1/jobs")

    assert res.status_code == 200
    item = next(x for x in res.json() if x["job_id"] == job.id)
    assert item["files"] == ["a.pdf", "b.docx", "c.pptx"]
    assert item["document_name"] == "invoice-set"
    assert item["current_item"] == "a.pdf"
    assert item["total_items"] == 3


def test_failed_job_still_listed_on_dashboard():
    clear_jobs_for_testing()
    job = create_job(kind="document_ingest", total_items=1, metadata={"document_name": "doc-a"})
    start_job(job.id)
    fail_job(job.id, error="example failure", detail="ingest failed")

    res = _jobs_client().get("/api/v1/jobs")

    assert res.status_code == 200
    ids = [item["job_id"] for item in res.json()]
    assert job.id in ids
    item = next(x for x in res.json() if x["job_id"] == job.id)
    assert item["status"] == "failed"
    assert item["error"] == "example failure"


def test_include_completed_shows_finished_jobs():
    clear_jobs_for_testing()
    job = create_job(kind="commit_pending", total_items=1)
    complete_job(job.id)

    res = _jobs_client().get("/api/v1/jobs", params={"include_completed": "true"})

    assert res.status_code == 200
    ids = [item["job_id"] for item in res.json()]
    assert job.id in ids
