"""Local Hugging Face Qwen3-VL-Reranker via sentence-transformers CrossEncoder."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from app.document_api.core.config import Settings
from app.document_api.lm_engine.hf_load_utils import (
    build_transformers_model_kwargs,
    ensure_cross_encoder_module_configs,
    is_usable_hf_model_dir,
    resolve_hf_model_path,
)

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model_ref: Any | None = None

_DEFAULT_RERANK_PROMPT = "Retrieve images or text relevant to the user's query."


def _load_cross_encoder(settings: Settings) -> Any:
    global _model_ref
    with _model_lock:
        if _model_ref is not None:
            return _model_ref

        from sentence_transformers import CrossEncoder

        hub_id = (settings.reranker_model or "Qwen/Qwen3-VL-Reranker-2B").strip()
        model_path, source = resolve_hf_model_path(
            model_id=hub_id,
            models_dir=settings.hf_models_dir,
            explicit_path=settings.reranker_model_path,
        )
        if source == "local" and not is_usable_hf_model_dir(Path(model_path)):
            logger.warning(
                "Reranker local path %s is incomplete (missing config.json or "
                "model weights); falling back to Hub id %s for download",
                model_path,
                hub_id,
            )
            print(
                f"[reranker] local snapshot incomplete at {model_path}; "
                f"falling back to Hub {hub_id}",
                flush=True,
            )
            model_path, source = hub_id, "hub"
        if source == "local":
            ensure_cross_encoder_module_configs(
                model_path,
                model_id=hub_id,
                reranker_prompt=settings.reranker_prompt or _DEFAULT_RERANK_PROMPT,
            )
        model_kwargs = build_transformers_model_kwargs(settings.reranker_load_bits)
        logger.info(
            "Loading reranker model %s from %s (load_bits=%s)",
            model_path,
            source,
            settings.reranker_load_bits,
        )
        print(
            f"[reranker] loading {model_path} ({source}, bits={settings.reranker_load_bits}) ...",
            flush=True,
        )
        _model_ref = CrossEncoder(
            model_path,
            trust_remote_code=True,
            model_kwargs=model_kwargs,
        )
        print(f"[reranker] ready: {model_path}", flush=True)
        return _model_ref


class QwenVLHFReranker:
    """HTTP-compatible ``rerank()`` wrapper around ``CrossEncoder``."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.prompt = settings.reranker_prompt or _DEFAULT_RERANK_PROMPT

    @property
    def configured(self) -> bool:
        return bool((self._settings.reranker_model or "").strip())

    @property
    def _model(self) -> Any:
        return _load_cross_encoder(self._settings)

    def rerank(
        self,
        *,
        query: str,
        documents: list[Any],
        top_n: int,
    ) -> list[tuple[int, float]]:
        if not documents:
            return []
        pairs = [(query, doc) for doc in documents]
        scores = self._model.predict(pairs, prompt=self.prompt)
        ranked = sorted(enumerate(scores), key=lambda item: float(item[1]), reverse=True)
        limit = min(max(1, top_n), len(documents))
        out: list[tuple[int, float]] = []
        for idx, score in ranked[:limit]:
            out.append((int(idx), float(score)))
        return out


def is_huggingface_reranker_backend(settings: Settings) -> bool:
    backend = (settings.reranker_backend or "auto").strip().lower()
    if backend in {"hf", "huggingface", "hub"}:
        return True
    if backend in {"vllm", "openai", "http"}:
        return False
    model = (settings.reranker_model or "").strip()
    if "/" in model and not (settings.reranker_base_url or "").strip():
        return True
    return False


def build_hf_reranker(settings: Settings) -> QwenVLHFReranker | None:
    if not settings.reranker_enabled:
        return None
    if not is_huggingface_reranker_backend(settings):
        return None
    model = (settings.reranker_model or "").strip()
    if not model:
        return None
    return QwenVLHFReranker(settings)


def warm_reranker_model(settings: Settings) -> bool:
    """Eager-load the local Hugging Face reranker model (startup warm-up)."""
    if not is_huggingface_reranker_backend(settings):
        return False
    _load_cross_encoder(settings)
    return True
