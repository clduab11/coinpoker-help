#!/usr/bin/env bash
# download-model.sh — fetch the Gemma 4 vision model in MLX format.
#
# The deployment constraint for this project is MLX (Apple's framework
# layout), NOT GGUF. MLX models are directories of safetensors files, so
# the script uses `huggingface-cli` to download the full repository.
#
# Usage:
#   ./download-model.sh            # Gemma 4 E2B (2B, default)
#   ./download-model.sh e4b        # Gemma 4 E4B (4B, higher accuracy)
#   ./download-model.sh e2b-qat    # QAT-based E2B quant
#
# Model choice note: early MLX quantizations of Gemma 4 produced garbage
# output because PLE (per-layer embedding) layers were quantized
# incorrectly. The OptiQ variants below are PLE-safe.

set -euo pipefail

VARIANT="${1:-e2b}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="${SCRIPT_DIR}/models"

case "$VARIANT" in
  e2b)
    REPO="mlx-community/gemma-4-e2b-it-OptiQ-4bit"
    DIR_NAME="gemma-4-e2b-it-OptiQ-4bit"
    ;;
  e4b)
    REPO="mlx-community/gemma-4-e4b-it-OptiQ-4bit"
    DIR_NAME="gemma-4-e4b-it-OptiQ-4bit"
    ;;
  e2b-qat)
    REPO="mlx-community/gemma-4-e2b-it-qat-OptiQ-4bit"
    DIR_NAME="gemma-4-e2b-it-qat-OptiQ-4bit"
    ;;
  *)
    echo "Unknown variant: $VARIANT (expected e2b, e4b, or e2b-qat)" >&2
    exit 1
    ;;
esac

TARGET="${MODELS_DIR}/${DIR_NAME}"

if [ -d "$TARGET" ] && [ -f "$TARGET/config.json" ]; then
  echo "Model already present: $TARGET"
  exit 0
fi

mkdir -p "$MODELS_DIR"

if command -v huggingface-cli >/dev/null 2>&1; then
  echo "Downloading $REPO (MLX format) into $TARGET ..."
  huggingface-cli download "$REPO" --local-dir "$TARGET"
elif command -v hf >/dev/null 2>&1; then
  echo "Downloading $REPO (MLX format) into $TARGET ..."
  hf download "$REPO" --local-dir "$TARGET"
else
  echo "ERROR: neither 'huggingface-cli' nor 'hf' was found." >&2
  echo "Install one of them first, e.g.:" >&2
  echo "  pip install -U \"huggingface_hub[cli]\"" >&2
  echo "or download the repository manually from" >&2
  echo "  https://huggingface.co/$REPO" >&2
  echo "into: $TARGET" >&2
  exit 1
fi

if [ -f "$TARGET/config.json" ]; then
  echo "Done: $TARGET"
  echo "Point the MLX VLM server at this directory (model name: ${DIR_NAME})."
else
  echo "Download finished but config.json was not found in $TARGET" >&2
  exit 1
fi
