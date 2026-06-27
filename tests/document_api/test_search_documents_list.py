"""Tests for search API: POST /api/v1/search and GET /api/v1/search/documents."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.document_api.api.v1.routes import query as query_routes


@pytest.fixture
def search_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(query_routes, "ensure_folder_table", lambda: None)
    monkeypatch.setattr(
        "app.document_api.rag_department_scope.list_committed_folder_files",
        lambda: [
            {
                "id": 1,
                "folder_name": "reports",
                "file_name": "q1.pdf",
                "created_by": "uploader@example.com",
                "updated_by": "admin@example.com",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T01:00:00+00:00",
                "llm_summary": "สรุปรายงานไตรมาส 1",
                "approved_by": "admin@example.com",
                "approved_at": "2026-01-01T01:00:00+00:00",
            },
            {
                "id": 2,
                "folder_name": "reports",
                "file_name": "q2.pdf",
                "created_by": "uploader@example.com",
                "updated_by": None,
                "created_at": "2026-01-02T00:00:00+00:00",
                "updated_at": "2026-01-02T00:00:00+00:00",
                "llm_summary": "",
                "approved_by": None,
                "approved_at": None,
            },
        ],
    )
    monkeypatch.setattr(
        query_routes,
        "list_catalog_documents",
        lambda: [
            {
                "source_filename": "q1.pdf",
                "chunk_count": 12,
                "folder_name": "reports",
                "llm_summary": "สรุปรายงานไตรมาส 1",
            },
        ],
    )
    monkeypatch.setattr(
        query_routes,
        "build_source_file_url",
        lambda folder, name: f"https://example.test/{folder}/source/{name}",
    )

    app = FastAPI()
    app.include_router(query_routes.router, prefix="/api/v1/search", tags=["search"])
    return TestClient(app)


def test_search_documents_list_returns_llm_summary(search_client: TestClient):
    res = search_client.get("/api/v1/search/documents")
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 2
    assert payload["items"][0]["llm_summary"] == "สรุปรายงานไตรมาส 1"
    assert payload["items"][0]["chunk_count"] == 12
    assert payload["items"][0]["approved_by"] == "admin@example.com"
    assert payload["items"][0]["source_file_url"].endswith("reports/source/q1.pdf")


def test_search_post_omits_llm_summary(monkeypatch: pytest.MonkeyPatch, search_client: TestClient):
    monkeypatch.setattr(query_routes, "build_embeddings", lambda _s: object())
    monkeypatch.setattr(query_routes, "build_reranker", lambda _s: None)
    monkeypatch.setattr(
        query_routes,
        "query_documents",
        lambda **kwargs: [
            {
                "source_filename": "q1.pdf",
                "chunk_index": 0,
                "content": "chunk text",
                "hybrid_score": 0.91,
                "llm_summary": "should not appear in response",
            }
        ],
    )
    fake_settings = type(
        "S",
        (),
        {
            "pg_host": "localhost",
            "pg_port": 5432,
            "pg_database": "db",
            "pg_user": "u",
            "pg_password": "p",
            "pg_sslmode": "prefer",
            "supabase_url": "https://example.test",
            "supabase_service_key": "key",
            "supabase_storage_bucket": "b",
            "supabase_transcript_bucket": "t",
            "supabase_table_name": "documents",
            "supabase_query_name": "match_documents",
            "reranker_candidates": 50,
        },
    )()
    monkeypatch.setattr(query_routes, "settings", fake_settings)

    res = search_client.post("/api/v1/search", params={"query_text": "quarterly report"})
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 1
    assert payload["results"][0]["source_filename"] == "q1.pdf"
    assert "llm_summary" not in payload["results"][0]


def test_search_documents_list_filters_by_docs(search_client: TestClient):
    res = search_client.get("/api/v1/search/documents", params={"docs": ["reports"]})
    assert res.status_code == 200
    assert res.json()["total"] == 2

    res_other = search_client.get("/api/v1/search/documents", params={"docs": ["other-set"]})
    assert res_other.status_code == 200
    assert res_other.json()["total"] == 0


def test_document_summary_persistence_helpers(monkeypatch: pytest.MonkeyPatch):
    from app.document_api.services import folder_catalog

    captured: dict = {}

    class FakeCursor:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = params

        @property
        def rowcount(self):
            return 1

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            captured["committed"] = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(folder_catalog, "ensure_folder_table", lambda: None)
    monkeypatch.setattr(folder_catalog, "_pg_conn", lambda: FakeConn())

    ok = folder_catalog.update_folder_file_summary("reports", "q1.pdf", "hello summary")
    assert ok is True
    assert "llm_summary" in captured["sql"]
    assert captured["params"][0] == "hello summary"
