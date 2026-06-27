"""Cancel must clear in-flight tool activity spinners (Running command…)."""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_finalize_running_process_steps_marks_cancelled():
    src = read("frontend/src/features/chat/utils/finalizeRunningProcessSteps.ts")
    assert 'status: "cancelled"' in src
    assert "finalizeRunningStepsInMessage" in src


def test_stream_abort_finalizes_live_tools_before_close():
    src = read("frontend/src/services/hermes/streamChat.ts")
    assert "finalizeStreamStateForCancel" in src
    assert "finalizeLiveToolCallsForCancel" in src
    assert "finalizeRunningProcessSteps" in src
    assert "finalizeStreamStateForCancel(state)" in src


def test_activity_timeline_stopped_label_for_cancelled_tools():
    src = read("frontend/src/features/chat/utils/activityTimeline.ts")
    assert 'status === "cancelled"' in src
    assert "Command stopped" in src
    assert 'toolActivityLabel(toolName, step.status)' in src


def test_merged_cancel_turn_finalizes_running_tool_steps():
    mappers = read("frontend/src/services/hermes/mappers.ts")
    assert "assistantRunHasCancelMarker" in mappers
    assert "finalizeRunningProcessSteps" in mappers
    assert "markIncompleteAsCancelled" in mappers
    types = read("frontend/src/types/index.ts")
    assert '"cancelled"' in types
