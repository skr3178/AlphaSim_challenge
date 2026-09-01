#!/usr/bin/env bash
until grep -q "RUN DONE" /home/skr/alpasim-challenge/logs/local300-starter.log 2>/dev/null; do sleep 60; done
sleep 20
/home/skr/alpasim-challenge/logs/run-local300.sh alpasim-e2e-vavam-driver:local-l-mup local300-l-mup > /home/skr/alpasim-challenge/logs/local300-l-mup.log 2>&1
