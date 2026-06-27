"""Mount document API search/list endpoints as MCP tools (fastapi-mcp)."""

from __future__ import annotations

import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_mcp_mounted = False


def normalized_mcp_mount_path() -> str | None:
    """Return configured MCP HTTP mount path when MCP is enabled, else None."""
    from app.document_api.core.config import get_settings
    from app.document_api.integration import document_api_enabled

    settings = get_settings()
    if not settings.mcp_enabled or not document_api_enabled():
        return None
    mount_path = (settings.mcp_mount_path or "/mcp").strip() or "/mcp"
    if not mount_path.startswith("/"):
        mount_path = f"/{mount_path}"
    return mount_path.rstrip("/") or "/mcp"


def is_mcp_mount_path(path: str) -> bool:
    """True when path targets the mounted Streamable HTTP MCP endpoint."""
    mount_path = normalized_mcp_mount_path()
    if not mount_path:
        return False
    return path == mount_path or path.startswith(mount_path + "/")


def is_mcp_public_path(path: str) -> bool:
    """Backward-compatible alias — MCP mount paths are no longer public."""
    return False


def mount_document_mcp(app: FastAPI) -> str | None:
    """Mount FastApiMCP when MCP_ENABLED and document API are active. Returns mount path or None."""
    global _mcp_mounted
    if _mcp_mounted:
        return None

    from app.document_api.core.config import get_settings
    from app.document_api.integration import document_api_enabled

    settings = get_settings()
    if not settings.mcp_enabled:
        return None
    if not document_api_enabled():
        logger.warning("MCP_ENABLED=true but document API is unavailable — skipping MCP mount")
        return None

    try:
        from fastapi_mcp import FastApiMCP
    except ImportError:
        logger.warning("MCP_ENABLED=true but fastapi-mcp is not installed — skipping MCP mount")
        return None

    mount_path = (settings.mcp_mount_path or "/mcp").strip() or "/mcp"
    if not mount_path.startswith("/"):
        mount_path = f"/{mount_path}"

    mcp = FastApiMCP(
        app,
        name="Hermes Document API",
        description="Document search and list-with-summary tools for Hermes WebUI",
        include_tags=["search"],
    )
    mcp.mount_http(mount_path=mount_path)
    _mcp_mounted = True
    from app.document_api.mcp_auth import warn_if_mcp_auth_misconfigured

    warn_if_mcp_auth_misconfigured()
    print(f"[document-api] MCP mounted at {mount_path} (tag=search, Bearer auth required)", flush=True)
    return mount_path
