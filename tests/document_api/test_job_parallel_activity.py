from __future__ import annotations

from app.document_api.api.v1.routes.job_common import job_to_status_response
from app.document_api.services.job_manager import (
    clear_jobs_for_testing,
    create_job,
    get_job,
    init_job_ingest_queue,
    register_job_active_item,
    release_job_ingest_file,
    start_job,
    update_job_file_activity,
)


def test_parallel_active_items_round_trip():
    clear_jobs_for_testing()
    job = create_job(kind="document_ingest", total_items=3)
    init_job_ingest_queue(
        job.id,
        [("s1", "a.docx"), ("s2", "b.docx"), ("s3", "c.docx")],
    )
    start_job(job.id)
    register_job_active_item(job.id, "s1", file_name="a.docx", detail="convert a")
    register_job_active_item(job.id, "s2", file_name="b.docx", detail="convert b")
    update_job_file_activity(job.id, "s1", detail="images 1/3", percent=12)

    refreshed = get_job(job.id)
    assert refreshed is not None
    resp = job_to_status_response(refreshed)
    assert resp.active_items == ["a.docx", "b.docx"]
    assert resp.active_slot_ids == ["s1", "s2"]
    assert resp.pending_items == ["c.docx"]
    assert resp.pending_slot_ids == ["s3"]
    assert resp.file_activity["s1"]["detail"] == "images 1/3"
    assert resp.file_activity["s1"]["percent"] == 12

    release_job_ingest_file(job.id, "s1")
    refreshed = get_job(job.id)
    assert refreshed is not None
    out = job_to_status_response(refreshed)
    assert out.active_items == ["b.docx"]
    assert out.pending_items == ["c.docx"]
    assert out.completed_files == ["a.docx"]
    assert "s1" not in out.file_activity


def test_duplicate_filenames_fill_all_parallel_slots():
    clear_jobs_for_testing()
    job = create_job(kind="commit_pending", total_items=7)
    slots = [(f"s{i}", "dup.docx") for i in range(1, 8)]
    init_job_ingest_queue(job.id, slots)
    start_job(job.id)

    for i in range(1, 6):
        register_job_active_item(job.id, f"s{i}", file_name="dup.docx", detail=f"slot {i}")

    resp = job_to_status_response(get_job(job.id))
    assert len(resp.active_items) == 5
    assert resp.active_items == ["dup.docx"] * 5
    assert len(resp.active_slot_ids) == 5
    assert resp.active_slot_ids == [f"s{i}" for i in range(1, 6)]
    assert len(resp.pending_items) == 2
    assert resp.pending_slot_ids == ["s6", "s7"]
