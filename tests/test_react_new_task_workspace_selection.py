"""New-task workspace pick must not reopen the latest session or reset workspace.

Root cause: URL sync cleared preferBlankChatRef on /chat/:id, so refreshSessions
treated a just-created blank session as missing and navigated to pickFirstUsableSessionId.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = (REPO / "frontend/src/App.tsx").read_text(encoding="utf-8")


def _url_sync_block() -> str:
    start = APP.index("// Sync URL to state; skip ids rejected by GET /session")
    end = APP.index("// Fetch Hermes sessions on mount / auth / SSE refresh", start)
    return APP[start:end]


def test_url_sync_does_not_clear_prefer_blank_on_chat_route():
    """Workspace pick navigates to /chat/:id; must keep new-task blank guard."""
    block = _url_sync_block()
    assert "preferBlankChatRef.current = false" not in block, (
        "URL sync must not clear preferBlankChatRef — refreshSessions would "
        "reopen the latest chat while the new session is absent from listSessions"
    )


def test_refresh_sessions_wants_blank_when_prefer_blank_with_active_id():
    """preferBlankChatRef must block auto-select even after /chat/:id navigation."""
    start = APP.index("const refreshSessions = useCallback")
    end = APP.index("const { agentModels", start)
    block = APP[start:end]
    assert "wantsBlankNewChat" in block
    assert "preferBlankChatRef.current ||" in block or "preferBlankChatRef.current||" in block


def test_refresh_sessions_keeps_locally_confirmed_active_missing_from_list():
    """POST /session/new may lag listSessions; do not jump to pickFirstUsableSessionId."""
    start = APP.index("const refreshSessions = useCallback")
    end = APP.index("const { agentModels", start)
    block = APP[start:end]
    assert "preserveActiveOnListLag" in block
    assert "activePendingListSync" in block
    assert "confirmSessionId(activeBeforeSync)" in block
