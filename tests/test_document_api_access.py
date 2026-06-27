"""Tests for Document RAG permission routing."""

from __future__ import annotations

from starlette.requests import Request

from app.document_api.access import (
    alternative_rag_permissions,
    check_document_api_access,
    is_document_api_path,
    is_mcp_search_public_route,
    required_rag_permission,
)


def _request(method: str, path: str) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
        "scheme": "http",
        "root_path": "",
    }
    return Request(scope)


def test_is_document_api_path() -> None:
    assert is_document_api_path("/api/v1/search")
    assert is_document_api_path("/api/v1/ingest-pending")
    assert is_document_api_path("/api/v1/jobs/abc")
    assert is_document_api_path("/api/v1/my-set/files")
    assert not is_document_api_path("/api/v1/auth/status")
    assert not is_document_api_path("/api/v1/admin/roles")
    assert not is_document_api_path("/api/v1/session/new")
    assert not is_document_api_path("/api/v1/chat/start")
    assert not is_document_api_path("/api/v1/workspaces")


def test_required_rag_permission_mapping() -> None:
    assert required_rag_permission("POST", "/api/v1/search") == "rag:search"
    assert required_rag_permission("GET", "/api/v1/search/documents") == "rag:search"
    assert (
        required_rag_permission("POST", "/api/v1/ingest-pending/commit-batch")
        == "rag:approve"
    )
    assert (
        required_rag_permission("POST", "/api/v1/ingest-pending/pid/commit")
        == "rag:approve"
    )
    assert required_rag_permission("GET", "/api/v1/ingest-pending") == "rag:ingest"
    assert (
        required_rag_permission("GET", "/api/v1/default/ingest-pending")
        == "rag:ingest"
    )
    assert (
        required_rag_permission("POST", "/api/v1/default/ingest")
        == "rag:ingest"
    )
    assert required_rag_permission("DELETE", "/api/v1/default/report.pdf") == "rag:manage"
    assert required_rag_permission("GET", "/api/v1/jobs") == "rag:ingest"
    assert required_rag_permission("GET", "/api/v1/transcript-report") == "transcript-report:read"
    assert (
        required_rag_permission("GET", "/api/v1/transcript-report/docs/meeting")
        == "transcript-report:read"
    )
    assert (
        required_rag_permission("POST", "/api/v1/transcript-report/docs/meeting")
        == "transcript-report:create"
    )
    assert (
        required_rag_permission("POST", "/api/v1/transcript-report/docs/meeting/process")
        == "transcript-report:edit"
    )
    assert (
        required_rag_permission("DELETE", "/api/v1/transcript-report/docs/meeting/uuid")
        == "transcript-report:delete"
    )
    assert "transcript-report:read" in alternative_rag_permissions("GET", "/api/v1/jobs/abc")


def test_alternative_rag_permissions_for_jobs() -> None:
    assert "transcript-report:read" in alternative_rag_permissions("GET", "/api/v1/jobs")
    assert "transcript-report:edit" in alternative_rag_permissions("POST", "/api/v1/jobs/x/retry")


def test_is_mcp_search_public_route_when_mcp_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.document_api.mcp_integration.normalized_mcp_mount_path",
        lambda: "/mcp",
    )
    assert not is_mcp_search_public_route("POST", "/api/v1/search")
    assert not is_mcp_search_public_route("GET", "/api/v1/search/documents")


def test_is_mcp_search_public_route_when_mcp_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.document_api.mcp_integration.normalized_mcp_mount_path",
        lambda: None,
    )
    assert not is_mcp_search_public_route("POST", "/api/v1/search")


def test_check_document_api_access_requires_rag_search_when_mcp_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.document_api.access.document_api_requires_rbac",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.document_api.mcp_integration.normalized_mcp_mount_path",
        lambda: "/mcp",
    )
    monkeypatch.setattr(
        "app.core.security.get_current_user",
        lambda _request: None,
    )
    denied = check_document_api_access(_request("POST", "/api/v1/search"))
    assert denied is not None
    assert denied.status_code == 401
    denied_list = check_document_api_access(_request("GET", "/api/v1/search/documents"))
    assert denied_list is not None
    assert denied_list.status_code == 401


def test_check_document_api_access_requires_rag_search_when_rbac_on(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.document_api.access.document_api_requires_rbac",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.document_api.mcp_integration.normalized_mcp_mount_path",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.core.security.get_current_user",
        lambda _request: None,
    )
    denied = check_document_api_access(_request("POST", "/api/v1/search"))
    assert denied is not None
    assert denied.status_code == 401
