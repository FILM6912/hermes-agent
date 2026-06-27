"""Smoke tests for integrated Document RAG API."""

from __future__ import annotations

import os

import pytest

from app.api.v1.router import api_v1_router


def _route_paths() -> set[str]:
    return {getattr(route, "path", "") for route in api_v1_router.routes}


def test_document_api_routes_registered() -> None:
    from app.document_api.integration import document_api_enabled

    if not document_api_enabled():
        import pytest

        pytest.skip("document API deps or SUPABASE_URL not configured")
    paths = _route_paths()
    assert "/api/v1/documents" in paths
    assert "/api/v1/search" in paths
    assert "/api/v1/jobs" in paths
    assert "/api/v1/ingest-pending" in paths


def test_api_proxy_routes_removed() -> None:
    paths = _route_paths()
    assert not any("/proxy" in p for p in paths)


def test_document_api_env_toggle_can_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_WEBUI_DOCUMENT_API_ENABLED", "false")
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:8000")

    from app.document_api import integration as doc_int

    assert doc_int.is_document_api_feature_requested() is False
    assert doc_int.document_api_enabled() is False
    assert doc_int.get_document_api_router().routes == []


def test_webui_auth_status_not_shadowed_by_document_api() -> None:
    """documents_dynamic /{document_name}/{file_name} must not handle /auth/status."""
    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).get("/api/v1/auth/status")
    assert response.status_code == 200
    payload = response.json()
    assert "auth_enabled" in payload
    detail = str(payload.get("error") or payload.get("detail") or "")
    assert "postgres" not in detail.lower()
    assert "document file" not in detail.lower()
