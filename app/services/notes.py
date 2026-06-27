"""External notes/knowledge source service."""

from __future__ import annotations

from urllib.parse import urlencode

from starlette.responses import Response

from app.core.legacy_handler import run_legacy_dispatch_sync


class NotesService:
    def _run_get(
        self,
        *,
        legacy_path: str,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        handler_fn,
    ) -> Response:
        path = legacy_path
        if query_params:
            path = f"{path}?{urlencode(query_params)}"

        def _dispatch(handler, parsed) -> None:
            handler_fn(handler, parsed)

        return run_legacy_dispatch_sync(
            method="GET",
            path=path,
            headers=headers,
            dispatch=_dispatch,
        )

    def list_sources(self, *, headers: dict[str, str] | None = None) -> Response:
        from app.domain.routes import _handle_notes_sources_list

        return self._run_get(
            legacy_path="/api/notes/sources",
            headers=headers,
            handler_fn=lambda handler, _parsed: _handle_notes_sources_list(handler),
        )

    def search(
        self,
        *,
        query_params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> Response:
        from app.domain.routes import _handle_notes_search

        return self._run_get(
            legacy_path="/api/notes/search",
            query_params=query_params,
            headers=headers,
            handler_fn=_handle_notes_search,
        )

    def get_item(
        self,
        *,
        query_params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> Response:
        from app.domain.routes import _handle_notes_item

        return self._run_get(
            legacy_path="/api/notes/item",
            query_params=query_params,
            headers=headers,
            handler_fn=_handle_notes_item,
        )
