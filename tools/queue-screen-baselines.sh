#!/usr/bin/env bash
L=/home/skr/alpasim-challenge/logs
for pair in "alpasim-e2e-vavam-driver:local-mup screen-vavam-mup" "alpasim-e2e-vavam-driver:local screen-vavam-stock"; do
  set -- $pair; rm -rf /home/skr/alpasim-challenge/alpasim/runs/$2
  echo "[$(date +%H:%M)] starting $2 ($1) on navtest_local100 dev_fast2"
  $L/run-eval.sh "$1" "$2" navtest_local100 dev_fast2 > "$L/$2.log" 2>&1
  echo "[$(date +%H:%M)] finished $2: $(grep -c 'Session COMPLETED' $L/$2.log)/100 | $(grep '^TIMING' $L/$2.log | sed 's/TIMING [^:]*: //')"
done
echo "QUEUE DONE"
