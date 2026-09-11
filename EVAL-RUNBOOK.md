# Eval runbook — how to run a local evaluation

Everything needed to produce a comparable local number: which scenes exist, which preset to use,
how to launch, and what the numbers mean. Method and measurements only — *what* to run next is
`archive/strategy.md` §8, *why* the score behaves as it does is `archive/RANKING.md`, live state is `CURRENT-BEST.md`.

Merged 2026-09-01 from `SHARDS-RUNBOOK.md` and `LOCAL-PLAN.md` (both retired).

---

## 0. Read every local result as a local result

The final official result for `wajepa-s2-400` demonstrated that a public local
mean must **not** be converted to PCS or treated as an official score forecast:
the same policy scored 0.9247 on this 400-scene public sample and 0.7748 on the
private 1,000-rollout board.  Local evaluation is still the right way to make a
paired A/B decision, but only on the same `clipgt_id`s.

After every valid run, use the board-shaped report:

```bash
cd ~/Downloads/alpasim_challenge
python3 tools/eval-report.py <run-name> --baseline <paired-baseline-run>
```

It prints the evaluator's exact mean `rollouts[].score`, zero causes, mean
`dist_to_gt_trajectory` (the board-compatible number), medians/p90s only as
diagnostics, worst-city and worst-recording stress views, and a paired delta.
It does not invent a PCS.  The active `run-eval.sh` invokes it automatically
after a valid run; set `EVAL_BASELINE=<run>` for the paired block and
`EVAL_CALIBRATION=<json>` only to display a factual prior official result.

The public local 400 has 38 source recordings and an exceptionally easy Vegas
slice (the submitted WA-JEPA scored 0.9978 there).  The report's
recording-block interval is more honest than treating its 400 clips as iid, but
neither interval covers unseen recordings or the private final-set shift.  A
candidate must improve the paired mean, the zero count, and the worst
non-Vegas/recording cells; it should not be promoted solely on its raw local
mean.

---

## 1. Scene sets — inventory and download

### Shard inventory  (updated 2026-08-31)

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

### What it does
- **Nothing is moved.** Shards are stream-extracted straight from Hugging Face into the existing data root
  `~/alpasim-challenge/nuplan-track` — no tarballs on disk. ~31 GB download / ~38 GB extracted each.
- Default shards: **007 (Boston), 009 (Pittsburgh)** → **300 scenes, 100 per city** (Vegas already present).
  Add Singapore later with `SHARDS="014"`.
- Regenerates `nuplan_scenes/navtest_local.yaml` (+ per-city `navtest_local_<city>.yaml`) in the repo.

Budget: ~76 GB of the 146 GB free on `/` (2026-08-30). Reclaim another 34 GB any time by deleting the already-extracted
tarballs in `~/alpasim-challenge/nuplan-track-hf/`. Singapore (`014`, +38 GB) fits after that.

### Steps
```bash
cd ~/Downloads/alpasim_challenge
bash download-shards.sh plan          # 10 s: prints the budget, changes nothing

# ~1.7 h at ~10 MB/s. Detached so it survives closing the terminal / assistant restarts:
setsid nohup bash download-shards.sh shards > ~/alpasim-challenge/logs/shards.log 2>&1 < /dev/null &
tail -f ~/alpasim-challenge/logs/shards.log   # Ctrl-C only stops the tail, not the download

bash download-shards.sh groups        # after shards finish: writes the scene-group yamls
```

### Verify
```bash
ls ~/alpasim-challenge/nuplan-track/navtest/assets | wc -l     # expect 300
grep -c '^    - ' ~/alpasim-challenge/alpasim/src/wizard/configs/nuplan_scenes/navtest_local.yaml   # expect 300
df -h /
```

### If something fails
- A shard stream dies mid-way → just re-run `bash download-shards.sh shards`; it re-extracts (tar overwrites) and
  skips nothing, so expect the finished shards to be re-downloaded too. To redo only one: `SHARDS="009" bash download-shards.sh shards`.
- "less than 45 GB free" → the script stops before starting a shard; free space or drop a shard.
- Wizard says scene X has no assets → run `groups` again (it only lists scenes with assets on disk).

### Afterwards
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

### Singapore (part014) — in place, after clearing space  (decided 2026-08-30 21:15)
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

### Fast local eval loop — see §2 below
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


---

## 2. The fast preset — findings and exact configs

#### Result in one line
Local eval went from **~12 s/scene to 4.2 s/scene (~3×)** with **no change to the benchmark** (286–291 of 300 scenes give
identical per-scene outcomes vs the original preset; aggregate deltas are inside the sampler's own noise). Standard from
now on: **`+e2e_challenge_nuplan=dev_fast2`**. Submission images are untouched — all of this is simulator-side config.

#### Exact configs used (all local-only, in `~/alpasim-challenge/alpasim/src/wizard/configs/`)

`e2e_challenge_nuplan/dev_fast.yaml`
```yaml
# @package _global_
defaults: [dev, _self_]
wizard: {run_name: e2e_challenge_nuplan_dev_fast}
scenes: {limit_to_first_n: 0}
runtime:
  simulation_config:
    cameras:                       # list -> replaces the 8-camera list wholesale
      - {logical_id: CAM_F0, frame_interval_us: 500_000, height: 1080, width: 1920}
eval:
  video: {render_video: false}     # also what the official ec2 preset does
```

`e2e_challenge_nuplan/dev_fast2.yaml`  (= dev_fast + two rollouts in ONE simulator stack)
```yaml
# @package _global_
defaults: [dev_fast, _self_]
wizard: {run_name: e2e_challenge_nuplan_dev_fast2}
defines: {nre_cache_size: 3}       # 2 in-use MTGS renderers + 1 (must exceed in-flight count)
runtime:
  nr_workers: 2                    # MUST be restated: e2e_challenge_nuplan_common/base.yaml forces 1 and composes after topology
  endpoints:
    renderer:   {n_concurrent_rollouts: 2}
    driver:     {n_concurrent_rollouts: 2}
    controller: {n_concurrent_rollouts: 2}
```
Everything else is inherited from `dev` → `e2e_challenge_nuplan_common/base.yaml` (200 sim steps clipped to the ~5.5 s
scenes, 0.5 s control tick, `RENDER_AGGREGATED`, physics/trafficsim skipped, MPC controller, `img_is_black` scorer on CAM_F0).

Scene groups (`nuplan_scenes/`, generated deterministically = evenly spaced by sorted scene id within each city):
`navtest_local20` (5/city, 18 logs — timing only) · `navtest_local100` (25/city, 34 logs — **T1 screen**) ·
`navtest_local400` (all 4 cities × 100 — **T2 confirm**) · `navtest_local_<city>` (diagnosis) ·
`navtest_local` (the frozen 300 = Vegas/Boston/Pittsburgh, used by every measurement below; **never regenerate**).

Launcher: `~/alpasim-challenge/logs/run-eval.sh IMG NAME GROUP PRESET` — hardened driver container (same flags as the
starter kit's `run_local_container.sh`) + wizard on default ports; ends with `TIMING …` (per-scene wall from the runtime's
`Session COMPLETED` timestamps, scene 1 excluded) and `DRIVER …` (Σ `Drive` time over all workers as % of wall, driver
VRAM by container PID, GPU total peak). Detach with `setsid nohup`.

### 3. Measurements (stock B = the submitted image's cu128 twin, `alpasim-e2e-vavam-driver:local`)

Timing, per-scene wall, warm-up scene excluded:

| Preset | 20-scene mix | frozen 300 | total wall / 300 | 100-scene screen | 400 confirm |
|---|---|---|---|---|---|
| `dev` | 10.9 s | ~12–13 s | ~65 min | ~20 min | ~80 min |
| `dev_fast` | 6.9 s | 7.4 s (median 7.3) | 40 min | ~12 min | ~50 min |
| **`dev_fast2`** | 3.8 s | **4.2 s** (median 3.7) | **24 min** | **~7 min** | **~28 min** |

Fidelity, same 300 scenes:

| | `dev` | `dev_fast` | `dev_fast2` |
|---|---|---|---|
| at-fault incidents (count) | 26 | 27 | 29 |
| at-fault distance | 0.51 km | 0.46 | 0.42 |
| any-collision / at-fault rate | 8 % / 6 % | 8 % / 7 % | 9 % / 8 % |
| wrong-lane scenes | 134 | 133 | 138 |
| dist_to_gt / lateral | 3.40 / 1.84 m | 3.48 / 1.85 | 3.45 / 1.86 |
| progress vs human | 1.05 | 1.05 | 1.05 |
| img_is_black | 0 | 0 | 0 |
| OOM / render failures | — | 0 | 0 |

Per-scene agreement: slow↔fast **291/300** identical collision outcomes (293/300 wrong-lane flags, median |Δ dist_to_gt|
0.35 m); slow↔fast2 **286/300** (288/300, 0.28 m); fast↔fast2 287/300. All three pairs sit at the same ~95–97 %, i.e. the
sampler's noise floor — no directional bias from cameras, video, or concurrency.

Resources (from `DRIVER` lines): driver B ≈ 2.7 GB; `dev_fast` GPU total peak ≈ 21 GB; **`dev_fast2` GPU total peak 23.8 GB
of 24.5** (0 OOM). `Drive` mean ~91 ms serial, ~102 ms with 2 rollouts (the sample serialises inference).

#### Caveats (measured, not assumed)
- **CAM_F0-only does not cut GPU raster.** MTGS builds its rig from the scene pkl and rasterises all 8 views regardless
  (`plugins/mtgs/server/artifact_adapter.py:183-215`, `engine/mtgs.py:248,490-500`; request h/w ignored). Saved: 7×
  JPEG encode / gRPC / ASL / eval pickling → run dirs 7× smaller (510 MB → 70 MB per 20 scenes).
- **Two rollouts is the ceiling on this 24 GB card** (each in-flight rollout = one live ~10 GB renderer). Two *stacks*
  OOM (measured 10:55). Drivers heavier than ~6 GB VRAM → use serial `dev_fast`.
- **Noise floor: ±3 at-fault incidents / 300 scenes between identical configs.** Effects < ~5 incidents/300 are not
  resolvable without seeding or repeats. The μP fix (26 → ~9 incidents) is ~6× the floor.
- Warm-up (gsplat JIT ~2 min per fresh renderer, first Drive calls) costs wall time only; sim time is synchronous, scores unaffected.
- Local numbers are **ratios on identical scenes**, never official predictions (stock B: 0.51 km local vs 1.62 official).

#### Next levers if more speed is ever needed
Local renderer patch to rasterise only the requested cameras (bind-mounted `plugins/mtgs`, no image rebuild; needs a
CAM_F0-pixel-identity check) — the only remaining large win; concurrency is capped by VRAM.

**Convention (decided 2026-08-31):** the current 300-scene / 3-city series (starter, B, B+μP, L+μP) is closed as-is for
comparability. **From the next round on, every eval uses `navtest_local400` (4 cities × 100).** Per-city groups
(`navtest_local_<city>`) for diagnosis. Regenerating `navtest_local.yaml` is no longer needed — use the 400 group by name.

---

## 4. Operating practices (learned the hard way)

- **Detach every long run.** `setsid nohup … &` or `docker run -d`. A plain background job dies when
  the launching session restarts — this stalled one 100-scene run at 64/100.
- **Never two simulator stacks on this GPU.** Each in-flight rollout holds a live ~10 GB renderer;
  two stacks OOM (measured). One stack, more rollouts.
- **Regenerate scene groups from what is on disk.** The wizard has no asset-existence check — a listed
  scene without assets fails at render time:
  ```bash
  ls ~/alpasim-challenge/nuplan-track/navtest/assets | sort | sed 's/^/    - /' \
    | (echo "# @package _global_"; echo "scenes:"; echo "  scene_ids:"; cat) \
    > ~/alpasim-challenge/alpasim/src/wizard/configs/nuplan_scenes/navtest_local.yaml
  ```
- **The frozen 300 series is closed** (starter, B, B+μP, L+μP) for comparability. All new work uses
  `navtest_local400`; per-city groups for diagnosis.
- **Equal allocation ≠ the benchmark.** The 400 are 25 % per city; navtest is Vegas 32 / Boston 31 /
  Pittsburgh 22 / Singapore 15. Reweight for a go/no-go number:
  `0.32·Vegas + 0.31·Boston + 0.22·Pittsburgh + 0.15·Singapore`.

## Is the GPU free? (check before every launch — two sim stacks OOM the 24 GB card)

```bash
docker ps --format '{{.Names}}'                                   # must print nothing
nvidia-smi --query-gpu=memory.used --format=csv,noheader          # ~480 MiB when idle
ps -eo pid,cmd --no-headers | grep -E 'alpasim_wizard|run-eval\.sh' | grep -vE 'bash -c|/bin/sh|grep' | wc -l   # must be 0
```
Do **not** use `pgrep -f alpasim_wizard` / `pgrep -af` for this: it matches the shell that contains the pattern, so the guard
always self-triggers (burned two sessions on 2026-09-01). When several Claude sessions are open, also announce the launch to the
others (cross-session message) — the agreement since 2026-09-01 is that every session declares before touching the GPU.
