"""Regression tests for #1909 CSP report-only security header."""

import io
import json
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

import app.domain.routes as routes
from app.middleware.security import (
    _CSP_REPORT_TO,
    build_csp_report_only_policy,
)


def _send_csp_report_only_headers(handler) -> None:
    handler.send_header(
        "Content-Security-Policy-Report-Only",
        build_csp_report_only_policy(),
    )
    handler.send_header("Report-To", _CSP_REPORT_TO)


def test_handler_adds_content_security_policy_report_only(monkeypatch):
    sent_headers = []
    handler = SimpleNamespace()
    handler.send_header = lambda key, value: sent_headers.append((key, value))
    monkeypatch.setattr(BaseHTTPRequestHandler, "end_headers", lambda self: None)

    _send_csp_report_only_headers(handler)

    headers = dict(sent_headers)
    assert "Content-Security-Policy-Report-Only" in headers
    assert "Report-To" in headers
    assert "Content-Security-Policy" not in headers
    policy = headers["Content-Security-Policy-Report-Only"]
    assert "default-src 'self'" in policy
    assert "object-src 'none'" in policy
    assert "frame-ancestors 'self'" in policy
    assert "base-uri 'self'" in policy
    assert "report-uri /api/csp-report" in policy
    assert "report-to csp-endpoint" in policy
    assert json.loads(headers["Report-To"]) == {
        "group": "csp-endpoint",
        "max_age": 10886400,
        "endpoints": [{"url": "/api/csp-report"}],
    }


def test_csp_report_only_keeps_legacy_inline_allowances_for_current_ui():
    policy = build_csp_report_only_policy()

    assert "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.jsdelivr.net" in policy
    assert "worker-src 'self' blob:" in policy
    assert (
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com"
        in policy
    )
    assert "font-src 'self' data: https://fonts.gstatic.com" in policy
    # unsafe-eval was dropped after Opus stage-339 verification.
    assert "'unsafe-eval'" not in policy
    assert "img-src 'self' data: blob:" in policy
    assert "connect-src 'self'" in policy


class _FakeHandler:
    def __init__(self, body=b"{}", headers=None, client_ip="203.0.113.10"):
        self.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": "application/csp-report",
            **(headers or {}),
        }
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.client_address = (client_ip, 54321)
        self.status = None
        self.sent_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent_headers[key] = value

    def end_headers(self):
        pass


def test_csp_report_endpoint_accepts_report_uri_payload_without_csrf(monkeypatch, caplog):
    routes._CSP_REPORT_RATE_LIMIT.clear()
    payload = {
        "csp-report": {
            "document-uri": "http://127.0.0.1:8787/",
            "violated-directive": "script-src-elem",
            "blocked-uri": "inline",
        }
    }
    handler = _FakeHandler(json.dumps(payload).encode("utf-8"))

    def fail_if_called(_handler):
        raise AssertionError("CSP reports must bypass the normal CSRF gate")

    monkeypatch.setattr(routes, "_check_csrf", fail_if_called)

    with caplog.at_level("INFO", logger="csp_report"):
        assert routes.handle_post(handler, SimpleNamespace(path="/api/csp-report")) is True

    assert handler.status == 204
    assert handler.sent_headers["Content-Length"] == "0"
    assert "violated-directive" in caplog.text


def test_csp_report_endpoint_accepts_report_to_array_payload():
    routes._CSP_REPORT_RATE_LIMIT.clear()
    payload = [
        {
            "type": "csp-violation",
            "url": "http://127.0.0.1:8787/",
            "body": {"blockedURL": "https://example.invalid/script.js"},
        }
    ]
    handler = _FakeHandler(
        json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/reports+json"},
    )

    assert routes.handle_post(handler, SimpleNamespace(path="/api/csp-report")) is True

    assert handler.status == 204
    assert handler.sent_headers["Content-Length"] == "0"


def test_csp_report_endpoint_rate_limits_by_client_ip(monkeypatch):
    routes._CSP_REPORT_RATE_LIMIT.clear()
    monkeypatch.setattr(routes, "_CSP_REPORT_RATE_LIMIT_MAX", 1)
    first = _FakeHandler(b"{}", client_ip="203.0.113.11")
    second = _FakeHandler(b"{}", client_ip="203.0.113.11")

    assert routes.handle_post(first, SimpleNamespace(path="/api/csp-report")) is True
    assert routes.handle_post(second, SimpleNamespace(path="/api/csp-report")) is True

    assert first.status == 204
    assert second.status == 204
    assert second.rfile.tell() == 0


def test_auth_gate_bypasses_csp_report(monkeypatch):
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import Response
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from app.middleware.security import AuthGateMiddleware

    def fail_auth(_request):
        raise AssertionError("CSP report collector must not require auth")

    monkeypatch.setattr("app.middleware.security.check_auth_request", fail_auth)

    async def csp_report(_request):
        return Response(status_code=204)

    app = Starlette(
        middleware=[Middleware(AuthGateMiddleware)],
        routes=[Route("/api/csp-report", csp_report, methods=["POST"])],
    )

    with TestClient(app) as client:
        response = client.post("/api/csp-report")

    assert response.status_code == 204
