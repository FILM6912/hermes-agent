"""Proxy Supabase Storage REST API through Hermes WebUI."""

from __future__ import annotations

import logging
from typing import Iterable

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.core.outbound_proxy import outbound_proxy_settings

logger = logging.getLogger(__name__)

STORAGE_PREFIX = "/storage/v1"

_FORWARD_REQUEST_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "if-modified-since",
        "if-none-match",
        "range",
    }
)
_FORWARD_RESPONSE_HEADERS = frozenset(
    {
        "accept-ranges",
        "cache-control",
        "content-disposition",
        "content-length",
        "content-range",
        "content-type",
        "etag",
        "last-modified",
    }
)

router = APIRouter(prefix=STORAGE_PREFIX, tags=["storage-proxy"])


def is_supabase_storage_path(path: str) -> bool:
    return path == STORAGE_PREFIX or path.startswith(STORAGE_PREFIX + "/")


def is_supabase_storage_public_path(path: str) -> bool:
    return path.startswith(STORAGE_PREFIX + "/object/public/")


def supabase_storage_proxy_enabled() -> bool:
    try:
        from app.document_api.core.config import get_settings

        return bool(get_settings().supabase_url.strip())
    except Exception:
        return False


def build_upstream_storage_url(*, supabase_url: str, request_path: str, query: str) -> str:
    base = supabase_url.rstrip("/")
    if not request_path.startswith(STORAGE_PREFIX):
        raise ValueError(f"expected path under {STORAGE_PREFIX}, got {request_path!r}")
    suffix = request_path[len(STORAGE_PREFIX) :] or ""
    upstream = f"{base}{STORAGE_PREFIX}{suffix}"
    if query:
        upstream = f"{upstream}?{query}"
    return upstream


def _filtered_request_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        if key.lower() in _FORWARD_REQUEST_HEADERS:
            headers[key] = value
    return headers


def _filtered_response_headers(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers:
        lower = key.lower()
        if lower in _FORWARD_RESPONSE_HEADERS:
            out[key] = value
    return out


def _httpx_client_kwargs() -> dict:
    kwargs: dict = {"follow_redirects": True, "timeout": httpx.Timeout(60.0)}
    proxy = outbound_proxy_settings()
    http_proxy = proxy.get("http", "").strip()
    https_proxy = proxy.get("https", http_proxy).strip()
    proxy_url = https_proxy or http_proxy
    if proxy_url:
        kwargs["proxy"] = proxy_url
    return kwargs


async def proxy_storage_request(request: Request) -> Response:
    if not supabase_storage_proxy_enabled():
        return JSONResponse(
            status_code=503,
            content={
                "error": "Supabase storage proxy is not configured",
                "detail": "Set SUPABASE_URL to enable /storage/v1 proxying",
            },
        )

    from app.document_api.core.config import get_settings

    settings = get_settings()
    upstream_url = build_upstream_storage_url(
        supabase_url=settings.supabase_url,
        request_path=request.url.path,
        query=request.url.query,
    )

    headers = _filtered_request_headers(request)
    is_public = is_supabase_storage_public_path(request.url.path)
    if not is_public and (settings.supabase_service_key or "").strip():
        key = settings.supabase_service_key.strip()
        headers.setdefault("Authorization", f"Bearer {key}")
        headers.setdefault("apikey", key)

    method = request.method.upper()
    try:
        async with httpx.AsyncClient(**_httpx_client_kwargs()) as client:
            upstream = await client.request(
                method,
                upstream_url,
                headers=headers,
            )
    except httpx.RequestError as exc:
        logger.warning("Supabase storage proxy upstream error: %s", exc)
        return JSONResponse(
            status_code=502,
            content={
                "error": "Supabase storage upstream unreachable",
                "detail": str(exc),
            },
        )

    response_headers = _filtered_response_headers(upstream.headers.multi_items())
    if method == "HEAD":
        return Response(status_code=upstream.status_code, headers=response_headers)

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )


@router.api_route("", methods=["GET", "HEAD"], include_in_schema=False)
@router.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def supabase_storage_v1_proxy(request: Request, path: str = "") -> Response:
    return await proxy_storage_request(request)
