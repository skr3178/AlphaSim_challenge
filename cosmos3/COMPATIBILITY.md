# Cosmos3-Edge — one-scene AlpaSim compatibility check

Date: 2026-09-18. User authorized one local evaluation smoke test, not a full
suite, training run, official warmup or submission.

## Result: compatibility passed; driving failed on this scene

The successful run was `cosmos3-compat-20260918t130423z`. Independent validation
of the saved ASL and evaluator summary confirmed:

| Check | Observed |
| --- | ---: |
| Completed rollouts | 1 / 1 |
| Successful Cosmos calls / Drive RPC responses | 10 / 10 |
| Controller requests / responses | 10 / 10 |
| Rendered front observations | 11 |
| Inference failures / straight fallbacks | 0 / 0 |
| Returned trajectory | 41 finite poses, 100 ms spacing, 4 s horizon |
| Mean policy call time | 2.477 s |
| Median / range | 2.393 s / 2.354–3.241 s |
| Sampled peak Cosmos process VRAM | 10.123 GiB |
| Simulator launch-to-exit wall time | 199.753 s, including cold renderer compilation |

AlpaSim shortened the requested 12 steps to the clip's 10 steps. Policy calls
ran from 17,000 through 4,517,000 us; simulation ended at 5,017,000 us.
The observed loop was genuinely closed after the initial ground-truth priming
interval. Saved-controller inspection confirms that the first Cosmos prediction
was not executed: the runtime used GT priming until 0.517 s, then used predictions
#2 through #10 for successive half-second intervals. No future GT was supplied
as Cosmos model conditioning.

**The local scene score was 0.0**, with evaluator failure reason
`left_corridor_laterally`. The saved metrics report:

- `progress_clipped_rel`: **0.29563** (~30% of reference progress).
- `dist_to_gt_trajectory`: **4.11459 m**.
- `collision_any`: **0**; `offroad`: **0**, as reported by this older local scorer.
- `dist_traveled_m`: **21.787 m**, versus reference **71.694 m**.

These saved aggregate metrics do not describe the entire post-failure trace.
The first flagged corridor-exit sample is at 3.517 s (4.1146 m lateral distance);
the logged simulation continues to 5.017 s (5.1624 m lateral distance).
See the [saved trajectory review and plots](TRAJECTORY-REVIEW.md), generated
without rerunning inference or evaluation.

This is evidence that the present image-only checkpoint/adapter combination
failed this scene, not proof of the model's general driving capability or an
isolated root cause. The loop did not fail because of missing RPCs, malformed
poses or an out-of-memory exception. Route/speed/history conditioning and the
experimental adapter remain important limitations. No further scene, parameter
sweep, fine-tuning or submission was run after this result.

All three temporary simulator containers and the host driver were stopped;
the GPU returned to 338 MiB / 0% utilization. Saved outputs were retained.

Artifacts:

- [Validated counts, timings and metrics](artifacts/20260918T130423Z_alpasim_compat/validation.json)
- [Driver summary](artifacts/20260918T130423Z_alpasim_compat/driver-summary.json)
- [Run manifest](artifacts/20260918T130423Z_alpasim_compat/run-summary.json)
- [Driver log](artifacts/20260918T130423Z_alpasim_compat/driver.log)
- [Simulator log](artifacts/20260918T130423Z_alpasim_compat/simulator.log)
- Official-format local output:
  `/home/skr/alpasim-challenge/alpasim/runs/cosmos3-compat-20260918t130423z/aggregate/results-summary.json`.
- First input image and `prediction-01.json` through `prediction-10.json` are
  saved alongside the driver summary, including raw and converted trajectories.

## Scope

An isolated host gRPC driver runs the full pinned generative MoT + VAE pipeline.
AlpaSim supplies current rendered `CAM_F0` images and ego pose; Cosmos predicts
40 future camera-pose deltas at 10 Hz, using 30 denoising steps and resolution
tier 256. The model sees the current image and the fixed prompt
`You are an autonomous vehicle planning system.` only. Route messages and ego
speed are not model conditioning. Ego pose/calibration anchor the returned poses.

The runner selects exactly one existing **development** scene:
`2021.05.25.14.24.08_veh-25_04059_04203-5395d42cc65e5c06`.
It was already used for the earlier hardware probe. This is not fresh validation.
Bounds: one rollout, one concurrent simulator session, at most 12 control steps
(0.5 seconds each), 20 policy calls and 900 seconds of simulator wall time.
AlpaSim may shorten the simulation to the available recorded clip.

No straight-line fallback, cached-plan reuse, future-frame conditioning,
ground-truth trajectory conditioning, or model tuning is included. Invalid
predictions or missing/stale observations stop the run. Failed rollouts cannot
produce an aggregate through the configured evaluator.

## Adapter contract

The upstream AV decoder uses:

- Translation divided by **1.35** to undo the AV scale.
- Column-based rot6d, projected to SO(3) using the upstream SVD implementation.
- Framewise composition: `camera_pose[k+1] = camera_pose[k] @ delta[k]`.
- OpenCV camera coordinates and the session's real sensor-to-rig calibration.

Let `E` be the camera pose in rig coordinates and `P[k]` the decoded camera
motion relative to the initial camera. The local rig pose is
`T_local_rig_initial @ E @ P[k] @ inverse(E)`. This includes camera lever-arm
motion during turns. MTGS exposes `sensor2ego` under the misleading protobuf
field name `rig_to_camera`; the actual source and calibration were checked.

The controller-facing trajectory preserves decoded **x, y and yaw**, removes
roll/pitch and holds z at the current rig ground height. This explicit planar
projection is an adaptation, not raw 6-DoF camera-motion control. No x/y/yaw,
speed, acceleration, corridor or progress correction is applied.

Forty actions produce 41 poses including the initial pose, spaced at 100 ms.
The trajectory starts at `time_now_us` and covers `time_query_us` (the next
control boundary). Current camera exposure **end**, not start, matches the
policy timestamp. Raw actions, full unprojected SE(3) poses and returned
protobuf trajectories are retained for every successful inference.

## Runtime and environment

- Existing local runtime: `f012862749366a72f356fce73e22091fe5160e41`, preserving
  its pre-existing local changes. Base image `alpasim-base:0.89.0`.
- Preset: `dev_fast`, one front camera, one worker, renderer cache size 2.
- Model and Diffusers revisions remain those in [FEASIBILITY.md](FEASIBILITY.md).
- Cosmos stays in its isolated overlay environment. Local `alpasim-grpc==0.54.0`
  was installed there with `--no-deps` for the service interface; no existing
  environment packages were upgraded. Its wheel build runs the repository's
  protobuf generator; no tracked runtime source modifications were introduced.
- Driver listens only on localhost:6795 and stops after the test.
- Driver torch allocator cap: 12 GiB to leave room for the renderer on the same
  GPU. It is not a total-process 16 GiB enforcement test.
- The regular eval lock is held. Cleanup targets only this runner's driver PID
  and its uniquely named Compose project. Download processes are left untouched.

## Setup issues retained in the record

- `20260918T125827Z_alpasim_compat`: Hydra enum spelling rejected during config
  generation; no model or simulator launch.
- `20260918T125845Z_alpasim_compat`: startup stopped before any Drive call to
  correct the interpretation of `time_query_us`.
- `20260918T130016Z_alpasim_compat`: first Drive request rejected by an overly
  strict image-start timestamp check. **Zero model predictions**. The observed
  exposure was 0–17,000 us and policy time 17,000 us. Failed result preserved.
- `20260918T130423Z_alpasim_compat`: same scene retried after adding a regression
  test for exposure-end and control-query timestamps. **Completed and validated**;
  this is the only attempt that executed neural policy predictions.

Five CPU unit tests cover forward scaling, rotation-column layout, turning with
camera offset/global transform, malformed actions, protobuf timing/planar output,
and exposure-end timing. They passed before the final attempt.

## Reproduction

The following starts one new rollout; do not run merely to inspect results:

```bash
/home/skr/alpasim-challenge/alpasim/.venv/bin/python cosmos3/run_compatibility.py
```

Validation of completed saved artifacts (writes only `validation.json`, no
inference or evaluation rerun):

```bash
/home/skr/alpasim-challenge/alpasim/.venv/bin/python cosmos3/validate_compatibility.py \
  cosmos3/artifacts/20260918T130423Z_alpasim_compat
```

## Interpretation limits

Passing establishes image → Cosmos inference → valid trajectory RPC → controller
→ next rendered observation → scorer integration on one public scene. It does
not establish good driving, route following, generalization or competition
compliance. The existing scorer has not yet received the planned upstream
migration; this is not organizer-score parity. No PCS/rank projection is valid.

Source references:

- [Pinned NVIDIA AV notebook: 1.35 scale and camera-pose decoder](https://github.com/NVIDIA/cosmos/blob/b0e54e88c322695dab188e6ed160c4d6d071c39d/cookbooks/cosmos3/generator/action/run_id_with_diffusers.ipynb)
- [Pinned NVIDIA pose conversion implementation](https://github.com/NVIDIA/cosmos-framework/blob/cc96ae8a34a6925efa523671a4c6220678b1fbe1/cosmos_framework/data/generator/action/utils/pose_utils.py)
- [Generator action API](https://github.com/NVIDIA/cosmos/blob/b0e54e88c322695dab188e6ed160c4d6d071c39d/cookbooks/cosmos3/generator/action/README.md)
