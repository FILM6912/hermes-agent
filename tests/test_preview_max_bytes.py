"""Preview size limits for /api/file/raw vs /api/file/read."""

from pathlib import Path

CONFIG_PY = Path(__file__).resolve().parents[1] / "app" / "domain" / "config.py"
ROUTES_PY = Path(__file__).resolve().parents[1] / "app" / "domain" / "routes.py"
WORKSPACE_PY = Path(__file__).resolve().parents[1] / "app" / "domain" / "workspace.py"


def test_preview_max_bytes_env_configured():
    src = CONFIG_PY.read_text(encoding="utf-8")
    assert 'PREVIEW_MAX_BYTES = _env_mb_bytes("HERMES_WEBUI_PREVIEW_MAX_MB", 50)' in src
    assert "MAX_FILE_BYTES = 200_000" in src


def test_file_raw_enforces_preview_max_bytes():
    src = ROUTES_PY.read_text(encoding="utf-8")
    handler_idx = src.index("def _handle_file_raw")
    end_idx = src.index("\ndef _handle_file_read", handler_idx)
    body = src[handler_idx:end_idx]
    assert "PREVIEW_MAX_BYTES" in body
    assert "File too large" in body
    assert "413" in body


def test_text_read_keeps_editor_limit():
    src = WORKSPACE_PY.read_text(encoding="utf-8")
    assert "if size > MAX_FILE_BYTES:" in src
    assert "read_text(encoding='utf-8'" in src
