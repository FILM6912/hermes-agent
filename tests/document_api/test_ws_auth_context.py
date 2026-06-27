"""WebSocket auth shim resolves query access_token like HTTP."""

from __future__ import annotations

from app.document_api.ws_context import WsAuthRequestShim, websocket_auth_request


class _FakeWebSocket:
    def __init__(self, *, path: str, query_string: bytes = b"", headers: dict | None = None) -> None:
        self.scope = {
            "path": path,
            "query_string": query_string,
            "type": "websocket",
        }
        self.cookies = {}
        self.headers = headers or {}


def test_ws_shim_exposes_query_params_for_access_token() -> None:
    ws = _FakeWebSocket(
        path="/api/v1/ingest-pending",
        query_string=b"access_token=session-token-abc",
    )
    shim = websocket_auth_request(ws)  # type: ignore[arg-type]
    assert isinstance(shim, WsAuthRequestShim)
    assert shim.query_params.get("access_token") == "session-token-abc"


def test_resolve_session_credential_from_ws_query_token(monkeypatch) -> None:
    from app.domain import auth as auth_mod

    monkeypatch.setattr(auth_mod, "verify_session", lambda _token: _token == "session-token-abc")

    ws = _FakeWebSocket(
        path="/api/v1/ingest-pending",
        query_string=b"access_token=session-token-abc",
    )
    shim = websocket_auth_request(ws)  # type: ignore[arg-type]
    assert auth_mod.resolve_session_credential_from_request(shim) == "session-token-abc"
