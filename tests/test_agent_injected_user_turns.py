"""Synthetic agent steering rows must not appear as user chat bubbles."""

from app.domain.routes import _merged_session_messages_for_display
from app.domain.streaming import _is_agent_injected_user_turn
from app.domain.models import Session


def test_is_agent_injected_user_turn_detects_continuation_nudge():
    msg = {
        "role": "user",
        "content": (
            "[System: The previous response was cut off by a "
            "network error mid-stream. Continue exactly where "
            "you left off. Do not restart or repeat prior text. "
            "Finish the answer directly.]"
        ),
    }
    assert _is_agent_injected_user_turn(msg) is True


def test_is_agent_injected_user_turn_allows_real_user_text():
    msg = {"role": "user", "content": "สร้างหน้า login production grade"}
    assert _is_agent_injected_user_turn(msg) is False


def test_empty_recovery_user_nudge_remaps_to_assistant_notice():
    from app.domain.streaming import (
        _is_empty_recovery_user_nudge,
        _remap_message_for_display,
    )

    nudge = {
        "role": "user",
        "content": (
            "You just executed tool calls but returned an empty response. "
            "Please process the tool results above and continue with the task."
        ),
        "_empty_recovery_synthetic": True,
    }
    assert _is_empty_recovery_user_nudge(nudge) is True
    remapped = _remap_message_for_display(nudge)
    assert remapped is not None
    assert remapped["role"] == "assistant"
    assert "โมเดลยังไม่ตอบหลังเรียกเครื่องมือ" in remapped["content"]


def test_empty_recovery_assistant_placeholder_hidden_from_display():
    from app.domain.streaming import _remap_message_for_display

    placeholder = {
        "role": "assistant",
        "content": "(empty)",
        "_empty_recovery_synthetic": True,
    }
    assert _remap_message_for_display(placeholder) is None


def test_merged_session_messages_for_display_remaps_empty_recovery():
    session = Session(
        session_id="testsession02",
        title="Empty recovery remap",
        messages=[
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "(empty)",
                "_empty_recovery_synthetic": True,
            },
            {
                "role": "user",
                "content": (
                    "You just executed tool calls but returned an empty response. "
                    "Please process the tool results above and continue with the task."
                ),
                "_empty_recovery_synthetic": True,
            },
            {"role": "assistant", "content": "done"},
        ],
    )
    merged = _merged_session_messages_for_display(session)
    assert len(merged) == 3
    assert merged[0]["content"] == "hello"
    assert merged[1]["role"] == "assistant"
    assert "โมเดลยังไม่ตอบหลังเรียกเครื่องมือ" in merged[1]["content"]
    assert merged[2]["content"] == "done"


def test_merged_session_messages_for_display_strips_injected_turns():
    session = Session(
        session_id="testsession01",
        title="Injected turn filter",
        messages=[
            {"role": "user", "content": "hello"},
            {
                "role": "user",
                "content": "[System: Continue exactly where you left off.]",
            },
            {"role": "assistant", "content": "done"},
        ],
    )
    merged = _merged_session_messages_for_display(session)
    assert len(merged) == 2
    assert all(m.get("role") != "user" or not _is_agent_injected_user_turn(m) for m in merged)
