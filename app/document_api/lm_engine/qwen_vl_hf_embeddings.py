"""Local Hugging Face Qwen3-VL-Embedding via sentence-transformers."""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.document_api.core.config import Settings
from app.document_api.lm_engine.hf_load_utils import (
    build_transformers_model_kwargs,
    ensure_pooling_module_config,
    resolve_embedding_dimension,
    resolve_hf_model_path,
)

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model_ref: Any | None = None


def _load_sentence_transformer(settings: Settings) -> Any:
    global _model_ref
    with _model_lock:
        if _model_ref is not None:
            return _model_ref

        from sentence_transformers import SentenceTransformer

        hub_id = (settings.embedding_model or "Qwen/Qwen3-VL-Embedding-2B").strip()
        model_path, source = resolve_hf_model_path(
            model_id=hub_id,
            models_dir=settings.hf_models_dir,
            explicit_path=settings.embedding_model_path,
        )
        model_kwargs = build_transformers_model_kwargs(settings.embedding_load_bits)
        embedding_dimension = resolve_embedding_dimension(
            model_path,
            settings.embedding_dimensions,
        )
        ensure_pooling_module_config(
            model_path,
            model_id=hub_id,
            embedding_dimension=embedding_dimension,
        )
        logger.info(
            "Loading embedding model %s from %s (load_bits=%s, embedding_dimension=%s)",
            model_path,
            source,
            settings.embedding_load_bits,
            embedding_dimension,
        )
        print(
            f"[embedding] loading {model_path} ({source}, bits={settings.embedding_load_bits}) ...",
            flush=True,
        )
        _model_ref = SentenceTransformer(
            model_path,
            trust_remote_code=True,
            model_kwargs=model_kwargs,
        )
        print(f"[embedding] ready: {model_path}", flush=True)
        return _model_ref


class QwenVLHFEmbeddings:
    """LangChain-compatible wrapper around ``SentenceTransformer``."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.document_instruction = settings.embedding_document_instruction
        self.query_instruction = settings.embedding_query_instruction

    @property
    def _model(self) -> Any:
        return _load_sentence_transformer(self._settings)

    def _to_vector(self, row: Any) -> list[float]:
        if hasattr(row, "tolist"):
            row = row.tolist()
        return [float(x) for x in row]

    def embed_query(self, text: str) -> list[float]:
        vec = self._model.encode([text], prompt=self.query_instruction)[0]
        return self._to_vector(vec)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        rows = self._model.encode(texts, prompt=self.document_instruction)
        return [self._to_vector(row) for row in rows]

    def embed_image_url(self, image_url: str, *, instruction: str | None = None) -> list[float]:
        payload: str | dict[str, str] = image_url
        if image_url.startswith(("http://", "https://")):
            payload = {"image": image_url}
        vec = self._model.encode([payload], prompt=instruction or self.document_instruction)[0]
        return self._to_vector(vec)


def is_huggingface_embedding_backend(settings: Settings) -> bool:
    backend = (settings.embedding_backend or "auto").strip().lower()
    if backend in {"hf", "huggingface", "hub"}:
        return True
    if backend in {"vllm", "openai", "ollama", "http"}:
        return False
    model = (settings.embedding_model or "").strip()
    if "/" in model and not (settings.embedding_base_url or "").strip():
        return True
    return False


def build_hf_embeddings(settings: Settings) -> QwenVLHFEmbeddings | None:
    if not is_huggingface_embedding_backend(settings):
        return None
    model = (settings.embedding_model or "").strip()
    if not model:
        return None
    return QwenVLHFEmbeddings(settings)


def warm_embedding_model(settings: Settings) -> bool:
    """Eager-load the local Hugging Face embedding model (startup warm-up)."""
    if not is_huggingface_embedding_backend(settings):
        return False
    _load_sentence_transformer(settings)
    return True
