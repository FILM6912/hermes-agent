"""Bearer token auth alongside session cookies."""

from __future__ import annotations

import hashlib
import hmac
import pathlib
import time

import app.domain.auth as auth
import app.domain.routes as routes
from app.core.security import get_current_user, session_valid
from app.repositories.auth import AuthRepository

REPO = pathlib.Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _signed_session(raw_token: str) -> str:
    auth._sessions[raw_token] = {
        "exp": time.time() + 3600,
        "user_id": "legacy",
        "role": "admin",
    }
    sig = hmac.new(auth._signing_key(), raw_token.encode(), hashlib.sha256).hexdigest()
    return f"{raw_token}.{sig}"


class _Request:
    def __init__(
        self,
        *,
        cookie: str | None = None,
        authorization: str | None = None,
        query_token: str | None = None,
    ):
        self.cookies = {auth.COOKIE_NAME: cookie} if cookie else {}
        self.headers = {}
        self.query_params = {}
        if cookie:
            self.headers["cookie"] = f"{auth.COOKIE_NAME}={cookie}"
        if authorization:
            self.headers["authorization"] = authorization
        if query_token:
            self.query_params["access_token"] = query_token


def test_login_returns_access_token(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HERMES_WEBUI_LOCAL_DATABASE_URL", f"sqlite:///{(tmp_path / 'webui.db').as_posix()}")
    monkeypatch.setattr("app.domain.config.STATE_DIR", tmp_path)
    monkeypatch.setattr(auth, "STATE_DIR", tmp_path)
    monkeypatch.setattr(auth, "_SESSIONS_FILE", tmp_path / ".sessions.json")
    auth._sessions.clear()
    from app.storage import connection as storage_connection
    from app.storage import config as storage_config
    from app.storage.repositories.sessions import reset_sessions_repository
    from app.storage.schema import init_storage

    storage_connection.reset_shared_connection()
    storage_config.clear_database_url_cache()
    reset_sessions_repository()
    init_storage()
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "verify_password", lambda _plain: True)
    monkeypatch.setattr(
        "app.domain.users.is_multi_user_enabled",
        lambda: False,
    )
    monkeypatch.setattr(auth, "_check_login_rate", lambda _ip: True)

    payload, status, cookie = AuthRepository().login("secret", client_ip="127.0.0.1")
    assert status == 200
    assert cookie
    assert payload["access_token"] == cookie
    assert payload["token_type"] == "bearer"
    assert payload["csrf_token"]


def test_bearer_authorization_authenticates_request(monkeypatch):
    token = "a" * 64
    signed = _signed_session(token)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(
        "app.core.security.is_multi_user_enabled",
        lambda: False,
        raising=False,
    )
    try:
        request = _Request(authorization=f"Bearer {signed}")
        assert session_valid(request) is True
        user = get_current_user(request)
        assert user is not None
        assert user.role == "admin"
    finally:
        auth._sessions.pop(token, None)


def test_bearer_skips_csrf_for_browser_origin(monkeypatch):
    token = "b" * 64
    signed = _signed_session(token)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)

    class _Handler:
        headers = {
            "Origin": "http://127.0.0.1:8787",
            "Host": "127.0.0.1:8787",
            "Authorization": f"Bearer {signed}",
        }

    try:
        assert routes._check_csrf(_Handler()) is True
    finally:
        auth._sessions.pop(token, None)


def test_query_access_token_authenticates_request(monkeypatch):
    token = "c" * 64
    signed = _signed_session(token)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    try:
        request = _Request(query_token=signed)
        assert session_valid(request) is True
        user = get_current_user(request)
        assert user is not None
        assert user.role == "admin"
    finally:
        auth._sessions.pop(token, None)


def test_auth_endpoints_resolve_bearer_session():
    src = read("app/api/v1/endpoints/auth.py")
    assert "resolve_session_credential_from_request" in src
    repo = read("app/repositories/auth.py")
    assert "access_token_response_field" in repo
