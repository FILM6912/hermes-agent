"""Document RAG API permission checks integrated with WebUI roles."""

from __future__ import annotations

import re
from typing import Final

from starlette.requests import Request

_DOCUMENT_API_PREFIXES: Final[tuple[str, ...]] = (
    "/api/v1/documents",
    "/api/v1/search",
    "/api/v1/jobs",
    "/api/v1/ingest-pending",
    "/api/v1/transcript-report",
    "/api/v1/rename/document",
    "/api/v1/rename/file",
)

# MCP search tools authenticate via Bearer (service key, per-user MCP key, or session).
_MCP_SEARCH_LIST_PATH = "/api/v1/search/documents"
_MCP_SEARCH_QUERY_PATH = "/api/v1/search"


def is_mcp_search_public_route(method: str, path: str) -> bool:
    """Deprecated — MCP search routes now require Bearer auth and RAG RBAC."""
    return False


def is_document_api_path(path: str) -> bool:
    normalized = path if path.startswith("/") else f"/{path}"
    if any(
        normalized == prefix or normalized.startswith(prefix + "/")
        for prefix in _DOCUMENT_API_PREFIXES
    ):
        return True
    match = re.match(r"^/api/v1/([^/]+)(?:/|$)", normalized)
    if not match:
        return False
    from app.document_api.integration import _WEBUI_V1_SEGMENTS

    return match.group(1) not in _WEBUI_V1_SEGMENTS


def _transcript_report_permission(method: str, path: str) -> str | None:
    normalized = path if path.startswith("/") else f"/{path}"
    verb = (method or "GET").upper()

    if normalized == "/api/v1/transcript-report" or normalized.startswith("/api/v1/transcript-report/"):
        if verb in {"GET", "HEAD"}:
            return "transcript-report:read"
        if verb == "DELETE":
            return "transcript-report:delete"
        if normalized.endswith("/process") and verb in {"POST", "PUT"}:
            return "transcript-report:edit"
        if normalized.endswith("/stream") and verb in {"POST", "PUT"}:
            return "transcript-report:create"
        if verb in {"POST", "PUT"}:
            return "transcript-report:create"
        return "transcript-report:edit"

    return None


def alternative_rag_permissions(method: str, path: str) -> tuple[str, ...]:
    """Extra permissions that also satisfy the route gate (e.g. shared job polling)."""
    normalized = path if path.startswith("/") else f"/{path}"
    verb = (method or "GET").upper()
    alts: list[str] = []
    if normalized.startswith("/api/v1/jobs") and verb in {"GET", "HEAD"}:
        alts.append("transcript-report:read")
    if normalized.startswith("/api/v1/jobs") and (
        "/cancel" in normalized or "/clear-error" in normalized or "/retry" in normalized
    ):
        alts.extend(["transcript-report:edit", "transcript-report:delete"])
    return tuple(alts)


def required_rag_permission(method: str, path: str) -> str | None:
    """Return the RAG permission required for this request, or None if unrestricted."""
    normalized = path if path.startswith("/") else f"/{path}"
    verb = (method or "GET").upper()

    transcript_perm = _transcript_report_permission(method, path)
    if transcript_perm is not None:
        return transcript_perm

    if normalized.startswith("/api/v1/ingest-pending"):
        if "/commit" in normalized and verb in {"POST", "PUT"}:
            return "rag:approve"
        if "/reject" in normalized and verb in {"POST", "PUT"}:
            return "rag:manage"
        if verb in {"GET", "HEAD"}:
            return "rag:ingest"
        return "rag:manage"

    if normalized.endswith("/ingest-pending") and verb in {"GET", "HEAD"}:
        return "rag:ingest"

    if normalized.startswith("/api/v1/search"):
        if verb in {"GET", "HEAD", "POST"}:
            return "rag:search"
        return "rag:manage"

    if normalized.startswith("/api/v1/jobs"):
        if verb in {"GET", "HEAD"}:
            return "rag:ingest"
        if "/cancel" in normalized or "/clear-error" in normalized or "/retry" in normalized:
            return "rag:manage"
        return "rag:ingest"

    if "/stream" in normalized and verb in {"POST", "PUT"}:
        return "rag:ingest"

    if "/ingest" in normalized and verb in {"POST", "PUT"}:
        return "rag:ingest"

    if normalized.startswith("/api/v1/documents") or _looks_like_document_set_path(normalized):
        if verb in {"GET", "HEAD"}:
            return "rag:search"
        return "rag:manage"

    if normalized.startswith("/api/v1/rename/"):
        return "rag:manage"

    return "rag:search"


def _looks_like_document_set_path(path: str) -> bool:
    """Match dynamic document routes mounted at /api/v1/{document_name}/..."""
    match = re.match(r"^/api/v1/([^/]+)(?:/(.+))?$", path)
    if not match:
        return False
    segment = match.group(1)
    from app.document_api.integration import _WEBUI_V1_SEGMENTS

    return segment not in _WEBUI_V1_SEGMENTS


def document_api_requires_rbac() -> bool:
    """RAG routes honor role permissions when WebUI auth + multi-user are active."""
    from app.core.security import is_auth_enabled
    from app.domain.users import is_multi_user_enabled

    return bool(is_auth_enabled() and is_multi_user_enabled())


def check_document_api_access(request: Request):
    """Return a JSON Response when access is denied, else None."""
    from starlette.responses import JSONResponse

    from app.core.security import get_current_user, user_has_permission

    path = request.url.path
    if is_mcp_search_public_route(request.method, path):
        return None

    if not document_api_requires_rbac():
        return None

    if not is_document_api_path(path):
        return None

    user = get_current_user(request)
    if user is None:
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    permission = required_rag_permission(request.method, path)
    if permission and user_has_permission(user, permission):
        return None
    alts = alternative_rag_permissions(request.method, path)
    if permission and any(user_has_permission(user, alt) for alt in alts):
        return None
    if permission:
        return JSONResponse(
            {"error": f"Permission required: {permission}"},
            status_code=403,
        )
    return None
