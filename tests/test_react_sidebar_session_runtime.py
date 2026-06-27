"""React sidebar: streaming spinner + per-session cancel (job history)."""
from __future__ import annotations

import json
import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _extract_ts_function(src: str, name: str) -> str:
    needle = f"export function {name}("
    start = src.find(needle)
    assert start != -1, f"missing {name} in sessionRuntime.ts"
    brace = src.find("{", start)
    assert brace != -1, f"missing opening brace for {name}"
    depth = 0
    for i in range(brace, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                body = src[start : i + 1]
                return (
                    body.replace("export function", "function")
                    .replace(": ChatSession", "")
                    .replace(": SidebarSessionRuntimeOptions", "")
                    .replace(
                        "): Pick<ChatSession, \"activeStreamId\" | \"isStreaming\">",
                        ")",
                    )
                    .replace("): boolean", ")")
                    .replace("): string", ")")
                    .replace("| undefined", "")
                    .replace("void existing;", "")
                )
    raise AssertionError(f"could not extract function body for {name}")


def _run_session_runtime_node(*, script_body: str) -> dict:
    runtime_src = read("frontend/src/features/sidebar/utils/sessionRuntime.ts")
    helpers = "\n".join(
        _extract_ts_function(runtime_src, name)
        for name in (
            "sessionHasLiveStream",
            "normalizeSessionStreamFlags",
            "reconcileSessionStreamMetadata",
            "isSidebarSessionRunning",
        )
    )
    script = f"""
{helpers}
{script_body}
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_session_runtime_exports_live_stream_helper():
    src = read("frontend/src/features/sidebar/utils/sessionRuntime.ts")
    assert "export function sessionHasLiveStream" in src
    assert "export function isSidebarSessionRunning" in src
    assert "session.isStreaming === true && Boolean(streamId)" in src
    assert "loadingChatId" not in src.split("isSidebarSessionRunning")[1].split("streamIdForSessionCancel")[0]


def test_session_has_live_stream_only_for_matching_session():
    payload = _run_session_runtime_node(
        script_body="""
const sessions = [
  { id: 'idle-a', isStreaming: false, activeStreamId: 'stale-a' },
  { id: 'idle-b', activeStreamId: 'stale-b' },
  { id: 'live-c', isStreaming: true, activeStreamId: 'stream-c' },
];
console.log(JSON.stringify({
  idleA: sessionHasLiveStream(sessions[0]),
  idleB: sessionHasLiveStream(sessions[1]),
  liveC: sessionHasLiveStream(sessions[2]),
  spinnerRows: sessions.filter((s) => isSidebarSessionRunning(s, {
    activeChatId: 'idle-a',
    isActivePaneStreaming: false,
  })).map((s) => s.id),
}));
""",
    )
    assert payload["idleA"] is False
    assert payload["idleB"] is False
    assert payload["liveC"] is True
    assert payload["spinnerRows"] == ["live-c"]


def test_sidebar_spinner_uses_live_stream_helper_not_loading_chat_id():
    payload = _run_session_runtime_node(
        script_body="""
const session = { id: 'history-load', isStreaming: false };
console.log(JSON.stringify({
  loadingRow: isSidebarSessionRunning(session, {
    activeChatId: 'other',
    isActivePaneStreaming: false,
    loadingChatId: 'history-load',
  }),
  activePaneOnly: isSidebarSessionRunning(
    { id: 'active', isStreaming: false },
    { activeChatId: 'active', isActivePaneStreaming: true },
  ),
}));
""",
    )
    assert payload["loadingRow"] is False
    assert payload["activePaneOnly"] is True


def test_reconcile_session_stream_metadata_clears_stale_sidebar_flags():
    payload = _run_session_runtime_node(
        script_body="""
const existing = {
  id: 'dogfood-session',
  isStreaming: true,
  activeStreamId: 'stale-stream',
};
const fetched = {
  id: 'dogfood-session',
  isStreaming: false,
  activeStreamId: null,
};
console.log(JSON.stringify(reconcileSessionStreamMetadata(existing, fetched)));
""",
    )
    assert payload["isStreaming"] is False
    assert payload.get("activeStreamId") in (None, False)


def test_sidebar_shows_spinner_for_running_sessions_not_only_loading():
    sidebar = read("frontend/src/features/sidebar/components/Sidebar.tsx")
    assert "isSidebarSessionRunning" in sidebar
    assert "normalizeSessionStreamFlags" in sidebar
    assert "reconcileSessionStreamMetadata" in sidebar
    assert re.search(
        r"isSidebarSessionRunning\([\s\S]*?\)[\s\S]{0,400}?Loader2[\s\S]{0,120}?animate-spin",
        sidebar,
    ), "running session rows must render Loader2 spinner via isSidebarSessionRunning"


def test_sidebar_has_per_session_cancel_control():
    sidebar = read("frontend/src/features/sidebar/components/Sidebar.tsx")
    assert "onCancelSession" in sidebar
    assert re.search(r"<Square[\s\S]{0,200}?onCancelSession", sidebar) or re.search(
        r"onCancelSession\([^)]*session\.id",
        sidebar,
    ), "each running row needs a stop control wired to onCancelSession"


def test_app_wires_cancel_session_to_chat_cancel_api():
    app = read("frontend/src/App.tsx")
    assert "handleCancelSession" in app
    assert "cancelChatStream" in app
    assert re.search(
        r"onCancelSession=\{(handleCancelSession|onCancelSession)\}",
        app,
    ), "Sidebar must receive a cancel handler from App shell"


def test_session_summary_mapper_preserves_stream_metadata():
    mappers = read("frontend/src/services/hermes/mappers.ts")
    assert "activeStreamId" in mappers
    assert "isStreaming" in mappers
    assert "active_stream_id" in mappers
