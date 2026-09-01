#!/usr/bin/env bash
# S1b: w_disc sweep on the CORRECTED discontinuity term (selector v4).
# Arm 0 is a v4 rerun of the w_disc=0 config at seed 1234. It must reproduce s1c-k5-on (v3);
# if it does not, v4 changed behaviour at w_disc=0 and the whole sweep is confounded.
set -uo pipefail
L=~/alpasim-challenge/logs
R=~/alpasim-challenge/alpasim/runs
IMG=alpasim-e2e-vavam-driver:local-mup-k
GROUP=navtest_local100
PRESET=dev_fast2
EXPECT=100

run_arm() {
  local name=$1 wdisc=$2 seed=$3
  echo "=== $name  w_disc=$wdisc seed=$seed  $(date +%H:%M:%S) ==="
  ( for i in $(seq 1 90); do docker ps --format '{{.Names}}' | grep -qx local-driver && break; sleep 2; done
    docker logs -f local-driver 2>&1 | grep --line-buffered 'S0 k=' > "$L/$name.s0.log" ) &
  DRIVER_ENV="VAVAM_SEED=$seed VAVAM_NUM_SAMPLES=5 VAVAM_ROUTE_SELECT=1 VAVAM_SELECT_W_DISC=$wdisc" \
    "$L/run-eval.sh" "$IMG" "$name" "$GROUP" "$PRESET" > "$L/$name.log" 2>&1
  local got; got=$(grep -c 'Session COMPLETED' "$L/$name.log")
  grep -E '^TIMING|^DRIVER' "$L/$name.log"
  if [ "$got" -lt "$EXPECT" ]; then
    echo "!!! ABORT: $name completed $got/$EXPECT — aggregate invalid"
    grep -m2 -E 'CUDA error|failed rollout row|AcceleratorError' "$L/$name.log"
    mv "$R/$name" "$R/$name-FAILED-$(date +%H%M%S)" 2>/dev/null
    return 1
  fi
  # base_x sanity. A plan's point 0 is one step AHEAD of the ego (make_cached_plan times
  # offsets at arange(1,n+1)*step_s), so after the shift the reference starts ~one step of
  # travel ahead: base_x positive, order 0-15 m at urban speeds. Flag values outside that -
  # strongly negative or huge means the pose transform is wrong. Do NOT re-arm this as
  # "must be negative": that expectation is what aborted the first attempt on correct code.
  local bad; bad=$(awk -F'base_x=' 'NF>1{v=$2+0; if(v<-2 || v>40) n++} END{print n+0}' "$L/$name.s0.log")
  local tot; tot=$(grep -c 'base_x=' "$L/$name.s0.log")
  echo "  base_x check: $bad of $tot lines out of range [-2, 40] (must be ~0)"
  if [ "$tot" -gt 0 ] && [ "$bad" -gt $((tot / 10)) ]; then
    echo "!!! ABORT: base_x out of range — rebase transform looks wrong"
    return 1
  fi
  return 0
}

run_arm disc-d00-s1234 0.0 1234 || exit 1
# FIRST PASS ONLY: control + w_disc=0.3 at seed 1234, paired on identical scenes. The
# remaining arms (1.0, and all three at seed 5678) are deliberately NOT run - we read these
# two first and decide whether the rest is worth 50 more minutes.
run_arm disc-d03-s1234 0.3 1234 || exit 1
echo "=== FIRST PASS DONE $(date +%H:%M:%S) - control + 0.3 ready to read ==="
