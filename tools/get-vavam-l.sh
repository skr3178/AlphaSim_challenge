#!/usr/bin/env bash
set -euo pipefail
cd /home/skr/alpasim-challenge/vavam-weights
B=https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0
for p in aa ab ac ad; do
  f=VAM_width_2048_pretrained_139k_chunked.tar.gz.part_$p
  [ -s "$f" ] || curl -L --fail --retry 5 -sS -o "$f" "$B/$f"
  echo "$(date +%H:%M) got $f $(stat -c%s "$f") bytes"
done
cat VAM_width_2048_pretrained_139k_chunked.tar.gz.part_* | tar -xzv
ls -l VAM_width_2048*.pt && rm -f VAM_width_2048_pretrained_139k_chunked.tar.gz.part_* && echo "VAVAM-L READY: $(ls VAM_width_2048*.pt)"
