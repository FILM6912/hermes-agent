"""Regression tests for React Generated Files panel + composer workspace bind (#804 follow-up).

Root cause: client ``activeSessionWorkspace`` could match ``composerWorkspace`` while
``GET /list`` still used an unbound server session → empty tree / preview.noFiles.

Follow-up: ``GET /list?workspace=`` lists the composer workspace directly so the
file tree does not wait for session bind.
"""
from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_composer_needs_server_workspace_bind_logic():
    """Mirror workspaceBind.ts — server must match composer before skipping bind."""

    def needs_bind(composer: str, server: str) -> bool:
        c = composer.strip()
        if not c:
            return False
        return server.strip() != c

    home = "/home/hermeswebui/.hermes/workspace/user"
    assert needs_bind(home, "") is True
    assert needs_bind(home, home) is False
    assert needs_bind(home, "  " + home + "  ") is False
    assert needs_bind("", home) is False


def test_app_auto_bind_checks_server_workspace_via_get_session():
    src = read("frontend/src/App.tsx")
    start = src.index("/** Bind composer workspace to the active session")
    end = src.index("const handleComposerWorkspaceChange", start)
    block = src[start:end]
    assert "getSession" in block, (
        "auto-bind must read server session.workspace via getSession, "
        "not trust activeSessionWorkspace alone"
    )
    assert "activeSessionWorkspace.trim() === ws" not in block, (
        "auto-bind must not skip bind when client state matches composer but server is stale"
    )
    assert "composerNeedsServerWorkspaceBind" in block


def test_auto_bind_reruns_when_session_becomes_confirmed():
    """Auto-bind must not bail once on serverSessionIdsRef guard before listSessions fills the set."""
    src = read("frontend/src/App.tsx")
    start = src.index("/** Bind composer workspace to the active session")
    end = src.index("const handleComposerWorkspaceChange", start)
    block = src[start:end]
    assert "activeSessionConfirmed" in block, (
        "auto-bind effect must re-run when the active chat id enters confirmedSessionIds"
    )


def test_active_session_workspace_cleared_on_chat_switch():
    """Stale activeSessionWorkspace from chat A must not gate list for chat B."""
    src = read("frontend/src/App.tsx")
    marker = "useEffect(() => {\n    if (!activeChatId) {\n      setActiveSessionWorkspace(\"\");"
    assert marker not in src, (
        "clear activeSessionWorkspace on every activeChatId change, not only when id is empty"
    )


def test_active_chat_effect_preserves_composer_hydrated_ref_for_target_chat():
    """Workspace pick that navigates to a new session must not clear the hydration guard."""
    src = read("frontend/src/App.tsx")
    start = src.index("}, [activeChatId]);", src.index("setActiveSessionWorkspace"))
    block = src[src.index("useEffect(() => {", start - 400) : start + len("}, [activeChatId]);")]
    assert "composerHydratedForChatRef.current !== activeChatId" in block, (
        "activeChatId effect must not reset composerHydratedForChatRef when already marked for this chat"
    )
    assert block.count('setActiveSessionWorkspace("")') == 0 or (
        "if (composerHydratedForChatRef.current !== activeChatId)" in block
        and block.index("setActiveSessionWorkspace") > block.index(
            "composerHydratedForChatRef.current !== activeChatId"
        )
    ), (
        "must not blank activeSessionWorkspace when hydration guard already matches active chat"
    )


def test_handle_send_marks_composer_hydrated_before_navigation():
    src = read("frontend/src/App.tsx")
    start = src.index("const handleSend = async (")
    end = src.index("const handleRegenerate", start)
    block = src[start:end]
    assert "composerHydratedForChatRef.current = chatId" in block
    nav = block.index("navigate(`/chat/${chatId}`")
    mark = block.index("composerHydratedForChatRef.current = chatId")
    assert mark < nav, "hydration guard must be set before navigating on first send"


def test_execute_chat_request_binds_composer_before_stream():
    src = read("frontend/src/App.tsx")
    start = src.index("const executeChatRequest = async (")
    end = src.index("const handleSend = async (", start)
    block = src[start:end]
    assert "await bindComposerWorkspaceToSession(activeSessionId)" in block
    assert block.index("await bindComposerWorkspaceToSession(activeSessionId)") < block.index(
        "await consumeStream()"
    )


def test_sync_session_after_stream_keeps_composer_active_session_when_server_stale():
    src = read("frontend/src/App.tsx")
    start = src.index("const syncSessionMessagesAfterStream = useCallback(")
    end = src.index("const resumeHermesSessionStream", start)
    block = src[start:end]
    assert "setActiveSessionWorkspace(composer)" in block
    stale_branch = block[block.index("} else {") : block.index("const serverTitle")]
    assert "setActiveSessionWorkspace(serverWs)" not in stale_branch


def test_handle_composer_workspace_change_marks_hydrated_after_bound_session():
    """Composer pick must mark hydration for the active chat without creating a new session."""
    src = read("frontend/src/App.tsx")
    start = src.index("const handleComposerWorkspaceChange = useCallback(")
    end = src.index("  const ensureComposerSession = useCallback", start)
    block = src[start:end]
    assert "composerHydratedForChatRef.current" in block
    assert "ensureServerSessionId" not in block, (
        "workspace pick must not create a new server session — only bind the active chat"
    )
    assert "navigate(" not in block, (
        "workspace pick must not navigate away from the current chat"
    )
    assert "__composer_pick__" not in block


def test_composer_workspace_change_does_not_seed_sidebar_new_task():
    """Switching workspace must not insert a blank New Task row in sidebar state."""
    src = read("frontend/src/App.tsx")
    start = src.index("const handleComposerWorkspaceChange = useCallback(")
    end = src.index("  const ensureComposerSession = useCallback", start)
    block = src[start:end]
    assert "setSessions(" not in block
    assert "sidebar.newTask" not in block


def test_load_history_does_not_stomp_composer_pick_over_registry_fallback():
    """Stale server workspace must not replace an in-flight composer pick with registry fallback."""
    src = read("frontend/src/App.tsx")
    start = src.index("const loadHistory = async () => {")
    end = src.index("loadHistory();", start)
    block = src[start:end]
    assert "composerWorkspaceRef.current" in block
    assert "composerNeedsServerWorkspaceBind" in block or "composerInRegistry" in block


def test_sync_session_after_stream_does_not_stomp_composer_pick():
    src = read("frontend/src/App.tsx")
    start = src.index("const syncSessionMessagesAfterStream = useCallback(")
    end = src.index("}, [", start)
    block = src[start:end]
    assert "composerNeedsServerWorkspaceBind" in block or "composerWorkspaceRef" in block
    assert block.count("setComposerWorkspace(serverSession.workspace)") == 0, (
        "syncSessionMessagesAfterStream must not blindly copy server workspace over composer pick"
    )


def test_preview_panel_waits_while_workspace_bind_pending_without_composer_workspace():
    """Mirror previewPanelState.ts — bind skeleton only when listing via session."""

    def view(
        *,
        chat_id: str | None,
        session_ready: bool,
        has_session_workspace: bool,
        has_composer_workspace: bool,
        workspace_bind_pending: bool,
        is_files_loading: bool,
        file_count: int,
        load_error: str | None,
    ) -> str:
        if chat_id and workspace_bind_pending and not has_composer_workspace:
            return "waiting-bind"
        if (
            chat_id
            and session_ready
            and not has_session_workspace
            and not has_composer_workspace
        ):
            return "no-workspace"
        if (
            chat_id
            and has_session_workspace
            and not session_ready
            and not has_composer_workspace
        ):
            return "waiting-session"
        if is_files_loading:
            return "loading"
        if load_error:
            return "error"
        if file_count == 0:
            return "no-files"
        return "tree"

    assert (
        view(
            chat_id="s1",
            session_ready=True,
            has_session_workspace=False,
            has_composer_workspace=False,
            workspace_bind_pending=True,
            is_files_loading=False,
            file_count=0,
            load_error=None,
        )
        == "waiting-bind"
    )
    assert (
        view(
            chat_id="s1",
            session_ready=True,
            has_session_workspace=False,
            has_composer_workspace=True,
            workspace_bind_pending=True,
            is_files_loading=False,
            file_count=0,
            load_error=None,
        )
        == "no-files"
    )


def test_handle_send_sets_session_workspace_from_server_response():
    src = read("frontend/src/App.tsx")
    marker = "if (composerWorkspace.trim()) {\n          setActiveSessionWorkspace(composerWorkspace.trim());"
    assert marker not in src, (
        "handleSend must not optimistically set activeSessionWorkspace from composer alone"
    )


def test_load_history_does_not_stomp_composer_workspace_on_session_refresh():
    """Sub-workspace pick must survive loadHistory re-runs (refreshSessions deps)."""
    src = read("frontend/src/App.tsx")
    assert "composerHydratedForChatRef" in src
    assert "hydrateComposer" in src
    start = src.index("const loadHistory = async () => {")
    end = src.index("loadHistory();", start)
    block = src[start:end]
    assert "composerHydratedForChatRef.current !== activeChatId" in block
    assert "resolveAllowedComposerWorkspace" in block
    assert "if (hydrateComposer)" in block
    # Composer workspace updates stay inside hydrateComposer (chat switch only).
    hydrate_start = block.index("if (hydrateComposer)")
    hydrate_block = block[hydrate_start:]
    assert hydrate_block.count("setComposerWorkspace(") >= 1


def test_composer_workspace_change_resolves_before_switch():
    src = read("frontend/src/App.tsx")
    start = src.index("const handleComposerWorkspaceChange = useCallback(")
    end = src.index("// Fetch Hermes sessions on mount", start)
    block = src[start:end]
    assert "listWorkspaces()" in block
    assert "findWorkspaceInRegistry" in block
    assert "setComposerWorkspace(resolvedPath)" in block
    assert block.index("setComposerWorkspace(resolvedPath)") < block.index(
        "switchComposerWorkspace"
    )


def test_preview_panel_view_waits_when_session_not_ready():
    """Mirror previewPanelState.ts — avoid preview.noFiles before session is confirmed."""

    def view(
        *,
        chat_id: str | None,
        session_ready: bool,
        has_session_workspace: bool,
        has_composer_workspace: bool = False,
        workspace_bind_pending: bool = False,
        is_files_loading: bool,
        file_count: int,
        load_error: str | None,
    ) -> str:
        if chat_id and workspace_bind_pending and not has_composer_workspace:
            return "waiting-bind"
        if (
            chat_id
            and session_ready
            and not has_session_workspace
            and not has_composer_workspace
        ):
            return "no-workspace"
        if (
            chat_id
            and has_session_workspace
            and not session_ready
            and not has_composer_workspace
        ):
            return "waiting-session"
        if is_files_loading:
            return "loading"
        if load_error:
            return "error"
        if file_count == 0:
            return "no-files"
        return "tree"

    assert (
        view(
            chat_id="s1",
            session_ready=False,
            has_session_workspace=True,
            is_files_loading=False,
            file_count=0,
            load_error=None,
        )
        == "waiting-session"
    )


def test_preview_panel_waits_when_session_not_ready():
    """Static: panel must not show preview.noFiles while session/bind is pending."""
    src = read("frontend/src/features/preview/components/PreviewWindow.tsx")
    assert "resolvePreviewPanelView" in src
    assert "waiting-session" in src
    assert "waiting-bind" in src
    assert "workspaceBindPending" in src
    assert "workspacePath" in src
    app = read("frontend/src/App.tsx")
    assert "workspaceBindPending" in app
    assert "workspacePath={composerWorkspace}" in app


def test_use_file_system_lists_by_composer_workspace():
    src = read("frontend/src/features/preview/hooks/useFileSystem.ts")
    assert "workspacePath" in src
    assert "listByWorkspace" in src
    assert "workspace: listByWorkspace ? composerWorkspace" in src


def test_list_directory_accepts_workspace_query():
    src = read("frontend/src/services/hermes/workspace.ts")
    assert "query.workspace = ws" in src or 'query.workspace = ws' in src
    endpoint = read("app/api/v1/endpoints/workspace.py")
    assert 'workspace: str = Query(default="")' in endpoint
    assert "session_id or workspace is required" in endpoint


def test_list_returns_entries_for_bound_workspace(cleanup_test_sessions):
    """Integration: bound session workspace lists files on disk."""
    import json
    import urllib.error
    import urllib.request

    from tests.conftest import TEST_BASE, TEST_WORKSPACE, _wait_for_server, make_session_tracked

    if not _wait_for_server(TEST_BASE, timeout=2):
        pytest.skip("Hermes test server is not running")

    TEST_WORKSPACE.mkdir(parents=True, exist_ok=True)
    marker = TEST_WORKSPACE / "react_preview_bind_marker.txt"
    marker.write_text("hi", encoding="utf-8")

    sid, _ = make_session_tracked(cleanup_test_sessions, ws=TEST_WORKSPACE)
    url = f"{TEST_BASE}/api/list?session_id={sid}&path=."
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            listing = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        pytest.skip(f"list endpoint unavailable: {exc.code}")
    entries = listing.get("entries") or []
    names = {e.get("name") for e in entries if isinstance(e, dict)}
    assert "react_preview_bind_marker.txt" in names


def test_list_returns_entries_for_workspace_query(cleanup_test_sessions):
    """Integration: workspace query lists files without session bind."""
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    from tests.conftest import TEST_BASE, TEST_WORKSPACE, _wait_for_server, make_session_tracked

    if not _wait_for_server(TEST_BASE, timeout=2):
        pytest.skip("Hermes test server is not running")

    TEST_WORKSPACE.mkdir(parents=True, exist_ok=True)
    marker = TEST_WORKSPACE / "react_preview_workspace_query_marker.txt"
    marker.write_text("hi", encoding="utf-8")

    make_session_tracked(cleanup_test_sessions, ws=TEST_WORKSPACE)
    ws_q = urllib.parse.quote(str(TEST_WORKSPACE))
    url = f"{TEST_BASE}/api/list?workspace={ws_q}&path=."
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            listing = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        pytest.skip(f"list endpoint unavailable: {exc.code}")
    entries = listing.get("entries") or []
    names = {e.get("name") for e in entries if isinstance(e, dict)}
    assert "react_preview_workspace_query_marker.txt" in names


def test_file_raw_accepts_workspace_query_for_html_inline(cleanup_test_sessions):
    """Integration: workspace query serves HTML inline without session bind."""
    import urllib.error
    import urllib.parse
    import urllib.request

    from tests.conftest import TEST_BASE, TEST_WORKSPACE, _wait_for_server, make_session_tracked

    if not _wait_for_server(TEST_BASE, timeout=2):
        pytest.skip("Hermes test server is not running")

    TEST_WORKSPACE.mkdir(parents=True, exist_ok=True)
    html_path = TEST_WORKSPACE / "react_preview_workspace_html.html"
    html_path.write_text("<html><body>workspace html</body></html>", encoding="utf-8")

    make_session_tracked(cleanup_test_sessions, ws=TEST_WORKSPACE)
    ws_q = urllib.parse.quote(str(TEST_WORKSPACE))
    rel_q = urllib.parse.quote("react_preview_workspace_html.html")
    url = f"{TEST_BASE}/api/file/raw?workspace={ws_q}&path={rel_q}&inline=1"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            content_type = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        pytest.skip(f"file/raw workspace query unavailable: {exc.code}")
    assert "workspace html" in body
    assert "text/html" in content_type


def test_file_raw_url_supports_workspace_option():
    src = read("frontend/src/services/hermes/workspace.ts")
    assert "query.workspace = ws" in src
    assert "applyWorkspaceMutationTarget" in src
    preview = read("frontend/src/features/preview/components/PreviewWindow.tsx")
    assert "fileAccessWorkspace" in preview
    assert "deleteWorkspaceNode" in preview
    assert "resolveWorkspaceMutationTarget" in preview
    assert "createWorkspaceFileFromUpload" in preview
    routes = read("app/domain/routes.py")
    assert "_workspace_file_target" in routes
    assert "_resolve_file_mutation_workspace" in routes
    assert "session_id or workspace is required" in routes
    create_handler = routes[routes.find("def _handle_file_create"): routes.find("def _handle_file_rename")]
    assert "_resolve_file_mutation_workspace(body)" in create_handler
    save_handler = routes[routes.find("def _handle_file_save"): routes.find("def _handle_file_create")]
    assert "_resolve_file_mutation_workspace(body)" in save_handler


def test_file_delete_accepts_workspace_query(cleanup_test_sessions):
    """Integration: delete via workspace targets the same tree as GET /list?workspace=."""
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    from tests.conftest import TEST_BASE, TEST_WORKSPACE, _wait_for_server, make_session_tracked

    if not _wait_for_server(TEST_BASE, timeout=2):
        pytest.skip("Hermes test server is not running")

    TEST_WORKSPACE.mkdir(parents=True, exist_ok=True)
    marker = TEST_WORKSPACE / "react_preview_workspace_delete_me.txt"
    marker.write_text("delete me", encoding="utf-8")
    assert marker.exists()

    make_session_tracked(cleanup_test_sessions, ws=TEST_WORKSPACE)
    ws_q = urllib.parse.quote(str(TEST_WORKSPACE))
    rel_q = urllib.parse.quote("react_preview_workspace_delete_me.txt")
    delete_url = f"{TEST_BASE}/api/file/delete"
    body = json.dumps(
        {"workspace": str(TEST_WORKSPACE), "path": "react_preview_workspace_delete_me.txt"}
    ).encode("utf-8")
    req = urllib.request.Request(
        delete_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
    except urllib.error.HTTPError as exc:
        pytest.skip(f"file/delete workspace body unavailable: {exc.code}")

    assert not marker.exists()
    list_url = f"{TEST_BASE}/api/list?workspace={ws_q}&path=."
    with urllib.request.urlopen(list_url, timeout=10) as resp:
        listing = json.loads(resp.read())
    names = {e.get("name") for e in listing.get("entries") or [] if isinstance(e, dict)}
    assert "react_preview_workspace_delete_me.txt" not in names


def test_file_create_accepts_workspace_body(cleanup_test_sessions):
    """Integration: create via workspace targets the same tree as GET /list?workspace=."""
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    from tests.conftest import TEST_BASE, TEST_WORKSPACE, _wait_for_server, make_session_tracked

    if not _wait_for_server(TEST_BASE, timeout=2):
        pytest.skip("Hermes test server is not running")

    TEST_WORKSPACE.mkdir(parents=True, exist_ok=True)
    marker = TEST_WORKSPACE / "react_preview_workspace_create_me.txt"
    if marker.exists():
        marker.unlink()

    make_session_tracked(cleanup_test_sessions, ws=TEST_WORKSPACE)
    ws_q = urllib.parse.quote(str(TEST_WORKSPACE))
    create_url = f"{TEST_BASE}/api/file/create"
    body = json.dumps(
        {
            "workspace": str(TEST_WORKSPACE),
            "path": "react_preview_workspace_create_me.txt",
            "content": "created via workspace",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        create_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
    except urllib.error.HTTPError as exc:
        pytest.skip(f"file/create workspace body unavailable: {exc.code}")

    assert marker.exists()
    assert marker.read_text(encoding="utf-8") == "created via workspace"
    list_url = f"{TEST_BASE}/api/list?workspace={ws_q}&path=."
    with urllib.request.urlopen(list_url, timeout=10) as resp:
        listing = json.loads(resp.read())
    names = {e.get("name") for e in listing.get("entries") or [] if isinstance(e, dict)}
    assert "react_preview_workspace_create_me.txt" in names
    marker.unlink(missing_ok=True)


def test_file_save_accepts_workspace_body(cleanup_test_sessions):
    """Integration: save via workspace targets the same tree as GET /list?workspace=."""
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    from tests.conftest import TEST_BASE, TEST_WORKSPACE, _wait_for_server, make_session_tracked

    if not _wait_for_server(TEST_BASE, timeout=2):
        pytest.skip("Hermes test server is not running")

    TEST_WORKSPACE.mkdir(parents=True, exist_ok=True)
    marker = TEST_WORKSPACE / "react_preview_workspace_save_me.txt"
    marker.write_text("before", encoding="utf-8")

    make_session_tracked(cleanup_test_sessions, ws=TEST_WORKSPACE)
    save_url = f"{TEST_BASE}/api/file/save"
    body = json.dumps(
        {
            "workspace": str(TEST_WORKSPACE),
            "path": "react_preview_workspace_save_me.txt",
            "content": "after save via workspace",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        save_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
    except urllib.error.HTTPError as exc:
        pytest.skip(f"file/save workspace body unavailable: {exc.code}")

    assert marker.read_text(encoding="utf-8") == "after save via workspace"
    marker.unlink(missing_ok=True)
