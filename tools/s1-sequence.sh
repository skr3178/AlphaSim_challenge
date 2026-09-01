#!/usr/bin/env bash
# S1: three paired runs on navtest_local100 / dev_fast2, one image, seed 1234.
#   s1a  k=1              -> new baseline (seeding changed, old runs not comparable)
#   s1b  k=5 select OFF   -> identity control: must match s1a
#   s1c  k=5 select ON    -> the experiment
set -u
L=~/alpasim-challenge/logs
IMG=alpasim-e2e-vavam-driver:local-mup-k
run () {
  local name="$1" denv="$2"
  echo "=== $name : $denv ==="
  DRIVER_ENV="$denv" "$L/run-eval.sh" "$IMG" "$name" navtest_local100 dev_fast2 \
    > "$L/$name.log" 2>&1
  echo "--- $name finished rc=$? ---"
  grep -E 'wizard exit|^TIMING|^DRIVER' "$L/$name.log" | tail -3
}
capture () {   # S0-style diagnostics for the k=5 arms
  local name="$1"
  ( for i in $(seq 1 90); do docker ps --format '{{.Names}}' | grep -qx local-driver && break; sleep 2; done
    docker logs -f local-driver 2>&1 | grep --line-buffered 'S0 k=' > "$L/$name.s0.log" ) &
}
run s1a-k1     "VAVAM_SEED=1234 VAVAM_NUM_SAMPLES=1"
capture s1b-k5-off; run s1b-k5-off "VAVAM_SEED=1234 VAVAM_NUM_SAMPLES=5"
capture s1c-k5-on;  run s1c-k5-on  "VAVAM_SEED=1234 VAVAM_NUM_SAMPLES=5 VAVAM_ROUTE_SELECT=1"
echo "=== S1 SEQUENCE DONE ==="
