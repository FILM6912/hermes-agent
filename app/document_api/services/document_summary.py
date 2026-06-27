"""สรุปเอกสารด้วย LLM (ใช้กับ document ingest และ list API)"""

from __future__ import annotations

import logging
from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage

from app.document_api.core.config import Settings, get_settings
from app.document_api.lm_engine import LlmEngine
from app.document_api.lm_engine.message_text import extract_langchain_message_text
from app.document_api.prompt_loader import load_system_prompt

logger = logging.getLogger(__name__)


def generate_document_summary_llm(
    *,
    markdown_text: str,
    document_name: str,
    source_filename: str,
    settings: Settings | None = None,
    stream_callback: Callable[[str], None] | None = None,
) -> tuple[str, str | None]:
    """
    สรุปเอกสาร (``prompts/document_summary.md``).

    คืน ``(summary_text, error_message)`` — ``error_message`` เป็น ``None`` เมื่อสำเร็จหรือข้าม
    """
    settings = settings or get_settings()
    if not settings.llm_enabled:
        return "", None
    body = (markdown_text or "").replace("\r\n", "\n").strip()
    if not body:
        return "", None
    if len(body) > 12000:
        body = body[:12000] + "\n\n[…truncated…]"

    chat = LlmEngine.from_settings(settings).build_langchain_chat(purpose="status")
    if not chat:
        return "", "LLM client unavailable — check LLM_API_KEY / LLM_BASE_URL / LLM_MODEL"

    doc = (document_name or "").strip()
    src_fn = (source_filename or "").strip()
    try:
        sys_p = load_system_prompt(filename="document_summary.md", section="document")
    except Exception as e:
        logger.warning("โหลด prompts/document_summary.md ไม่สำเร็จ: %s", e)
        sys_p = (
            "Summarize the document for search and archives. "
            "Output compact Markdown in Thai with ## สรุป and bullet points."
        )
    hum_p = (
        f"ชื่อชุดเอกสาร (document set): {doc}\n"
        f"ชื่อไฟล์: {src_fn}\n\n"
        f"เนื้อหาเอกสาร (markdown):\n---\n{body}\n---"
    )
    try:
        messages = [SystemMessage(content=sys_p), HumanMessage(content=hum_p)]
        msg = chat.invoke(messages)
        text = extract_langchain_message_text(msg).strip()
        if stream_callback is not None and text:
            stream_callback(text)
        if not text:
            return "", "LLM returned an empty summary"
        return text, None
    except Exception as e:
        logger.warning("document llm summary failed: %s", e)
        err = str(e).strip() or type(e).__name__
        return "", f"LLM summary failed: {err}"
