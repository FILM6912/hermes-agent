"""Cron service — native FastAPI cutover over api.routes cron handlers."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from starlette.responses import Response

from app.core.legacy_handler import run_legacy_dispatch_sync


def _crons_legacy_path(subpath: str, query_params: dict[str, str] | None = None) -> str:
    normalized = subpath.strip("/")
    path = f"/api/crons/{normalized}" if normalized else "/api/crons"
    if query_params:
        path = f"{path}?{urlencode(query_params)}"
    return path


def _run_cron_dispatch(
    *,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
    dispatch,
) -> Response:
    def _wrapped(handler, parsed) -> None:
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            dispatch(handler, parsed)

    return run_legacy_dispatch_sync(
        method=method,
        path=path,
        headers=headers,
        body=body,
        dispatch=_wrapped,
    )


class CronsService:
    def list_crons(self) -> dict[str, Any]:
        from cron.jobs import list_jobs
        from app.domain.profiles import cron_profile_context
        from app.domain.routes import _cron_jobs_for_api

        with cron_profile_context():
            return {"jobs": _cron_jobs_for_api(list_jobs(include_disabled=True))}

    def cron_output(
        self,
        query_params: dict[str, str],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_cron_output

            _handle_cron_output(handler, parsed)

        return _run_cron_dispatch(
            method="GET",
            path=_crons_legacy_path("output", query_params),
            headers=headers,
            dispatch=_dispatch,
        )

    def cron_history(
        self,
        query_params: dict[str, str],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_cron_history

            _handle_cron_history(handler, parsed)

        return _run_cron_dispatch(
            method="GET",
            path=_crons_legacy_path("history", query_params),
            headers=headers,
            dispatch=_dispatch,
        )

    def cron_run_detail(
        self,
        query_params: dict[str, str],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_cron_run_detail

            _handle_cron_run_detail(handler, parsed)

        return _run_cron_dispatch(
            method="GET",
            path=_crons_legacy_path("run", query_params),
            headers=headers,
            dispatch=_dispatch,
        )

    def cron_recent(
        self,
        query_params: dict[str, str],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_cron_recent

            _handle_cron_recent(handler, parsed)

        return _run_cron_dispatch(
            method="GET",
            path=_crons_legacy_path("recent", query_params),
            headers=headers,
            dispatch=_dispatch,
        )

    def cron_status(
        self,
        query_params: dict[str, str],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_cron_status

            _handle_cron_status(handler, parsed)

        return _run_cron_dispatch(
            method="GET",
            path=_crons_legacy_path("status", query_params),
            headers=headers,
            dispatch=_dispatch,
        )

    def cron_delivery_options(
        self,
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_cron_delivery_options

            _handle_cron_delivery_options(handler)

        return _run_cron_dispatch(
            method="GET",
            path=_crons_legacy_path("delivery-options"),
            headers=headers,
            dispatch=_dispatch,
        )

    def cron_create(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_cron_create

            _handle_cron_create(handler, body)

        return _run_cron_dispatch(
            method="POST",
            path=_crons_legacy_path("create"),
            headers=headers,
            body=json.dumps(body).encode("utf-8"),
            dispatch=_dispatch,
        )

    def cron_update(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_cron_update

            _handle_cron_update(handler, body)

        return _run_cron_dispatch(
            method="POST",
            path=_crons_legacy_path("update"),
            headers=headers,
            body=json.dumps(body).encode("utf-8"),
            dispatch=_dispatch,
        )

    def cron_delete(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_cron_delete

            _handle_cron_delete(handler, body)

        return _run_cron_dispatch(
            method="POST",
            path=_crons_legacy_path("delete"),
            headers=headers,
            body=json.dumps(body).encode("utf-8"),
            dispatch=_dispatch,
        )

    def cron_run(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_cron_run

            _handle_cron_run(handler, body)

        return _run_cron_dispatch(
            method="POST",
            path=_crons_legacy_path("run"),
            headers=headers,
            body=json.dumps(body).encode("utf-8"),
            dispatch=_dispatch,
        )

    def cron_pause(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_cron_pause

            _handle_cron_pause(handler, body)

        return _run_cron_dispatch(
            method="POST",
            path=_crons_legacy_path("pause"),
            headers=headers,
            body=json.dumps(body).encode("utf-8"),
            dispatch=_dispatch,
        )

    def cron_resume(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_cron_resume

            _handle_cron_resume(handler, body)

        return _run_cron_dispatch(
            method="POST",
            path=_crons_legacy_path("resume"),
            headers=headers,
            body=json.dumps(body).encode("utf-8"),
            dispatch=_dispatch,
        )
