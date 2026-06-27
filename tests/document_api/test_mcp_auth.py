"""MCP Bearer authentication for /mcp and search tools."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.document_api.mcp_auth import (
    hash_mcp_api_key,
    is_mcp_service_key,
    is_valid_mcp_bearer,
    resolve_user_from_mcp_bearer,
)


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


def test_is_mcp_service_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_API_KEY", "svc-secret")
    monkeypatch.setattr(
        "app.document_api.core.config.get_settings",
        lambda: type(
            "S",
            (),
            {"mcp_api_key": "svc-secret", "mcp_require_bearer": True},
        )(),
    )
    assert is_mcp_service_key("svc-secret")
    assert not is_mcp_service_key("wrong")


def test_resolve_service_key_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_API_KEY", "svc-secret")
    monkeypatch.setattr(
        "app.document_api.core.config.get_settings",
        lambda: type("S", (), {"mcp_api_key": "svc-secret"})(),
    )
    user = resolve_user_from_mcp_bearer("svc-secret")
    assert user is not None
    assert user.role == "admin"
    assert user.user_id == "mcp-service"


def test_resolve_user_mcp_key(monkeypatch: pytest.MonkeyPatch) -> None:
    plain = "hmcp_test_user_key"
    monkeypatch.setattr(
        "app.document_api.mcp_auth.configured_mcp_service_key",
        lambda: "",
    )
    monkeypatch.setattr(
        "app.domain.mcp_keys.lookup_user_by_mcp_api_key",
        lambda _raw: {
            "email": "user@example.com",
            "role": "user",
            "profile_name": "user",
            "profile_names": ["user"],
            "enabled": True,
        },
    )
    user = resolve_user_from_mcp_bearer(plain)
    assert user is not None
    assert user.user_id == "user@example.com"
    assert user.role == "user"


def test_is_valid_mcp_bearer_accepts_service_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.document_api.mcp_auth.configured_mcp_service_key",
        lambda: "svc-secret",
    )
    assert is_valid_mcp_bearer("svc-secret")


def test_check_auth_request_denies_mcp_without_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import security

    monkeypatch.setattr(security, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(security, "session_valid", lambda _request: False)
    monkeypatch.setattr(
        "app.document_api.mcp_integration.normalized_mcp_mount_path",
        lambda: "/mcp",
    )
    monkeypatch.setattr(
        "app.document_api.core.config.get_settings",
        lambda: type("S", (), {"mcp_require_bearer": True, "mcp_api_key": "svc"})(),
    )
    denied = security.check_auth_request(_request("/mcp"))
    assert denied is not None
    assert denied.status_code == 401


def test_check_auth_request_allows_mcp_with_service_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import security

    monkeypatch.setattr(security, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(security, "session_valid", lambda _request: False)
    monkeypatch.setattr(
        "app.document_api.mcp_integration.normalized_mcp_mount_path",
        lambda: "/mcp",
    )
    monkeypatch.setattr(
        "app.document_api.core.config.get_settings",
        lambda: type("S", (), {"mcp_require_bearer": True, "mcp_api_key": "svc-secret"})(),
    )
    assert security.check_auth_request(_request("/mcp", authorization="Bearer svc-secret")) is None


def test_hash_mcp_api_key_is_stable() -> None:
    assert hash_mcp_api_key("hmcp_abc") == hash_mcp_api_key("hmcp_abc")
    assert hash_mcp_api_key("hmcp_abc") != hash_mcp_api_key("hmcp_xyz")
