#!/usr/bin/env bash
# Sequential 300-scene evals, each waiting for the GPU (previous run) and for its image to exist.
L=/home/skr/alpasim-challenge/logs
wait_run(){ while ! grep -q "RUN DONE" "$L/$1.log" 2>/dev/null && pgrep -f "run-local300.sh .* $1\$" >/dev/null; do sleep 60; done; }
wait_img(){ until docker image inspect "$1" >/dev/null 2>&1; do sleep 60; done; }
echo "[$(date +%H:%M)] waiting for local300-vavam"; wait_run local300-vavam
for pair in "alpasim-e2e-vavam-driver:local-mup local300-vavam-mup" "alpasim-e2e-starter-driver:latest local300-starter" "alpasim-e2e-vavam-driver:local-l-mup local300-l-mup"; do
  set -- $pair; img=$1; name=$2
  echo "[$(date +%H:%M)] waiting for image $img"; wait_img "$img"
  echo "[$(date +%H:%M)] starting $name"; /home/skr/alpasim-challenge/logs/run-local300.sh "$img" "$name" > "$L/$name.log" 2>&1
  echo "[$(date +%H:%M)] finished $name: $(grep -c 'Session COMPLETED' $L/$name.log) scenes completed"
done
echo "QUEUE DONE"
