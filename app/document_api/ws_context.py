"""Bind HTTP-equivalent auth/access for document API WebSocket routes.

Starlette ``BaseHTTPMiddleware`` does not run for WebSocket handshakes, so
``ProfileContextMiddleware`` never sets ``get_request_user_access()``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import WebSocket
from starlette.datastructures import QueryParams, URL

from app.domain.users import resolve_request_user_access
from app.domain.workspace import clear_request_user_access, set_request_user_access


class WsAuthRequestShim:
    """Request-like surface for auth helpers — WebSocket scopes are not HTTP."""

    __slots__ = ("scope", "cookies", "headers", "method", "query_params", "url")

    def __init__(self, websocket: WebSocket) -> None:
        self.scope = websocket.scope
        self.cookies = websocket.cookies
        self.headers = websocket.headers
        self.method = "GET"
        path = str(websocket.scope.get("path") or "/")
        raw_qs = websocket.scope.get("query_string") or b""
        qs = raw_qs.decode("latin-1") if isinstance(raw_qs, bytes) else str(raw_qs)
        self.url = URL(path + (f"?{qs}" if qs else ""))
        self.query_params = QueryParams(qs)


def websocket_auth_request(websocket: WebSocket) -> WsAuthRequestShim:
    return WsAuthRequestShim(websocket)


@asynccontextmanager
async def bind_document_api_ws_access(websocket: WebSocket) -> AsyncIterator[WsAuthRequestShim]:
    """Resolve session cookies from the WS handshake and bind ``UserAccess``."""
    request = websocket_auth_request(websocket)
    token = set_request_user_access(resolve_request_user_access(request))
    try:
        yield request
    finally:
        clear_request_user_access(token)


async def ensure_document_api_ws_authorized(
    websocket: WebSocket,
    request: WsAuthRequestShim,
) -> bool:
    """Close the socket and return False when auth or RAG RBAC denies access."""
    from app.core.security import check_auth_request
    from app.document_api.access import check_document_api_access

    denied = check_auth_request(request)
    if denied is not None:
        await websocket.close(code=1008, reason="authentication required")
        return False

    denied = check_document_api_access(request)
    if denied is not None:
        await websocket.close(code=1008, reason="forbidden")
        return False

    return True
