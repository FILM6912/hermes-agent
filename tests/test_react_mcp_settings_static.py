"""React frontend must expose MCP management in Settings (not legacy-only)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relpath: str) -> str:
    return (ROOT / relpath).read_text(encoding="utf-8")


def test_settings_view_exposes_mcp_tab_and_panel():
    settings = read("frontend/src/features/settings/components/SettingsView.tsx")
    assert '"mcp"' in settings or "'mcp'" in settings
    assert "McpTab" in settings
    assert 'id: "mcp"' in settings or "id: 'mcp'" in settings


def test_app_routes_allow_settings_mcp_tab():
    app = read("frontend/src/App.tsx")
    assert '"mcp"' in app or "'mcp'" in app


def test_mcp_service_exposes_server_mutations():
    mcp = read("frontend/src/services/hermes/mcp.ts")
    for fn in (
        "updateMcpServer",
        "toggleMcpServer",
        "deleteMcpServer",
        "discoverMcpServers",
        "testMcpServer",
    ):
        assert f"export async function {fn}" in mcp or f"export function {fn}" in mcp


def test_mcp_settings_tab_auto_discovers_on_load():
    tab = read("frontend/src/features/settings/components/tabs/McpTab.tsx")
    assert "await discoverMcpServers()" in tab
    assert "testMcpServer" in tab


def test_mcp_settings_tab_exposes_http_auth_fields():
    tab = read("frontend/src/features/settings/components/tabs/McpTab.tsx")
    assert "McpAuthFields" in tab
    auth = read("frontend/src/features/mcp/mcpAuth.ts")
    assert "buildMcpAuthPayload" in auth
    assert "bearer" in auth
