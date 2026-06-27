"""MCP server repository — wraps api.routes MCP handlers."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.parse import urlencode

from starlette.responses import Response

from app.core.legacy_handler import run_legacy_dispatch_sync


def _mcp_legacy_path(subpath: str, query_params: dict[str, str] | None = None) -> str:
    normalized = subpath.strip("/")
    path = f"/api/mcp/{normalized}" if normalized else "/api/mcp"
    if query_params:
        path = f"{path}?{urlencode(query_params)}"
    return path


class McpRepository:
    def run_handler(
        self,
        *,
        method: str,
        subpath: str,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        dispatch: Callable[..., bool | None],
    ) -> Response:
        body_bytes = json.dumps(body or {}).encode("utf-8")
        return run_legacy_dispatch_sync(
            method=method,
            path=_mcp_legacy_path(subpath, query_params),
            headers=headers,
            body=body_bytes,
            dispatch=dispatch,
        )
