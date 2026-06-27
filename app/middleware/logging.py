"""Structured JSON request logging (ported from server.py Handler.log_request)."""

from __future__ import annotations

import json
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        started = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - started) * 1000, 1)
        remote = "-"
        if request.client:
            remote = str(request.client.host)
        forwarded_for = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or None
        record_data = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "remote": remote,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": duration_ms,
        }
        if forwarded_for:
            record_data["forwarded_for"] = forwarded_for
        print(f"[webui] {json.dumps(record_data)}", flush=True)
        return response
