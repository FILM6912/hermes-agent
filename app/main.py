"""
Hermes Web UI FastAPI application entry point.

Legacy api.routes handlers are bridged via app.core.legacy_handler until
Agent 2 migrates endpoints under app.api.v1.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.api.v1.router import root_router
from app.core.config import get_settings
from app.core.legacy_handler import handle_legacy_request
from app.core.network_isolation import install_test_network_block
from app.core.startup import run_shutdown, run_startup
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.security import (
    AcceptLoopMiddleware,
    AuthGateMiddleware,
    CorsOptionsMiddleware,
    CsrfMiddleware,
    ProfileContextMiddleware,
    SecurityHeadersMiddleware,
)

install_test_network_block()

_LEGACY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_startup(app)
    yield
    run_shutdown()


def _legacy_error_body(detail: object) -> dict[str, str]:
    message = detail if isinstance(detail, str) else str(detail)
    return {"error": message, "detail": message}


def _openapi_url_with_query(request: Request, base: str = "/openapi.json") -> str:
    token = request.query_params.get("access_token") or request.query_params.get("token")
    if not token:
        return base
    return f"{base}?{urlencode({'access_token': token})}"


def _configure_openapi(app: FastAPI) -> None:
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version="0.1.0",
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        schemes = components.setdefault("securitySchemes", {})
        schemes["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "description": "Session token from POST /api/v1/auth/login (Authorization: Bearer …)",
        }
        schemes["AccessTokenQuery"] = {
            "type": "apiKey",
            "in": "query",
            "name": "access_token",
            "description": "Same session token as query parameter (used when cookies are unavailable)",
        }
        schema["security"] = [{"BearerAuth": []}, {"AccessTokenQuery": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


_SWAGGER_REQUEST_INTERCEPTOR = """
      requestInterceptor: (req) => {
        const params = new URLSearchParams(window.location.search);
        const token = params.get('access_token') || params.get('token');
        if (token) {
          req.headers = req.headers || {};
          if (!req.headers.Authorization) {
            req.headers.Authorization = 'Bearer ' + token;
          }
          try {
            const url = new URL(req.url, window.location.origin);
            if (!url.searchParams.has('access_token') && !url.searchParams.has('token')) {
              url.searchParams.set('access_token', token);
              req.url = url.pathname + url.search;
            }
          } catch (_err) {
            /* keep original url */
          }
        }
        return req;
      },
"""


def _swagger_ui_html_with_session_token(request: Request, *, title: str) -> HTMLResponse:
    from fastapi.openapi.docs import get_swagger_ui_html

    response = get_swagger_ui_html(
        openapi_url=_openapi_url_with_query(request),
        title=title,
        swagger_ui_parameters={"persistAuthorization": True},
    )
    body = response.body.decode(response.charset or "utf-8")
    if "SwaggerUIBundle({" in body and "requestInterceptor:" not in body:
        body = body.replace("SwaggerUIBundle({", f"SwaggerUIBundle({{{_SWAGGER_REQUEST_INTERCEPTOR}", 1)
    return HTMLResponse(content=body, status_code=response.status_code)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Hermes Web UI", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.exception_handler(HTTPException)
    async def _http_exception_legacy(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_legacy_error_body(exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_legacy(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        if errors:
            first = errors[0]
            loc = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
            msg = str(first.get("msg") or "Invalid request")
            message = f"{loc}: {msg}" if loc else msg
        else:
            message = "Invalid request"
        return JSONResponse(
            status_code=400,
            content=_legacy_error_body(message),
        )
    app.state.accept_loop_requests_total = 0
    app.state.accept_loop_last_request_at = 0.0
    app.state.settings = settings

    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(AuthGateMiddleware)
    app.add_middleware(ProfileContextMiddleware)
    app.add_middleware(CorsOptionsMiddleware)
    app.add_middleware(AcceptLoopMiddleware)

    app.include_router(root_router)

    _configure_openapi(app)

    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui(request: Request) -> Response:
        return _swagger_ui_html_with_session_token(
            request,
            title=f"{app.title} - Swagger UI",
        )

    @app.get("/redoc", include_in_schema=False)
    async def custom_redoc_ui(request: Request) -> Response:
        from fastapi.openapi.docs import get_redoc_html

        return get_redoc_html(
            openapi_url=_openapi_url_with_query(request),
            title=f"{app.title} - ReDoc",
        )

    async def _dispatch(request: Request) -> Response:
        state = request.app.state
        return await handle_legacy_request(
            request,
            accept_loop_total=int(getattr(state, "accept_loop_requests_total", 0)),
            accept_loop_last_at=float(getattr(state, "accept_loop_last_request_at", 0.0)),
            skip_auth=True,
        )

    if settings.legacy_api:
        @app.api_route("/api/v1", methods=_LEGACY_METHODS, include_in_schema=False)
        @app.api_route("/api/v1/{path:path}", methods=_LEGACY_METHODS, include_in_schema=False)
        async def legacy_api_v1(request: Request, path: str = "") -> Response:
            return await _dispatch(request)

        @app.api_route("/api", methods=_LEGACY_METHODS, include_in_schema=False)
        @app.api_route("/api/{path:path}", methods=_LEGACY_METHODS, include_in_schema=False)
        async def legacy_api(request: Request, path: str = "") -> Response:
            return await _dispatch(request)

    @app.api_route("/", methods=_LEGACY_METHODS, include_in_schema=False)
    async def legacy_root(request: Request) -> Response:
        return await _dispatch(request)

    @app.api_route("/{path:path}", methods=_LEGACY_METHODS, include_in_schema=False)
    async def legacy_pages(request: Request, path: str) -> Response:
        if path.startswith("api/") or path.startswith("api"):
            return Response(status_code=404)
        return await _dispatch(request)

    return app


app = create_app()
