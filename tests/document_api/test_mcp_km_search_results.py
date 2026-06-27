"""MCP KM search result count from MCP_KM_NUMBER_OF_RESULTS only."""

from __future__ import annotations

import pytest


def test_default_mcp_km_number_of_results_reads_env(monkeypatch: pytest.MonkeyPatch):
    from app.document_api.core import config as cfg

    monkeypatch.setenv("MCP_KM_NUMBER_OF_RESULTS", "9")
    assert cfg.default_mcp_km_number_of_results() == 9


def test_get_query_request_omits_number_of_results(monkeypatch: pytest.MonkeyPatch):
    from app.document_api.api.v1.param_deps import get_query_request

    monkeypatch.setenv("MCP_KM_NUMBER_OF_RESULTS", "7")
    req = get_query_request(
        query_text="hello",
        query_mode="hybrid",
        docs=[],
        rrf_k=60,
        use_reranker=True,
    )
    assert req.query_text == "hello"
    assert not hasattr(req, "number_of_results") or getattr(req, "number_of_results", None) is None
