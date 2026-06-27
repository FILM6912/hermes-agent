"""Native FastAPI MCP endpoints (McpService)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from starlette.responses import Response

from app.services.mcp import McpService

router = APIRouter(tags=["mcp"])
_service = McpService()

_JsonBody = Annotated[dict[str, Any], Body()]


@router.get("/mcp/servers")
def list_mcp_servers(request: Request) -> Response:
    return _service.list_servers(
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )


@router.get("/mcp/tools")
def list_mcp_tools(request: Request) -> Response:
    return _service.list_tools(headers=dict(request.headers))


@router.post("/mcp/discover")
def discover_mcp_servers(request: Request, body: _JsonBody = {}) -> Response:
    return _service.discover(
        body,
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )


@router.post("/mcp/servers/{name}/test")
def test_mcp_server(name: str, request: Request, body: _JsonBody = {}) -> Response:
    return _service.test_server(
        name,
        body,
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )


@router.post("/mcp/servers/import")
def import_mcp_servers(request: Request, body: _JsonBody = {}) -> Response:
    return _service.import_servers(
        body,
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )


@router.put("/mcp/servers/{name}")
def update_mcp_server(name: str, request: Request, body: _JsonBody = {}) -> Response:
    return _service.update_server(
        name,
        body,
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )


@router.patch("/mcp/servers/{name}")
def toggle_mcp_server(name: str, request: Request, body: _JsonBody = {}) -> Response:
    return _service.toggle_server(
        name,
        body,
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )


@router.delete("/mcp/servers/{name}")
def delete_mcp_server(name: str, request: Request, body: _JsonBody = {}) -> Response:
    return _service.delete_server(
        name,
        body,
        query_params=dict(request.query_params),
        headers=dict(request.headers),
    )
