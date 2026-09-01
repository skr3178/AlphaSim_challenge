# Runbook — nuPlan eval shards

## Shard inventory  (updated 2026-08-31 10:40)

| Shard | Contents (inferred, verified for downloaded ones) | Size (tar / extracted) | Status |
|---|---|---|---|
| part001 | Vegas ×100 (2021-05-25) | 31.7 / 38 GB | ✅ on disk (archive moved to Seagate) |
| part002 | Vegas ×100 (05-25 → 06-03) | 31.2 / ~38 | — |
| part003 | Vegas ×100 (06-03 → 06-28) | 31.4 / ~38 | — |
| part004 | Vegas ×100 (06-28) | 32.3 / ~38 | — |
| part005 | Vegas 81, Pittsburgh 12, Boston 7 | 31.3 / ~38 | — |
| part006 | Boston ×100 | 30.7 / ~37 | — |
| **part007** | **Boston ×100** (09-09) | 32.3 / 38 | ✅ **downloaded 08-30** |
| part008 | Pittsburgh 55, Boston 45 | 30.1 / ~36 | — |
| **part009** | **Pittsburgh ×100** (09-16) | 29.7 / 36 | ✅ **downloaded 08-30** |
| part010 | Pittsburgh ×100 | 28.4 / ~34 | — |
| part011 | Pittsburgh 56, Boston 44 | 28.9 / ~35 | — |
| part012 | Boston ×100 (09-29) | 30.9 / ~37 | — |
| part013 | Boston 71, Singapore 29 | 30.2 / ~36 | — |
| **part014** | **Singapore ×100** (10-06) | 30.2 / 38 | ✅ **downloaded 08-31** |
| part015 | Singapore ×91 | 26.9 / ~33 | — |

**Downloaded: 4 of 15 shards → 400 of 1,485 scenes (27 %), all 4 cities × 100, verified complete.**
Remaining: 11 shards, ~1,085 scenes, ~330 GB extracted — adds depth per city, no new cities; fetch to
SeagateHub1 only when 400-scene A/Bs are within noise. Scene groups: `navtest_local400` (all),
`navtest_local` (the original 300), `navtest_local_<city>` (per city).

## What it does
- **Nothing is moved.** Shards are stream-extracted straight from Hugging Face into the existing data root
  `~/alpasim-challenge/nuplan-track` — no tarballs on disk. ~31 GB download / ~38 GB extracted each.
- Default shards: **007 (Boston), 009 (Pittsburgh)** → **300 scenes, 100 per city** (Vegas already present).
  Add Singapore later with `SHARDS="014"`.
- Regenerates `nuplan_scenes/navtest_local.yaml` (+ per-city `navtest_local_<city>.yaml`) in the repo.

Budget: ~76 GB of the 146 GB free on `/` (2026-08-30). Reclaim another 34 GB any time by deleting the already-extracted
tarballs in `~/alpasim-challenge/nuplan-track-hf/`. Singapore (`014`, +38 GB) fits after that.

## Steps
```bash
cd ~/Downloads/alpasim_challenge
bash download-shards.sh plan          # 10 s: prints the budget, changes nothing

# ~1.7 h at ~10 MB/s. Detached so it survives closing the terminal / assistant restarts:
setsid nohup bash download-shards.sh shards > ~/alpasim-challenge/logs/shards.log 2>&1 < /dev/null &
tail -f ~/alpasim-challenge/logs/shards.log   # Ctrl-C only stops the tail, not the download

bash download-shards.sh groups        # after shards finish: writes the scene-group yamls
```

## Verify
```bash
ls ~/alpasim-challenge/nuplan-track/navtest/assets | wc -l     # expect 300
grep -c '^    - ' ~/alpasim-challenge/alpasim/src/wizard/configs/nuplan_scenes/navtest_local.yaml   # expect 300
df -h /
```

## If something fails
- A shard stream dies mid-way → just re-run `bash download-shards.sh shards`; it re-extracts (tar overwrites) and
  skips nothing, so expect the finished shards to be re-downloaded too. To redo only one: `SHARDS="009" bash download-shards.sh shards`.
- "less than 45 GB free" → the script stops before starting a shard; free space or drop a shard.
- Wizard says scene X has no assets → run `groups` again (it only lists scenes with assets on disk).

## Afterwards
Re-baseline both drivers on the 300 before judging any policy change — VaVAM's at-fault distance should move
from 0.38 km (Strip-only) toward the official 1.62 km:
```bash
cd ~/alpasim-challenge/alpasim
# terminal A: driver
IMAGE=alpasim-e2e-vavam-driver:local e2e_challenge/sample_submission_vavam/run_local_container.sh
# terminal B: ~1.2 h
uv run --no-sync alpasim_wizard +e2e_challenge_nuplan=dev nuplan_scenes=navtest_local scenes.limit_to_first_n=0 wizard.log_dir=./runs/local300-vavam
```
Optional cleanup: the 34 GB of already-extracted tarballs in `~/alpasim-challenge/nuplan-track-hf/`.

## Singapore (part014) — in place, after clearing space  (decided 2026-08-30 21:15)
Simplest path: same root on `/home`, no second disk, no symlinks. Needs ~38 GB. `/home` will have ~56 GB free
after Pittsburgh; delete the two already-extracted tarballs first for a comfortable margin:
```bash
rm ~/alpasim-challenge/nuplan-track-hf/MTGS_asset/navtest/assets/part001.tar.gz ~/alpasim-challenge/nuplan-track-hf/trajdata_cache/nuplan_test.tar.gz   # +34 GB
cd ~/Downloads/alpasim_challenge
SHARDS="014" setsid nohup bash download-shards.sh shards > ~/alpasim-challenge/logs/shard014.log 2>&1 < /dev/null &
tail -f ~/alpasim-challenge/logs/shard014.log        # ~55 min
bash download-shards.sh groups                        # -> 400 scenes, 100 per city; plain `dev` preset works
```
(The script refuses to start a shard with < 45 GB free.)

## Fast local eval loop  (added 2026-08-31)
```bash
# screen (100 scenes, 25/city) — every new idea starts here. dev_fast2 = CAM_F0 only + no video + 2 rollouts/stack (validated)
~/alpasim-challenge/logs/run-eval.sh <driver-image> <run-name> navtest_local100 dev_fast2   # ~7 min
# confirm (400 scenes, ~28 min) — only for candidates that pass the screen
~/alpasim-challenge/logs/run-eval.sh <driver-image> <run-name> navtest_local400 dev_fast2
# detached: setsid nohup ~/alpasim-challenge/logs/run-eval.sh IMG NAME GROUP dev_fast > ~/alpasim-challenge/logs/NAME.log 2>&1 < /dev/null &
```
`dev_fast` = `dev` + only `CAM_F0` requested + eval video off. Measured 10.9 → 6.9 s/scene (1.58×), identical
metrics code; the MTGS renderer still rasterises all 8 views internally (rig comes from the scene pkl), so
CAM_F0-only saves encode/transport/eval work, not GPU raster. Run dirs are ~7× smaller.
The launcher prints at the end: `TIMING …` (per-scene wall from runtime timestamps, scene 1 excluded) and
`DRIVER …` (Σ Drive time as % of wall = the quantity the official throughput budget constrains; VRAM peaks).
Groups: `navtest_local20` (timing only) · `navtest_local100` (screen) · `navtest_local400` (confirm) ·
`navtest_local_<city>` (diagnosis) · `navtest_local` (the frozen 300 used by the Aug-30/31 series).
One simulator stack per GPU — two stacks OOM the renderer (24 GB). `dev_fast2` itself peaks at ~23.8 GB total (thin margin):
use `dev_fast` (serial) for drivers heavier than ~6 GB VRAM. Possible step 2 if more speed is needed:
`dev_fast2` with `runtime.nr_workers: 2`, `endpoints.{renderer,driver,controller}.n_concurrent_rollouts: 2`,
`defines.nre_cache_size: 3` — validate separately, watch for `OutOfMemory`.

Throughput check for a new driver (official shape = 8 streams per GPU), with ONLY the driver container running:
`python ~/Downloads/alpasim_challenge/capture/driver_loadtest.py --port 6789 --streams 8 --seconds 60`
Compare its p50/p90 to stock B's under the same test; ratios transfer to the H100, absolutes don't.
