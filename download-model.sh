#!/usr/bin/env bash
# Download a pinned Gemma 4 MLX model and verify its required artifacts.

set -euo pipefail

VARIANT="${1:-e2b}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="${SCRIPT_DIR}/models"
TMP_DIR=""

case "$VARIANT" in
  e2b)
    REPO="mlx-community/gemma-4-e2b-it-OptiQ-4bit"
    REVISION="ffcf5c056bdd0df50627867ee8c7cba890eabe33"
    DIR_NAME="gemma-4-e2b-it-OptiQ-4bit"
    ;;
  e4b)
    REPO="mlx-community/gemma-4-e4b-it-OptiQ-4bit"
    REVISION="e1404a83551b6eb571dc5fb0de93e52310399bcd"
    DIR_NAME="gemma-4-e4b-it-OptiQ-4bit"
    ;;
  e2b-qat)
    REPO="mlx-community/gemma-4-e2b-it-qat-OptiQ-4bit"
    REVISION="c6c6572580501e5fcb9248bf12040d25cfc71118"
    DIR_NAME="gemma-4-e2b-it-qat-OptiQ-4bit"
    ;;
  *)
    echo "Unknown variant: $VARIANT (expected e2b, e4b, or e2b-qat)" >&2
    exit 2
    ;;
esac

TARGET="${MODELS_DIR}/${DIR_NAME}"

cleanup() {
  if [[ -n "${TMP_DIR:-}" && -d "$TMP_DIR" ]]; then
    rm -rf -- "$TMP_DIR"
  fi
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: required command '$1' was not found." >&2
    exit 1
  fi
}

validate_model() {
  local root="$1"
  local required

  for required in \
    config.json \
    tokenizer.json \
    tokenizer_config.json \
    model.safetensors.index.json \
    optiq/optiq_vision.safetensors
  do
    if [[ ! -s "${root}/${required}" ]]; then
      echo "ERROR: required model file is missing or empty: ${required}" >&2
      return 1
    fi
  done

  python3 - "${root}/model.safetensors.index.json" "$root" <<'PY'
import json
import os
import pathlib
import sys

index_path = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2]).resolve()

try:
    index = json.loads(index_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    raise SystemExit(f"ERROR: invalid safetensors index {index_path}: {error}")

weight_map = index.get("weight_map")
if not isinstance(weight_map, dict) or not weight_map:
    raise SystemExit("ERROR: safetensors index has no non-empty weight_map")

shards = sorted(set(weight_map.values()))
for shard in shards:
    if not isinstance(shard, str) or not shard:
        raise SystemExit("ERROR: safetensors index contains an invalid shard name")
    shard_path = (root / shard).resolve()
    try:
        shard_path.relative_to(root)
    except ValueError:
        raise SystemExit(f"ERROR: shard path escapes model directory: {shard}")
    if not shard_path.is_file() or shard_path.stat().st_size == 0:
        raise SystemExit(f"ERROR: referenced shard is missing or empty: {shard}")

print(f"Verified {len(shards)} safetensors shard(s) referenced by the index.")
PY
}

metadata_matches() {
  local metadata="${1}/SOURCE_REVISION"
  [[ -s "$metadata" ]] || return 1
  grep -Fqx "repository=${REPO}" "$metadata" &&
    grep -Fqx "revision=${REVISION}" "$metadata" &&
    grep -Fqx "variant=${VARIANT}" "$metadata"
}

require_command python3
mkdir -p "$MODELS_DIR"

if [[ -e "$TARGET" ]]; then
  if [[ -d "$TARGET" ]] && validate_model "$TARGET" && metadata_matches "$TARGET"; then
    echo "Pinned model already present: $TARGET"
    exit 0
  fi

  echo "ERROR: target exists but is incomplete, unverified, or from another revision:" >&2
  echo "  $TARGET" >&2
  echo "Move or remove it explicitly, then rerun this script." >&2
  exit 1
fi

DOWNLOADER=""
if command -v hf >/dev/null 2>&1; then
  HF_HELP="$(hf download --help 2>&1 || true)"
  if [[ "$HF_HELP" != *"--revision"* || "$HF_HELP" != *"--local-dir"* ]]; then
    echo "ERROR: installed 'hf' does not support --revision and --local-dir." >&2
    echo "Update it with: hf update" >&2
    exit 1
  fi
  DOWNLOADER="hf"
elif command -v huggingface-cli >/dev/null 2>&1; then
  LEGACY_HELP="$(huggingface-cli download --help 2>&1 || true)"
  if [[ "$LEGACY_HELP" != *"--revision"* || "$LEGACY_HELP" != *"--local-dir"* ]]; then
    echo "ERROR: deprecated 'huggingface-cli' is too old for pinned downloads." >&2
    echo "Install the current CLI: pip install -U \"huggingface_hub[cli]\"" >&2
    exit 1
  fi
  echo "WARNING: using deprecated 'huggingface-cli'; install current 'hf' when possible." >&2
  DOWNLOADER="huggingface-cli"
else
  echo "ERROR: Hugging Face CLI not found." >&2
  echo "Install the current CLI, then review MODEL_LICENSES.md before downloading." >&2
  echo "  pip install -U \"huggingface_hub[cli]\"" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d "${MODELS_DIR}/.${DIR_NAME}.tmp.XXXXXX")"

echo "Review MODEL_LICENSES.md before using downloaded weights."
echo "Downloading ${REPO}@${REVISION} into a temporary directory ..."

if [[ "$DOWNLOADER" == "hf" ]]; then
  hf download "$REPO" --revision "$REVISION" --local-dir "$TMP_DIR"
else
  huggingface-cli download "$REPO" --revision "$REVISION" --local-dir "$TMP_DIR"
fi

validate_model "$TMP_DIR"

if [[ "$DOWNLOADER" == "hf" ]] && hf cache verify --help >/dev/null 2>&1; then
  hf cache verify "$REPO" \
    --revision "$REVISION" \
    --local-dir "$TMP_DIR" \
    --fail-on-missing-files
fi

cat >"${TMP_DIR}/SOURCE_REVISION" <<EOF
format=1
repository=${REPO}
revision=${REVISION}
variant=${VARIANT}
EOF

if ! metadata_matches "$TMP_DIR"; then
  echo "ERROR: failed to write source revision metadata." >&2
  exit 1
fi

if [[ -e "$TARGET" ]]; then
  echo "ERROR: target appeared during download; refusing to overwrite it: $TARGET" >&2
  exit 1
fi

mv "$TMP_DIR" "$TARGET"
TMP_DIR=""

echo "Verified model installed at: $TARGET"
echo "Source revision: ${REPO}@${REVISION}"
