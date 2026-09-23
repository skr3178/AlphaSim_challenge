# Py123D improvement work — 2026-09-19

## Decision and scope

Start with the existing Garage `resnet34_v0.1.0/model_0014.pth` and isolate adapter changes before training. The first implemented candidate preserves the checkpoint's predicted heading. It is **opt-in, tested for conversion correctness, and not yet demonstrated to improve driving**.

This session inspected existing logs/ASLs and ran CPU unit tests plus a configuration-only check. No neural checkpoint inference, renderer, closed-loop evaluation, training, download, submission, image build, or runtime migration was run. The original checkpoint and Docker image remain unchanged.

Do not equate this released `0014` checkpoint with the newer leaderboard `0062` artifacts without release/provenance evidence.

## What the saved 400-scene run actually shows

Source: `/media/skr/storage/alpasim-runs/py123d-0014-400/aggregate/results-summary.json`.

Mean saved scene score: **0.8419950483**. These are old-runtime, repeatedly inspected development results, not an estimate of the private leaderboard score.

| Outcome | Scenes | Contribution to mean-score deficit from 1.0 |
| --- | ---: | ---: |
| Corridor-exit zero scores | 24 | 0.060000 |
| At-fault-collision zero scores | 9 | 0.022500 |
| Positive but sub-maximal progress scores | 75 | 0.075505 |
| Full score | 292 | 0 |

Failure reasons use the scorer's precedence; categories are not independent counts of every event. Hard failures account for roughly 52% of the deficit, progress for 48%. A blanket speed increase could trade progress gains for more collision/corridor zeros.

### Correction: hidden planning failures exist, but did not lower these two scores

Driver log: `/home/skr/alpasim-challenge/logs/driver-py123d-0014-400.log`.

There are **20 `failed to plan` events across two sessions**, not zero. Counting every traceback line mentioning `InsufficientRouteError` overcounts events. All ten route requests in each affected ASL contained 20 waypoints and **zero finite XY waypoints**:

| Scene | Session | Saved score |
| --- | --- | ---: |
| `2021.09.09.14.18.22_veh-48_00322_00895-6d08dce7cfaa5035` | `d4d85632-adb0-11f1-9a2a-b3947635a0fd` | 1.0 |
| `2021.10.06.07.26.10_veh-52_01245_02064-9ebcea6ba47651f0` | `10fc70f6-adb3-11f1-bfd0-2943bff3f35a` | 1.0 |

Evidence files are `rollouts/<scene>/<session>/rollout.asl` beneath the run directory above. Route timestamps run from 17,000 to 4,517,000 microseconds at 500,000-microsecond intervals.

The adapter filters the NaNs, retains its empty placeholder route, and cannot extract its required 45 m target. `_plan` raises before neural forward; with no cached plan, `drive` returns its existing straight-line fallback. RPC/rollout validity is therefore **not** proof that the neural policy ran successfully. The supplied route being invalid is established; the upstream reason for these all-NaN routes has not been established here.

Both scenes already scored 1.0 under the saved scorer, so these failures **do not explain the low mean**. No invented route, GT-based replacement, scene-ID special case, or new fallback behavior was introduced.

## First isolated candidate: retain predicted yaw

Evidence in local source:

- Checkpoint `config.yaml`: `planning_config.predict_yaw: true`.
- `policy/transfuser/predictions.py`: `ego_trajectory_se2` exposes the predicted `(x, y, yaw)` tensor when present.
- Original `evaluation/alpasim/help/driver_service.py`: selects only `ego_trajectory_xy`, then derives yaw from successive XY positions in `_make_plan`.
- The local MPC has a heading-error cost. Heading supplied to it can therefore affect tracking even when XY waypoints are unchanged.

Hypothesis: preserving learned heading may help curved or low-displacement trajectories where position-derived heading differs from the intended vehicle orientation. This is **not** evidence that the learned yaw is superior; it could be inconsistent with the XY path or worsen control. Paired testing is required.

Implemented in the Garage checkout based on commit `288d34c3969c039a921f9fb2d820c2c99a7665b0`:

1. `AlpasimBenchmarkConfig.use_predicted_yaw`, default **False**.
2. When enabled, select `ego_trajectory_se2` and rotate its relative yaw into the rollout-local frame. XY positions, waypoint times, replan interval, and cached-plan interpolation stay unchanged.
3. Preserve legacy XY-derived heading when the option is False.
4. Reject malformed/non-finite predicted trajectories and catch conversion failures in the existing replan failure path. This shared validation change affects malformed outputs even with the option off; it is not a promise of byte-identical behavior for invalid predictions.

Hydra override for a future run using the **patched source**:

```text
use_predicted_yaw=true
```

The existing image `py123d-garage-alpasim:nuplan-0014` (`0c5b9bf22f11`) does not contain this patch. Do not mistake testing a read-only source mount for rebuilding or deploying an image. Keep the original image tag immutable; use a distinct candidate tag if later authorized to build.

### Verification performed

**59 passed, 1 existing expected failure** in 5.10 s. Includes 15 new adapter tests and existing trajectory, online-scene, and target-point tests. The expected failure is the pre-existing single-pose trajectory interpolation test. Warnings concerned protobuf deprecation and the existing non-writable NumPy-to-Torch conversion.

Tests cover opt-in/default behavior, real `TransfuserPredictions` property selection with a stubbed neural forward, legacy geometry, local-frame rotation, stationary positions, yaw wraparound, cached-plan anchoring, 10 Hz timestamps, malformed predictions, and replan exception containment.

Run from the workspace root:

```bash
docker run --rm --network none \
  --mount type=bind,source=/home/skr/Downloads/alpasim_challenge/py123d/py123d_garage,target=/work,readonly \
  --workdir /work --env PYTHONPATH=/work/src --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint /opt/venv/bin/python py123d-garage-alpasim:nuplan-0014 \
  -m pytest -q -p no:cacheprovider \
  tests/unit/evaluation/alpasim/test_driver_trajectory.py \
  tests/unit/datatypes/test_trajectory.py \
  tests/unit/py123d_help/scene_api/test_online_scene_api.py \
  tests/unit/py123d_help/scene_readers/test_target_point_extraction.py
```

Also verified configuration parsing using `--cfg job use_predicted_yaw=true device=cpu`, which exits before starting the driver or loading a model. `git diff --check` passed. No GPU was attached to the test containers; network was disabled.

## Next steps, in order — not run yet

1. **Small saved-observation checkpoint check.** Use approximately 10 already exposed development observations spanning straight, turning, stopped, and low-speed behavior. Run the unchanged checkpoint once per observation and compare its predicted yaw to legacy XY-derived yaw. Check finite outputs, XY equality, heading/path consistency, and cost. This is a diagnostic, not a new driving score or proof of improvement.
2. **Version-align a separate local runtime.** The last audited active runtime was `f012862`; the challenge server advertised `0bb4c4bfe10951ea5589aa8ea514e422cf3c3506`. Reverify the deployed revision before running. Preserve the current dirty runtime and old results. Use the same updated runtime, scorer, sensors, controller, and rollout settings for both arms; do not compare new-runtime candidate results directly to the old 400 baseline.
3. **Bounded paired closed-loop pilot.** Predeclare a small diagnostic set including corridor failures and matched successes across straight/turning/stopped/traffic cases. Compare patched-source `use_predicted_yaw=false` versus `true` with identical weights and seeds. Record per-scene score differences, collision/corridor failures, progress, distance to trajectory, actual model/fallback counts, and latency/VRAM. A failure-enriched set diagnoses behavior; it is not representative leaderboard validation.
4. **Broader untouched validation before promotion.** If the pilot supports yaw preservation without an observed safety regression, test on a predeclared diverse set from previously unused source logs. Keep protected holdout logs untouched until candidate selection. Report uncertainty and per-log/city behavior, not a local-score-to-PCS conversion. Tiny pilots cannot establish safety equivalence.
5. **Only then choose the next intervention.** If losses remain mainly progress-related, audit image/ego/route timestamp alignment and speed conditioning before changing speed. If tracking failures remain, inspect heading/path consistency and control behavior. Do not stack a route tweak, velocity fix, smoothing rule, and speed multiplier in one candidate. Do not transfer the Cosmos velocity workaround to Py123D without Py123D-specific evidence.
6. **Training is a later option.** Any supervised fine-tuning needs eligible, separately split training data with the actual three camera streams and labels. Public rendering assets are not automatically a raw training corpus. Do not train on validation/holdout footage or treat Cosmos's quarantined training split as clean validation for derived models.

Reserve official warmups for packaging/runtime/throughput checks and submissions for candidates supported by local paired evidence. Neither this adapter patch nor CPU tests establish a leaderboard gain.
