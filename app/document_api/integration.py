"""Integrate Document RAG API into Hermes WebUI."""

from __future__ import annotations

import asyncio
import logging
import os
import re

from fastapi import APIRouter

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"true", "yes", "on", "enabled", "1"})
_FALSY = frozenset({"false", "no", "off", "disabled", "0"})


def is_document_api_feature_requested() -> bool:
    """Whether the integrated document API should load (env toggle + SUPABASE_URL).

    ``HERMES_WEBUI_DOCUMENT_API_ENABLED`` overrides the default:
      - unset → enabled when ``SUPABASE_URL`` is non-empty (legacy behaviour)
      - ``false`` → disabled regardless of Supabase config
      - ``true`` → enabled (still requires ``SUPABASE_URL``)
    """
    raw = os.getenv("HERMES_WEBUI_DOCUMENT_API_ENABLED", "").strip().lower()
    if raw in _FALSY:
        return False
    if raw in _TRUTHY:
        return True
    try:
        from app.document_api.core.config import get_settings

        return bool(get_settings().supabase_url.strip())
    except Exception:
        return False

_document_api_initialized = False
_document_api_router: APIRouter | None = None
_document_api_import_error: str | None = None

# First path segment under /api/v1/ owned by Hermes WebUI (not document API).
_WEBUI_V1_SEGMENTS = frozenset({
    "admin",
    "agent-actions",
    "approval",
    "auth",
    "background",
    "btw",
    "chat",
    "clarify",
    "client-events",
    "commands",
    "crons",
    "dashboard",
    "file",
    "files",
    "gateway",
    "git-info",
    "git",
    "goal",
    "health",
    "insights",
    "kanban",
    "list",
    "logs",
    "mcp",
    "memory",
    "models",
    "notes",
    "onboarding",
    "personalities",
    "personality",
    "plugins",
    "profiles",
    "projects",
    "providers",
    "proxy",
    "rollback",
    "session",
    "sessions",
    "settings",
    "shutdown",
    "skills",
    "system",
    "terminal",
    "test",
    "transcribe",
    "transcript-report",
    "updates",
    "upload",
    "wiki",
    "workspace",
    "workspaces",
})

_DOCUMENT_API_PREFIXES = (
    "/api/v1/documents",
    "/api/v1/search",
    "/api/v1/jobs",
    "/api/v1/ingest-pending",
    "/api/v1/transcript-report",
    "/api/v1/rename/document",
    "/api/v1/rename/file",
)

_PIPELINE_TEST_PREFIX = "/api/v1/test"


def is_pipeline_test_public_path(path: str) -> bool:
    """Stateless pipeline test API — no auth, no persistence."""
    return path == _PIPELINE_TEST_PREFIX or path.startswith(_PIPELINE_TEST_PREFIX + "/")


def is_document_api_public_path(path: str) -> bool:
    """Document API is public when RBAC is off, or for MCP search tools when MCP is mounted."""
    if is_pipeline_test_public_path(path):
        return True
    if _load_document_api_router() is None:
        return False
    from app.document_api.access import (
        document_api_requires_rbac,
        is_document_api_path,
        is_mcp_search_public_route,
    )

    # Document API paths honor RBAC when multi-user is active (including MCP search tools).

    if document_api_requires_rbac() and is_document_api_path(path):
        return False
    if any(path == prefix or path.startswith(prefix + "/") for prefix in _DOCUMENT_API_PREFIXES):
        return True
    match = re.match(r"^/api/v1/([^/]+)(?:/|$)", path)
    if not match:
        return False
    segment = match.group(1)
    return segment not in _WEBUI_V1_SEGMENTS


def _load_document_api_router() -> APIRouter | None:
    global _document_api_router, _document_api_import_error
    if not is_document_api_feature_requested():
        return None
    if _document_api_router is not None:
        return _document_api_router
    if _document_api_import_error is not None:
        return None
    try:
        from app.document_api.api.v1.router import api_router

        _document_api_router = api_router
        return _document_api_router
    except Exception as exc:
        _document_api_import_error = str(exc)
        logger.warning("Document API unavailable: %s", exc)
        return None


def get_document_api_router() -> APIRouter:
    return _load_document_api_router() or APIRouter()


def document_api_enabled() -> bool:
    """Document API is enabled when requested, Supabase is configured, and deps import."""
    if not is_document_api_feature_requested():
        return False
    try:
        from app.document_api.core.config import get_settings

        if not get_settings().supabase_url.strip():
            return False
    except Exception:
        return False
    return _load_document_api_router() is not None


async def startup_document_api() -> None:
    global _document_api_initialized
    if _document_api_initialized:
        return

    if not is_document_api_feature_requested():
        raw = os.getenv("HERMES_WEBUI_DOCUMENT_API_ENABLED", "").strip()
        if raw.lower() in _FALSY:
            print(
                "[document-api] disabled — HERMES_WEBUI_DOCUMENT_API_ENABLED=false",
                flush=True,
            )
        else:
            print(
                "[document-api] skipped — set SUPABASE_URL (and related env) to enable.",
                flush=True,
            )
        return

    router = _load_document_api_router()
    if router is None:
        print(
            "[document-api] skipped — install requirements.txt "
            f"({_document_api_import_error or 'import failed'})",
            flush=True,
        )
        return

    from app.document_api.core.config import get_settings as get_document_settings
    from app.document_api.core.logging_setup import configure_app_logging
    from app.document_api.services.document_pipeline import bootstrap_on_startup

    settings = get_document_settings()
    if not settings.supabase_url.strip():
        print(
            "[document-api] skipped — set SUPABASE_URL (and related env) to enable.",
            flush=True,
        )
        return

    configure_app_logging(settings.log_level)

    print("[document-api] bootstrapping document pipeline...", flush=True)
    await asyncio.to_thread(bootstrap_on_startup)

    if settings.embedding_enabled:
        print("[document-api] EMBEDDING_ENABLED=true → warming embedding model...", flush=True)
        try:
            from app.document_api.lm_engine.hf_load_utils import resolve_hf_model_path
            from app.document_api.lm_engine.qwen_vl_hf_embeddings import warm_embedding_model

            model_path, model_source = resolve_hf_model_path(
                model_id=settings.embedding_model,
                models_dir=settings.hf_models_dir,
                explicit_path=settings.embedding_model_path,
            )
            print(
                f"[document-api] embedding resolve: {model_path} (source={model_source})",
                flush=True,
            )
            if model_source == "hub" and settings.hf_models_dir.strip():
                print(
                    "[document-api] tip: pre-download snapshots to "
                    f"{settings.hf_models_dir.rstrip('/')}/Qwen3-VL-Embedding-2B "
                    "or run scripts/download-embedding-models.sh",
                    flush=True,
                )
            from app.document_api.lm_engine.hf_load_utils import log_torch_device_status

            log_torch_device_status(label="embedding")
            logger.info("Embedding: warming up model (startup)...")
            warmed = await asyncio.to_thread(warm_embedding_model, settings)
            if warmed:
                logger.info("Embedding: model ready")
                print("[document-api] embedding model ready", flush=True)
            else:
                print(
                    "[document-api] EMBEDDING_ENABLED=true but backend is not local Hugging Face "
                    "(set EMBEDDING_BACKEND=huggingface or use a Hub model id without EMBEDDING_BASE_URL)",
                    flush=True,
                )
        except Exception:
            logger.exception("Embedding: warm-up failed")
            print(
                "[document-api] embedding warm-up failed — install requirements.txt and check GPU",
                flush=True,
            )
    else:
        print(
            "[document-api] embedding lazy-load — set EMBEDDING_ENABLED=true to warm up at startup",
            flush=True,
        )

    if settings.reranker_enabled:
        print("[document-api] RERANKER_ENABLED=true → warming reranker model...", flush=True)
        try:
            from app.document_api.lm_engine.hf_load_utils import resolve_hf_model_path
            from app.document_api.lm_engine.qwen_vl_hf_reranker import warm_reranker_model

            model_path, model_source = resolve_hf_model_path(
                model_id=settings.reranker_model,
                models_dir=settings.hf_models_dir,
                explicit_path=settings.reranker_model_path,
            )
            print(
                f"[document-api] reranker resolve: {model_path} (source={model_source})",
                flush=True,
            )
            if model_source == "hub" and settings.hf_models_dir.strip():
                print(
                    "[document-api] tip: local HF cache under "
                    f"{settings.hf_models_dir.rstrip('/')} is missing config or weights; "
                    "pre-download with: scripts/download-embedding-models.sh DOWNLOAD_RERANKER=1",
                    flush=True,
                )
            from app.document_api.lm_engine.hf_load_utils import log_torch_device_status

            log_torch_device_status(label="reranker")
            logger.info("Reranker: warming up model (startup)...")
            warmed = await asyncio.to_thread(warm_reranker_model, settings)
            if warmed:
                logger.info("Reranker: model ready")
                print("[document-api] reranker model ready", flush=True)
            else:
                print(
                    "[document-api] RERANKER_ENABLED=true but backend is not local Hugging Face "
                    "(set RERANKER_BACKEND=huggingface or use a Hub model id without RERANKER_BASE_URL)",
                    flush=True,
                )
        except Exception:
            logger.exception("Reranker: warm-up failed")
            print(
                "[document-api] reranker warm-up failed — install requirements.txt and check GPU",
                flush=True,
            )
    else:
        print(
            "[document-api] reranker disabled — set RERANKER_ENABLED=true to warm up at startup",
            flush=True,
        )

    if settings.asr_enabled:
        url = (settings.asr_api_url or "").strip()
        model = (settings.asr_model_id or "").strip()
        if not url or not model:
            print(
                "[document-api] ASR_ENABLED=true but ASR_API_URL or ASR_MODEL_ID is missing",
                flush=True,
            )
        else:
            print(f"[document-api] ASR enabled (HTTP) → {url} model={model}", flush=True)
    else:
        print(
            "[document-api] ASR disabled — set ASR_ENABLED=true to enable HTTP transcription",
            flush=True,
        )

    _document_api_initialized = True
    print("[document-api] ready", flush=True)
