"""Activity timeline shows terminal command text, not only generic 'Ran command'."""

from pathlib import Path


def read(rel: str) -> str:
    return (Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")


def test_activity_timeline_extracts_command_preview():
    tool_content = read("frontend/src/features/preview/utils/toolStepContent.ts")
    timeline = read("frontend/src/features/chat/utils/activityTimeline.ts")
    assert "commandPreviewFromStep" in tool_content
    assert '"command"' in tool_content
    assert "commandPreviewFromStep(step)" in timeline
