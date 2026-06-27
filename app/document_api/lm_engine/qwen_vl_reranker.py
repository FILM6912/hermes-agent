from __future__ import annotations

from typing import Any

import httpx

from app.document_api.core.config import Settings


def is_qwen_vl_reranker_model(model: str) -> bool:
    m = (model or "").strip().lower()
    return "qwen3-vl-reranker" in m or "qwen3_vl_reranker" in m


class QwenVLReranker:
    """HTTP client สำหรับ Qwen3-VL-Reranker ผ่าน vLLM /v1/rerank."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = (api_key or "EMPTY").strip() or "EMPTY"
        self.base_url = (base_url or "").rstrip("/")
        self.model = (model or "").strip()
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def _endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/rerank"
        return f"{self.base_url}/v1/rerank"

    def rerank(
        self,
        *,
        query: str,
        documents: list[Any],
        top_n: int,
    ) -> list[tuple[int, float]]:
        if not documents:
            return []

        body = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": min(max(1, top_n), len(documents)),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self._endpoint(), headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        out: list[tuple[int, float]] = []
        for item in data.get("results") or []:
            idx = int(item.get("index", -1))
            score = float(item.get("relevance_score", 0.0) or 0.0)
            if idx >= 0:
                out.append((idx, score))
        return out


def build_qwen_vl_reranker(settings: Settings) -> QwenVLReranker | None:
    from app.document_api.lm_engine.qwen_vl_hf_reranker import build_hf_reranker

    hf = build_hf_reranker(settings)
    if hf is not None:
        return hf

    if not settings.reranker_enabled:
        return None
    base = (settings.reranker_base_url or "").strip()
    model = (settings.reranker_model or "").strip()
    if not base or not model:
        return None
    return QwenVLReranker(
        api_key=settings.reranker_api_key or settings.embedding_api_key or "EMPTY",
        base_url=base,
        model=model,
    )


def document_payload_for_rerank(row: dict[str, Any]) -> Any:
    """แปลงแถว vector เป็นข้อความหรือ image_url สำหรับ reranker."""
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        import json

        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    chunk_type = str(metadata.get("chunk_type") or "text")
    image_url = metadata.get("image_url") or ""
    content = (row.get("content") or "").strip()

    if chunk_type == "image" and image_url:
        return {"type": "image_url", "image_url": {"url": str(image_url)}}
    return content or str(image_url or "")
