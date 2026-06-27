# coding: utf-8
"""Profile-aware MCP discovery helpers."""

from unittest.mock import MagicMock, patch

import pytest

from app.domain import mcp_runtime


@pytest.fixture(autouse=True)
def _reset_mcp_runtime_state():
    mcp_runtime._MCP_LAST_PROFILE_HOME = None
    yield
    mcp_runtime._MCP_LAST_PROFILE_HOME = None


class TestDiscoverProfileMcpTools:
    @patch("tools.mcp_tool.discover_mcp_tools", return_value=["mcp_km_search"])
    @patch("tools.mcp_tool.shutdown_mcp_servers")
    def test_first_profile_clears_stale_connections(self, mock_shutdown, mock_discover):
        tools = mcp_runtime.discover_profile_mcp_tools("/tmp/hermes/profiles/usera")
        assert tools == ["mcp_km_search"]
        mock_shutdown.assert_called_once()
        mock_discover.assert_called_once()
        assert mcp_runtime._MCP_LAST_PROFILE_HOME == "/tmp/hermes/profiles/usera"

    @patch("tools.mcp_tool.discover_mcp_tools", return_value=[])
    @patch("tools.mcp_tool.shutdown_mcp_servers")
    def test_profile_switch_shuts_down_before_discover(self, mock_shutdown, mock_discover):
        mcp_runtime._MCP_LAST_PROFILE_HOME = "/tmp/hermes/default"
        mcp_runtime.discover_profile_mcp_tools("/tmp/hermes/profiles/usera")
        mock_shutdown.assert_called_once()
        mock_discover.assert_called_once()

    @patch("tools.mcp_tool.discover_mcp_tools", return_value=[])
    @patch("tools.mcp_tool.shutdown_mcp_servers")
    def test_same_profile_rediscover_does_not_shutdown(self, mock_shutdown, mock_discover):
        mcp_runtime._MCP_LAST_PROFILE_HOME = "/tmp/hermes/profiles/usera"
        mcp_runtime.discover_profile_mcp_tools("/tmp/hermes/profiles/usera")
        mock_shutdown.assert_not_called()
        mock_discover.assert_called_once()


class TestRefreshCachedAgentTools:
    @patch("model_tools.get_tool_definitions", return_value=[{"function": {"name": "mcp_km_search"}}])
    def test_refreshes_cached_agent_tool_lists(self, mock_defs):
        agent = MagicMock()
        agent.enabled_toolsets = None
        agent.disabled_toolsets = None
        agent.tools = []
        agent.valid_tool_names = set()

        from app.domain.config import SESSION_AGENT_CACHE, SESSION_AGENT_CACHE_LOCK

        with SESSION_AGENT_CACHE_LOCK:
            SESSION_AGENT_CACHE.clear()
            SESSION_AGENT_CACHE["sess-1"] = (agent, "sig")

        try:
            mcp_runtime.refresh_cached_agent_tools()
            assert agent.tools == [{"function": {"name": "mcp_km_search"}}]
            assert agent.valid_tool_names == {"mcp_km_search"}
            mock_defs.assert_called_once_with(
                enabled_toolsets=None,
                disabled_toolsets=None,
                quiet_mode=True,
            )
        finally:
            with SESSION_AGENT_CACHE_LOCK:
                SESSION_AGENT_CACHE.clear()
