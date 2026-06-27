"""Progress shape for upload (pending) vs commit jobs."""

from app.document_api.api.v1.routes.job_common import (
    COMMIT_PENDING_STAGE_KEYS,
    UPLOAD_PENDING_STAGE_KEYS,
    apply_commit_pending_stage_progress,
    apply_document_ingest_stage_progress,
    empty_commit_pending_progress,
    empty_upload_pending_progress,
    job_to_status_response,
)
from app.document_api.services.document_pipeline import (
    estimate_token_count,
    format_export_images_progress_label,
    format_llm_chunks_progress_label,
    format_summary_progress_label,
)
from app.document_api.services.job_manager import clear_jobs_for_testing, create_job, get_job


def test_format_summary_progress_label():
    text = "hello world summary"
    assert format_summary_progress_label(file_index=1, total_files=10, llm_text=text) == (
        f"files 1/10 tokens {estimate_token_count(text)}"
    )


def test_format_export_images_progress_label():
    assert format_export_images_progress_label(done=3, total=12) == "images 3/12"
    assert format_export_images_progress_label(done=0, total=0) == "images 0/0"


def test_format_llm_chunks_progress_label():
    text = "chunk body text from llm"
    assert format_llm_chunks_progress_label(done=1, total=5, llm_text=text) == (
        f"chunks 1/5 tokens {estimate_token_count(text)}"
    )


def test_upload_pending_progress_keys():
    prog = empty_upload_pending_progress()
    assert set(prog.keys()) == {"converter_files", "summary", "total"}
    assert UPLOAD_PENDING_STAGE_KEYS == ("converter_files", "summary")
    assert prog["summary"] == ""


def test_commit_pending_progress_keys():
    prog = empty_commit_pending_progress()
    assert set(prog.keys()) == {"export_images", "llm_chunks", "embedding", "import_db", "total"}
    assert COMMIT_PENDING_STAGE_KEYS == ("export_images", "llm_chunks", "embedding", "import_db")
    assert prog["export_images"] == ""
    assert prog["llm_chunks"] == ""


def test_upload_pending_summary_is_string_label():
    clear_jobs_for_testing()
    job = create_job(
        kind="document_ingest",
        total_items=10,
        metadata={"progress_profile": "upload_pending", "progress": empty_upload_pending_progress()},
    )
    progress = dict(empty_upload_pending_progress())
    summary_label = "files 1/10 tokens 444"

    apply_document_ingest_stage_progress(
        job.id,
        progress,
        stage="convert",
        percent=100,
        detail="convert done",
        file_index=1,
        total_files=10,
        current_file="a.pdf",
        profile="upload_pending",
    )
    apply_document_ingest_stage_progress(
        job.id,
        progress,
        stage="summary",
        percent=100,
        detail=summary_label,
        file_index=1,
        total_files=10,
        current_file="a.pdf",
        profile="upload_pending",
    )

    stored = get_job(job.id).metadata["progress"]
    assert stored["converter_files"] == 100
    assert stored["summary"] == summary_label
    assert "summary_detail" not in stored


def test_commit_pending_export_images_is_string_label():
    clear_jobs_for_testing()
    job = create_job(
        kind="commit_pending",
        total_items=1,
        metadata={"progress_profile": "commit_pending", "progress": empty_commit_pending_progress()},
    )
    progress = dict(empty_commit_pending_progress())
    images_label = format_export_images_progress_label(done=2, total=5)

    apply_commit_pending_stage_progress(
        job.id,
        progress,
        stage="images",
        percent=40,
        detail=images_label,
    )

    stored = get_job(job.id).metadata["progress"]
    assert stored["export_images"] == images_label
    assert get_job(job.id).detail == images_label


def test_commit_pending_llm_chunks_is_string_label():
    clear_jobs_for_testing()
    job = create_job(
        kind="commit_pending",
        total_items=1,
        metadata={"progress_profile": "commit_pending", "progress": empty_commit_pending_progress()},
    )
    progress = dict(empty_commit_pending_progress())
    chunks_label = "chunks 1/5 tokens 669"

    apply_commit_pending_stage_progress(
        job.id,
        progress,
        stage="llm_chunks",
        percent=20,
        detail=chunks_label,
    )

    stored = get_job(job.id).metadata["progress"]
    assert stored["llm_chunks"] == chunks_label
    assert "llm_chunks_detail" not in stored


def test_heartbeat_waiting_detail_does_not_overwrite_llm_chunks_label():
    clear_jobs_for_testing()
    job = create_job(
        kind="commit_pending",
        total_items=1,
        metadata={"progress_profile": "commit_pending", "progress": empty_commit_pending_progress()},
    )
    progress = dict(empty_commit_pending_progress())
    chunks_label = "chunks 1/5 tokens 669"

    apply_commit_pending_stage_progress(
        job.id,
        progress,
        stage="llm_chunks",
        percent=20,
        detail=chunks_label,
    )
    apply_commit_pending_stage_progress(
        job.id,
        progress,
        stage="llm_chunks",
        percent=25,
        detail="[reflow] waiting for LLM… (4s)",
    )

    stored = get_job(job.id).metadata["progress"]
    assert stored["llm_chunks"] == chunks_label


def test_job_to_status_response_uses_progress_profile_defaults():
    clear_jobs_for_testing()
    upload_job = create_job(
        kind="document_ingest",
        total_items=1,
        metadata={"progress_profile": "upload_pending"},
    )
    commit_job = create_job(
        kind="commit_pending",
        total_items=1,
        metadata={"progress_profile": "commit_pending"},
    )

    upload_resp = job_to_status_response(get_job(upload_job.id))
    commit_resp = job_to_status_response(get_job(commit_job.id))

    assert set(upload_resp.progress.keys()) == {"converter_files", "summary", "total"}
    assert upload_resp.progress["summary"] == ""
    assert set(commit_resp.progress.keys()) == {
        "export_images",
        "llm_chunks",
        "embedding",
        "import_db",
        "total",
    }
    assert commit_resp.progress["export_images"] == ""
    assert commit_resp.progress["llm_chunks"] == ""
