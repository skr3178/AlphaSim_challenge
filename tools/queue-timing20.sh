#!/usr/bin/env bash
L=/home/skr/alpasim-challenge/logs
for pair in "dev t20-slow" "dev_fast t20-fast"; do set -- $pair
  echo "[$(date +%H:%M)] starting $2 (preset $1)"; NAME=$2 $L/run-eval.sh alpasim-e2e-vavam-driver:local $2 navtest_local20 $1 > $L/$2.log 2>&1; grep -h "TIMING" $L/$2.log
done; echo "QUEUE DONE"
