"""Chunk preview must scope by document set, not global source_filename."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.document_api.api.v1.routes import documents_dynamic


@pytest.fixture
def chunks_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        documents_dynamic,
        "file_exists_in_folder",
        lambda folder, name: folder == "Set A" and name == "cover.docx",
    )
    monkeypatch.setattr(
        documents_dynamic,
        "_resolve_file_name",
        lambda folder, name: name if folder == "Set A" else None,
    )

    captured: dict[str, str | None] = {}

    def fake_get_document(source_filename: str, document_name: str | None = None):
        captured["source"] = source_filename
        captured["document_name"] = document_name
        if document_name == "Set A":
            return {
                "source_filename": source_filename,
                "chunk_count": 1,
                "folders": ["Set A"],
                "image_paths": [],
                "source_file_url": None,
            }
        return {
            "source_filename": source_filename,
            "chunk_count": 3,
            "folders": ["Set B"],
            "image_paths": [],
            "source_file_url": None,
        }

    def fake_list_chunks(source_filename: str, document_name: str):
        if document_name == "Set A":
            return [
                {
                    "id": "c1",
                    "chunk_index": 0,
                    "token_count": 10,
                    "document_name": document_name,
                    "content": "Set A body",
                    "metadata": {},
                    "created_by": None,
                    "updated_by": None,
                    "created_at": None,
                    "updated_at": None,
                }
            ]
        return []

    monkeypatch.setattr(documents_dynamic, "get_document", fake_get_document)
    monkeypatch.setattr(documents_dynamic, "list_chunks_for_file", fake_list_chunks)
    monkeypatch.setattr(documents_dynamic, "_chunks_captured", captured, raising=False)

    app = FastAPI()
    app.include_router(documents_dynamic.router, prefix="/api/v1")
    return TestClient(app)


def test_get_document_file_scopes_chunk_count_by_document_set(chunks_client: TestClient):
    res = chunks_client.get("/api/v1/Set%20A/cover.docx")
    assert res.status_code == 200
    assert res.json()["chunk_count"] == 1


def test_list_file_chunks_returns_rows_for_matching_document_set(chunks_client: TestClient):
    res = chunks_client.get("/api/v1/Set%20A/cover.docx/chunks")
    assert res.status_code == 200
    body = res.json()
    assert body["document_name"] == "Set A"
    assert len(body["chunks"]) == 1
    assert body["chunks"][0]["content"] == "Set A body"
