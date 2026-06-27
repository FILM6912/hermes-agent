"""ASGI bridge from Starlette Request to api.routes BaseHTTPRequestHandler handlers."""

from __future__ import annotations

import asyncio
import contextlib
import io
import queue
import threading
import time
import traceback
from typing import Any, AsyncIterator, Callable
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from app.domain.helpers import j
from app.domain.profiles import clear_request_profile, set_request_profile
from app.domain.routes import (
    handle_delete,
    handle_get,
    handle_patch,
    handle_post,
    handle_put,
)
from app.core.security import check_auth_legacy, is_csp_report_post

_ROUTE_HANDLERS: dict[str, Callable] = {
    "GET": handle_get,
    "POST": handle_post,
    "PATCH": handle_patch,
    "PUT": handle_put,
    "DELETE": handle_delete,
}

_SSE_QUEUE_GET_TIMEOUT = 0.5
_HEADERS_WAIT_TIMEOUT = 120.0


def map_legacy_path(path: str) -> str:
    """Map /api/v1/* to /api/* for existing route handlers."""
    if path == "/api/v1" or path.startswith("/api/v1/"):
        suffix = path[len("/api/v1") :]
        if not suffix or suffix == "/":
            return "/api"
        return "/api" + suffix
    return path


def _build_request_path(request: Request) -> str:
    path = request.url.path
    if request.url.query:
        return f"{path}?{request.url.query}"
    return path


class _AcceptLoopServer:
    def __init__(self, requests_total: int, last_request_at: float) -> None:
        self.accept_loop_requests_total = requests_total
        self.accept_loop_last_request_at = last_request_at


class _HeaderProxy:
    """Minimal headers mapping for legacy handler code."""

    def __init__(self, headers: Any) -> None:
        self._headers = headers

    def get(self, key: str, default: str | None = None) -> str | None:
        value = self._headers.get(key)
        if value is None:
            value = self._headers.get(key.lower())
        if value is None:
            value = self._headers.get(key.title())
        if value is None:
            return default
        return value


class _StreamingWFile:
    """Queue-backed wfile for SSE responses."""

    def __init__(self) -> None:
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._closed = False

    def write(self, data: bytes) -> int:
        if self._closed:
            raise BrokenPipeError("SSE client disconnected")
        if data:
            self._queue.put(data)
        return len(data)

    def flush(self) -> None:
        if self._closed:
            raise BrokenPipeError("SSE client disconnected")
        return None

    def close_stream(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put(None)


class _BufferingWFile:
    def __init__(self) -> None:
        self._buffer = io.BytesIO()

    def write(self, data: bytes) -> int:
        return self._buffer.write(data)

    def flush(self) -> None:
        return None

    def getvalue(self) -> bytes:
        return self._buffer.getvalue()


class LegacyHTTPHandler:
    """Fake BaseHTTPRequestHandler-compatible object for api.routes."""

    protocol_version = "HTTP/1.1"

    def __init__(
        self,
        *,
        method: str,
        path: str,
        headers: _HeaderProxy,
        body: bytes,
        client_host: str,
        client_port: int,
        server: _AcceptLoopServer | None,
        starlette_request: Request | None = None,
    ) -> None:
        self.command = method
        self.path = path
        self.headers = headers
        self.rfile = io.BytesIO(body)
        self.client_address = (client_host, client_port)
        self.server = server
        self.request = starlette_request
        self._req_t0 = time.time()
        self._response_code = 200
        self._response_message = "OK"
        self._response_headers: list[tuple[str, str]] = []
        self._headers_sent = False
        self._streaming = False
        self._headers_ready = threading.Event()
        self.wfile: _StreamingWFile | _BufferingWFile = _BufferingWFile()

    def send_response(self, code: int, message: str | None = None) -> None:
        self._response_code = code
        self._response_message = message or "OK"

    def send_header(self, key: str, value: str) -> None:
        self._response_headers.append((key, value))

    def end_headers(self) -> None:
        if self._headers_sent:
            return
        self._headers_sent = True
        content_type = ""
        for key, value in self._response_headers:
            if key.lower() == "content-type":
                content_type = value.lower()
                break
        if "text/event-stream" in content_type:
            self._streaming = True
            self.wfile = _StreamingWFile()
        self._headers_ready.set()

    def log_message(self, fmt: str, *args) -> None:
        return


class _ResponseAccumulator:
    def __init__(self) -> None:
        self.handler: LegacyHTTPHandler | None = None
        self.error_response: Response | None = None


def _headers_to_starlette(handler: LegacyHTTPHandler) -> list[tuple[str, str]]:
    # Preserve duplicate headers (e.g. multiple Set-Cookie values).
    return [(key, str(value)) for key, value in handler._response_headers]


def _apply_response_headers(response: Response, handler: LegacyHTTPHandler) -> Response:
    for key, value in _headers_to_starlette(handler):
        if key.lower() == "set-cookie":
            response.headers.append(key, value)
        else:
            response.headers[key] = value
    return response


def _build_response(handler: LegacyHTTPHandler) -> Response:
    body = b""
    if isinstance(handler.wfile, _BufferingWFile):
        body = handler.wfile.getvalue()
    response = Response(content=body, status_code=handler._response_code)
    return _apply_response_headers(response, handler)


def run_legacy_dispatch_sync(
    *,
    method: str,
    path: str,
    headers: Any | None = None,
    body: bytes = b"",
    dispatch: Callable[[LegacyHTTPHandler, Any], bool | None],
) -> Response:
    """Run a legacy handler dispatch callable synchronously (non-streaming)."""
    parsed = urlparse(path)
    handler = LegacyHTTPHandler(
        method=method.upper(),
        path=path,
        headers=_HeaderProxy(headers or {}),
        body=body,
        client_host="-",
        client_port=0,
        server=None,
    )
    cookie_profile = None
    try:
        from app.domain.helpers import get_profile_cookie

        cookie_profile = get_profile_cookie(handler)
    except Exception:
        cookie_profile = None
    if cookie_profile:
        set_request_profile(cookie_profile)
    try:
        dispatch(handler, parsed)
    finally:
        clear_request_profile()
    return _build_response(handler)


def dispatch_legacy_route(
    *,
    method: str,
    legacy_path: str,
    headers: Any | None = None,
    body: bytes = b"",
    query: dict[str, str] | None = None,
) -> Response:
    """Dispatch a legacy api.routes handler for a mapped /api/* path."""
    from urllib.parse import urlencode

    path = legacy_path
    if query:
        path = f"{path}?{urlencode(query)}"
    method_upper = method.upper()

    def _dispatch(handler: LegacyHTTPHandler, parsed) -> None:
        route_func = _ROUTE_HANDLERS.get(method_upper)
        if route_func is None:
            j(handler, {"error": "method not allowed"}, status=405)
            return
        route_func(handler, parsed)

    return run_legacy_dispatch_sync(
        method=method_upper,
        path=path,
        headers=headers,
        body=body,
        dispatch=_dispatch,
    )


def _close_streaming_wfile(handler: LegacyHTTPHandler) -> None:
    if isinstance(handler.wfile, _StreamingWFile):
        handler.wfile.close_stream()


async def _await_legacy_headers(
    handler: LegacyHTTPHandler,
    request: Request,
    dispatch_task: asyncio.Task[None],
) -> bool:
    """Wait until the legacy handler sends headers or the dispatch task finishes."""
    loop = asyncio.get_running_loop()
    deadline = time.monotonic() + _HEADERS_WAIT_TIMEOUT

    while not handler._headers_sent:
        if dispatch_task.done():
            break
        if await request.is_disconnected():
            return False
        if time.monotonic() >= deadline:
            break
        await loop.run_in_executor(
            None,
            lambda: handler._headers_ready.wait(timeout=_SSE_QUEUE_GET_TIMEOUT),
        )
    return handler._headers_sent


async def _stream_from_handler(
    handler: LegacyHTTPHandler,
    request: Request | None = None,
) -> AsyncIterator[bytes]:
    assert isinstance(handler.wfile, _StreamingWFile)
    wfile = handler.wfile
    loop = asyncio.get_running_loop()

    while True:
        if request is not None and await request.is_disconnected():
            wfile.close_stream()
            break

        try:
            chunk = await loop.run_in_executor(
                None,
                lambda: wfile._queue.get(timeout=_SSE_QUEUE_GET_TIMEOUT),
            )
        except queue.Empty:
            continue

        if chunk is None:
            break
        yield chunk


def _dispatch_sync(
    handler: LegacyHTTPHandler,
    parsed,
    route_func: Callable,
    *,
    skip_auth: bool,
) -> None:
    cookie_profile = None
    try:
        from app.domain.helpers import get_profile_cookie

        cookie_profile = get_profile_cookie(handler)
    except Exception:
        cookie_profile = None
    if cookie_profile:
        set_request_profile(cookie_profile)
    try:
        if not skip_auth:
            if not is_csp_report_post(parsed.path, handler.command) and not check_auth_legacy(
                handler, parsed
            ):
                return
        result = route_func(handler, parsed)
        if result is False and not handler._headers_sent:
            j(handler, {"error": "not found"}, status=404)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        # Client closed the connection mid-response; do not convert it into a misleading server 500.
        return
    except Exception:
        print(
            f"[webui] ERROR {handler.command} {handler.path}\n" + traceback.format_exc(),
            flush=True,
        )
        if not handler._headers_sent:
            j(handler, {"error": "Internal server error"}, status=500)
    finally:
        clear_request_profile()
        handler._headers_ready.set()
        if isinstance(handler.wfile, _StreamingWFile):
            handler.wfile.close_stream()


async def _finalize_dispatch(dispatch_task: asyncio.Task[None]) -> None:
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await dispatch_task


async def handle_legacy_sse(
    request: Request,
    *,
    skip_auth: bool = True,
) -> Response:
    """Bridge a legacy SSE handler to a Starlette StreamingResponse."""
    state = request.app.state
    return await handle_legacy_request(
        request,
        accept_loop_total=int(getattr(state, "accept_loop_requests_total", 0)),
        accept_loop_last_at=float(getattr(state, "accept_loop_last_request_at", 0.0)),
        skip_auth=skip_auth,
    )


async def handle_legacy_request(
    request: Request,
    *,
    accept_loop_total: int,
    accept_loop_last_at: float,
    skip_auth: bool = False,
) -> Response:
    """Run a legacy api.routes handler and return a Starlette response."""
    if request.method.upper() in ("GET", "HEAD", "OPTIONS"):
        body = b""
    else:
        body = await request.body()
    legacy_path = map_legacy_path(_build_request_path(request))
    parsed = urlparse(legacy_path)
    route_func = _ROUTE_HANDLERS.get(request.method.upper())
    if route_func is None:
        return Response(status_code=405)

    client = request.client
    client_host = client.host if client else "-"
    client_port = client.port if client else 0
    server = _AcceptLoopServer(accept_loop_total, accept_loop_last_at)
    handler = LegacyHTTPHandler(
        method=request.method.upper(),
        path=legacy_path,
        headers=_HeaderProxy(request.headers),
        body=body,
        client_host=client_host,
        client_port=client_port,
        server=server,
        starlette_request=request,
    )

    dispatch_task = asyncio.create_task(
        asyncio.to_thread(
            _dispatch_sync,
            handler,
            parsed,
            route_func,
            skip_auth=skip_auth,
        )
    )

    headers_sent = await _await_legacy_headers(handler, request, dispatch_task)
    if not headers_sent:
        _close_streaming_wfile(handler)
        disconnected = await request.is_disconnected()
        if disconnected:
            dispatch_task.cancel()
        await _finalize_dispatch(dispatch_task)
        if disconnected:
            return Response(status_code=499)
        return Response(status_code=404)

    if handler._streaming and isinstance(handler.wfile, _StreamingWFile):
        media_type = "text/event-stream"
        for key, value in _headers_to_starlette(handler):
            if key.lower() == "content-type":
                media_type = value
                break

        async def _streaming_body() -> AsyncIterator[bytes]:
            try:
                async for chunk in _stream_from_handler(handler, request):
                    yield chunk
            finally:
                _close_streaming_wfile(handler)
                if await request.is_disconnected():
                    dispatch_task.cancel()
                await _finalize_dispatch(dispatch_task)

        stream = StreamingResponse(
            _streaming_body(),
            status_code=handler._response_code,
            media_type=media_type,
        )
        return _apply_response_headers(stream, handler)

    await _finalize_dispatch(dispatch_task)
    return _build_response(handler)
