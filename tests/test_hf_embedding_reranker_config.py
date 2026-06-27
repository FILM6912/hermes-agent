"""Tests for Hugging Face embedding/reranker backend selection."""

from __future__ import annotations

import json
from pathlib import Path

from app.document_api.core.config import Settings
from app.document_api.lm_engine.hf_load_utils import (
    ensure_cross_encoder_module_configs,
    ensure_pooling_module_config,
    infer_hidden_size_from_config,
    is_usable_hf_model_dir,
    normalize_load_bits,
    resolve_embedding_dimension,
)
from app.document_api.lm_engine.qwen_vl_hf_embeddings import (
    build_hf_embeddings,
    is_huggingface_embedding_backend,
)
from app.document_api.lm_engine.qwen_vl_hf_reranker import (
    build_hf_reranker,
    is_huggingface_reranker_backend,
    warm_reranker_model,
)


def test_normalize_load_bits_accepts_4_8_16() -> None:
    assert normalize_load_bits(16) == 16
    assert normalize_load_bits("8bit") == 8
    assert normalize_load_bits("4") == 4


def test_huggingface_backend_selected_for_hub_model_ids() -> None:
    settings = Settings(
        EMBEDDING_BACKEND="huggingface",
        EMBEDDING_MODEL="Qwen/Qwen3-VL-Embedding-2B",
        EMBEDDING_LOAD_BITS=16,
    )
    assert is_huggingface_embedding_backend(settings) is True
    assert build_hf_embeddings(settings) is not None

    rerank_settings = Settings(
        RERANKER_BACKEND="huggingface",
        RERANKER_MODEL="Qwen/Qwen3-VL-Reranker-2B",
        RERANKER_LOAD_BITS=16,
    )
    assert is_huggingface_reranker_backend(rerank_settings) is True
    assert build_hf_reranker(rerank_settings) is not None


def test_resolve_hf_model_path_prefers_mounted_directory(tmp_path: Path) -> None:
    from app.document_api.lm_engine.hf_load_utils import resolve_hf_model_path

    models_root = tmp_path / "models"
    local_dir = models_root / "Qwen3-VL-Embedding-2B"
    local_dir.mkdir(parents=True)
    (local_dir / "config.json").write_text("{}", encoding="utf-8")
    (local_dir / "model.safetensors").write_bytes(b"")

    resolved, source = resolve_hf_model_path(
        model_id="Qwen/Qwen3-VL-Embedding-2B",
        models_dir=str(models_root),
    )
    assert source == "local"
    assert resolved == str(local_dir.resolve())

    explicit, explicit_source = resolve_hf_model_path(
        model_id="Qwen/Qwen3-VL-Embedding-2B",
        models_dir="",
        explicit_path=str(local_dir),
    )
    assert explicit_source == "local"
    assert explicit == str(local_dir.resolve())


def test_resolve_hf_model_path_finds_hub_cache_snapshot(tmp_path: Path) -> None:
    from app.document_api.lm_engine.hf_load_utils import resolve_hf_model_path

    models_root = tmp_path / "models"
    snapshot = (
        models_root
        / "hub"
        / "models--Qwen--Qwen3-VL-Embedding-2B"
        / "snapshots"
        / "abc123"
    )
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(b"")

    resolved, source = resolve_hf_model_path(
        model_id="Qwen/Qwen3-VL-Embedding-2B",
        models_dir=str(models_root),
    )
    assert source == "local"
    assert resolved == str(snapshot.resolve())


def test_infer_hidden_size_from_qwen_vl_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"text_config": {"hidden_size": 2048}}',
        encoding="utf-8",
    )
    assert infer_hidden_size_from_config(str(tmp_path)) == 2048


def test_resolve_embedding_dimension_prefers_settings(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        '{"text_config": {"hidden_size": 1024}}',
        encoding="utf-8",
    )
    assert resolve_embedding_dimension(str(tmp_path), configured_dim=2048) == 2048
    assert resolve_embedding_dimension(str(tmp_path), configured_dim=0) == 1024


def test_ensure_pooling_module_config_writes_missing_file(tmp_path: Path) -> None:
    ensure_pooling_module_config(
        str(tmp_path),
        model_id="",
        embedding_dimension=2048,
        pooling_mode="lasttoken",
    )
    config_path = tmp_path / "1_Pooling" / "config.json"
    assert config_path.is_file()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["embedding_dimension"] == 2048
    assert payload["pooling_mode"] == "lasttoken"


def test_vllm_backend_when_base_url_set() -> None:
    settings = Settings(
        EMBEDDING_MODEL="Qwen/Qwen3-VL-Embedding-2B",
        EMBEDDING_BASE_URL="http://127.0.0.1:8101/v1",
        EMBEDDING_BACKEND="vllm",
    )
    assert is_huggingface_embedding_backend(settings) is False
    assert build_hf_embeddings(settings) is None


def test_resolve_hf_model_path_skips_incomplete_hub_snapshot(tmp_path: Path) -> None:
    from app.document_api.lm_engine.hf_load_utils import resolve_hf_model_path

    models_root = tmp_path / "models"
    snapshot = (
        models_root
        / "hub"
        / "models--Qwen--Qwen3-VL-Reranker-2B"
        / "snapshots"
        / "partial"
    )
    snapshot.mkdir(parents=True)
    (snapshot / "modules.json").write_text("[]", encoding="utf-8")

    resolved, source = resolve_hf_model_path(
        model_id="Qwen/Qwen3-VL-Reranker-2B",
        models_dir=str(models_root),
    )
    assert source == "hub"
    assert resolved == "Qwen/Qwen3-VL-Reranker-2B"


def test_resolve_hf_model_path_skips_snapshot_missing_weights(tmp_path: Path) -> None:
    from app.document_api.lm_engine.hf_load_utils import resolve_hf_model_path

    models_root = tmp_path / "models"
    snapshot = (
        models_root
        / "hub"
        / "models--Qwen--Qwen3-VL-Reranker-2B"
        / "snapshots"
        / "metadata_only"
    )
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "modules.json").write_text("[]", encoding="utf-8")

    resolved, source = resolve_hf_model_path(
        model_id="Qwen/Qwen3-VL-Reranker-2B",
        models_dir=str(models_root),
    )
    assert source == "hub"
    assert resolved == "Qwen/Qwen3-VL-Reranker-2B"


def test_is_usable_hf_model_dir_requires_config_json(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert is_usable_hf_model_dir(empty) is False

    (empty / "config.json").write_text("{}", encoding="utf-8")
    assert is_usable_hf_model_dir(empty) is False

    (empty / "model.safetensors").write_bytes(b"")
    assert is_usable_hf_model_dir(empty) is True


def test_is_usable_hf_model_dir_accepts_pytorch_and_sharded_weights(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")

    pytorch_dir = tmp_path / "pytorch"
    pytorch_dir.mkdir()
    (pytorch_dir / "config.json").write_text("{}", encoding="utf-8")
    (pytorch_dir / "pytorch_model.bin").write_bytes(b"")
    assert is_usable_hf_model_dir(pytorch_dir) is True

    shard_dir = tmp_path / "sharded"
    shard_dir.mkdir()
    (shard_dir / "config.json").write_text("{}", encoding="utf-8")
    (shard_dir / "model.safetensors.index.json").write_text("{}", encoding="utf-8")
    assert is_usable_hf_model_dir(shard_dir) is True


def test_ensure_cross_encoder_module_configs_writes_missing_files(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text('{"model_type": "qwen3_vl"}', encoding="utf-8")

    ensure_cross_encoder_module_configs(
        str(tmp_path),
        model_id="",
        reranker_prompt="Custom rerank prompt.",
    )

    st_config = json.loads(
        (tmp_path / "config_sentence_transformers.json").read_text(encoding="utf-8")
    )
    assert st_config["model_type"] == "CrossEncoder"
    assert st_config["prompts"]["query"] == "Custom rerank prompt."

    logit_config = json.loads(
        (tmp_path / "1_LogitScore" / "config.json").read_text(encoding="utf-8")
    )
    assert logit_config["true_token_id"] == 9693
    assert logit_config["false_token_id"] == 2152


def test_warm_reranker_model_skips_non_hf_backend() -> None:
    settings = Settings(
        RERANKER_BACKEND="vllm",
        RERANKER_BASE_URL="http://127.0.0.1:8102/v1",
        RERANKER_MODEL="Qwen/Qwen3-VL-Reranker-2B",
    )
    assert warm_reranker_model(settings) is False
