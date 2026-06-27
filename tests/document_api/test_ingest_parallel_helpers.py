from __future__ import annotations

from app.document_api.api.v1.routes.documents_dynamic import (
    _format_ingest_file_error,
    _ingest_file_skip_reason,
    _ingest_max_parallel_files,
)
from fastapi import HTTPException


def test_ingest_file_skip_reason_lock_files():
    assert _ingest_file_skip_reason("~$สารบัญ.docx") == "Microsoft Office temporary lock file"
    assert _ingest_file_skip_reason("folder/~$report.docx") == "Microsoft Office temporary lock file"
    assert _ingest_file_skip_reason("report.docx") is None


def test_ingest_file_skip_reason_system_files():
    assert _ingest_file_skip_reason(".DS_Store") == "system metadata file"
    assert _ingest_file_skip_reason("notes.pdf") is None


def test_format_ingest_file_error_http_exception():
    exc = HTTPException(status_code=422, detail={"message": "bad file"})
    assert _format_ingest_file_error(exc) == "bad file"


def test_ingest_max_parallel_files_clamps(monkeypatch):
    monkeypatch.setenv("INGEST_MAX_PARALLEL_FILES", "100")
    assert _ingest_max_parallel_files() == 32
    monkeypatch.setenv("INGEST_MAX_PARALLEL_FILES", "0")
    assert _ingest_max_parallel_files() == 1
    monkeypatch.setenv("INGEST_MAX_PARALLEL_FILES", "5")
    assert _ingest_max_parallel_files() == 5
