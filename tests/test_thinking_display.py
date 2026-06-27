"""Tests for reasoning vs visible answer distinction (frontend #852 parity)."""

from app.domain.helpers import redact_session_data
from app.domain.thinking_display import reasoning_is_distinct_from_content


def test_reasoning_duplicate_of_answer_is_not_distinct():
    intro = "ฟิล์ม! Hermes Agent ของคุณมี skills ทั้งหมด **109 skills**"
    assert reasoning_is_distinct_from_content(intro, intro) is False
    assert (
        reasoning_is_distinct_from_content(
            intro,
            f"{intro}\n\n## More sections follow",
        )
        is False
    )


def test_reasoning_with_real_thought_is_distinct():
    assert reasoning_is_distinct_from_content(
        "Let me list the installed skills first.",
        "Here are your 109 skills.",
    )


def test_reasoning_longer_than_answer_intro_stays_distinct():
    intro = "กำลังสร้างหน้า Login สวยๆ"
    reasoning = intro + " ให้ครับ! " + ("plan step " * 20)
    assert reasoning_is_distinct_from_content(reasoning, intro) is True


def test_redact_session_nulls_duplicate_reasoning():
    session = {
        "messages": [
            {
                "role": "assistant",
                "content": "Full visible answer text.",
                "reasoning": "Full visible answer text.",
            },
        ],
    }
    out = redact_session_data(session)
    assert out["messages"][0]["reasoning"] is None


def test_redact_session_dedupes_reasoning_content_field():
    session = {
        "messages": [
            {
                "role": "assistant",
                "content": "visible answer",
                "reasoning": "stale copy",
                "reasoning_content": "Let me check the skills list.",
            },
        ],
    }
    out = redact_session_data(session)
    row = out["messages"][0]
    assert row["reasoning"] == "Let me check the skills list."
    assert "reasoning_content" not in row


def test_redact_session_nulls_duplicate_reasoning_content():
    session = {
        "messages": [
            {
                "role": "assistant",
                "content": "same text",
                "reasoning": "same text",
                "reasoning_content": "same text",
            },
        ],
    }
    out = redact_session_data(session)
    row = out["messages"][0]
    assert row["reasoning"] is None
    assert "reasoning_content" not in row
