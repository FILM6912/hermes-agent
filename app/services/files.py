"""Files service — native dispatch over api.routes file handlers."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from starlette.responses import Response

from app.core.legacy_handler import run_legacy_dispatch_sync


class FileService:
    def read_file(
        self,
        *,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_get(
            "/api/file",
            query_params=query_params,
            headers=headers,
        )

    def read_file_raw(
        self,
        *,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_get(
            "/api/file/raw",
            query_params=query_params,
            headers=headers,
        )

    def view_file(
        self,
        *,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_get(
            "/api/file/view",
            query_params=query_params,
            headers=headers,
        )

    def folder_download(
        self,
        *,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_get(
            "/api/folder/download",
            query_params=query_params,
            headers=headers,
        )

    def media(
        self,
        *,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_get(
            "/api/media",
            query_params=query_params,
            headers=headers,
        )

    def save_file(
        self,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_post(
            "/api/file/save",
            body=body,
            headers=headers,
        )

    def delete_file(
        self,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_post(
            "/api/file/delete",
            body=body,
            headers=headers,
        )

    def create_file(
        self,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_post(
            "/api/file/create",
            body=body,
            headers=headers,
        )

    def rename_file(
        self,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_post(
            "/api/file/rename",
            body=body,
            headers=headers,
        )

    def move_file(
        self,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_post(
            "/api/file/move",
            body=body,
            headers=headers,
        )

    def create_dir(
        self,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_post(
            "/api/file/create-dir",
            body=body,
            headers=headers,
        )

    def reveal_file(
        self,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_post(
            "/api/file/reveal",
            body=body,
            headers=headers,
        )

    def file_path(
        self,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_post(
            "/api/file/path",
            body=body,
            headers=headers,
        )

    def open_vscode(
        self,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return self._dispatch_post(
            "/api/file/open-vscode",
            body=body,
            headers=headers,
        )

    def _dispatch_get(
        self,
        legacy_path: str,
        *,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        path = legacy_path
        if query_params:
            path = f"{path}?{urlencode(query_params)}"

        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import (
                _handle_file_raw,
                _handle_file_read,
                _handle_file_view,
                _handle_folder_download,
                _handle_media,
            )

            if legacy_path == "/api/file":
                _handle_file_read(handler, parsed)
            elif legacy_path == "/api/file/raw":
                _handle_file_raw(handler, parsed)
            elif legacy_path == "/api/file/view":
                _handle_file_view(handler, parsed)
            elif legacy_path == "/api/folder/download":
                _handle_folder_download(handler, parsed)
            elif legacy_path == "/api/media":
                _handle_media(handler, parsed)

        return run_legacy_dispatch_sync(
            method="GET",
            path=path,
            headers=headers,
            dispatch=_dispatch,
        )

    def _dispatch_post(
        self,
        legacy_path: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        body_bytes = json.dumps(body or {}).encode("utf-8")

        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import (
                _handle_create_dir,
                _handle_file_create,
                _handle_file_delete,
                _handle_file_move,
                _handle_file_open_vscode,
                _handle_file_path,
                _handle_file_rename,
                _handle_file_reveal,
                _handle_file_save,
            )

            payload = body if isinstance(body, dict) else {}
            if legacy_path == "/api/file/save":
                _handle_file_save(handler, payload)
            elif legacy_path == "/api/file/delete":
                _handle_file_delete(handler, payload)
            elif legacy_path == "/api/file/create":
                _handle_file_create(handler, payload)
            elif legacy_path == "/api/file/rename":
                _handle_file_rename(handler, payload)
            elif legacy_path == "/api/file/move":
                _handle_file_move(handler, payload)
            elif legacy_path == "/api/file/create-dir":
                _handle_create_dir(handler, payload)
            elif legacy_path == "/api/file/reveal":
                _handle_file_reveal(handler, payload)
            elif legacy_path == "/api/file/path":
                _handle_file_path(handler, payload)
            elif legacy_path == "/api/file/open-vscode":
                _handle_file_open_vscode(handler, payload)

        return run_legacy_dispatch_sync(
            method="POST",
            path=legacy_path,
            headers=headers,
            body=body_bytes,
            dispatch=_dispatch,
        )
