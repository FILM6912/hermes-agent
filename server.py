"""
Hermes Web UI -- deprecated thin uvicorn launcher (rollback path).

Primary entrypoint: ``python -m uvicorn app.main:app --host HOST --port PORT``
(or ``bootstrap.py`` / ``docker_init.bash``, which prefer uvicorn when safe).

This module remains for rollback and Windows ``start.ps1`` compatibility.
Business logic lives in app.domain/*; HTTP serving is handled by app.main:app.
"""
from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler

try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]

from app.domain.updates import WEBUI_VERSION
from app.middleware.security import (
    _CSP_REPORT_TO,
    build_csp_report_only_policy,
)

_VER_SUFFIX = WEBUI_VERSION.removeprefix("v")
SERVER_VERSION = (
    ("HermesWebUI/" + _VER_SUFFIX) if _VER_SUFFIX != "unknown" else "HermesWebUI"
)


def configure_accepted_connection_tcp_keepalive(sock) -> None:
    """Per-connection TCP keepalive for idle HTTP keep-alive sockets (#1581)."""
    import socket as _socket

    try:
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1)
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPIDLE, 10)
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPINTVL, 5)
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPCNT, 3)
    except (OSError, AttributeError):
        pass


class Handler(BaseHTTPRequestHandler):
    """Backward-compatible shim for tests that import Handler from server.py."""

    _CSP_REPORT_TO = _CSP_REPORT_TO

    @classmethod
    def csp_report_only_policy(cls) -> str:
        return build_csp_report_only_policy()

    def end_headers(self) -> None:
        self.send_header("Content-Security-Policy-Report-Only", self.csp_report_only_policy())
        self.send_header("Report-To", self._CSP_REPORT_TO)
        super().end_headers()

    def log_message(self, fmt, *args) -> None:
        return None

    def do_PATCH(self) -> None:
        """ThreadingHTTPServer hook retained for regression tests; use app.main."""

    def do_DELETE(self) -> None:
        """ThreadingHTTPServer hook retained for regression tests; use app.main."""

    # Historical dispatch: self._handle_write(handle_patch) / handle_delete

    def log_request(self, code: str = "-", size: str = "-") -> None:
        duration_ms = round((time.time() - getattr(self, "_req_t0", time.time())) * 1000, 1)
        remote = "-"
        try:
            if getattr(self, "client_address", None):
                remote = str(self.client_address[0])
        except Exception:
            remote = "-"
        forwarded_for = None
        try:
            forwarded_for = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or None
        except Exception:
            forwarded_for = None
        record_data = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "remote": remote,
            "method": getattr(self, "command", None) or "-",
            "path": getattr(self, "path", None) or "-",
            "status": int(code) if str(code).isdigit() else code,
            "ms": duration_ms,
        }
        if forwarded_for:
            record_data["forwarded_for"] = forwarded_for
        print(f"[webui] {json.dumps(record_data)}", flush=True)


def _raise_fd_soft_limit(target: int = 4096) -> dict:
    """Best-effort raise of RLIMIT_NOFILE for persistent WebUI hosts."""
    if resource is None:
        return {"status": "unsupported"}
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    desired = int(target)
    if hard not in (-1, getattr(resource, "RLIM_INFINITY", object())):
        desired = min(desired, int(hard))
    if soft >= desired:
        return {"status": "unchanged", "soft": soft, "hard": hard}
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (desired, hard))
    except Exception as exc:
        return {"status": "error", "soft": soft, "hard": hard, "error": str(exc)}
    return {"status": "raised", "soft": desired, "hard": hard, "previous_soft": soft}


def _warn_non_loopback_without_auth(host: str) -> None:
    from app.domain.auth import is_auth_enabled

    if host not in ("127.0.0.1", "::1", "localhost") and not is_auth_enabled():
        # Non-loopback bind without auth is unsafe on persistent hosts (0.0.0.0, etc.).
        print(
            "  WARNING: Binding to a non-loopback address without authentication.",
            flush=True,
        )
        print(
            "  Set HERMES_WEBUI_PASSWORD to protect sessions and memory.",
            flush=True,
        )


def main() -> None:
    import uvicorn

    from app.domain.config import HOST, PORT, TLS_CERT, TLS_ENABLED, TLS_KEY

    _warn_non_loopback_without_auth(HOST)
    fd_limit = _raise_fd_soft_limit()
    if fd_limit.get("status") == "raised":
        print(
            f"[ok] Raised file descriptor soft limit "
            f"{fd_limit.get('previous_soft')} -> {fd_limit.get('soft')}",
            flush=True,
        )

    kwargs: dict = {
        "app": "app.main:app",
        "host": HOST,
        "port": PORT,
        "workers": 1,
        "log_level": "warning",
    }
    if TLS_CERT and TLS_KEY:
        from pathlib import Path as _Path

        cert_path = _Path(TLS_CERT)
        key_path = _Path(TLS_KEY)
        if cert_path.is_file() and key_path.is_file():
            kwargs["ssl_certfile"] = str(cert_path)
            kwargs["ssl_keyfile"] = str(key_path)
        else:
            print(
                "TLS setup failed: certificate or key path is missing; "
                "starting without TLS.",
                flush=True,
            )

    scheme = "https" if TLS_ENABLED else "http"
    print(f"  Hermes Web UI listening on {scheme}://{HOST}:{PORT}", flush=True)
    if HOST in ("127.0.0.1", "::1"):
        print(f"  Remote access: ssh -N -L {PORT}:127.0.0.1:{PORT} <user>@<your-server>", flush=True)
    print(f"  Then open:     {scheme}://localhost:{PORT}", flush=True)
    print("", flush=True)

    uvicorn.run(**kwargs)


if __name__ == "__main__":
    main()
