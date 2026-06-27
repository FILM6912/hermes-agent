"""Native chat control service (FastAPI phase 3).

Owns POST /api/v1/chat/start, GET /api/v1/chat/cancel, POST /api/v1/chat/steer,
and GET /api/v1/chat/stream/status while legacy ``/api/chat/*`` routes delegate
through the same helpers where applicable.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.responses import Response

from app.core.legacy_handler import run_legacy_dispatch_sync

logger = logging.getLogger(__name__)


class ChatControlService:
    def start_chat(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Start a streaming chat turn (POST /api/v1/chat/start)."""
        from app.domain.request_diagnostics import RequestDiagnostics
        from app.domain.routes import _handle_chat_start

        diag = RequestDiagnostics.maybe_start("POST", "/api/v1/chat/start", logger=logger)
        payload = body if isinstance(body, dict) else {}

        def _dispatch(handler, parsed) -> None:
            _handle_chat_start(handler, payload, diag=diag)

        return run_legacy_dispatch_sync(
            method="POST",
            path="/api/chat/start",
            headers=headers,
            body=json.dumps(payload).encode("utf-8"),
            dispatch=_dispatch,
        )

    def cancel_chat(self, stream_id: str) -> tuple[dict[str, Any], int]:
        """Cancel an in-flight chat stream (GET /api/v1/chat/cancel)."""
        from app.domain.chat_streaming import cancel_chat_stream

        return cancel_chat_stream(stream_id)

    def chat_sync(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Legacy synchronous chat POST (POST /api/v1/chat)."""
        from app.domain.routes import _handle_chat_sync

        payload = body if isinstance(body, dict) else {}

        def _dispatch(handler, parsed) -> None:
            _handle_chat_sync(handler, payload)

        return run_legacy_dispatch_sync(
            method="POST",
            path="/api/chat",
            headers=headers,
            body=json.dumps(payload).encode("utf-8"),
            dispatch=_dispatch,
        )

    def steer_chat(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Inject mid-turn steer text (POST /api/v1/chat/steer)."""
        payload = body if isinstance(body, dict) else {}

        def _dispatch(handler, parsed) -> None:
            from app.domain.streaming import _handle_chat_steer

            _handle_chat_steer(handler, payload)

        return run_legacy_dispatch_sync(
            method="POST",
            path="/api/chat/steer",
            headers=headers,
            body=json.dumps(payload).encode("utf-8"),
            dispatch=_dispatch,
        )

    def stream_status(self, stream_id: str) -> dict[str, Any]:
        """Poll chat stream lifecycle state (GET /api/v1/chat/stream/status)."""
        from app.domain.chat_streaming import chat_stream_status_payload

        return chat_stream_status_payload(stream_id)
