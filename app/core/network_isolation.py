"""Test-mode outbound network isolation (ported from server.py import block)."""

from __future__ import annotations

import os
import re
import socket


def _env_enabled() -> bool:
    return os.environ.get("HERMES_WEBUI_TEST_NETWORK_BLOCK", "").strip() in (
        "1",
        "true",
        "yes",
    )


def install_test_network_block() -> None:
    """Refuse non-local outbound sockets when HERMES_WEBUI_TEST_NETWORK_BLOCK is set.

    Mirrors tests/conftest.py pytest-side isolation for the server subprocess.
    No-op in production when the env var is unset.
    """
    if not _env_enabled():
        return
    if getattr(socket, "_hermes_test_network_block_installed", False):
        return

    real_create_conn = socket.create_connection
    real_sock_connect = socket.socket.connect

    def _re_match_unique_local_ipv6(host: str) -> bool:
        return bool(re.match(r"^f[cd][0-9a-f]{0,2}:", host))

    def _addr_is_local(host) -> bool:
        if not isinstance(host, str):
            return False
        h = host.strip().lower()
        if not h:
            return False
        if (
            h in ("::1", "0:0:0:0:0:0:0:1")
            or h.startswith("fe80:")
            or _re_match_unique_local_ipv6(h)
        ):
            return True
        if h == "localhost" or h.endswith(".localhost"):
            return True
        if h.endswith(".local") or h.endswith(".test") or h.endswith(".invalid"):
            return True
        if h == "example.com" or h.endswith(".example.com"):
            return True
        if h == "example.net" or h.endswith(".example.net"):
            return True
        if h == "example.org" or h.endswith(".example.org"):
            return True
        if h.endswith(".example"):
            return True
        if h and h[0].isdigit() and h.count(".") == 3:
            try:
                o1, o2, o3, o4 = [int(p) for p in h.split(".")]
            except ValueError:
                return False
            if o1 == 127:
                return True
            if o1 == 10:
                return True
            if o1 == 192 and o2 == 168:
                return True
            if o1 == 172 and 16 <= o2 <= 31:
                return True
            if o1 == 169 and o2 == 254:
                return True
            if o1 == 203 and o2 == 0 and o3 == 113:
                return True
        return False

    def _blocked_create_connection(address, *args, **kwargs):
        try:
            host = address[0]
        except (TypeError, IndexError):
            host = ""
        if _addr_is_local(host):
            return real_create_conn(address, *args, **kwargs)
        raise OSError(
            f"hermes test network isolation (server.py): outbound to {address!r} blocked"
        )

    def _blocked_socket_connect(self, address):
        try:
            host = address[0]
        except (TypeError, IndexError):
            host = ""
        if _addr_is_local(host):
            return real_sock_connect(self, address)
        raise OSError(
            f"hermes test network isolation (server.py): socket.connect to {address!r} blocked"
        )

    socket.create_connection = _blocked_create_connection
    socket.socket.connect = _blocked_socket_connect
    socket._hermes_test_network_block_installed = True
