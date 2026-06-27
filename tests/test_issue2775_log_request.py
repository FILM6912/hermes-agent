"""Regression tests for structured request logging (FastAPI migration)."""

from __future__ import annotations

import asyncio
import json

from starlette.requests import Request
from starlette.responses import Response

from app.middleware.logging import RequestLoggingMiddleware


def _http_scope(*, method: str = "GET", path: str = "/health", client=None):
    return {
        "type": "http",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "client": client,
        "server": ("testserver", 80),
        "scheme": "http",
        "root_path": "",
    }


def test_request_logging_uses_dashes_when_client_missing(capsys):
    """Missing client address should not break JSON request logging."""

    async def _run() -> None:
        request = Request(_http_scope(client=None))
        middleware = RequestLoggingMiddleware(app=None)

        async def call_next(_request: Request) -> Response:
            return Response(status_code=400)

        await middleware.dispatch(request, call_next)

    asyncio.run(_run())

    line = capsys.readouterr().out.strip()
    assert line.startswith("[webui] ")
    record = json.loads(line.removeprefix("[webui] "))
    assert record["method"] == "GET"
    assert record["path"] == "/health"
    assert record["status"] == 400
    assert record["remote"] == "-"
