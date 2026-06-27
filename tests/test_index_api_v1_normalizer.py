"""Regression tests for the client-side /api -> /api/v1 normalizer.

A stale service-worker-cached bundle from before the frontend v1 migration
calls the network with bare ``/api/<x>`` paths (its ``api()`` helper resolved
``api/settings`` to ``/api/settings`` with no v1 prefix). With the legacy
``/api/*`` bridge disabled by default those requests 404. The fresh
``index.html`` is served network-first on every navigation and patches
``window.fetch`` (and friends) before any module JS runs, so normalizing the
path there lets the app self-heal without a manual cache / service-worker clear.

These tests pin the normalizer wiring in ``static/index.html`` and prove the
backend routing contract the normalizer targets (bare ``/api/settings`` 404s,
``/api/v1/settings`` does not).
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
INDEX_HTML = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
APP_MAIN = REPO_ROOT / "app" / "main.py"


def test_index_defines_api_v1_path_normalizer():
    assert "function rewritePathname(pathname)" in INDEX_HTML
    assert "function normalizeUrl(raw)" in INDEX_HTML
    # Rewrite the first /api/ segment to /api/v1/ ...
    assert "pathname.replace(/\\/api\\//,'/api/v1/')" in INDEX_HTML
    # ... but never double-prefix already-v1 paths or rewrite the CSP sink.
    assert "/\\/api\\/(v1\\/|csp-report(?:$|[/?]))/.test(pathname)" in INDEX_HTML


def test_normalizer_is_independent_of_csrf_token():
    """Normalization must run even when no CSRF token is injected."""
    # The old guard bailed the whole wrapper out when token was empty; the new
    # guard only requires fetch to exist so normalization always installs.
    assert "if(!window.fetch)return;" in INDEX_HTML
    assert "if(!token||!window.fetch)return;" not in INDEX_HTML
    # CSRF attachment is now gated on token, normalization is not.
    assert "if(token&&sameOriginUnsafe(input,init)){" in INDEX_HTML


def test_fetch_wrapper_normalizes_before_csrf():
    fetch_idx = INDEX_HTML.find("window.fetch=function(input,init){")
    csrf_idx = INDEX_HTML.find("X-Hermes-CSRF-Token", fetch_idx)
    normalize_idx = INDEX_HTML.find("normalizeUrl(input)", fetch_idx)
    assert fetch_idx != -1 and csrf_idx != -1 and normalize_idx != -1
    # Path normalization happens before the CSRF header is attached.
    assert normalize_idx < csrf_idx


def test_normalizer_covers_all_network_vectors():
    assert "navigator.sendBeacon=function(url,data){" in INDEX_HTML
    assert "var nb=normalizeUrl(url);" in INDEX_HTML
    # EventSource (SSE) callers.
    assert "window.EventSource=PatchedES;" in INDEX_HTML
    # XMLHttpRequest callers.
    assert "window.XMLHttpRequest.prototype.open=function(method,url){" in INDEX_HTML
    assert "var nx=normalizeUrl(url);" in INDEX_HTML


@pytest.mark.skipif(
    not APP_MAIN.exists(),
    reason="app/main.py not present yet (FastAPI migration in progress)",
)
def test_bare_api_settings_404s_but_v1_settings_routes(monkeypatch):
    """The routing contract the client normalizer targets."""
    monkeypatch.setenv("HERMES_WEBUI_LEGACY_API", "0")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app
    from starlette.testclient import TestClient

    app = create_app()
    try:
        with TestClient(app) as client:
            bare = client.get("/api/settings")
            v1 = client.get("/api/v1/settings")
        assert bare.status_code == 404, "legacy /api/settings must 404 with bridge off"
        assert v1.status_code != 404, "/api/v1/settings must be a real route"
    finally:
        get_settings.cache_clear()
