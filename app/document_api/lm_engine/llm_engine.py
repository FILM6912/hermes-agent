from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.document_api.core.config import Settings, get_settings


@dataclass
class LlmEngine:
    """เลเยอร์ LLM — สร้าง ``langchain_openai.ChatOpenAI`` (OpenAI API หรือ OpenAI-compatible เช่น LM Studio / vLLM)."""

    settings: Settings

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> LlmEngine:
        return cls(settings=settings if settings is not None else get_settings())

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_enabled)

    @property
    def model(self) -> str:
        return (self.settings.llm_model or "gpt-4o-mini").strip()

    @property
    def base_url(self) -> str:
        return (self.settings.llm_base_url or "").strip()

    @property
    def api_key(self) -> str:
        return self.settings.llm_api_key

    @property
    def effective_api_key(self) -> str:
        """คีย์ที่ใช้จริง — fallback ไป EMBEDDING_API_KEY เหมือนเดิมในโปรเจ็กต์"""
        return (self.settings.llm_api_key or self.settings.embedding_api_key or "").strip()

    @property
    def effective_base_url(self) -> str:
        """base URL ที่ใช้จริง — fallback ไป EMBEDDING_BASE_URL"""
        return (self.settings.llm_base_url or self.settings.embedding_base_url or "").strip()

    @property
    def rearrange_enabled(self) -> bool:
        return bool(self.settings.enable_llm_rearrange)

    def build_langchain_chat(
        self,
        *,
        purpose: Literal["toc", "status", "rearrange"] = "toc",
    ) -> Any | None:
        """
        สร้าง client แชทแบบ OpenAI API (ผ่าน LangChain).
        - ``purpose=toc|status`` — ต้อง ``LLM_ENABLED``
        - ``purpose=rearrange`` — ต้อง ``ENABLE_LLM_REARRANGE`` ไม่ใช่ ``off`` (โหมด ``reflow_then_chunk`` หรือ ``chunk_then_reflow``)
        """
        api_key = self.effective_api_key
        if not api_key:
            return None
        if purpose == "rearrange":
            if not getattr(self.settings, "enable_llm_rearrange", False):
                return None
        elif not self.settings.llm_enabled:
            return None
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            return None

        if purpose == "status":
            temp = 0.25
        elif purpose == "rearrange":
            temp = 0.15
        else:
            temp = 0.2
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "model": self.model,
            "temperature": temp,
        }
        if purpose == "rearrange":
            kwargs["max_tokens"] = 24576
        base = self.effective_base_url
        if base:
            kwargs["base_url"] = base
        return ChatOpenAI(**kwargs)
