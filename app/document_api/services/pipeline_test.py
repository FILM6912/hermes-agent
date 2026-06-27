"""Stateless document pipeline helpers for /api/v1/test/* (no persistence)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Literal

from app.document_api.core.config import Settings, get_settings
from app.document_api.lm_engine.llm_engine import LlmEngine
from app.document_api.services.document_pipeline import (
    chunk_text,
    convert_file_to_markdown,
)
from app.document_api.services.embeddings import build_embeddings, build_reranker

OrganizeTiming = Literal["before_chunk", "after_chunk"]


def resolve_organize_timing(settings: Settings | None = None) -> OrganizeTiming:
    settings = settings or get_settings()
    raw = (getattr(settings, "test_pipeline_llm_organize_timing", None) or "before_chunk").strip().lower()
    if raw in {"after_chunk", "after", "chunk_then_reflow", "chunk_then_organize"}:
        return "after_chunk"
    return "before_chunk"


def resolve_organize_model(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    override = (getattr(settings, "test_pipeline_organize_model", None) or "").strip()
    if override:
        return override
    return (settings.llm_model or "gpt-4o-mini").strip()


def convert_uploaded_bytes(*, filename: str, content: bytes) -> dict[str, Any]:
    """Convert uploaded bytes to markdown using the document converter registry."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="pipeline_test_conv_"))
    try:
        out_path = tmp_dir / Path(filename).name
        out_path.write_bytes(content)
        conv = convert_file_to_markdown(out_path)
        return {
            "markdown": conv.markdown,
            "source_filename": conv.source_filename or filename,
            "metadata": dict(conv.metadata or {}),
            "image_count": len(conv.images or []),
            "persisted": False,
        }
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


def embed_texts(*, texts: list[str], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    cleaned = [t for t in (texts or []) if (t or "").strip()]
    if not cleaned:
        raise ValueError("texts must contain at least one non-empty string")

    embeddings = build_embeddings(settings)
    if embeddings is None:
        raise ValueError("embedding backend not configured — set EMBEDDING_* env vars")

    if hasattr(embeddings, "embed_documents"):
        vectors = embeddings.embed_documents(cleaned)
    else:
        vectors = [embeddings.embed_query(t) for t in cleaned]

    if not vectors or any(v is None for v in vectors):
        raise ValueError("embedding returned empty vectors")

    dim = len(vectors[0]) if vectors else 0
    return {
        "vectors": vectors,
        "dimensions": dim,
        "count": len(vectors),
        "persisted": False,
    }


def rerank_texts(
    *,
    query: str,
    documents: list[str],
    top_n: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    q = (query or "").strip()
    docs = [d for d in (documents or []) if (d or "").strip()]
    if not q:
        raise ValueError("query is required")
    if not docs:
        raise ValueError("documents must contain at least one non-empty string")

    reranker = build_reranker(settings)
    if reranker is None:
        raise ValueError("reranker backend not configured — set RERANKER_* env vars")

    limit = top_n if top_n is not None else len(docs)
    limit = min(max(1, int(limit)), len(docs))
    scored = reranker.rerank(query=q, documents=docs, top_n=limit)

    results = []
    for idx, score in scored:
        if 0 <= idx < len(docs):
            results.append({"index": idx, "score": float(score), "document": docs[idx]})

    return {
        "query": q,
        "results": results,
        "persisted": False,
    }


def organize_text(
    *,
    text: str,
    settings: Settings | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Structure or clean raw text with the configured LLM (no DB writes)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    settings = settings or get_settings()
    body = (text or "").replace("\r\n", "\n").strip()
    if not body:
        raise ValueError("text is required")

    engine = LlmEngine.from_settings(settings)
    chat = engine.build_langchain_chat(purpose="rearrange") or engine.build_langchain_chat(purpose="status")
    if not chat:
        raise ValueError("LLM client unavailable — check LLM_API_KEY / LLM_BASE_URL / LLM_MODEL")

    model_name = (model or resolve_organize_model(settings)).strip()
    if hasattr(chat, "model_name"):
        chat.model_name = model_name
    elif hasattr(chat, "model"):
        chat.model = model_name

    system_prompt = (
        "You are a document preparation assistant. Restructure the user's text into clear, "
        "search-friendly markdown. Preserve factual content; fix headings, lists, and paragraph breaks. "
        "Output markdown only — no preamble."
    )
    human_prompt = f"Organize this text:\n\n---\n{body}\n---"

    try:
        msg = chat.invoke([SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)])
        organized = (getattr(msg, "content", None) or str(msg)).strip()
        if not organized:
            raise ValueError("LLM returned empty text")
        return {"text": organized, "model": model_name, "persisted": False, "error": None}
    except Exception as exc:
        err = str(exc).strip() or type(exc).__name__
        return {"text": "", "model": model_name, "persisted": False, "error": err}


def run_test_pipeline(
    *,
    text: str | None = None,
    filename: str | None = None,
    file_bytes: bytes | None = None,
    query: str | None = None,
    rerank_documents: list[str] | None = None,
    run_organize: bool = True,
    run_embed: bool = True,
    run_rerank: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """In-memory pipeline: convert → organize? → chunk → organize? → embed → rerank?."""
    settings = settings or get_settings()
    timing = resolve_organize_timing(settings)

    markdown = (text or "").strip()
    convert_meta: dict[str, Any] | None = None

    if file_bytes and filename:
        converted = convert_uploaded_bytes(filename=filename, content=file_bytes)
        markdown = converted["markdown"]
        convert_meta = converted

    if not markdown:
        raise ValueError("provide text or upload a file")

    organized_before: str | None = None
    organized_after: str | None = None
    working = markdown

    if run_organize and timing == "before_chunk":
        org = organize_text(text=working, settings=settings)
        if org.get("error"):
            raise ValueError(f"organize failed: {org['error']}")
        working = org["text"]
        organized_before = working

    chunks = chunk_text(
        working,
        settings.chunk_size,
        settings.chunk_overlap,
        split_text=settings.split_text,
    ) or ([working] if working else [])

    if run_organize and timing == "after_chunk":
        combined = "\n\n".join(chunks)
        org = organize_text(text=combined, settings=settings)
        if org.get("error"):
            raise ValueError(f"organize failed: {org['error']}")
        organized_after = org["text"]
        chunks = chunk_text(
            organized_after,
            settings.chunk_size,
            settings.chunk_overlap,
            split_text=settings.split_text,
        ) or ([organized_after] if organized_after else [])

    embed_result: dict[str, Any] | None = None
    if run_embed and chunks:
        try:
            embed_result = embed_texts(texts=chunks, settings=settings)
        except ValueError:
            embed_result = None

    rerank_result: dict[str, Any] | None = None
    if run_rerank and query and (rerank_documents or chunks):
        candidates = rerank_documents if rerank_documents else chunks
        try:
            rerank_result = rerank_texts(
                query=query,
                documents=candidates,
                settings=settings,
            )
        except ValueError:
            rerank_result = None

    return {
        "convert": convert_meta,
        "markdown": markdown,
        "organized_text": organized_before or organized_after,
        "llm_organize_timing": timing,
        "chunks": chunks,
        "embedding": embed_result,
        "rerank": rerank_result,
        "persisted": False,
    }
