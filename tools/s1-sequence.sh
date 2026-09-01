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
  # GATE: the wizard exits 0 even when the renderer dies and 98/100 rollouts fail, writing a
  # junk aggregate and printing RUN DONE. s1b-k5-off did exactly that on 2026-09-01. Never let
  # the sequence move on unless the expected number of scenes actually completed.
  local got; got=$(grep -c 'Session COMPLETED' "$L/$name.log")
  if [ "$got" -lt "${EXPECT:-100}" ]; then
    echo "!!! ABORT: $name completed $got/${EXPECT:-100} scenes — aggregate is invalid"
    grep -m2 -E 'CUDA error|failed rollout row|AcceleratorError' "$L/$name.log" | sed 's/^/    /'
    mv "$HOME/alpasim-challenge/alpasim/runs/$name" \
       "$HOME/alpasim-challenge/alpasim/runs/$name-FAILED-$(date +%H%M%S)" 2>/dev/null
    return 1
  fi
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
