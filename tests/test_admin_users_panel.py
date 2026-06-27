"""Admin Users settings panel — static UI contract tests."""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).parent.parent
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
PANELS_JS = (ROOT / "static-legacy" / "panels.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "static-legacy" / "style.css").read_text(encoding="utf-8")


class TestAdminUsersSettingsUi:
    def test_settings_sidebar_has_users_section_hidden_by_default(self):
        assert 'id="settingsMenuUsers"' in INDEX_HTML
        assert 'data-settings-section="users"' in INDEX_HTML
        assert "settingsPaneUsers" in INDEX_HTML
        assert 'id="usersPanelBody"' in INDEX_HTML
        assert 'style="display:none"' in INDEX_HTML.split('id="settingsMenuUsers"')[1].split(">")[0]

    def test_panels_js_wires_users_section(self):
        assert "'users'" in PANELS_JS
        assert "settingsPaneUsers" in PANELS_JS
        assert "loadUsersPanel()" in PANELS_JS
        assert "_applyAdminUsersSectionVisibility" in PANELS_JS

    def test_panels_js_uses_v1_admin_users_api(self):
        assert "apiV1Path" in PANELS_JS
        segment = PANELS_JS[PANELS_JS.find("// ── Admin users panel"): PANELS_JS.find("// ── Providers panel")]
        assert "/api/admin/users" in segment
        assert "_usersAdminJson" in segment
        assert "openUserDetail" in segment
        assert "submitAdminUserCreate" in segment

    def test_auth_role_from_session_or_status(self):
        segment = PANELS_JS[PANELS_JS.find("async function _fetchAuthRole"): PANELS_JS.find("function _isAdminAuth")]
        assert "/api/auth/session" in segment
        assert "/api/auth/status" in segment
        assert "role==='admin'" in segment.replace(" ", "")

    def test_users_table_styles_exist(self):
        assert ".users-table" in STYLE_CSS
        assert ".users-panel-toolbar" in STYLE_CSS
