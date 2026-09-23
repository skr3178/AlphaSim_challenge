# AlpaSim upstream comparison — 2026-09-16

## Fetch and local state

Fetched NVlabs/alpasim `e2e_challenge` from GitHub. Created an isolated,
detached worktree at `alpasim-upstream-20260916/` containing:

- `7611632f17a623a10564f4648c778ebb18079735` — Add Warmup Track (#183), September 15.
- Its parent `0bb4c4bfe10951ea5589aa8ea514e422cf3c3506` — Enable and Fix Offroad Evaluation (#181), September 14.
- Earlier reference `cd713e0d0563352ce45b99d0a53a7173d581bde2` — initial reopening deployment.

The official status page checked this session identifies `0bb4c4b` as deployed.
The newer `7611632` changes only CLI/docs; its `src/` is identical to `0bb4c4b`.
LFS smudging was disabled when checking out: large LFS assets are not downloaded.
This is a source-review checkout, not a configured replacement runtime.

Existing `alpasim-latest/` remains at `54952f4`. The working runtime at
`/home/skr/alpasim-challenge/alpasim` remains at `f012862` with its existing
custom VaVAM/WA-JEPA files, controller dependency modification, and local
scene/preset files. No merge, reset, dependency installation, simulation,
evaluation, rescore, or submission was performed. No tests were executed.
Existing untracked `leaderboard/2026-09-13/` was left untouched.

## Critical evaluator change: a three-part fix

`cd713e0..0bb4c4b`: six files, 220 insertions and 27 deletions, including tests.

| Layer | Upstream change | Why it matters |
| --- | --- | --- |
| Scene configuration | `src/wizard/configs/e2e_challenge_nuplan_common/base.yaml` adds `incl_road_areas: true` | nuPlan lacks road-edge polylines; the fallback needs road-area geometry loaded. |
| Map loading/coordinates | `src/utils/alpasim_utils/trajdata_data_source.py` transforms road-area exterior rings and interior holes into the same local frame as lanes and ego | Enabling polygons without this change can compare geometry in inconsistent frames. |
| Off-road scorer | `src/eval/src/eval/scorers/offroad.py` repairs each polygon before union, closes tiny seams with +1 mm / -1 mm buffering, and increases road-area search radius from 15 m to 25 m | Avoids false positives from numerical seams, invalid polygons, and distant boundary vertices. |

The radius comment specifically describes sparse boundary vertices in private
competition maps. This is evidence of a map-geometry issue, not evidence that
the private scenes come from a different source dataset.

Added regression tests cover seam closure, rejection of actual outer-boundary
incursion, invalid-polygon repair, query radius, absence of a road-area index,
coordinate transformation of exterior/interior rings, and the enabled config.
These tests were reviewed, not run.

Do not cherry-pick only `offroad.py`: config, coordinate conversion, and scorer
must move together. Nor should the road-area flag be enabled on its own.

## What did not change

Against our runtime base `f012862`, upstream has no changes to
`src/eval/src/eval/aggregation/scene_score.py` or the public
`src/wizard/configs/nuplan_scenes/navtest_full.yaml`.
The scene-score formula already treats off-road as a hard failure; the new
changes make its off-road input meaningful for nuPlan. No new public scene
selection is introduced by these commits.

This does not establish that the old WA-JEPA ranking was caused by this bug.
Enabling real off-road detection can penalize policies, while correcting false
positives can improve results relative to a buggy enabled implementation.
Only a consistent rescore can establish the net effect per policy.

## Other changes relative to our older runtime

The full `f012862..7611632` comparison spans 49 files (5,665 insertions,
71 deletions), including earlier reopening changes and reference data:

- Driver session API now supplies ego bounding box and its pose relative to
  the rig. Runtime session configuration and protobuf schema change together.
- Common service channels use 64 MiB gRPC send/receive limits, addressing
  multi-camera message overflow; previously this larger limit was specific
  to the video-model service.
- Controller-tuning documentation, local ranking utilities and PAI reference
  runs, and a `drive-irt` optional dependency were added. These do not make
  local PCS directly comparable to the official private-suite PCS.
- `7611632` adds `pai-warmup` / `nuplan-warmup` CLI choices. Documentation
  specifies 32 scenes, a 45-minute simulation cap, independent limits of
  three per warmup track per rolling 30 days, and no leaderboard scores.
  Warmup completion does not certify full-run throughput.

## Recommended migration sequence (not executed)

1. Use the isolated upstream checkout as the review/migration base; preserve
   the current runnable environment and custom driver changes.
2. Integrate the complete three-part off-road fix, or migrate the runtime to
   the pinned upstream version and carefully reapply our custom changes.
   Check resolved local presets actually load road areas; do not assume a
   config inherited correctly merely because the source default changed.
3. Run only targeted configuration/map/scorer regression tests initially.
   If migrating the runtime/API, regenerate protobufs and check driver
   compatibility before any future simulation.
4. Inspect saved rollout artifacts and map availability to establish whether
   evaluation-only rescoring is possible. Aggregate JSON alone cannot recover
   missing off-road geometry; do not assume a reporting-script change repairs
   old metrics. Write any future rescored results separately from originals.
5. Record simulator/evaluator commit, map settings, and scene-manifest hash in
   local reports. Compare models under one scoring version before drawing
   conclusions; broaden source-log coverage as a separate validation task.
6. Run no full evaluation or scored submission without a separate go-ahead.

## Sources

- https://github.com/NVlabs/alpasim/commit/0bb4c4bfe10951ea5589aa8ea514e422cf3c3506
- https://github.com/NVlabs/alpasim/commit/7611632f17a623a10564f4648c778ebb18079735
- https://nvidia-alpasime2eclosedloopchallenge2026.hf.space/

Reproduce source comparisons from the workspace:

```bash
git -C alpasim-upstream-20260916 diff cd713e0 0bb4c4b
git -C alpasim-upstream-20260916 diff 0bb4c4b 7611632
git -C alpasim-upstream-20260916 diff f012862 7611632
```
