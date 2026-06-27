from __future__ import annotations

from typing import Annotated, TYPE_CHECKING

from fastapi import Depends, HTTPException

from app.document_api.core.config import Settings, get_settings

if TYPE_CHECKING:
    from app.document_api.lm_engine import EmbeddingEngine


def get_settings_dep() -> Settings:
    return get_settings()


def require_asr_enabled(settings: Annotated[Settings, Depends(get_settings_dep)]) -> Settings:
    if not getattr(settings, "asr_enabled", False):
        raise HTTPException(
            status_code=503,
            detail="ASR is disabled — set ASR_ENABLED=true in .env",
        )
    if not (settings.asr_api_url or "").strip():
        raise HTTPException(
            status_code=503,
            detail="ASR_API_URL is not configured",
        )
    if not (settings.asr_model_id or "").strip():
        raise HTTPException(
            status_code=503,
            detail="ASR_MODEL_ID is not configured",
        )
    return settings


def get_embedding_engine(settings: Annotated[Settings, Depends(get_settings_dep)]) -> EmbeddingEngine:
    from app.document_api.lm_engine import EmbeddingEngine

    return EmbeddingEngine.from_settings(settings)
