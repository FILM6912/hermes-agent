"""Settings General tab must expose clear-all history wired to server deletes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relpath: str) -> str:
    return (ROOT / relpath).read_text(encoding="utf-8")


def test_general_tab_exposes_clear_history_action():
    general = read("frontend/src/features/settings/components/tabs/GeneralTab.tsx")
    assert "settings.clearHistory" in general
    assert "settings.clearAll" in general
    assert "showClearAllConfirm" in general
    assert "onClearAllChats" in general


def test_clear_all_history_deletes_server_sessions():
    app = read("frontend/src/App.tsx")
    sessions = read("frontend/src/services/hermes/sessions.ts")
    assert "deleteAllSessions" in sessions
    assert "export async function deleteAllSessions" in sessions
    assert "deleteAllSessions()" in app
    assert "syncConfirmedSessionIds(new Set())" in app
