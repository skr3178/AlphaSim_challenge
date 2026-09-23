#!/usr/bin/env bash
set -euo pipefail
cd /home/skr/Downloads/alpasim_challenge
exec >> cosmos3/feasibility.log 2>&1
printf 'Feasibility workflow started: %s\n' "$(date -u +%FT%TZ)"
for ((attempt = 0; attempt < 240; attempt++)); do
    if [[ -f /media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918/checkpoint/transformer/diffusion_pytorch_model-00001-of-00002.safetensors ]]; then
        break
    fi
    sleep 5
done
if [[ ! -f /media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918/checkpoint/transformer/diffusion_pytorch_model-00001-of-00002.safetensors ]]; then
    printf 'Checkpoint did not finish within the bounded wait; no GPU work started.\n'
    exit 1
fi
timeout 600 python3 -u cosmos3/verify_checkpoint.py
# Do not evict other GPU jobs. Refuse the probe if another process has filled VRAM.
cosmos_free_mib=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -n 1)
if ((cosmos_free_mib < 22000)); then
    printf 'Insufficient free GPU memory (%s MiB); no model loaded.\n' "$cosmos_free_mib"
    exit 1
fi
timeout 900 /media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python -u cosmos3/profile_edge.py --profile driving --steps 30 --resolution 256
printf 'Feasibility workflow finished: %s\n' "$(date -u +%FT%TZ)"
