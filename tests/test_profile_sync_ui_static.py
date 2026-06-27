# coding: utf-8
"""Static UI coverage for profile sync-from-default controls."""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANELS_JS = (REPO / "static-legacy" / "panels.js").read_text(encoding="utf-8")
INDEX_HTML = (REPO / "static" / "index.html").read_text(encoding="utf-8")
STYLE_CSS = (REPO / "static-legacy" / "style.css").read_text(encoding="utf-8")
I18N_JS = (REPO / "static-legacy" / "i18n.js").read_text(encoding="utf-8")


def test_profiles_panel_has_sync_all_control():
    assert 'id="btnSyncAllProfiles"' in INDEX_HTML
    assert 'onclick="syncAllProfilesFromDefault()"' in INDEX_HTML
    assert "profile_sync_panel_hint" in INDEX_HTML


def test_profile_detail_has_sync_controls():
    assert 'id="btnSyncProfileDetail"' in INDEX_HTML
    assert "function syncProfileFromDefault(" in PANELS_JS
    assert "function syncProfileFromDefaultBtn(" in PANELS_JS
    assert "function _renderProfileSyncCard(" in PANELS_JS
    assert "profile-card-sync-btn" in PANELS_JS
    assert "profile-sync-item" in PANELS_JS
    assert 'id="profileSyncResult"' in PANELS_JS


def test_profile_sync_styles_present():
    assert ".profile-sync-card" in STYLE_CSS
    assert ".profile-card-sync-btn" in STYLE_CSS
    assert ".profile-sync-result" in STYLE_CSS


def test_profile_sync_i18n_keys_exist_in_en_locale():
    en_start = I18N_JS.find("  en: {")
    en_end = I18N_JS.find("\n  it: {", en_start)
    en_block = I18N_JS[en_start:en_end]
    for key in (
        "profile_sync_panel_hint",
        "profile_sync_items_config",
        "profile_sync_items_mcp",
        "profile_sync_items_skills",
        "profile_sync_items_soul",
        "profile_sync_result_added",
        "profile_sync_result_none",
    ):
        assert key in en_block
