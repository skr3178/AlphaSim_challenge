#!/usr/bin/env bash
cd /home/skr/alpasim-challenge/alpasim
for i in $(seq 1 60); do timeout 1 bash -c 'exec 3<>/dev/tcp/127.0.0.1/6789' 2>/dev/null && break; sleep 1; done; sleep 3
export ALPASIM_NUPLAN_ROOT=/home/skr/alpasim-challenge/nuplan-track ALPASIM_DRIVER_HOST=localhost ALPASIM_DRIVER_PORT=6789
uv run --no-sync alpasim_wizard +e2e_challenge_nuplan=dev nuplan_scenes=navtest_local scenes.limit_to_first_n=0 wizard.log_dir=./runs/local100-starter2
echo "wizard exit: $?"
