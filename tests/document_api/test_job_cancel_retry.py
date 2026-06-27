"""Integration-style tests for POST /jobs/{id}/cancel, /clear-error, and /retry."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.document_api.api.v1.routes import jobs as jobs_routes
from app.document_api.services.job_manager import (
    cancel_job,
    clear_jobs_for_testing,
    complete_job,
    create_job,
    fail_job,
    get_job,
    start_job,
    update_job_metadata,
)


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


def test_cancel_queued_job_returns_cancelled_immediately():
    clear_jobs_for_testing()
    job = create_job(kind="document_ingest", total_items=1, metadata={"document_name": "docs"})

    res = _jobs_client().post(f"/api/v1/jobs/{job.id}/cancel")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "cancelled"
    assert body["job_id"] == job.id
    assert get_job(job.id).status == "cancelled"


def test_cancel_completed_job_returns_409():
    clear_jobs_for_testing()
    job = create_job(kind="document_ingest", total_items=1)
    complete_job(job.id)

    res = _jobs_client().post(f"/api/v1/jobs/{job.id}/cancel")

    assert res.status_code == 409
    assert get_job(job.id).status == "completed"


def test_cancelled_job_not_listed_in_jobs_dashboard():
    clear_jobs_for_testing()
    job = create_job(kind="document_ingest", total_items=1)
    start_job(job.id)
    cancel_job(job.id)

    res = _jobs_client().post(f"/api/v1/jobs/{job.id}/cancel")

    # already cancelled — 409; list should still hide it
    assert res.status_code == 409

    listed = _jobs_client().get("/api/v1/jobs")
    ids = [item["job_id"] for item in listed.json()]
    assert job.id not in ids


def test_clear_error_on_failed_job_dismisses_from_dashboard():
    clear_jobs_for_testing()
    job = create_job(kind="document_ingest", total_items=1, metadata={"document_name": "doc-a"})
    start_job(job.id)
    fail_job(job.id, error="Buffer size limit exceeded", detail="ingest failed")

    res = _jobs_client().post(f"/api/v1/jobs/{job.id}/clear-error")

    assert res.status_code == 200
    body = res.json()
    assert body["job_id"] == job.id
    assert body["status"] == "cancelled"
    assert body["error"] is None
    assert get_job(job.id).status == "cancelled"

    listed = _jobs_client().get("/api/v1/jobs")
    ids = [item["job_id"] for item in listed.json()]
    assert job.id not in ids

    errors = _jobs_client().get("/api/v1/jobs/errors")
    error_ids = [item["job_id"] for item in errors.json()]
    assert job.id not in error_ids


def test_clear_error_on_completed_soft_error_clears_metadata_only():
    clear_jobs_for_testing()
    job = create_job(kind="document_ingest", total_items=1, metadata={"document_name": "doc-a"})
    complete_job(job.id)
    update_job_metadata(job.id, {"llm_summary_error": "summary model timeout"})

    res = _jobs_client().post(f"/api/v1/jobs/{job.id}/clear-error")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "completed"
    assert body["error"] is None
    assert body["llm_summary_error"] is None
    assert get_job(job.id).metadata.get("llm_summary_error") is None


def test_clear_error_on_active_job_returns_409():
    clear_jobs_for_testing()
    job = create_job(kind="document_ingest", total_items=1)
    start_job(job.id)

    res = _jobs_client().post(f"/api/v1/jobs/{job.id}/clear-error")

    assert res.status_code == 409
    assert "active" in res.json()["detail"].lower() or "running" in res.json()["detail"].lower()


def test_clear_error_on_clean_job_returns_409():
    clear_jobs_for_testing()
    job = create_job(kind="document_ingest", total_items=1)
    complete_job(job.id)

    res = _jobs_client().post(f"/api/v1/jobs/{job.id}/clear-error")

    assert res.status_code == 409
    assert "no error" in res.json()["detail"].lower()


def test_retry_cancelled_commit_pending_creates_new_job():
    clear_jobs_for_testing()
    old = create_job(
        kind="commit_pending",
        total_items=1,
        metadata={
            "pending_ingest_id": "f2b345f1-828e-46fc-9ef2-86679b1c8679",
            "document_name": "doc-a",
            "source_filename": "file.pdf",
        },
    )
    cancel_job(old.id)

    res = _jobs_client().post(f"/api/v1/jobs/{old.id}/retry")

    assert res.status_code == 200
    body = res.json()
    assert body["job_id"] != old.id
    new = get_job(body["job_id"])
    assert new is not None
    assert new.kind == "commit_pending"
    assert new.metadata["pending_ingest_id"] == "f2b345f1-828e-46fc-9ef2-86679b1c8679"
    assert new.metadata["retried_from"] == old.id
