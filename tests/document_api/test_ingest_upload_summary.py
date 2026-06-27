"""Regression: IngestResponse.upload must be readable after Pydantic coercion."""

from __future__ import annotations

from app.document_api.api.v1.schemas import IngestResponse, IngestUploadSummary, upload_summary_as_dict


def test_upload_summary_as_dict_from_pydantic_model():
    model = IngestUploadSummary(
        status="pending_approval",
        pending_ingest_id="abc-123",
        chunks_uploaded=0,
        rearrange_llm_raw="preview",
    )
    data = upload_summary_as_dict(model)
    assert data["status"] == "pending_approval"
    assert data["pending_ingest_id"] == "abc-123"
    assert data["rearrange_llm_raw"] == "preview"


def test_ingest_response_upload_coercion_uses_model_dump_not_get():
    summary = {
        "status": "pending_approval",
        "pending_ingest_id": "pid-1",
        "chunks_uploaded": 2,
        "llm_summary": "done",
    }
    response = IngestResponse(
        source_filename="report.csv",
        markdown="",
        upload=summary,
    )
    assert isinstance(response.upload, IngestUploadSummary)
    normalized = upload_summary_as_dict(response.upload)
    assert normalized["status"] == "pending_approval"
    assert normalized["pending_ingest_id"] == "pid-1"
    assert normalized["chunks_uploaded"] == 2
