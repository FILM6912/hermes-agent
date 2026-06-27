"""Tests for Supabase Storage API proxy (/storage/v1/**)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.storage_proxy import (
    build_upstream_storage_url,
    is_supabase_storage_public_path,
    is_supabase_storage_path,
    supabase_storage_proxy_enabled,
)
from app.main import app


@pytest.fixture(autouse=True)
def _clear_document_settings_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERMES_WEBUI_DOCUMENT_API_ENABLED", raising=False)


def test_is_supabase_storage_path() -> None:
    assert is_supabase_storage_path("/storage/v1")
    assert is_supabase_storage_path("/storage/v1/object/public/bucket/file.jpg")
    assert not is_supabase_storage_path("/api/v1/documents")


def test_is_supabase_storage_public_path() -> None:
    assert is_supabase_storage_public_path(
        "/storage/v1/object/public/document-files/rp-008344/files/img.jpeg"
    )
    assert not is_supabase_storage_public_path("/storage/v1/object/document-files/private.jpg")
    assert not is_supabase_storage_public_path("/storage/v1/bucket")


def test_build_upstream_storage_url_preserves_path_and_query() -> None:
    path = (
        "/storage/v1/object/public/document-files/"
        "rp-008344-ds-5-raspberry-pi-4-product-brief-f32d4ffa43/"
        "files/img_002_63bb9569-b14ad33737.jpeg"
    )
    url = build_upstream_storage_url(
        supabase_url="https://example.supabase.co",
        request_path=path,
        query="download=1",
    )
    assert url == (
        "https://example.supabase.co/storage/v1/object/public/document-files/"
        "rp-008344-ds-5-raspberry-pi-4-product-brief-f32d4ffa43/"
        "files/img_002_63bb9569-b14ad33737.jpeg?download=1"
    )


def _request_call(await_args) -> tuple[str, str, dict[str, str]]:
    args, kwargs = await_args
    method = args[0] if args else str(kwargs.get("method", ""))
    url = args[1] if len(args) > 1 else str(kwargs.get("url", ""))
    headers = kwargs.get("headers") or {}
    return method, url, {k.lower(): v for k, v in headers.items()}


def test_supabase_storage_proxy_enabled_requires_supabase_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    assert supabase_storage_proxy_enabled() is False

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    assert supabase_storage_proxy_enabled() is True


def test_storage_proxy_returns_503_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    client = TestClient(app)
    response = client.get("/storage/v1/object/public/document-files/example.jpg")
    assert response.status_code == 503
    payload = response.json()
    assert "not configured" in payload["error"].lower()


def test_storage_proxy_forwards_public_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-role-key")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers(
        {
            "content-type": "image/jpeg",
            "content-length": "9",
            "etag": '"abc123"',
        }
    )
    mock_response.content = b"JPEG-DATA"

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    object_path = (
        "/storage/v1/object/public/document-files/"
        "rp-008344-ds-5-raspberry-pi-4-product-brief-f32d4ffa43/"
        "files/img_002_63bb9569-b14ad33737.jpeg"
    )

    with patch("app.api.storage_proxy.httpx.AsyncClient", return_value=mock_client):
        client = TestClient(app)
        response = client.get(object_path, headers={"Accept": "image/jpeg"})

    assert response.status_code == 200
    assert response.content == b"JPEG-DATA"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["etag"] == '"abc123"'

    mock_client.request.assert_awaited_once()
    method, url, forwarded = _request_call(mock_client.request.await_args)
    assert method == "GET"
    assert url == f"https://example.supabase.co{object_path}"
    assert forwarded.get("accept") == "image/jpeg"
    assert "authorization" not in forwarded
    assert "apikey" not in forwarded


def test_storage_proxy_adds_service_key_for_private_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-role-key")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"content-type": "application/pdf"})
    mock_response.content = b"PDF"

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    object_path = "/storage/v1/object/document-files/private/report.pdf"

    with patch("app.api.storage_proxy.httpx.AsyncClient", return_value=mock_client):
        client = TestClient(app)
        response = client.get(object_path)

    assert response.status_code == 200
    _, url, forwarded = _request_call(mock_client.request.await_args)
    assert forwarded["authorization"] == "Bearer service-role-key"
    assert forwarded["apikey"] == "service-role-key"


def test_storage_proxy_forwards_query_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"content-type": "image/png"})
    mock_response.content = b"PNG"

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.storage_proxy.httpx.AsyncClient", return_value=mock_client):
        client = TestClient(app)
        response = client.get(
            "/storage/v1/object/public/document-files/example.png?download=1"
        )

    assert response.status_code == 200
    _, url, _ = _request_call(mock_client.request.await_args)
    assert url.endswith("example.png?download=1")
