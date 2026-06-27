"""Background, btw, and goal agent action service."""

from __future__ import annotations

import json
from typing import Any

from starlette.responses import Response

from app.core.legacy_handler import run_legacy_dispatch_sync


class AgentActionsService:
    def background_status(self, session_id: str) -> tuple[dict[str, Any], int]:
        if not session_id:
            return {"error": "Missing session_id"}, 400
        from app.domain.background import get_results

        return {"results": get_results(session_id)}, 200

    def _run_post(
        self,
        *,
        legacy_path: str,
        body: dict[str, Any],
        headers: dict[str, str] | None,
        handler_fn,
    ) -> Response:
        def _dispatch(handler, _parsed) -> None:
            handler_fn(handler, body)

        return run_legacy_dispatch_sync(
            method="POST",
            path=legacy_path,
            headers=headers,
            body=json.dumps(body).encode("utf-8"),
            dispatch=_dispatch,
        )

    def run_background(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        from app.domain.routes import _handle_background

        return self._run_post(
            legacy_path="/api/background",
            body=body,
            headers=headers,
            handler_fn=_handle_background,
        )

    def run_btw(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        from app.domain.routes import _handle_btw

        return self._run_post(
            legacy_path="/api/btw",
            body=body,
            headers=headers,
            handler_fn=_handle_btw,
        )

    def run_goal(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        from app.domain.routes import _handle_goal_command

        return self._run_post(
            legacy_path="/api/goal",
            body=body,
            headers=headers,
            handler_fn=_handle_goal_command,
        )
