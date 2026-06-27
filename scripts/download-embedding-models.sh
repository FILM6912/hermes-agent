#!/usr/bin/env bash
# Download Qwen3-VL embedding/reranker snapshots into ./models for Docker bind mount.
#
# Usage (from repo root):
#   ./scripts/download-embedding-models.sh
#   HERMES_MODELS_DIR=/path/to/models ./scripts/download-embedding-models.sh
#
# Docker compose mounts HERMES_MODELS_DIR (default ./models) to /models in the WebUI container.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${HERMES_MODELS_DIR:-${ROOT}/models}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-Qwen/Qwen3-VL-Embedding-2B}"
RERANKER_MODEL="${RERANKER_MODEL:-Qwen/Qwen3-VL-Reranker-2B}"
DOWNLOAD_RERANKER="${DOWNLOAD_RERANKER:-0}"

mkdir -p "${MODELS_DIR}"

download_one() {
  local repo_id="$1"
  local short_name="${repo_id##*/}"
  local target="${MODELS_DIR}/${short_name}"
  echo "==> Downloading ${repo_id} -> ${target}"
  if command -v hf >/dev/null 2>&1; then
    hf download "${repo_id}" --local-dir "${target}"
    return
  fi
  python3 - <<PY
from huggingface_hub import snapshot_download
snapshot_download(repo_id="${repo_id}", local_dir="${target}")
PY
}

download_one "${EMBEDDING_MODEL}"

if [[ "${DOWNLOAD_RERANKER}" == "1" ]]; then
  download_one "${RERANKER_MODEL}"
fi

echo ""
echo "Done. Host layout:"
ls -la "${MODELS_DIR}" || true
echo ""
echo "In .env (Docker): HF_MODELS_DIR=/models and optionally"
echo "  EMBEDDING_MODEL_PATH=/models/${EMBEDDING_MODEL##*/}"
echo "Recreate the WebUI container after download:"
echo "  docker compose up -d --force-recreate hermes-webui"
