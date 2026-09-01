#!/usr/bin/env bash
until grep -q "RUN DONE" /home/skr/alpasim-challenge/logs/local300-l-mup.log 2>/dev/null; do sleep 60; done; sleep 20
/home/skr/alpasim-challenge/logs/run-group.sh alpasim-e2e-vavam-driver:local sg100-vavam-submitted navtest_local_singapore > /home/skr/alpasim-challenge/logs/sg100-vavam-submitted.log 2>&1
