#!/usr/bin/env bash
# usage: run-eval.sh <driver-image> <run-name> <scene-group> [preset]
#   preset: dev (default) | dev_fast | dev_fast2
#   DRIVER_ENV="VAVAM_OUTPUT_GAIN=1.05 VAVAM_SEED=1234"  -> extra env vars passed into the driver container
# One simulator stack on default ports + one hardened driver container; prints per-scene timing at the end.
# Run detached:  setsid nohup run-eval.sh IMG NAME GROUP PRESET > ~/alpasim-challenge/logs/NAME.log 2>&1 < /dev/null &
set -u
IMG="$1"; NAME="$2"; GROUP="$3"; PRESET="${4:-dev}"
LOGDIR=/home/skr/alpasim-challenge/logs; cd /home/skr/alpasim-challenge/alpasim
docker rm -f local-driver >/dev/null 2>&1
docker run -d --name local-driver --init --cap-drop ALL --security-opt no-new-privileges:true --read-only --pids-limit 1024 --memory 32g --cpus 8 \
  --tmpfs /tmp:rw,nosuid,nodev,size=2g --tmpfs /run:rw,nosuid,nodev,size=64m -p 127.0.0.1:6789:6789 \
  -e ALPASIM_DRIVER_HOST=0.0.0.0 -e ALPASIM_DRIVER_PORT=6789 -e ALPASIM_CONTESTANT_REPLICA_INDEX=0 -e ALPASIM_CONTESTANT_REPLICAS=1 \
  -e ALPASIM_DRIVER_GRPC_WORKERS=4 -e OMP_NUM_THREADS=1 -e TORCH_NUM_THREADS=1 $(for kv in ${DRIVER_ENV:-}; do printf -- "-e %s " "$kv"; done) --gpus all "$IMG" >/dev/null
echo "[$(date +%H:%M:%S)] driver env extras: ${DRIVER_ENV:-none}"
for i in $(seq 1 120); do timeout 1 bash -c 'exec 3<>/dev/tcp/127.0.0.1/6789' 2>/dev/null && break; sleep 1; done; sleep 20
T0=$(date +%s); echo "[$(date +%H:%M:%S)] driver $IMG up; wizard preset=$PRESET group=$GROUP -> runs/$NAME"
VR=$LOGDIR/vram-$NAME.csv; : > "$VR"; : > "$VR.gpu"
( while docker ps --format '{{.Names}}' | grep -q '^local-driver$'; do
    DP=$(docker top local-driver -eo pid 2>/dev/null | tail -n +2 | tr '\n' '|' | sed 's/|$//')   # host PIDs of the driver container only
    [ -n "$DP" ] && nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null | grep -E "^($DP)," >> "$VR"
    nvidia-smi --query-gpu=memory.used --format=csv,noheader >> "$VR.gpu" 2>/dev/null; sleep 5; done ) & SAMP=$!
ALPASIM_NUPLAN_ROOT=/home/skr/alpasim-challenge/nuplan-track ALPASIM_DRIVER_HOST=localhost ALPASIM_DRIVER_PORT=6789 \
uv run --no-sync alpasim_wizard +e2e_challenge_nuplan=$PRESET nuplan_scenes=$GROUP scenes.limit_to_first_n=0 wizard.log_dir=./runs/$NAME
RC=$?; T1=$(date +%s); docker rm -f local-driver >/dev/null 2>&1
echo "[$(date +%H:%M:%S)] wizard exit: $RC | total wall $((T1-T0)) s"
kill $SAMP 2>/dev/null
# per-scene timing from the runtime's own "Session COMPLETED" timestamps (scene 1 excluded: gsplat JIT warm-up),
# driver share of wall time (the quantity the official throughput budget constrains), and VRAM peaks.
LOG="$LOGDIR/$NAME.log"; RUNDIR=/home/skr/alpasim-challenge/alpasim/runs/$NAME
python3 - "$LOG" "$RUNDIR" "$((T1-T0))" "$VR" <<'PYEOF'
import re, sys, statistics as st, glob
log, rundir, tot, vr = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
ts=[]
for line in open(log, errors='ignore'):
    m=re.search(r'runtime-0-1\s*\|\s*(\d\d):(\d\d):(\d\d)\.(\d+).*Session COMPLETED', line)
    if m: h,mi,s,f=m.groups(); ts.append(int(h)*3600+int(mi)*60+int(s)+int(f[:3])/1000)
d=[b-a for a,b in zip(ts,ts[1:])]
drive=None; calls=0.0
for f in glob.glob(f"{rundir}/telemetry/metrics_worker_*.prom"):   # sum over all runtime workers (nr_workers may be > 1)
    for line in open(f):
        if line.startswith('rpc_duration_seconds_sum{method="drive"'): drive=(drive or 0.0)+float(line.split()[-1])
        if line.startswith('rpc_duration_seconds_count{method="drive"'): calls+=float(line.split()[-1])
peak=0; gpeak=0
try:
    for line in open(vr):
        p=line.strip().split(','); 
        if len(p)==2: peak=max(peak, int(p[1].split()[0]))
    for line in open(vr+'.gpu'): gpeak=max(gpeak, int(line.split()[0]))
except Exception: pass
if d: print(f"TIMING {rundir.split('/')[-1]}: {len(ts)} scenes | per-scene wall (excl. #1) mean {st.mean(d):.1f} s median {st.median(d):.1f} [{min(d):.1f}-{max(d):.1f}] | total wall {tot} s")
if drive is not None: print(f"DRIVER {rundir.split('/')[-1]}: Drive sum {drive:.1f} s over {int(calls)} calls (mean {1000*drive/calls:.0f} ms) = {100*drive/tot:.1f}% of wall | peak driver-proc VRAM {peak} MiB | peak GPU total {gpeak} MiB")
PYEOF
echo "RUN DONE $NAME"
