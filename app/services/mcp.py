"""MCP service — native FastAPI cutover over api.routes MCP handlers."""

from __future__ import annotations

from typing import Any

from starlette.responses import Response

from app.repositories.mcp import McpRepository


class McpService:
    def __init__(self, repository: McpRepository | None = None) -> None:
        self._repo = repository or McpRepository()

    def list_servers(
        self,
        *,
        query_params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_mcp_servers_list

            _handle_mcp_servers_list(handler, parsed)

        return self._repo.run_handler(
            method="GET",
            subpath="servers",
            query_params=query_params,
            headers=headers,
            dispatch=_dispatch,
        )

    def list_tools(
        self,
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_mcp_tools_list

            _handle_mcp_tools_list(handler)

        return self._repo.run_handler(
            method="GET",
            subpath="tools",
            headers=headers,
            dispatch=_dispatch,
        )

    def discover(
        self,
        body: dict[str, Any],
        *,
        query_params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_mcp_discover

            _handle_mcp_discover(handler, parsed, body)

        return self._repo.run_handler(
            method="POST",
            subpath="discover",
            query_params=query_params,
            headers=headers,
            body=body,
            dispatch=_dispatch,
        )

    def test_server(
        self,
        name: str,
        body: dict[str, Any],
        *,
        query_params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_mcp_server_test

            _handle_mcp_server_test(handler, name, parsed, body)

        return self._repo.run_handler(
            method="POST",
            subpath=f"servers/{name}/test",
            query_params=query_params,
            headers=headers,
            body=body,
            dispatch=_dispatch,
        )

    def import_servers(
        self,
        body: dict[str, Any],
        *,
        query_params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_mcp_servers_import

            _handle_mcp_servers_import(handler, parsed, body)

        return self._repo.run_handler(
            method="POST",
            subpath="servers/import",
            query_params=query_params,
            headers=headers,
            body=body,
            dispatch=_dispatch,
        )

    def update_server(
        self,
        name: str,
        body: dict[str, Any],
        *,
        query_params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_mcp_server_update

            _handle_mcp_server_update(handler, name, body, parsed)

        return self._repo.run_handler(
            method="PUT",
            subpath=f"servers/{name}",
            query_params=query_params,
            headers=headers,
            body=body,
            dispatch=_dispatch,
        )

    def toggle_server(
        self,
        name: str,
        body: dict[str, Any],
        *,
        query_params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_mcp_server_toggle

            _handle_mcp_server_toggle(handler, name, body, parsed)

        return self._repo.run_handler(
            method="PATCH",
            subpath=f"servers/{name}",
            query_params=query_params,
            headers=headers,
            body=body,
            dispatch=_dispatch,
        )

    def delete_server(
        self,
        name: str,
        body: dict[str, Any],
        *,
        query_params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_mcp_server_delete

            _handle_mcp_server_delete(handler, name, parsed, body)

        return self._repo.run_handler(
            method="DELETE",
            subpath=f"servers/{name}",
            query_params=query_params,
            headers=headers,
            body=body,
            dispatch=_dispatch,
        )
