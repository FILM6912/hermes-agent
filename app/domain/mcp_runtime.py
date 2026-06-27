"""Profile-aware MCP discovery for WebUI chat streams and settings APIs."""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_MCP_LAST_PROFILE_HOME: str | None = None
_MCP_RUNTIME_LOCK = threading.Lock()


def profile_mcp_home_changed(profile_home: str) -> bool:
    """Return True when *profile_home* differs from the last MCP discovery scope."""
    home = str(profile_home or "").strip()
    if not home:
        return False
    with _MCP_RUNTIME_LOCK:
        return _MCP_LAST_PROFILE_HOME != home


def discover_profile_mcp_tools(profile_home: str) -> list[str]:
    """Discover MCP tools for *profile_home*, resetting stale connections on profile switch."""
    home = str(profile_home or "").strip()
    if not home:
        return []

    try:
        from tools.mcp_tool import discover_mcp_tools, shutdown_mcp_servers
    except ImportError:
        logger.debug("MCP SDK not available — skipping profile MCP discovery")
        return []

    global _MCP_LAST_PROFILE_HOME
    with _MCP_RUNTIME_LOCK:
        profile_changed = _MCP_LAST_PROFILE_HOME != home
        if profile_changed:
            try:
                shutdown_mcp_servers()
            except Exception:
                logger.debug(
                    "MCP shutdown before profile switch to %s failed",
                    home,
                    exc_info=True,
                )
        _MCP_LAST_PROFILE_HOME = home

    try:
        return list(discover_mcp_tools() or [])
    except Exception:
        logger.debug("MCP discovery failed for profile home %s", home, exc_info=True)
        return []


def refresh_cached_agent_tools() -> None:
    """Refresh tool lists on cached AIAgent instances after MCP discovery."""
    try:
        from model_tools import get_tool_definitions
        from app.domain.config import SESSION_AGENT_CACHE, SESSION_AGENT_CACHE_LOCK
    except ImportError:
        return

    with SESSION_AGENT_CACHE_LOCK:
        entries = list(SESSION_AGENT_CACHE.items())

    for _sid, entry in entries:
        try:
            agent = entry[0] if isinstance(entry, tuple) else entry
        except Exception:
            continue
        if agent is None:
            continue
        try:
            new_defs = get_tool_definitions(
                enabled_toolsets=getattr(agent, "enabled_toolsets", None),
                disabled_toolsets=getattr(agent, "disabled_toolsets", None),
                quiet_mode=True,
            )
            agent.tools = new_defs
            agent.valid_tool_names = (
                {t["function"]["name"] for t in new_defs} if new_defs else set()
            )
        except Exception:
            logger.debug(
                "Failed to refresh cached agent tools after MCP discovery",
                exc_info=True,
            )
