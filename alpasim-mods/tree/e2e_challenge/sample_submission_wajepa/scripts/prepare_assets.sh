#!/usr/bin/env bash
# usage: prepare_assets.sh [weights_dir]   (default ~/alpasim-challenge/wajepa-weights)
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-$HOME/alpasim-challenge/wajepa-weights}"
mkdir -p "$HERE/assets/wajepa"
cp -v "$SRC/model_state_dict.pt" "$HERE/assets/wajepa/model_state_dict.pt"
cp -v "$HERE/wajepa_src/configs/wa_jepa_infer.yaml" "$HERE/assets/wajepa/wa_jepa_infer.yaml"
sha256sum "$HERE/assets/wajepa/model_state_dict.pt"
