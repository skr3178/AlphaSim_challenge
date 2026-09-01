#!/usr/bin/env bash
L=/home/skr/alpasim-challenge/logs
for pair in "alpasim-e2e-starter-driver:latest local300-starter" "alpasim-e2e-vavam-driver:local-l-mup local300-l-mup"; do
  set -- $pair; img=$1; name=$2
  echo "[$(date +%H:%M)] starting $name"; /home/skr/alpasim-challenge/logs/run-local300.sh "$img" "$name" > "$L/$name.log" 2>&1
  echo "[$(date +%H:%M)] finished $name: $(grep -c 'Session COMPLETED' $L/$name.log) scenes"
done
echo "QUEUE DONE"
