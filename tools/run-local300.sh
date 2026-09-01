#!/usr/bin/env bash
# usage: run-local300.sh <driver-image> <run-name>   (detached; driver container + wizard on navtest_local, 300 scenes)
set -u
IMG="$1"; NAME="$2"; cd /home/skr/alpasim-challenge/alpasim
docker rm -f local-driver >/dev/null 2>&1
docker run -d --name local-driver --init --cap-drop ALL --security-opt no-new-privileges:true --read-only --pids-limit 1024 --memory 32g --cpus 8 \
  --tmpfs /tmp:rw,nosuid,nodev,size=2g --tmpfs /run:rw,nosuid,nodev,size=64m -p 127.0.0.1:6789:6789 \
  -e ALPASIM_DRIVER_HOST=0.0.0.0 -e ALPASIM_DRIVER_PORT=6789 -e ALPASIM_CONTESTANT_REPLICA_INDEX=0 -e ALPASIM_CONTESTANT_REPLICAS=1 \
  -e ALPASIM_DRIVER_GRPC_WORKERS=4 -e OMP_NUM_THREADS=1 -e TORCH_NUM_THREADS=1 --gpus all "$IMG" >/dev/null
for i in $(seq 1 120); do timeout 1 bash -c 'exec 3<>/dev/tcp/127.0.0.1/6789' 2>/dev/null && break; sleep 1; done; sleep 20
echo "[$(date +%H:%M)] driver $IMG up; starting wizard -> runs/$NAME"
ALPASIM_NUPLAN_ROOT=/home/skr/alpasim-challenge/nuplan-track ALPASIM_DRIVER_HOST=localhost ALPASIM_DRIVER_PORT=6789 \
uv run --no-sync alpasim_wizard +e2e_challenge_nuplan=dev nuplan_scenes=navtest_local scenes.limit_to_first_n=0 wizard.log_dir=./runs/$NAME
echo "[$(date +%H:%M)] wizard exit: $?"
docker rm -f local-driver >/dev/null 2>&1; echo "RUN DONE $NAME"
