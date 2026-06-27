from __future__ import annotations

from typing import Any

from app.document_api.core.config import Settings
from app.document_api.lm_engine.embedding_engine import build_langchain_embeddings
from app.document_api.lm_engine.qwen_vl_reranker import build_qwen_vl_reranker


def build_embeddings(settings: Settings) -> Any | None:
    """สร้าง LangChain embeddings — เลเยอร์จริงอยู่ที่ ``app.lm_engine.embedding_engine``."""
    return build_langchain_embeddings(settings)


def build_reranker(settings: Settings) -> Any | None:
    """สร้าง reranker client (Hugging Face local หรือ vLLM HTTP)."""
    return build_qwen_vl_reranker(settings)
