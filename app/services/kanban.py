"""Kanban service — thin dispatch over api.kanban_bridge."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from starlette.responses import Response

from app.core.legacy_handler import run_legacy_dispatch_sync


class KanbanService:
    def dispatch(
        self,
        *,
        method: str,
        subpath: str,
        query_params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        normalized = subpath.strip("/")
        legacy_path = f"/api/kanban/{normalized}" if normalized else "/api/kanban"
        if query_params:
            legacy_path = f"{legacy_path}?{urlencode(query_params)}"
        body_bytes = json.dumps(body or {}).encode("utf-8")
        method_upper = method.upper()

        def _dispatch(handler, parsed) -> None:
            from app.domain.kanban_bridge import (
                handle_kanban_delete,
                handle_kanban_get,
                handle_kanban_patch,
                handle_kanban_post,
            )
            from app.domain.routes import _kanban_unknown_endpoint

            payload = body if isinstance(body, dict) else {}
            if method_upper == "GET":
                result = handle_kanban_get(handler, parsed)
            elif method_upper == "POST":
                result = handle_kanban_post(handler, parsed, payload)
            elif method_upper == "PATCH":
                result = handle_kanban_patch(handler, parsed, payload)
            elif method_upper == "DELETE":
                result = handle_kanban_delete(handler, parsed, payload)
            else:
                result = False

            if result is False:
                _kanban_unknown_endpoint(handler, parsed, method_upper)

        return run_legacy_dispatch_sync(
            method=method_upper,
            path=legacy_path,
            headers=headers,
            body=body_bytes,
            dispatch=_dispatch,
        )
