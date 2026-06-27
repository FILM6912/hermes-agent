"""Regression: document summary must not persist LangChain AIMessage repr strings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

from app.document_api.lm_engine.message_text import extract_langchain_message_text
from app.document_api.services.document_summary import generate_document_summary_llm


@dataclass
class _FakeChunk:
    content: str = ""
    additional_kwargs: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"content={self.content!r} additional_kwargs={self.additional_kwargs} "
            "response_metadata={'model_provider': 'openai'} id='lc_run--fake' tool_calls=[]"
        )


def test_extract_langchain_message_text_skips_empty_repr():
    chunk = _FakeChunk(content="")
    assert extract_langchain_message_text(chunk) == ""
    assert "lc_run" not in extract_langchain_message_text(chunk)


def test_extract_langchain_message_text_reads_content():
    chunk = _FakeChunk(content="สรุปเอกสารทดสอบ")
    assert extract_langchain_message_text(chunk) == "สรุปเอกสารทดสอบ"


def test_extract_langchain_message_text_reads_reasoning_content():
    chunk = _FakeChunk(content="", additional_kwargs={"reasoning_content": "คิดก่อนตอบ"})
    assert extract_langchain_message_text(chunk) == "คิดก่อนตอบ"


def test_generate_document_summary_invoke_persists_full_text_not_stream_join():
    settings = MagicMock()
    settings.llm_enabled = True

    chat = MagicMock()
    chat.invoke.return_value = _FakeChunk(
        content="## สรุป\n\nProduct brief ของ Raspberry Pi 4 Model B.\n\n### ประเด็นสำคัญ\n- RAM สูงสุด 8GB"
    )

    engine = MagicMock()
    engine.build_langchain_chat.return_value = chat

    streamed: list[str] = []
    with (
        patch("app.document_api.services.document_summary.get_settings", return_value=settings),
        patch("app.document_api.services.document_summary.LlmEngine.from_settings", return_value=engine),
        patch("app.document_api.services.document_summary.load_system_prompt", return_value="sys"),
    ):
        summary, err = generate_document_summary_llm(
            markdown_text="# รายงาน\nเนื้อหา",
            document_name="doc",
            source_filename="report.md",
            stream_callback=streamed.append,
        )

    assert err is None
    assert summary.startswith("## สรุป")
    assert "Raspberry Pi 4 Model B" in summary
    assert "lc_run" not in summary
    assert "additional_kwargs" not in summary
    chat.stream.assert_not_called()
    chat.invoke.assert_called_once()
    assert streamed == [summary]


def test_generate_document_summary_returns_error_when_invoke_empty():
    settings = MagicMock()
    settings.llm_enabled = True

    chat = MagicMock()
    chat.invoke.return_value = _FakeChunk(content="")

    engine = MagicMock()
    engine.build_langchain_chat.return_value = chat

    with (
        patch("app.document_api.services.document_summary.get_settings", return_value=settings),
        patch("app.document_api.services.document_summary.LlmEngine.from_settings", return_value=engine),
        patch("app.document_api.services.document_summary.load_system_prompt", return_value="sys"),
    ):
        summary, err = generate_document_summary_llm(
            markdown_text="# รายงาน\nเนื้อหา",
            document_name="doc",
            source_filename="report.md",
            stream_callback=lambda _t: None,
        )

    assert summary == ""
    assert err == "LLM returned an empty summary"
    chat.invoke.assert_called_once()
