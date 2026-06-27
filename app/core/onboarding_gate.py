"""Client network gate for onboarding write/oauth/probe endpoints."""

from __future__ import annotations

import ipaddress
import os


def onboarding_client_allowed(
    *,
    client_host: str,
    x_forwarded_for: str = "",
    x_real_ip: str = "",
    auth_enabled: bool | None = None,
) -> bool:
    if auth_enabled is None:
        from app.domain.auth import is_auth_enabled
        auth_enabled = is_auth_enabled()
    if auth_enabled:
        return True
    if os.environ.get("HERMES_WEBUI_ONBOARDING_OPEN", "").strip() in {"1", "true", "yes"}:
        return True
    xff = (x_forwarded_for or "").split(",")[0].strip()
    xri = (x_real_ip or "").strip()
    ip_str = xff or xri or (client_host or "")
    try:
        addr = ipaddress.ip_address(ip_str)
        return addr.is_loopback or addr.is_private
    except ValueError:
        return False


ONBOARDING_SETUP_FORBIDDEN_MSG = (
    "Onboarding setup is only available from local networks when auth is not "
    "enabled. To bypass this on a remote server, set HERMES_WEBUI_ONBOARDING_OPEN=1."
)
ONBOARDING_OAUTH_FORBIDDEN_MSG = (
    "Onboarding OAuth is only available from local networks when auth is not "
    "enabled. To bypass this on a remote server, set HERMES_WEBUI_ONBOARDING_OPEN=1."
)
ONBOARDING_PROBE_FORBIDDEN_MSG = (
    "Onboarding probe is only available from local networks when auth is not "
    "enabled. To bypass this on a remote server, set HERMES_WEBUI_ONBOARDING_OPEN=1."
)
