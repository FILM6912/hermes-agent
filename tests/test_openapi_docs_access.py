"""OpenAPI /docs access behind auth gate."""

from __future__ import annotations

from starlette.testclient import TestClient

from app.main import create_app


def test_docs_redirects_unauthenticated_to_login(monkeypatch) -> None:
    monkeypatch.setattr("app.domain.auth.is_auth_enabled", lambda: True)
    monkeypatch.setattr("app.core.security.session_valid", lambda _request: False)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/docs", follow_redirects=False)

    assert response.status_code == 302
    location = response.headers.get("location") or ""
    assert "/login" in location
    assert "next=" in location
    assert "%2Fdocs" in location or "/docs" in location


def test_docs_available_when_authenticated(monkeypatch) -> None:
    monkeypatch.setattr("app.middleware.security.check_auth_request", lambda _request: None)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/docs", follow_redirects=False)

    assert response.status_code == 200
    assert "swagger" in (response.text or "").lower()


def test_openapi_json_available_when_authenticated(monkeypatch) -> None:
    monkeypatch.setattr("app.middleware.security.check_auth_request", lambda _request: None)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/openapi.json", follow_redirects=False)

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("openapi", "").startswith("3.")
    assert payload.get("info", {}).get("title") == "Hermes Web UI"
    assert "BearerAuth" in payload.get("components", {}).get("securitySchemes", {})


def test_swagger_ui_injects_request_interceptor_for_access_token(monkeypatch) -> None:
    monkeypatch.setattr("app.middleware.security.check_auth_request", lambda _request: None)

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/docs",
            params={"access_token": "test-session-token"},
            follow_redirects=False,
        )

    assert response.status_code == 200
    assert "requestInterceptor:" in response.text
    assert "Authorization" in response.text
