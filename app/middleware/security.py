"""Security middleware: CSP, headers, profile, auth, CSRF, CORS OPTIONS."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.domain.helpers import get_profile_cookie, j
from app.domain.profiles import clear_request_profile, set_request_profile
from app.domain.users import resolve_request_user_access
from app.domain.workspace import clear_request_user_access, set_request_user_access
from app.domain.routes import _check_csrf, _csrf_exempt_path, _csrf_rejection_error
from app.core.legacy_handler import LegacyHTTPHandler, _HeaderProxy
from app.core.security import check_auth_request, get_current_user, is_csp_report_post, resolve_effective_profile

logger = logging.getLogger(__name__)

_CSP_CONNECT_BASE = (
    "'self' http://127.0.0.1:* http://localhost:* "
    "ws://127.0.0.1:* ws://localhost:*"
)
_CSP_EXTRA_CONNECT_RE = re.compile(
    r"^(?:https?|wss?)://(?:\*\.)?[A-Za-z0-9._~-]+(?::(?P<port>\d{1,5}|\*))?$"
)
_CSP_REPORT_TO = (
    '{"group":"csp-endpoint","max_age":10886400,'
    '"endpoints":[{"url":"/api/csp-report"}]}'
)


def _valid_csp_extra_connect_source(source: str) -> bool:
    match = _CSP_EXTRA_CONNECT_RE.fullmatch(source)
    if not match:
        return False
    port = match.group("port")
    if not port or port == "*":
        return True
    try:
        return 1 <= int(port) <= 65535
    except ValueError:
        return False


def _csp_extra_connect_src() -> str:
    raw = os.getenv("HERMES_WEBUI_CSP_CONNECT_EXTRA", "").strip()
    if not raw:
        return ""
    sources = raw.split()
    if not sources or any(not _valid_csp_extra_connect_source(src) for src in sources):
        logger.warning("Ignoring invalid HERMES_WEBUI_CSP_CONNECT_EXTRA value")
        return ""
    return " " + " ".join(sources)


def build_csp_report_only_policy() -> str:
    connect_src = _CSP_CONNECT_BASE + _csp_extra_connect_src()
    return (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'self'; "
        "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.jsdelivr.net; "
        "worker-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "media-src 'self' data: blob:; "
        f"connect-src {connect_src}; "
        "report-uri /api/csp-report; report-to csp-endpoint"
    )


class AcceptLoopMiddleware(BaseHTTPMiddleware):
    """Track accept-loop heartbeat counters for /health."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        state = request.app.state
        state.accept_loop_requests_total = int(
            getattr(state, "accept_loop_requests_total", 0)
        ) + 1
        state.accept_loop_last_request_at = time.time()
        return await call_next(request)


class CorsOptionsMiddleware(BaseHTTPMiddleware):
    """Handle CORS preflight (ported from server.py do_OPTIONS)."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method == "OPTIONS":
            return Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization",
                },
            )
        return await call_next(request)


class ProfileContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        class _Shim:
            headers = request.headers

        def _resolve_context() -> tuple[str | None, Any]:
            profile = get_profile_cookie(_Shim())
            user = get_current_user(request)
            profile = resolve_effective_profile(user, profile)
            access = resolve_request_user_access(request)
            return profile, access

        import asyncio

        profile, access = await asyncio.to_thread(_resolve_context)
        if profile:
            set_request_profile(profile)
        access_token = set_request_user_access(access)
        try:
            return await call_next(request)
        finally:
            clear_request_user_access(access_token)
            clear_request_profile()


class AuthGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        if is_csp_report_post(request.url.path, request.method):
            return await call_next(request)
        denied = check_auth_request(request)
        if denied is not None:
            return denied
        try:
            from app.document_api.access import check_document_api_access

            denied = check_document_api_access(request)
            if denied is not None:
                return denied
        except Exception:
            logger.debug("Document API access check failed", exc_info=True)
        return await call_next(request)


class CsrfMiddleware(BaseHTTPMiddleware):
    """Reject unsafe browser writes without a valid CSRF token."""

    _WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method not in self._WRITE_METHODS:
            return await call_next(request)
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        legacy_path = path
        if path.startswith("/api/v1"):
            from app.core.legacy_handler import map_legacy_path

            legacy_path = map_legacy_path(path)
        if _csrf_exempt_path(legacy_path):
            return await call_next(request)
        try:
            from app.document_api.integration import is_document_api_public_path

            if is_document_api_public_path(path):
                return await call_next(request)
        except Exception:
            pass
        if is_csp_report_post(legacy_path, request.method):
            return await call_next(request)

        body = await request.body()
        client = request.client
        handler = LegacyHTTPHandler(
            method=request.method,
            path=legacy_path,
            headers=_HeaderProxy(request.headers),
            body=body,
            client_host=client.host if client else "-",
            client_port=client.port if client else 0,
            server=None,
            starlette_request=request,
        )

        def _check() -> bool:
            return _check_csrf(handler)

        import asyncio

        ok = await asyncio.to_thread(_check)
        if not ok:

            def _reject() -> None:
                j(handler, {"error": _csrf_rejection_error(handler)}, status=403)

            await asyncio.to_thread(_reject)
            from app.core.legacy_handler import _build_response

            return _build_response(handler)

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(request.scope, receive)
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach standard security headers on every response (ported from app.domain.helpers)."""

    _PERMISSIONS_POLICY = (
        "camera=(), microphone=(self), geolocation=(), clipboard-write=(self)"
    )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        csp_values = response.headers.getlist("content-security-policy")
        if not any("sandbox" in value for value in csp_values):
            response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", self._PERMISSIONS_POLICY)
        response.headers.setdefault(
            "Content-Security-Policy-Report-Only",
            build_csp_report_only_policy(),
        )
        response.headers.setdefault("Report-To", _CSP_REPORT_TO)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
