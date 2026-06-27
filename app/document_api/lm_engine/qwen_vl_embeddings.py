from __future__ import annotations

from typing import Any

import httpx

from app.document_api.core.config import Settings


def is_qwen_vl_embedding_model(model: str) -> bool:
    m = (model or "").strip().lower()
    return "qwen3-vl-embedding" in m or "qwen3_vl_embedding" in m


class QwenVLEmbeddings:
    """HTTP client สำหรับ Qwen3-VL-Embedding ผ่าน vLLM Chat Embeddings API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int = 0,
        document_instruction: str = "Represent the user's input.",
        query_instruction: str = "Retrieve images or text relevant to the user's query.",
        timeout: float = 120.0,
    ) -> None:
        self.api_key = (api_key or "EMPTY").strip() or "EMPTY"
        self.base_url = (base_url or "").rstrip("/")
        self.model = (model or "").strip()
        self.dimensions = int(dimensions or 0)
        self.document_instruction = document_instruction
        self.query_instruction = query_instruction
        self.timeout = timeout

    def _endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/embeddings"
        return f"{self.base_url}/v1/embeddings"

    def _post(self, messages: list[dict[str, Any]]) -> list[float]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "encoding_format": "float",
            "continue_final_message": True,
            "add_special_tokens": True,
        }
        if self.dimensions > 0:
            body["dimensions"] = self.dimensions

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self._endpoint(), headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        rows = data.get("data") or []
        if not rows:
            raise ValueError("empty embedding response")
        emb = rows[0].get("embedding")
        if not emb:
            raise ValueError("missing embedding vector")
        return [float(x) for x in emb]

    def _qwen_messages(
        self,
        *,
        instruction: str,
        text: str = "",
        image_url: str | None = None,
    ) -> list[dict[str, Any]]:
        user_content: list[dict[str, Any]] = []
        if image_url:
            user_content.append({"type": "image_url", "image_url": {"url": image_url}})
        user_content.append({"type": "text", "text": text or ""})
        return [
            {"role": "system", "content": [{"type": "text", "text": instruction}]},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": [{"type": "text", "text": ""}]},
        ]

    def embed_query(self, text: str) -> list[float]:
        messages = self._qwen_messages(instruction=self.query_instruction, text=text)
        return self._post(messages)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_document(t) for t in texts]

    def _embed_document(self, text: str) -> list[float]:
        messages = self._qwen_messages(instruction=self.document_instruction, text=text)
        return self._post(messages)

    def embed_image_url(self, image_url: str, *, instruction: str | None = None) -> list[float]:
        messages = self._qwen_messages(
            instruction=instruction or self.document_instruction,
            image_url=image_url,
        )
        return self._post(messages)


def build_qwen_vl_embeddings(settings: Settings) -> QwenVLEmbeddings | None:
    from app.document_api.lm_engine.qwen_vl_hf_embeddings import is_huggingface_embedding_backend

    if is_huggingface_embedding_backend(settings):
        return None
    if not (settings.embedding_api_key or "").strip() and not (settings.embedding_base_url or "").strip():
        return None
    if not is_qwen_vl_embedding_model(settings.embedding_model):
        return None
    return QwenVLEmbeddings(
        api_key=settings.embedding_api_key or "EMPTY",
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        document_instruction=settings.embedding_document_instruction,
        query_instruction=settings.embedding_query_instruction,
    )
