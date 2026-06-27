"""MCP mount registers when MCP_ENABLED and document API are available."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from starlette.requests import Request


def _request(path: str, *, authorization: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
        "scheme": "http",
        "root_path": "",
    }
    return Request(scope)


def test_mount_document_mcp_skipped_when_disabled(monkeypatch: pytest.MonkeyPatch):
    from app.document_api import mcp_integration

    mcp_integration._mcp_mounted = False
    monkeypatch.setattr(
        "app.document_api.core.config.get_settings",
        lambda: type("S", (), {"mcp_enabled": False, "mcp_mount_path": "/mcp"})(),
    )
    app = FastAPI()
    assert mcp_integration.mount_document_mcp(app) is None


def test_mount_document_mcp_uses_include_tags(monkeypatch: pytest.MonkeyPatch):
    from app.document_api import mcp_integration

    mcp_integration._mcp_mounted = False
    monkeypatch.setattr(
        "app.document_api.core.config.get_settings",
        lambda: type("S", (), {"mcp_enabled": True, "mcp_mount_path": "/mcp"})(),
    )
    monkeypatch.setattr("app.document_api.integration.document_api_enabled", lambda: True)

    fake_mcp = MagicMock()
    monkeypatch.setitem(
        __import__("sys").modules,
        "fastapi_mcp",
        type("mod", (), {"FastApiMCP": lambda *a, **k: fake_mcp})(),
    )

    app = FastAPI()
    path = mcp_integration.mount_document_mcp(app)
    assert path == "/mcp"
    fake_mcp.mount_http.assert_called_once_with(mount_path="/mcp")


def test_is_mcp_mount_path_when_enabled(monkeypatch: pytest.MonkeyPatch):
    from app.document_api import mcp_integration

    monkeypatch.setattr(
        "app.document_api.core.config.get_settings",
        lambda: type("S", (), {"mcp_enabled": True, "mcp_mount_path": "/mcp"})(),
    )
    monkeypatch.setattr("app.document_api.integration.document_api_enabled", lambda: True)

    assert mcp_integration.is_mcp_mount_path("/mcp")
    assert mcp_integration.is_mcp_mount_path("/mcp/")
    assert not mcp_integration.is_mcp_mount_path("/api/v1/mcp/servers")


def test_check_auth_request_denies_mcp_without_bearer(monkeypatch: pytest.MonkeyPatch):
    from app.core import security

    monkeypatch.setattr(security, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(security, "session_valid", lambda _request: False)
    monkeypatch.setattr(
        "app.document_api.core.config.get_settings",
        lambda: type("S", (), {"mcp_enabled": True, "mcp_mount_path": "/mcp", "mcp_require_bearer": True, "mcp_api_key": "svc"})(),
    )
    monkeypatch.setattr("app.document_api.integration.document_api_enabled", lambda: True)

    denied = security.check_auth_request(_request("/mcp"))
    assert denied is not None
    assert denied.status_code == 401


def test_check_auth_request_allows_mcp_with_service_bearer(monkeypatch: pytest.MonkeyPatch):
    from app.core import security

    monkeypatch.setattr(security, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(security, "session_valid", lambda _request: False)
    monkeypatch.setattr(
        "app.document_api.core.config.get_settings",
        lambda: type(
            "S",
            (),
            {
                "mcp_enabled": True,
                "mcp_mount_path": "/mcp",
                "mcp_require_bearer": True,
                "mcp_api_key": "svc-secret",
            },
        )(),
    )
    monkeypatch.setattr("app.document_api.integration.document_api_enabled", lambda: True)

    assert (
        security.check_auth_request(_request("/mcp", authorization="Bearer svc-secret"))
        is None
    )


def test_check_auth_request_requires_auth_for_search_when_rbac_on(monkeypatch: pytest.MonkeyPatch):
    from app.core import security

    monkeypatch.setattr(security, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(security, "session_valid", lambda _request: False)
    monkeypatch.setattr(
        "app.document_api.integration._load_document_api_router",
        lambda: object(),
    )
    monkeypatch.setattr(
        "app.document_api.access.document_api_requires_rbac",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.document_api.mcp_integration.normalized_mcp_mount_path",
        lambda: "/mcp",
    )

    denied = security.check_auth_request(_request("/api/v1/search"))
    assert denied is not None
    assert denied.status_code == 401
