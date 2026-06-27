"""Preview panel content view state — todos/tool-detail vs file tree."""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_preview_panel_content_module_exports_modes():
    src = read("frontend/src/features/preview/previewPanelContent.ts")
    assert 'mode: "files"' in src
    assert 'mode: "todos"' in src
    assert 'mode: "tool-detail"' in src
    assert "findLatestTodosInSteps" in src
    assert "resolvePreviewPanelContentForStep" in src


def test_preview_window_renders_todos_and_back_nav():
    src = read("frontend/src/features/preview/components/PreviewWindow.tsx")
    assert "TodosToolList" in src
    assert "onBackToFiles" in src
    assert "showAlternatePanel" in src
    assert re.search(r'panelContent\.mode === "todos"', src)


def test_stream_consumer_does_not_auto_open_todos_panel():
    src = read("frontend/src/features/chat/utils/consumeHermesStream.ts")
    assert "findLatestTodosInSteps" in src
    assert "setPreviewPanelContent" in src
    idx = src.find("const latestTodos = findLatestTodosInSteps")
    assert idx != -1
    branch = src[idx : idx + 900]
    assert "latestTodos && setPreviewPanelContent" in branch
    assert 'prev.mode !== "todos"' in branch
    assert "setIsPreviewOpen(true)" not in branch.split("const latestTodos")[1].split("} else {")[0]


def test_activity_timeline_opens_panel_only_for_todos_tools():
    src = read("frontend/src/features/chat/components/ActivityTimeline.tsx")
    assert "isTodosToolName" in src
    assert "useTodosPanel" in src
    assert "isTodosStep" in src


def test_todos_tool_name_includes_to_dos():
    src = read("frontend/src/features/preview/utils/parseTodosToolPayload.ts")
    assert '"to_dos"' in src
    assert '"todo"' in src


def test_collect_todos_from_steps_merges_todo_tools():
    src = read("frontend/src/features/preview/previewPanelContent.ts")
    assert "collectTodosFromSteps" in src
    assert "findLatestTodosStep" in src
    assert "extractTodosFromStep(step) ?? []" in src


def test_preview_clears_selected_file_for_todos_panel():
    src = read("frontend/src/features/preview/components/PreviewWindow.tsx")
    assert 'panelContent.mode === "todos"' in src
    assert "setSelectedFile(null)" in src


def test_skill_view_payload_not_parsed_as_todos():
    todos = read("frontend/src/features/preview/utils/parseTodosToolPayload.ts")
    skill = read("frontend/src/features/preview/utils/parseSkillViewToolPayload.ts")
    panel = read("frontend/src/features/preview/previewPanelContent.ts")
    assert "isSkillViewToolResult" in skill
    assert "isSkillViewToolResult(obj)" in todos
    assert "if (!isTodos) return null" in panel
    assert "const todos = extractTodosFromStep(step)" not in panel


def test_tool_complete_maps_preview_to_snippet():
    src = read("frontend/src/services/hermes/mappers.ts")
    assert "toolResultSnippetFromPayload" in src
    assert "asString(payload.preview)" in src


def test_preview_tool_detail_shows_input_and_output():
    src = read("frontend/src/features/preview/components/ToolDetailPanel.tsx")
    assert "parseStepInputOutput" in src
    assert 'label={t("process.input")}' in src
    assert 'label={t("process.output")}' in src
    assert "ToolPlainOutputView" in src
    window = read("frontend/src/features/preview/components/PreviewWindow.tsx")
    assert "ToolDetailPanel" in window


def test_tool_output_readability_helpers():
    fmt = read("frontend/src/features/preview/utils/formatToolOutput.ts")
    assert "normalizeToolOutputText" in fmt
    assert "parseToolOutputBlocks" in fmt
    assert "isTerminalLikeTool" in fmt
    view = read("frontend/src/features/preview/components/ToolPlainOutputView.tsx")
    assert "whitespace-pre-wrap" in view
    assert "JsonPrettyBlock" in view


def test_stream_syncs_open_tool_detail_step():
    src = read("frontend/src/features/chat/utils/consumeHermesStream.ts")
    assert 'prev.mode === "tool-detail"' in src
    assert "toolDetailStepChanged" in src


def test_skill_view_panel_avoids_fetch_reset_on_stream():
    src = read("frontend/src/features/preview/components/SkillViewToolPanel.tsx")
    assert "fetchedSkillRef" in src
    assert "[skillName]" in src
    assert "setFetchedContent(null)" in src
    assert "fetching && !output?.content?.trim()" in src


def test_tool_detail_only_parses_todos_for_todo_tools():
    detail = read("frontend/src/features/preview/components/ToolDetailPanel.tsx")
    todos = read("frontend/src/features/preview/utils/parseTodosToolPayload.ts")
    assert "isTodosTool ? parseTodosFromToolPayload" in detail
    assert "parseTodosFromToolPayload(parsed ?? raw) ??" not in detail
    assert "isTodoItemRecord" in todos
    assert '"file_path" in rec' in todos
