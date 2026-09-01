#!/usr/bin/env bash
L=/home/skr/alpasim-challenge/logs; IMG=alpasim-e2e-vavam-driver:local-mup
for g in 1.00 1.05 1.10; do
  name=screen-mup-g$(echo $g | tr -d '.'); rm -rf /home/skr/alpasim-challenge/alpasim/runs/$name
  echo "[$(date +%H:%M)] starting $name (gain $g, seed 1234) on navtest_local100 dev_fast2"
  DRIVER_ENV="VAVAM_OUTPUT_GAIN=$g VAVAM_SEED=1234" $L/run-eval.sh "$IMG" "$name" navtest_local100 dev_fast2 > "$L/$name.log" 2>&1
  echo "[$(date +%H:%M)] finished $name: $(grep -c 'Session COMPLETED' $L/$name.log)/100 | $(grep '^TIMING' $L/$name.log | sed 's/TIMING [^:]*: //')"
done
echo "QUEUE DONE"
