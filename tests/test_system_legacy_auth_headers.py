"""System repository forwards Bearer auth to legacy insights/logs handlers."""

from __future__ import annotations

from app.repositories.system import _legacy_auth_headers


def test_legacy_auth_headers_forwards_cookie_and_bearer() -> None:
    headers = {
        "Cookie": "hermes_session=abc.def",
        "Authorization": "Bearer token.sig",
    }
    assert _legacy_auth_headers(headers) == {
        "Cookie": "hermes_session=abc.def",
        "Authorization": "Bearer token.sig",
    }


def test_legacy_auth_headers_bearer_only() -> None:
    assert _legacy_auth_headers({"Authorization": "Bearer token.sig"}) == {
        "Authorization": "Bearer token.sig",
    }


def test_legacy_auth_headers_empty_when_missing() -> None:
    assert _legacy_auth_headers({}) == {}
    assert _legacy_auth_headers(None) == {}
