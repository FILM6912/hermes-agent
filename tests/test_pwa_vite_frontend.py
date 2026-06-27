"""PWA contract tests for the Vite React frontend shell."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_INDEX = ROOT / "frontend" / "index.html"
FRONTEND_MANIFEST = ROOT / "frontend" / "public" / "manifest.json"
SW = ROOT / "static" / "sw.js"
PWA_STARTUP_TS = ROOT / "frontend" / "src" / "lib" / "pwaStartup.ts"


class TestViteIndexPwa:
    def test_index_links_manifest(self):
        src = FRONTEND_INDEX.read_text(encoding="utf-8")
        assert 'rel="manifest"' in src

    def test_index_base_href_before_manifest(self):
        src = FRONTEND_INDEX.read_text(encoding="utf-8")
        base_pos = src.find("createElement('base')")
        manifest_pos = src.find('rel="manifest"')
        assert base_pos != -1
        assert manifest_pos != -1
        assert base_pos < manifest_pos

    def test_index_registers_service_worker_via_main(self):
        src = FRONTEND_INDEX.read_text(encoding="utf-8")
        register_src = (ROOT / "frontend" / "src" / "lib" / "pwaRegister.ts").read_text(
            encoding="utf-8"
        )
        assert "sw.js?v=__WEBUI_VERSION__" in register_src
        assert "registerServiceWorker" in (ROOT / "frontend" / "src" / "main.tsx").read_text(
            encoding="utf-8"
        )

    def test_index_has_ios_pwa_meta_tags(self):
        src = FRONTEND_INDEX.read_text(encoding="utf-8")
        assert "apple-mobile-web-app-capable" in src


class TestViteManifest:
    def test_public_manifest_matches_server_manifest_fields(self):
        import json

        data = json.loads(FRONTEND_MANIFEST.read_text(encoding="utf-8"))
        assert data.get("name") == "Hermes"
        assert data.get("display") == "standalone"
        assert data.get("start_url") == "./?source=pwa"


class TestViteServiceWorker:
    def test_sw_matches_vite_assets_prefix(self):
        src = SW.read_text(encoding="utf-8")
        assert "isViteShellRelPath" in src
        assert "assets/" in src
        assert "./index.html" in src

    def test_pwa_startup_ported_to_typescript(self):
        src = PWA_STARTUP_TS.read_text(encoding="utf-8")
        assert "pwa-standalone" in src
        assert "HermesPWA" in src
        assert "beforeinstallprompt" in src
