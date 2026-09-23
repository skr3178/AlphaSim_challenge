#!/usr/bin/env bash
# Detach the authorized Seagate download from this terminal; never launch an eval.
set -euo pipefail
TASK_DIR=/home/skr/Downloads/alpasim_challenge/evaluation/downloads/2026-09-18-seagate
TASK_SCRIPT=/home/skr/Downloads/alpasim_challenge/tools/download-navtest-expansion.py
TASK_PLAN="$TASK_DIR/plan.json"
mkdir -p "$TASK_DIR"
test -f "$TASK_PLAN"
# Dedicated tmux server survives closing the terminal. A per-dataset flock in
# Python also prevents a second job from starting outside this launcher.
if tmux -L alpasim-downloads has-session -t navtest-expansion 2>/dev/null; then
  echo 'Download session already exists: tmux -L alpasim-downloads attach -t navtest-expansion'
  exit 0
fi
tmux -L alpasim-downloads new-session -d -s navtest-expansion \
  "bash -c 'python3 -u $TASK_SCRIPT run --plan $TASK_PLAN >> $TASK_DIR/download.log 2>&1'"
echo 'Started detached tmux session: navtest-expansion (server: alpasim-downloads)'
echo "Persistent log: $TASK_DIR/download.log"
echo 'Status: /media/skr/SeagateHub1/alpasim-navtest-expansion-20260918/status.json'
