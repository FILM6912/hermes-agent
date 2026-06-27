"""Regression: tool steps must render while reasoning streams (before answer text)."""

from pathlib import Path


def _message_blocks_src() -> str:
    return Path("frontend/src/features/chat/utils/messageBlocks.ts").read_text(
        encoding="utf-8"
    )


def test_streaming_blocks_include_tools_when_thinking_present():
    src = _message_blocks_src()
    assert "if (tools.length > 0 && !answerText)" in src
    assert "if (!thinking.length)" not in src, (
        "buildBlocksForStreamingAssistant must not drop tools when thinking steps exist"
    )
    assert 'blocks.push({ type: "tools", steps: tools })' in src


def test_streaming_blocks_push_tools_before_answer_text():
    src = _message_blocks_src()
    idx = src.find("if (tools.length > 0 && !answerText)")
    assert idx != -1
    branch = src[idx : idx + 220]
    assert 'blocks.push({ type: "tools", steps: tools })' in branch, (
        "tools block must render before assistant answer text arrives"
    )


def test_streaming_blocks_push_tools_before_answer_text_with_anchors():
    src = _message_blocks_src()
    idx = src.find("if (tools.length > 0 && hasAnchoredTools)")
    assert idx != -1
    branch = src[idx : idx + 260]
    no_text_idx = branch.find("if (!answerText)")
    assert no_text_idx != -1
    no_text_branch = branch[no_text_idx : no_text_idx + 180]
    assert 'blocks.push({ type: "tools", steps: tools })' in no_text_branch


def test_resolve_message_blocks_reconciles_missing_tool_steps():
    src = _message_blocks_src()
    assert "missingTools" in src
    assert "toolIdsInBlocks" in src
