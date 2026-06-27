import unittest
from pathlib import Path

from app.domain.streaming import (
    _fallback_title_from_exchange,
    _first_exchange_snippets,
    _sanitize_generated_title,
)


class TestGeneratedTitleSanitization(unittest.TestCase):
    def test_strips_session_title_markdown_prefix(self):
        self.assertEqual(
            _sanitize_generated_title("**Session Title:** Clarifying Topic for Discussion"),
            "Clarifying Topic for Discussion",
        )

    def test_strips_plain_title_prefix(self):
        self.assertEqual(
            _sanitize_generated_title("Title: Clarifying Topic for Discussion"),
            "Clarifying Topic for Discussion",
        )

    def test_strips_wrapping_markdown_emphasis(self):
        self.assertEqual(
            _sanitize_generated_title("**Clarifying Topic for Discussion**"),
            "Clarifying Topic for Discussion",
        )

    def test_first_exchange_skips_empty_assistant_tool_call_placeholder(self):
        messages = [
            {"role": "user", "content": "What time is it in San Francisco?"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1"}]},
            {"role": "tool", "content": "tool output", "tool_call_id": "call_1"},
            {"role": "assistant", "content": "It is 6:16 PM in San Francisco."},
        ]
        self.assertEqual(
            _first_exchange_snippets(messages),
            ("What time is it in San Francisco?", "It is 6:16 PM in San Francisco."),
        )

    def test_exchange_snippets_include_attachment_names(self):
        from app.domain.streaming import _exchange_snippets_for_title

        messages = [
            {
                "role": "user",
                "content": "เห็นอะไร",
                "attachments": [{"name": "minipack.step"}],
            },
            {
                "role": "assistant",
                "content": "นี่คือโมเดล 3D CAD minipack สำหรับบรรจุภัณฑ์",
            },
        ]
        user_text, assistant_text = _exchange_snippets_for_title(messages)
        self.assertIn("เห็นอะไร", user_text)
        self.assertIn("minipack.step", user_text)
        self.assertIn("3D CAD minipack", assistant_text)

    def test_fallback_title_uses_attachment_for_generic_thai_prompt(self):
        title = _fallback_title_from_exchange(
            "เห็นอะไร\n[User attached: minipack.step]",
            "นี่คือโมเดล 3D CAD minipack สำหรับบรรจุภัณฑ์ขนาดเล็ก",
        )
        self.assertEqual(title, "minipack")

    def test_fallback_title_does_not_copy_assistant_answer(self):
        assistant = "นี่คือโมเดล 3D CAD minipack สำหรับบรรจุภัณฑ์ขนาดเล็ก"
        title = _fallback_title_from_exchange("เห็นอะไร", assistant)
        self.assertNotEqual(title, assistant.split("。")[0].strip())
        self.assertNotIn("3D CAD minipack", title or "")

    def test_title_is_unhelpful_echo_rejects_provisional_repeat(self):
        from app.domain.streaming import _title_is_unhelpful_echo

        messages = [
            {"role": "user", "content": "เห็นอะไร"},
            {"role": "assistant", "content": "โมเดล CAD minipack"},
        ]
        self.assertTrue(
            _title_is_unhelpful_echo(
                "เห็นอะไร",
                "เห็นอะไร\n[User attached: minipack.step]",
                messages,
                current_title="เห็นอะไร",
            )
        )
        self.assertFalse(
            _title_is_unhelpful_echo(
                "โมเดล CAD minipack",
                "เห็นอะไร",
                messages,
            )
        )

    def test_title_is_unhelpful_echo_rejects_assistant_copy(self):
        from app.domain.streaming import _title_is_unhelpful_echo

        messages = [
            {"role": "user", "content": "Explain the minipack CAD model"},
            {
                "role": "assistant",
                "content": "This is a 3D CAD minipack model for small packaging",
            },
        ]
        assistant_text = messages[1]["content"]
        self.assertTrue(
            _title_is_unhelpful_echo(
                "This is a 3D CAD minipack model for small packaging",
                "Explain the minipack CAD model",
                messages,
                assistant_text=assistant_text,
            )
        )
        self.assertFalse(
            _title_is_unhelpful_echo(
                "Minipack CAD packaging model",
                "Explain the minipack CAD model",
                messages,
                assistant_text=assistant_text,
            )
        )

    def test_fallback_title_uses_english_discussion_suffix(self):
        self.assertEqual(
            _fallback_title_from_exchange('Please review "random cancel"', ""),
            "random cancel discussion",
        )

    def test_fallback_title_summary_label_is_english(self):
        self.assertEqual(
            _fallback_title_from_exchange("Generate a short title summary test", ""),
            "Session title auto-summary test",
        )

    def test_fallback_title_non_latin_input_uses_english_placeholder(self):
        self.assertEqual(
            _fallback_title_from_exchange("讨论一下这个问题", ""),
            "Conversation topic",
        )

    def test_fallback_title_non_latin_quoted_topic_uses_english_placeholder(self):
        self.assertEqual(
            _fallback_title_from_exchange('Please review "讨论主题"', ""),
            "Conversation topic",
        )

    def test_title_generation_source_has_no_cjk_literals(self):
        src = Path("app/domain/streaming.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"[\u4e00-\u9fff]", "title generation code should stay English-only")
