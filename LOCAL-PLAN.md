# Competing locally — the fixes and work needed

Written 2026-08-30 after the first official submission. `SETUP-NOTES.md` is the history; this is the
forward plan. Status of the claim "we can compete locally without spending submissions":

| Requirement | State | What's needed |
|---|---|---|
| Local harness faithful to the evaluator | ✅ **proven** — official 1590.4 vs reference 1587.3; dist_to_gt 3.045 vs 3.055 m | nothing |
| Local scene set able to rank policies | ❌ **proven broken** — 100 Strip scenes invert starter vs VaVAM (0.68 vs 0.38 km local; 0.28 vs 1.62 official) | **Fix 1** |
| Repeatable measurements | ❌ model is stochastic; ±3 incidents noise on 100 scenes | **Fix 2** |
| A place on the board | ✅ rank 6, PCS 1590.4, submission `6ba9c546…` | keep 1 submission per real improvement |

---

## Fix 1 — Get a representative local scene set  (the yardstick)

> **Status 2026-08-30 22:10: DONE for 3 cities.** Shards 007 (Boston) + 009 (Pittsburgh) stream-extracted in place;
> `navtest_local.yaml` = **300 scenes** (Vegas/Boston/Pittsburgh 100 each) + `navtest_local_<city>.yaml`. All 300 asset
> dirs verified complete. Singapore (014) pending: needs ~38 GB on `/home` (81 GB free now) — see SHARDS-RUNBOOK.
> Re-baselines on the 300 running: `runs/local300-vavam` (started 22:10), starter next.


> **Ready to execute:** `download-shards.sh` + `SHARDS-RUNBOOK.md` (this folder) — relocates the root to
> `/media/skr/storage` and stream-extracts shards 007/009/014 (Boston/Pittsburgh/Singapore) → 400 scenes, 100 per city, ~156 GB.


The only thing standing between "smoke test" and "experiment you can trust".

- Assets are shard-granular: `MTGS_asset/navtest/assets/part002…part015.tar.gz`, ~30 GiB each, ~100 scenes each.
  Full set = 424 GiB more (455.7 total). Have: `part001` only.
- **The benchmark is 4 cities; our 100 scenes are 1** (analysed from the 1,491 configs on disk, 2026-08-30):
  Las Vegas Strip 32 % · Boston 31 % · Pittsburgh 22 % · Singapore one-north 15 %. Shards are consecutive
  100-scene chunks in sorted id order (verified: `part001` == first 100), so each shard's contents are known
  before download:

  | shard | dates | contents |
  |---|---|---|
  | 001 (have) | 2021-05-25 | Vegas 100 |
  | 002–004 | 05-25 → 06-28 | Vegas 100 each |
  | 005 | 06-28 → 08-30 | Vegas 81, Pittsburgh 12, Boston 7 |
  | 006, 007 | 08-30 → 09-09 | Boston 100 each |
  | 008 | 09-09 → 09-16 | Pittsburgh 55, Boston 45 |
  | 009, 010 | 09-16 | Pittsburgh 100 each |
  | 011 | 09-16 → 09-29 | Pittsburgh 56, Boston 44 |
  | 012 | 09-29 | Boston 100 |
  | 013 | 09-29 → 10-06 | Boston 71, Singapore 29 |
  | 014, 015 | 10-06 | Singapore 100, 91 |

- **Recommended stratified set — 4 shards, ~120 GiB → 500 scenes ≈ benchmark proportions**:
  `part004` (Vegas, different month) + `part007` (Boston) + `part009` (Pittsburgh) + `part014` (Singapore)
  → Vegas 200 / Boston 100 / Pittsburgh 100 / Singapore 100 (40/20/20/20 vs 32/31/22/15). Eval ≈ 1.5 h/driver.
  Download ≈ 3.5 h at the ~10 MB/s seen so far. Fits `/home` only after deleting the 34 GB of extracted
  tarballs (173 GiB free now); otherwise SeagateHub1.
- **Full set** (all 14, 424 GiB, ~12 h download) → SeagateHub1; the gold standard, 1,485 scenes ≈ 4.5 h/driver. Fits `/home` only after
  reclaiming the 34 GB of extracted tarballs in `~/alpasim-challenge/nuplan-track-hf/`. **Preferred**: all
  shards → SeagateHub1 (1.9 TB), `ALPASIM_NUPLAN_ROOT` pointed there.
- Command per shard (data root stays `~/alpasim-challenge/nuplan-track`):
  ```bash
  cd ~/alpasim-challenge
  uv run --no-project --with huggingface-hub hf download --repo-type dataset --local-dir nuplan-track-hf \
    OpenDriveLab/AlpasimChallenge2026_nuplan_track MTGS_asset/navtest/assets/part002.tar.gz
  tar -xzf nuplan-track-hf/MTGS_asset/navtest/assets/part002.tar.gz -C nuplan-track
  ```
- Then regenerate the local scene group from what is on disk (no asset-existence check exists in the wizard —
  a listed scene without assets fails at render time):
  ```bash
  ls ~/alpasim-challenge/nuplan-track/navtest/assets | sort | sed 's/^/    - /' \
    | (echo "# @package _global_"; echo "scenes:"; echo "  scene_ids:"; cat) \
    > ~/alpasim-challenge/alpasim/src/wizard/configs/nuplan_scenes/navtest_local.yaml
  ```
- Runtime cost: ~10–11 s/scene warm → 500 scenes ≈ 1.5 h, 1,485 ≈ 4.5 h per driver, unattended.

> Operating strategy (tiers, rules, submission policy): **`strategy.md`**.

## Fast eval loop — findings and exact configs  (2026-08-31, plan `i-would-say-lets-snug-bear`)

### Result in one line
Local eval went from **~12 s/scene to 4.2 s/scene (~3×)** with **no change to the benchmark** (286–291 of 300 scenes give
identical per-scene outcomes vs the original preset; aggregate deltas are inside the sampler's own noise). Standard from
now on: **`+e2e_challenge_nuplan=dev_fast2`**. Submission images are untouched — all of this is simulator-side config.

### Exact configs used (all local-only, in `~/alpasim-challenge/alpasim/src/wizard/configs/`)

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

### Measurements (stock B = the submitted image's cu128 twin, `alpasim-e2e-vavam-driver:local`)

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

### Caveats (measured, not assumed)
- **CAM_F0-only does not cut GPU raster.** MTGS builds its rig from the scene pkl and rasterises all 8 views regardless
  (`plugins/mtgs/server/artifact_adapter.py:183-215`, `engine/mtgs.py:248,490-500`; request h/w ignored). Saved: 7×
  JPEG encode / gRPC / ASL / eval pickling → run dirs 7× smaller (510 MB → 70 MB per 20 scenes).
- **Two rollouts is the ceiling on this 24 GB card** (each in-flight rollout = one live ~10 GB renderer). Two *stacks*
  OOM (measured 10:55). Drivers heavier than ~6 GB VRAM → use serial `dev_fast`.
- **Noise floor: ±3 at-fault incidents / 300 scenes between identical configs.** Effects < ~5 incidents/300 are not
  resolvable without seeding or repeats. The μP fix (26 → ~9 incidents) is ~6× the floor.
- Warm-up (gsplat JIT ~2 min per fresh renderer, first Drive calls) costs wall time only; sim time is synchronous, scores unaffected.
- Local numbers are **ratios on identical scenes**, never official predictions (stock B: 0.51 km local vs 1.62 official).

### Next levers if more speed is ever needed
Local renderer patch to rasterise only the requested cameras (bind-mounted `plugins/mtgs`, no image rebuild; needs a
CAM_F0-pixel-identity check) — the only remaining large win; concurrency is capped by VRAM.

**Convention (decided 2026-08-31):** the current 300-scene / 3-city series (starter, B, B+μP, L+μP) is closed as-is for
comparability. **From the next round on, every eval uses `navtest_local400` (4 cities × 100).** Per-city groups
(`navtest_local_<city>`) for diagnosis. Regenerating `navtest_local.yaml` is no longer needed — use the 400 group by name.

## Fix 2 — Make runs repeatable  (variance control)

- Seed the flow-matching sampler (`forward_inference` starts from `torch.randn`) — set `torch.manual_seed`
  per session in `vavam_policy.predict`, or sample N trajectories and average/medoid them
  (the PAI #2 tag `baseline-k5-medoid` is exactly that).
- Run each variant on the same scene list with the same seed; for small deltas, 2–3 seeds.
- Compare with the per-scene parquet pivot (long format: `name`/`values`; group by scene, max), not just
  the aggregate — the aggregate truncates rollouts at first incident / 4 m deviation.

## Fix 3 — Validate harness fidelity scene-by-scene  (free, once)

The submission record exposes the evaluator's per-scene metrics (`metrics_s3_uri`, `result_summary_s3_uri`).
Join them to `runs/local100-vavam/rollouts/*/*/metrics.parquet` on scene id for the 100 overlapping
scenes. Agreement (up to stochasticity) is the definitive proof the two harnesses match, and every later
submission becomes another calibration point for the local→official mapping. Needs a fresh CLI token
(`auth-url` → `configure-token`, 12 h expiry).

---

## The policy work, in evidence-ranked order (all local, no submissions)

> How the score rewards these: `navhard-docs/SUMMARY.md` (DriveIRT / `zoib` model — hard zeros are a separate branch,
> hard scenes weigh most, failing easy scenes costs more than passing hard ones gains).


| # | Change | Evidence it matters | Where |
|---|---|---|---|
| **P-1** | **Apply the μP base shapes** the checkpoint was trained with (sample sets them `None`; MuReadout ÷ width_mult = 4 for B / 8 for L) | **VALIDATED on 300 scenes: at-fault distance 0.51→1.11 km, collisions halved, every metric better.** Submission candidate #2 | `vavam_policy.py` patch, env `VAVAM_MUP_SHAPES_DIR` |
| **P-0.5** | **Gain on top of μP** (×1.05–1.10) so progress ≥ 1.05 — **A1 patch done 2026-08-31 15:15** (`VAVAM_OUTPUT_GAIN`, `VAVAM_SEED`, `VAVAM_WARMUP`, all inert by default; verified: seed reproducible to 0.0, gain scales endpoint exactly, warm-up 3 calls in 1.7 s); **A2 DONE 15:51: gain loses** — ×1.05/×1.10 add 3 collisions each, +0.4/+1.1 m drift, ≤ +0.03 progress on the paired seeded screen. **Gain stays 1.00.** Candidate = μP ×1.00; 400-scene confirm running | leaderboard: gain1.075 = #3 (1690); μP+g1.20 = 1560 (< stock); PCS tracks progress, not safety (§6.13). **Required before submitting μP** | `VAVAM_OUTPUT_GAIN` env; A/B on 300 |
| P0 | **Warm-up at container start** — run 2–3 dummy inferences before serving | first 2 of 10 `Drive` calls took 0.5–1 s; steady state 99.2 % < 0.1 s | `vavam_challenge/driver.py` startup |
| P1 | **Route conditioning beyond left/right/straight** — bias/select the trajectory toward the 40–80 m route polyline | wrong-lane 20 %, median lateral drift 4.3 m, 11 at-fault collisions/100; #1 tag `vavam-route` | `driver.py: _command_from_route` + post-processing in `trajectory.py` |
| P2 | **Brake / safety guard** — decelerate on closing obstacle or off-route | 7 % front collisions at 3.2 m min obstacle distance; leaderboard tag `brake` | wrapper, before returning the `Trajectory` |
| P3 | **Output gain calibration** (`action_scaling` ×1.05-ish) | `gain105` tag; local progress_rel 1.08 suggests small tuning both ways | `vavam_policy.py` |
| P4 | **Temporal context** — feed 2–8 frames instead of 1 | backbone trained with 8-frame context; sample uses 1 | `vavam_policy.predict`; **requires pinning VideoActionModel to `738050e`** (rolling-slice hot-fix), not `v1.0.0` |
| P5 | Throughput under 2 concurrent rollouts | official shape; untested | `runtime.endpoints.driver.n_concurrent_rollouts=2` locally |
| T2 | (later) fine-tune the action expert on **sim-rendered frames** | render domain gap; SimScale recipe | capture with `capture/capture_driver.py` |

Build/test loop per change: edit → `docker build -f …/Dockerfile.local -t alpasim-e2e-vavam-driver:local .`
(~1 min) → `run_local_container.sh` (`IMAGE=…:local`) → wizard on `navtest_local` → pivot per-scene metrics →
compare to the previous run with the same seed.

## Next round after candidate #2 — route conditioning + decode  (decided 2026-08-31 16:10; detailed plan: `ROUTE-SELECTION-PLAN.md`, 16:40)

**Corrections from the code exploration (16:40):** (1) the challenge sets `route_start_offset_m: 40.0` — the polyline starts ~40 m ahead,
so "distance to the polyline over the 3 s horizon" needs a bridged reference path (Hermite from the ego pose to the route start); (2) k
samples are one batched `forward_inference` call (no `bsz==1` assumption, trunk KV-cached) — the 450 ms serial figure is an upper bound,
VRAM of the k× visual KV cache is the real limit; (3) no actor/obstacle information reaches the driver — B2 is implementable only as a
slow-down keyed on sample disagreement, route curvature, or inference failure. Details and the staged gates are in the plan file.

**Why gain (A2) is deprioritised — measured, not assumed:** on the paired, seeded 100-scene screen, μP × 1.05 and × 1.10 each
added 3 collisions (0 removed), pushed the car +0.4 / +1.1 m further off the path, and moved progress by ≤ +0.03 (median 0).
SymPhi's gain wins (1588 → 1690) were on the μP-*broken* model (velocity field 4× too large), a different regime. Gain stays 1.00.
Record: SETUP-NOTES §6.16, CURRENT-BEST §3.

**B1 — route conditioning (the big lever).** `_command_from_route` reduces the 40–80 m polyline to one integer via a single
waypoint and a 3 m lateral threshold. Three designs, in order of preference:
1. **Route-aware sample selection (B1 + B4 in one):** draw k flow samples (seeded), pick the trajectory that best follows the route
   polyline (min lateral distance to the polyline over the 3 s horizon, tie-break by progress). Uses the existing sampler, no new
   training; also removes sampler variance. Throughput: k = 5 → ~450 ms per call serial; official demand is ~0.4 calls/s per replica
   vs ~10 calls/s capacity → still ≥ 4× headroom **without batching** (§6.14). Batch later if needed.
2. **Better command:** derive the command from the route's heading/curvature at 20–40 m instead of one lateral threshold; cheap,
   but still 3 values.
3. **Trajectory blending toward the route:** lateral correction of the predicted path toward the polyline with a capped gain — risk
   of fighting the model; only if 1 underperforms.
Screen each on `navtest_local_boston` first (62 % wrong-lane there = strongest signal), then the 100, then the 400.

**B2 — conditional brake:** only on a closing obstacle in the ego lane; measure rear-end side effects (rear collisions are not
at-fault but cost progress). After B1.

**B7 — `terminate_session`: do NOT use as a fallback.** It ends the rollout early; an incomplete scene almost certainly lands in the
scorer's zero branch (and forfeits progress). It exists for RL episode control, not for scoring.

Keep VaVAM-B as the submission line (N6): no architecture sweeps; the board says the points are in conditioning and decode.

## Submission strategy

- Board only knows submitted images; final entry (Oct 31) is chosen from them; organizers re-run it on the
  final dataset. **Minimum to compete = 1 (done).**
- Submit only to bank a locally-proven gain: realistically 2–4 more over the competition.
- **Submission mechanics gotcha**: the CLI's `submit` pre-check (`docker manifest inspect`) is broken on Docker
  CLI 28.1.1. Either upgrade Docker CLI ≥ 28.2 or POST via the CLI's `ChallengeClient` after
  `docker buildx imagetools inspect <uri>` succeeds (see SETUP-NOTES §6.11).
- Always: specific tag (never `latest`), push first (free), then `submit --track nuplan`.
- August's 4 remaining submissions expire Sept 1; downtime Aug 31 → Sep 6; format freeze Sept 15.

## Housekeeping (small, do once)

- [ ] Commit the local repo changes to a branch so a `git pull`/reset can't erase them:
      `casadi<3.8` pin, `Dockerfile.local(+.dockerignore)`, `nuplan_scenes/navtest_local.yaml`.
- [ ] Delete `~/alpasim-challenge/nuplan-track-hf/*.tar.gz` (34 GB, already extracted) before new shards.
- [ ] Rotate the HF token (it was pasted into a chat).
- [ ] Launch long runs with `setsid nohup …` / `docker run -d` — assistant-session restarts kill plain
      background jobs (it stalled one 100-scene run at 64/100).
- [ ] File upstream: `setup_local_env.sh` editable-install bug; unconstrained `casadi`; CLI manifest check.
