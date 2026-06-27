"""Stateless document pipeline test API — TDD vertical slices."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
BASE = "/api/v1/test"


def test_pipeline_test_routes_registered() -> None:
    from app.api.v1.router import api_v1_router

    paths = {getattr(route, "path", "") for route in api_v1_router.routes}
    assert f"{BASE}/convert" in paths
    assert f"{BASE}/embed" in paths
    assert f"{BASE}/rerank" in paths
    assert f"{BASE}/organize" in paths
    assert f"{BASE}/pipeline" in paths


def test_convert_upload_returns_markdown_without_persistence() -> None:
    """POST /api/v1/test/convert turns an uploaded .txt file into markdown in-memory."""
    content = b"Hello pipeline test\nLine two"
    response = client.post(
        f"{BASE}/convert",
        files={"file": ("sample.txt", io.BytesIO(content), "text/plain")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "markdown" in payload
    assert "Hello pipeline test" in payload["markdown"]
    assert payload.get("source_filename") == "sample.txt"
    assert payload.get("persisted") is False


def test_embed_texts_returns_vectors() -> None:
    """POST /api/v1/test/embed returns one vector per input text."""
    mock_emb = MagicMock()
    mock_emb.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]

    with patch(
        "app.document_api.services.pipeline_test.build_embeddings",
        return_value=mock_emb,
    ):
        response = client.post(
            f"{BASE}/embed",
            json={"texts": ["alpha", "beta"]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["vectors"] == [[0.1, 0.2], [0.3, 0.4]]
    assert payload["dimensions"] == 2
    mock_emb.embed_documents.assert_called_once_with(["alpha", "beta"])


def test_rerank_returns_scored_order() -> None:
    """POST /api/v1/test/rerank scores and orders candidate documents."""
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = [(1, 0.9), (0, 0.4)]

    with patch(
        "app.document_api.services.pipeline_test.build_reranker",
        return_value=mock_reranker,
    ):
        response = client.post(
            f"{BASE}/rerank",
            json={
                "query": "search term",
                "documents": ["doc A", "doc B"],
                "top_n": 2,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["index"] == 1
    assert payload["results"][0]["score"] == 0.9
    assert payload["results"][0]["document"] == "doc B"
    mock_reranker.rerank.assert_called_once()


def test_organize_returns_structured_text() -> None:
    """POST /api/v1/test/organize formats text via LLM without saving."""
    mock_chat = MagicMock()
    mock_chat.invoke.return_value = MagicMock(content="## Clean\n\nStructured body")

    with patch(
        "app.document_api.services.pipeline_test.LlmEngine.from_settings"
    ) as mock_engine_cls:
        mock_engine_cls.return_value.build_langchain_chat.return_value = mock_chat
        response = client.post(
            f"{BASE}/organize",
            json={"text": "messy raw text"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert "Structured body" in payload["text"]
    assert payload.get("persisted") is False


def test_pipeline_runs_organize_before_chunk_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Combined pipeline honors TEST_PIPELINE_LLM_ORGANIZE_TIMING=before_chunk."""
    monkeypatch.setenv("TEST_PIPELINE_LLM_ORGANIZE_TIMING", "before_chunk")

    organize_calls: list[str] = []
    chunk_calls: list[str] = []

    def fake_organize(text: str, **_kwargs: object) -> dict:
        organize_calls.append(text)
        return {"text": f"ORG:{text}", "error": None}

    def fake_chunk(text: str, *_args: object, **_kwargs: object) -> list[str]:
        chunk_calls.append(text)
        return [f"chunk:{text}"]

    with (
        patch(
            "app.document_api.services.pipeline_test.organize_text",
            side_effect=fake_organize,
        ),
        patch(
            "app.document_api.services.pipeline_test.chunk_text",
            side_effect=fake_chunk,
        ),
        patch(
            "app.document_api.services.pipeline_test.build_embeddings",
            return_value=None,
        ),
    ):
        response = client.post(
            f"{BASE}/pipeline",
            json={"text": "raw body", "query": "q", "documents": ["raw body"]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["llm_organize_timing"] == "before_chunk"
    assert organize_calls == ["raw body"]
    assert chunk_calls == ["ORG:raw body"]
    assert payload["chunks"] == ["chunk:ORG:raw body"]


def test_pipeline_runs_organize_after_chunk_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Combined pipeline honors TEST_PIPELINE_LLM_ORGANIZE_TIMING=after_chunk."""
    monkeypatch.setenv("TEST_PIPELINE_LLM_ORGANIZE_TIMING", "after_chunk")

    organize_inputs: list[str] = []

    def fake_organize(text: str, **_kwargs: object) -> dict:
        organize_inputs.append(text)
        return {"text": f"ORG:{text}", "error": None}

    with (
        patch(
            "app.document_api.services.pipeline_test.organize_text",
            side_effect=fake_organize,
        ),
        patch(
            "app.document_api.services.pipeline_test.chunk_text",
            return_value=["part-one", "part-two"],
        ),
        patch(
            "app.document_api.services.pipeline_test.build_embeddings",
            return_value=None,
        ),
    ):
        response = client.post(
            f"{BASE}/pipeline",
            json={"text": "raw body"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["llm_organize_timing"] == "after_chunk"
    assert organize_inputs == ["part-one\n\npart-two"]
    assert payload["chunks"] == ["part-one", "part-two"]
    assert "ORG:part-one" in payload.get("organized_text", "")
