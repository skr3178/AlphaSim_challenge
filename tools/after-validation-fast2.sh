#!/usr/bin/env bash
until grep -q "RUN DONE" /home/skr/alpasim-challenge/logs/local300-vavam-fast.log 2>/dev/null; do sleep 60; done; sleep 15
rm -rf /home/skr/alpasim-challenge/alpasim/runs/t20-fast2
/home/skr/alpasim-challenge/logs/run-eval.sh alpasim-e2e-vavam-driver:local t20-fast2 navtest_local20 dev_fast2 > /home/skr/alpasim-challenge/logs/t20-fast2.log 2>&1
