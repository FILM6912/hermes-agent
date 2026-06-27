from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.document_api.core.config import Settings, get_settings


def _ollama_detection(base_url: str, model: str) -> bool:
    """แยก Ollama เดิมใน embeddings.py — ใช้ native Ollama client"""
    is_ollama = False
    if base_url:
        parsed = urlparse(base_url)
        host = (parsed.hostname or "").lower()
        is_ollama = host in {"localhost", "127.0.0.1", "0.0.0.0", "192.168.99.1"} and parsed.port == 11434
        is_ollama = is_ollama or "/api" in parsed.path
    if not is_ollama and ":" in model:
        is_ollama = True
    return is_ollama


def build_langchain_embeddings(settings: Settings) -> Any | None:
    """
    สร้าง LangChain embeddings instance.

    ลำดับ backend:
      1. ``EMBEDDING_BACKEND=huggingface`` → โหลดจาก Hugging Face Hub (sentence-transformers)
      2. Qwen3-VL + ``EMBEDDING_BASE_URL`` → vLLM Chat Embeddings HTTP
      3. Ollama / OpenAI-compatible API
    """
    from app.document_api.lm_engine.qwen_vl_hf_embeddings import build_hf_embeddings
    from app.document_api.lm_engine.qwen_vl_embeddings import build_qwen_vl_embeddings

    hf = build_hf_embeddings(settings)
    if hf is not None:
        return hf

    qwen_vl = build_qwen_vl_embeddings(settings)
    if qwen_vl is not None:
        return qwen_vl

    if not settings.embedding_api_key:
        return None

    base_url = (settings.embedding_base_url or "").strip()
    model = (settings.embedding_model or "").strip()

    if _ollama_detection(base_url, model):
        cleaned_base_url = base_url.replace("/v1", "") if base_url else "http://localhost:11434"
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError:
            from langchain_community.embeddings import OllamaEmbeddings

        return OllamaEmbeddings(base_url=cleaned_base_url, model=model)

    from langchain_openai import OpenAIEmbeddings

    kwargs: dict[str, Any] = {"api_key": settings.embedding_api_key, "model": model}
    if base_url:
        kwargs["base_url"] = base_url
    if settings.embedding_dimensions > 0:
        kwargs["dimensions"] = settings.embedding_dimensions
    return OpenAIEmbeddings(**kwargs)


@dataclass
class EmbeddingEngine:
    """เลเยอร์ embedding — official OpenAI หรือ OpenAI-compatible endpoint ตามค่า EMBEDDING_*"""

    settings: Settings

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> EmbeddingEngine:
        return cls(settings=settings if settings is not None else get_settings())

    @property
    def configured(self) -> bool:
        return bool((self.settings.embedding_api_key or "").strip())

    @property
    def model(self) -> str:
        return (self.settings.embedding_model or "").strip()

    @property
    def base_url(self) -> str:
        return (self.settings.embedding_base_url or "").strip()

    @property
    def api_key(self) -> str:
        return self.settings.embedding_api_key

    @property
    def dimensions(self) -> int:
        return int(self.settings.embedding_dimensions or 0)

    def build_langchain(self) -> Any | None:
        return build_langchain_embeddings(self.settings)
