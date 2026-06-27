"""สรุปข้อความถอดเสียงด้วย LLM (ใช้กับ transcript audio jobs)"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.document_api.core.config import Settings, get_settings
from app.document_api.lm_engine import LlmEngine
from app.document_api.lm_engine.message_text import extract_langchain_message_text
from app.document_api.prompt_loader import load_system_prompt

logger = logging.getLogger(__name__)


def generate_transcript_audio_summary_llm(
    *,
    transcript_text: str,
    document_name: str,
    transcript_name: str,
    source_filename: str,
    settings: Settings | None = None,
) -> tuple[str, str | None]:
    """
    สรุปข้อความถอดเสียง (``prompts/transcript_audio_summary.md``).

    คืน ``(summary_text, error_message)`` — ``error_message`` เป็น ``None`` เมื่อสำเร็จหรือข้าม
    """
    settings = settings or get_settings()
    if not settings.llm_enabled:
        return "", None
    body = (transcript_text or "").replace("\r\n", "\n").strip()
    if not body:
        return "", None
    if len(body) > 12000:
        body = body[:12000] + "\n\n[…truncated…]"

    chat = LlmEngine.from_settings(settings).build_langchain_chat(purpose="status")
    if not chat:
        return "", "LLM client unavailable — check LLM_API_KEY / LLM_BASE_URL / LLM_MODEL"

    doc = (document_name or "").strip()
    tname = (transcript_name or "").strip()
    src_fn = (source_filename or "").strip()
    try:
        sys_p = load_system_prompt(filename="transcript_audio_summary.md", section="transcript_audio")
    except Exception as e:
        logger.warning("โหลด prompts/transcript_audio_summary.md ไม่สำเร็จ: %s", e)
        sys_p = (
            "Summarize the speech transcript for search and archives. "
            "Output compact Markdown in Thai with ## สรุป and bullet points."
        )
    hum_p = (
        f"ชื่อชุดเอกสาร (document set): {doc}\n"
        f"ชื่อชุด transcript: {tname}\n"
        f"ชื่อไฟล์เสียง: {src_fn}\n\n"
        f"ข้อความถอดเสียง:\n---\n{body}\n---"
    )
    try:
        msg = chat.invoke([SystemMessage(content=sys_p), HumanMessage(content=hum_p)])
        text = extract_langchain_message_text(msg)
        if not text:
            return "", "LLM returned an empty summary"
        return text, None
    except Exception as e:
        logger.warning("transcript audio llm summary failed: %s", e)
        err = str(e).strip() or type(e).__name__
        return "", f"LLM summary failed: {err}"


def generate_transcript_audio_report_llm(
    *,
    transcript_text: str,
    document_name: str,
    transcript_name: str,
    source_filename: str,
    settings: Settings | None = None,
) -> tuple[str, str | None]:
    """
    สร้างรายงานจากข้อความถอดเสียง (``prompts/transcript_audio_report.md``).

    คืน ``(report_text, error_message)`` — ``error_message`` เป็น ``None`` เมื่อสำเร็จหรือข้าม
    """
    settings = settings or get_settings()
    if not settings.llm_enabled:
        return "", None
    body = (transcript_text or "").replace("\r\n", "\n").strip()
    if not body:
        return "", None
    if len(body) > 12000:
        body = body[:12000] + "\n\n[…truncated…]"

    chat = LlmEngine.from_settings(settings).build_langchain_chat(purpose="status")
    if not chat:
        return "", "LLM client unavailable — check LLM_API_KEY / LLM_BASE_URL / LLM_MODEL"

    doc = (document_name or "").strip()
    tname = (transcript_name or "").strip()
    src_fn = (source_filename or "").strip()
    try:
        sys_p = load_system_prompt(filename="transcript_audio_report.md", section="transcript_audio_report")
    except Exception as e:
        logger.warning("โหลด prompts/transcript_audio_report.md ไม่สำเร็จ: %s", e)
        sys_p = (
            "Write a formal Markdown report in Thai from the speech transcript. "
            "Use ## รายงาน and structured sections; do not invent facts."
        )
    hum_p = (
        f"ชื่อชุดเอกสาร (document set): {doc}\n"
        f"ชื่อชุด transcript: {tname}\n"
        f"ชื่อไฟล์เสียง: {src_fn}\n\n"
        f"ข้อความถอดเสียง:\n---\n{body}\n---"
    )
    try:
        msg = chat.invoke([SystemMessage(content=sys_p), HumanMessage(content=hum_p)])
        text = extract_langchain_message_text(msg)
        if not text:
            return "", "LLM returned an empty report"
        return text, None
    except Exception as e:
        logger.warning("transcript audio llm report failed: %s", e)
        err = str(e).strip() or type(e).__name__
        return "", f"LLM report failed: {err}"
