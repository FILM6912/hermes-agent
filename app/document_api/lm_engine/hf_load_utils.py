"""Shared Hugging Face model load helpers (dtype / bits / local paths)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VALID_LOAD_BITS = frozenset({4, 8, 16})

_CROSS_ENCODER_HUB_REL_PATHS = (
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "1_LogitScore/config.json",
)

_DEFAULT_RERANKER_PROMPT = "Retrieve text relevant to the user's query."


def _has_model_weights(path: Path) -> bool:
    """Return True when weight files exist (single-file or sharded)."""
    for name in (
        "model.safetensors",
        "pytorch_model.bin",
        "model.safetensors.index.json",
        "pytorch_model.bin.index.json",
    ):
        if (path / name).is_file():
            return True
    return False


def is_usable_hf_model_dir(path: Path) -> bool:
    """Return True when a local tree has ``config.json`` and loadable weights."""
    return (path / "config.json").is_file() and _has_model_weights(path)


def _find_hub_cache_snapshot(root: Path, model_id: str) -> Path | None:
    """Locate a HuggingFace hub cache snapshot under ``root/hub``."""
    hub_root = root / "hub"
    if not hub_root.is_dir():
        return None
    cache_dir_name = "models--" + model_id.replace("/", "--")
    snapshots_dir = hub_root / cache_dir_name / "snapshots"
    if not snapshots_dir.is_dir():
        return None
    candidates = [p for p in snapshots_dir.iterdir() if p.is_dir()]
    if not candidates:
        return None

    usable = [path for path in candidates if is_usable_hf_model_dir(path)]
    if not usable:
        return None

    return max(usable, key=lambda path: path.stat().st_mtime)


def resolve_hf_model_path(
    *,
    model_id: str,
    models_dir: str = "",
    explicit_path: str = "",
) -> tuple[str, str]:
    """Return ``(resolved_path, source)`` where source is ``local`` or ``hub``."""
    model_id = (model_id or "").strip()
    override = (explicit_path or "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_dir():
            return str(path.resolve()), "local"
        if path.exists():
            return str(path.resolve()), "local"
        return override, "local"

    base = (models_dir or "").strip()
    if base and model_id:
        root = Path(base).expanduser()
        short_name = model_id.split("/")[-1]
        for candidate in (root / model_id, root / short_name):
            if candidate.is_dir() and is_usable_hf_model_dir(candidate):
                return str(candidate.resolve()), "local"
        snapshot = _find_hub_cache_snapshot(root, model_id)
        if snapshot is not None:
            return str(snapshot.resolve()), "local"
    return model_id, "hub"


def normalize_load_bits(value: object, *, name: str = "LOAD_BITS") -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be 4, 8, or 16")
    if isinstance(value, int):
        bits = value
    else:
        raw = str(value or "16").strip().lower()
        if raw.endswith("bit"):
            raw = raw[:-3].strip()
        bits = int(raw)
    if bits not in VALID_LOAD_BITS:
        raise ValueError(f"{name} must be one of 4, 8, 16 (got {bits})")
    return bits


def log_torch_device_status(*, label: str = "hf") -> None:
    """Print torch/CUDA availability (startup diagnostics for embedding/reranker)."""
    try:
        import torch
    except ImportError:
        print(f"[{label}] torch not installed", flush=True)
        return
    cuda = torch.cuda.is_available()
    count = torch.cuda.device_count() if cuda else 0
    device_name = torch.cuda.get_device_name(0) if cuda and count else "n/a"
    print(
        f"[{label}] torch={torch.__version__} cuda_available={cuda} "
        f"device_count={count} device0={device_name}",
        flush=True,
    )
    if not cuda:
        print(
            f"[{label}] tip: pass GPU into the container "
            "(docker compose up -d; use docker-compose.cpu.yml on hosts without NVIDIA)",
            flush=True,
        )


def infer_hidden_size_from_config(model_path: str) -> int | None:
    """Read ``hidden_size`` from a local ``config.json`` when present."""
    config_path = Path(model_path).expanduser() / "config.json"
    if not config_path.is_file():
        return None
    try:
        with config_path.open(encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    text_config = config.get("text_config")
    if isinstance(text_config, dict):
        hidden_size = text_config.get("hidden_size")
        if isinstance(hidden_size, int) and hidden_size > 0:
            return hidden_size
    hidden_size = config.get("hidden_size")
    if isinstance(hidden_size, int) and hidden_size > 0:
        return hidden_size
    return None


def resolve_embedding_dimension(model_path: str, configured_dim: int) -> int:
    """Resolve pooling input width from settings or the model config."""
    if configured_dim > 0:
        return configured_dim
    inferred = infer_hidden_size_from_config(model_path)
    if inferred is not None:
        return inferred
    return 2048


def _fetch_hf_hub_file(hub_id: str, rel_path: str, *, local_dir: str) -> bool:
    try:
        from huggingface_hub import hf_hub_download

        fetched = hf_hub_download(hub_id, rel_path, local_dir=local_dir)
        return Path(fetched).is_file()
    except Exception:
        logger.debug("Could not fetch %s for %s", rel_path, hub_id, exc_info=True)
        return False


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")


def ensure_cross_encoder_module_configs(
    model_path: str,
    *,
    model_id: str = "",
    reranker_prompt: str = "",
) -> None:
    """Ensure sentence-transformers 5.x CrossEncoder wrapper files exist locally.

    Incomplete Hugging Face hub cache snapshots may include ``modules.json`` but
    omit ``config_sentence_transformers.json`` or ``1_LogitScore/config.json``.
    CrossEncoder then assumes a SentenceTransformer conversion path and fails
    with a missing ``model_type`` in ``config.json``.
    """
    root = Path(model_path).expanduser()
    hub_id = (model_id or "").strip()
    prompt = (reranker_prompt or _DEFAULT_RERANKER_PROMPT).strip()

    missing = [
        rel_path
        for rel_path in _CROSS_ENCODER_HUB_REL_PATHS
        if not (root / rel_path).is_file()
    ]
    if not missing:
        return

    if hub_id and "/" in hub_id:
        for rel_path in list(missing):
            if _fetch_hf_hub_file(hub_id, rel_path, local_dir=str(root)):
                missing.remove(rel_path)

    defaults: dict[str, dict[str, Any]] = {
        "config_sentence_transformers.json": {
            "activation_fn": "torch.nn.modules.linear.Identity",
            "default_prompt_name": "query",
            "model_type": "CrossEncoder",
            "prompts": {"query": prompt},
        },
        "modules.json": [
            {
                "idx": 0,
                "name": "0",
                "path": "",
                "type": "sentence_transformers.base.modules.transformer.Transformer",
            },
            {
                "idx": 1,
                "name": "1",
                "path": "1_LogitScore",
                "type": "sentence_transformers.cross_encoder.modules.logit_score.LogitScore",
            },
        ],
        "sentence_bert_config.json": {
            "transformer_task": "any-to-any",
            "modality_config": {
                "text": {"method": "forward", "method_output_name": "logits"},
                "image": {"method": "forward", "method_output_name": "logits"},
                "video": {"method": "forward", "method_output_name": "logits"},
                "message": {
                    "method": "forward",
                    "method_output_name": "logits",
                    "format": "structured",
                },
            },
            "module_output_name": "causal_logits",
            "unpad_inputs": False,
            "processing_kwargs": {
                "chat_template": {
                    "chat_template": "reranker",
                    "add_generation_prompt": True,
                }
            },
        },
        "1_LogitScore/config.json": {
            "true_token_id": 9693,
            "false_token_id": 2152,
        },
    }

    for rel_path in missing:
        payload = defaults.get(rel_path)
        if payload is None:
            continue
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        indent = 4 if isinstance(payload, dict) else 2
        target.write_text(json.dumps(payload, indent=indent) + "\n", encoding="utf-8")
        logger.info("Wrote missing CrossEncoder config at %s", target)


def ensure_pooling_module_config(
    model_path: str,
    *,
    model_id: str = "",
    embedding_dimension: int,
    pooling_mode: str = "lasttoken",
) -> None:
    """Ensure ``1_Pooling/config.json`` exists for sentence-transformers 5.x loads.

    Incomplete Hugging Face hub cache snapshots may include ``modules.json`` but
    omit subfolder configs. ``Pooling.load()`` then receives an empty config and
    fails with a missing ``embedding_dimension`` argument.
    """
    root = Path(model_path).expanduser()
    config_path = root / "1_Pooling" / "config.json"
    if config_path.is_file():
        return

    hub_id = (model_id or "").strip()
    if hub_id and "/" in hub_id:
        try:
            from huggingface_hub import hf_hub_download

            fetched = hf_hub_download(
                hub_id,
                "1_Pooling/config.json",
                local_dir=str(root),
            )
            if Path(fetched).is_file():
                return
        except Exception:
            logger.debug(
                "Could not fetch 1_Pooling/config.json for %s",
                hub_id,
                exc_info=True,
            )

    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "embedding_dimension": int(embedding_dimension),
        "pooling_mode": pooling_mode,
        "include_prompt": True,
    }
    config_path.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")
    logger.info(
        "Wrote missing Pooling config at %s (embedding_dimension=%s)",
        config_path,
        embedding_dimension,
    )


def build_transformers_model_kwargs(load_bits: int) -> dict[str, Any]:
    """Build ``model_kwargs`` for SentenceTransformer / CrossEncoder."""
    import torch

    bits = normalize_load_bits(load_bits)
    if bits == 4:
        try:
            from transformers import BitsAndBytesConfig
        except ImportError as exc:
            raise RuntimeError(
                "EMBEDDING_LOAD_BITS=4 requires bitsandbytes. "
                "Install with: pip install bitsandbytes"
            ) from exc
        return {
            "quantization_config": BitsAndBytesConfig(load_in_4bit=True),
            "device_map": "auto",
        }
    if bits == 8:
        try:
            from transformers import BitsAndBytesConfig
        except ImportError as exc:
            raise RuntimeError(
                "EMBEDDING_LOAD_BITS=8 requires bitsandbytes. "
                "Install with: pip install bitsandbytes"
            ) from exc
        return {
            "quantization_config": BitsAndBytesConfig(load_in_8bit=True),
            "device_map": "auto",
        }
    return {
        "torch_dtype": torch.bfloat16,
        "device_map": "auto",
    }
