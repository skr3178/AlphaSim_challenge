# Plan — route-aware sample selection (B1+B4) with a conditional slow-down fallback (B2), no early termination (B7)

Written 2026-08-31 after code exploration of the driver, runtime, controller and scorer. Companion to `strategy.md` §8
("Next round after candidate #2") and `strategy.md` §8. Baseline for every comparison: **candidate #2 = VaVAM-B + μP, gain ×1.00**
(`alpasim-e2e-vavam-driver:local-mup`, seed 1234, `dev_fast2`).

**Status 2026-09-01:** `selection.py` (225 lines) + `tests/test_selection.py` (21 tests, passing) exist.
`predict_k`, `slowdown.py`, the failure fallback and the driver wiring do **not**. No GPU stage has run.
§2 below is superseded by **§2b**, which ports the CarPlanner scorer.

## 0. What the exploration changed (read first — three assumptions were wrong)

| Assumed | Measured in code | Consequence for the design |
|---|---|---|
| The route polyline starts at the ego, so "lateral distance of the 6 predicted points to the polyline" is the score | Challenge config sets `route_start_offset_m: 40.0` (`e2e_challenge_nuplan_common/base.yaml:121`, `dev.yaml:46`, `ec2.yaml:37`; `route_generator.py:138-151` drops all waypoints before 40 m). The driver receives ~10 waypoints covering **40–80 m ahead**, NaN-padded to 20 | The 3 s prediction (≈15–35 m) never overlaps the route. The scorer must **bridge** ego → route start; see §2 reference path. `waypoints[0]` is *not* the ego's cross-track error |
| k samples cost k× (≈450 ms for k=5, serial) | `forward_inference` (`vam/action_expert/video_action_model.py:233-302`) reads `bsz` from the visual tokens, has no `bsz==1` assert, draws `torch.randn((bsz,1,6,2))` — k i.i.d. samples in **one call**; the GPT trunk runs once and is KV-cached, only the action-expert steps scale with k | k=5 batched ≈ 1 trunk + 10×5 small steps — expected well under 2× the single-sample 103 ms. Inference runs on 1 of every 5 Drive calls (`inference_interval_us = 500 000` vs 100 ms Drive), so throughput is not the constraint; **VRAM for the k× visual KV cache is** (900×1600 input → ~5.6k visual tokens per row) — measure at k = 1/5/8 |
| A "brake on closing obstacle" is possible | Driver-facing protos carry **no actor/obstacle data** (`egodriver.proto`, `common.proto`): only JPEG images, ego `PoseAtTime` + `DynamicState` (rig-frame velocities/accelerations), route. `send_recording_ground_truth` is False in all challenge configs | B2 cannot key on obstacles. Feasible in-driver triggers: (a) **sample disagreement** across the k candidates, (b) **route curvature ahead**, (c) **inference failure**. Speed is commanded purely by pose spacing in time (`linear_mpc.py:163-198`, velocity weights are 0), and the MPC only penalises 1.0–2.0 s ahead (`idx_start_penalty: 10`), so a slow-down must compress the *whole* 3 s plan |

Also confirmed: route and prediction are in the **same rig frame at the same timestamp** (`policy.py:107-125` sends the route then
drains before `drive()`; `route.timestamp_us == time_now_us == latest_pose.timestamp_us`), x forward / y left in both — no transform
needed for scoring. Scorer facts that set the objective: at-fault = front ∪ lateral collision (`aggregation/processing.py:46-50`),
rear is not at-fault but truncates progress; `left_corridor_laterally` (≥ 4 m from GT path) is a hard zero; scene score
`= min(progress_clipped_rel / 0.8, 1)` — **≥ 80 % of the log car's progress already scores full**, so a modest, conditional slow-down is
cheap while any at-fault collision is a zero.

**B7 invariant:** the driver never ends a rollout early and never sets a "not safe" flag. Grep confirms the current driver has no
`terminate`/`safety_monitor` usage; the plan keeps it that way and adds a test asserting `DriveResponse` is always returned with a
≥ 2-pose trajectory.

## 1. Architecture of the change (driver-side only, no training, no new images until it wins locally)

Hook point: `driver.py:396-401` — the single `policy.predict(image, command)` inside `_inference_lock`. Everything below is
opt-in via env vars with **inert defaults**, so the same code path reproduces candidate #2 exactly when unset
(row 0 of a seeded `randn((k,1,6,2))` equals the seeded `randn((1,1,6,2))` draw — Stage 0 relies on this).

| File | Change |
|---|---|
| `vavam_policy.py` | `predict_k(image, command, k, num_inference_steps=None) -> (k,6,2)`: `tokens.repeat(k,1,1).unsqueeze(1)`, `torch.full((k,1), command)`, pass `num_inference_steps` through as kwarg (signature already supports it, `video_action_model.py:239,251`). New `_format_trajectories` (the existing `_format_trajectory` raises for k>1, `vavam_policy.py:170-176`). `predict()` becomes `predict_k(k=1)[0]` |
| `driver.py` `SessionState` | add `route_xy: np.ndarray \| None` (finite waypoints only, shape (n,2)) and `route_timestamp_us` |
| `driver.py submit_route` | keep computing `command`; also store the masked polyline under `self._lock` |
| `driver.py _maybe_run_inference` | snapshot route with image/pose/command; call `predict_k`; `selection.select(candidates, route_xy, speed_mps, cfg)` → index, per-candidate costs, spread; apply `slowdown.scale(candidate, factor)`; pass winner to `make_cached_plan`. Keep `plan.selected_index`, `costs`, `spread_m` on the `CachedPlan` for logging |
| new `selection.py` (pure numpy, unit-tested offline) | reference path + cost + tie-break (§2) |
| new `slowdown.py` (pure numpy) | speed factor from spread / curvature; compress waypoints (§3) |
| `driver.py drive()` | when `VAVAM_DEBUG_SAMPLES=1`: fill `DriveResponse.debug_info.sampled_trajectories` (k candidates via `build_trajectory_from_plan`) and pickle `{selected_index, route_costs, spread_m, speed_factor, command}` into `unstructured_debug_info` — the eval already parses both (`eval/data.py:433-445, 549-558`, lights up `minADE` and colours the chosen sample in overlays). Off by default (payload) |
| `trajectory.py` | new decelerating fallback (§3c) used instead of the ≥ 2 m/s straight line when a plan exists but inference has failed |
| `Dockerfile.local-mup` | no change if it `COPY`s the package directory (verify); env defaults stay inert |

Env knobs (all read once at policy/driver init): `VAVAM_NUM_SAMPLES` (1), `VAVAM_ROUTE_SELECT` (0/1), `VAVAM_SELECT_TIE_EPS_M`
(0.25), `VAVAM_SELECT_HEADING_W` (2.0 m/rad), `VAVAM_SELECT_REF` (`hermite`|`chord`), `VAVAM_SLOWDOWN` (0/1), `VAVAM_SLOWDOWN_SPREAD_M`
(1.5), `VAVAM_SLOWDOWN_MIN_FACTOR` (0.7), `VAVAM_EULER_STEPS` (10), `VAVAM_DEBUG_SAMPLES` (0). For a submission image the winning
values are baked as `ENV` in the Dockerfile (NVIDIA runs the container with no env of ours).

## 2. Selection rule (`selection.py`)

Inputs: `C` (k,6,2) rig-frame candidates at t = 0.5…3.0 s; `R` (n,2) finite route waypoints (n = 0…20, typically ~10 at 40–80 m);
current speed `v` (m/s) from `DynamicState.linear_velocity.x`.

1. **Guards → return index 0 (baseline behaviour):** `n < 2`; `|R[0].y| > 12 m` or `R[0].x < 5 m` (route implausible / behind);
   k = 1.
2. **Reference path** (bridges the 40 m gap): cubic Hermite from P0 = (0,0) with tangent (1,0)·L to P1 = R[0] with tangent
   `unit(R[1]−R[0])·L`, `L = |R[0]|`; then continue along R. Sample at 1 m. Rationale: honours the current heading and lands on the
   route with its heading — a straight chord to R[0] cuts corners (sagitta ≈ 4 m for a 40 m chord at 50 m radius, i.e. the width of
   the corridor). `chord` variant kept as a flag for the A/B.
3. **Cost per candidate:** `mean_i d_lat(C[i], ref)` over the 6 points (perpendicular distance to the sampled reference, nearest
   segment) `+ w_h · |Δheading|` where Δheading = angle between the candidate's last segment and the reference tangent at the
   projection of its last point. Points that project beyond the reference end cost nothing extra.
4. **Tie-break on progress:** among candidates with `cost ≤ min_cost + tie_eps`, pick the largest arc-length of the projected end
   point along the reference (user's rule: follow the route first, then go further).
5. Outputs: index, costs (k,), `spread_m` = RMS distance of the k end points from their mean (the uncertainty signal for §3).

Why not "closest to the command's side": the route already says where to go; the 3-way command stays as the model's input (unchanged
`_command_from_route`), selection just picks the sample that agrees with the map.

## 3. Conditional slow-down (`slowdown.py`) — the fallback lever, B2 as it is actually implementable

a. **Disagreement-conditioned:** `factor = clip(1 − (spread_m − S0)/S0, min_factor, 1)` with `S0 = VAVAM_SLOWDOWN_SPREAD_M`.
   When the k samples disagree strongly the model is unsure (occluded intersection, lead vehicle braking, ambiguous merge);
   shrink the chosen waypoints radially toward the ego by `factor` — same lever as `VAVAM_OUTPUT_GAIN`, but per-tick and
   only downward. Speed reduction ≤ 30 % by default; progress cost is bounded because the scene score saturates at 80 % progress.
b. **Curvature-conditioned (optional, second A/B):** cap implied speed at `sqrt(a_lat_max · r)` with `r` from the reference path's
   curvature over the next 3 s (`a_lat_max` 3 m/s²); only bites in tight turns.
c. **Failure fallback (replaces the ≥ 2 m/s straight line):** if `predict_k` raises or the plan is exhausted (`trajectory.py:135-142`)
   the driver today keeps serving the stale plan and then a 2 m/s straight line — it *cannot stop*. New behaviour: extend the last
   plan along its final heading with speed decaying linearly to 0 over 3 s, emitted over the full horizon (a degenerate/short plan
   bounces back into the straight-line branch, `trajectory.py:135`). Never `terminate_session` (B7).
d. **Never latch:** every factor is recomputed per inference; a full stop is only reached through repeated failures.

Expected side effect to measure explicitly: **rear collisions** (not at-fault, but they truncate progress) and `dist_to_gt_location`
(timing lag). The screen compares at-fault count, rear count, progress, dist_to_gt together.

## 4. Staged validation (the eval ladder from `strategy.md` §2; each stage gates the next)

| Stage | What | Run | Pass criterion |
|---|---|---|---|
| **S0 diagnose** (behaviour-identical) | `VAVAM_NUM_SAMPLES=5 VAVAM_DEBUG_SAMPLES=1`, selection **off** (index 0) | `navtest_local20`, `dev_fast2`, seed 1234; plus `driver_loadtest.py` at k = 1/5/8 | Driving identical to candidate #2 on the same 20 (same collisions, progress within 0.01); Drive mean at k=5 < 250 ms (2 rollouts × 2 Hz per replica must fit); driver VRAM at k=8 < 16 GiB (official cap); **candidate spread**: median end-point spread > 0.5 m — if the samples barely differ, selection cannot help → stop here and switch to design 2 (route-derived command) |
| **S1 select** | `VAVAM_ROUTE_SELECT=1`, k=5, hermite | `navtest_local_boston` (62 % wrong-lane there — strongest signal), then `navtest_local100` | Boston: wrong-lane and dist_to_gt down, at-fault not up. 100: at-fault ≤ baseline − 2 (noise ±2/100) or equal with progress ↑ and dist_to_gt ↓; fraction of ticks where argmin ≠ 0 reported (sanity: 30–70 %) |
| **S1b variants** (only if S1 is close) | `chord` ref; `w_h` 0 / 4; k = 8; `VAVAM_EULER_STEPS=6` at k=8 (same GPU time as k=5×10) | 100 screen each | pick by the same rule; do not chase < 1 incident differences |
| **S2 slow-down** | best S1 + `VAVAM_SLOWDOWN=1` | 100 screen | at-fault ↓ by ≥ 2 **and** rear collisions not up by more than the at-fault gain, progress ≥ 0.95 × baseline |
| **S3 confirm** | winner | `navtest_local400`, seed 1234 (~31 min) vs `confirm400-mup-g100` | at-fault rate down beyond ±3/300-equivalent (±4/400), progress within 3 %, dist_to_gt not up |
| **S4 ship** | bake env into `Dockerfile.submit-mup` → new tag, push, submit | — | only on explicit go (quota, memory: no rebuild/push without asking) |

Offline tests before any GPU run (`pytest`, seconds): `selection.py` on synthetic routes (straight / left / right / route offset 40 m)
with hand-built candidates — the route-aligned one must win, ties resolve to the longer one, guards return 0, NaN routes handled;
`slowdown.py` factor monotone and bounded; `trajectory.py` failure fallback yields ≥ 2 poses over 3 s with decreasing spacing.
Then a **replay** on captured Drive requests (`capture/capture_driver.py` output) to eyeball selections with `visualize_stages.py`
before touching the simulator.

## 4b. Throughput budget — total wall time, 9.7 % margin (SETUP-NOTES §6.15)

Submission #1 (stock B): `observed_wall_time_s 2265` vs `limit_wall_time_s 2485`, margin 220 s = **9.7 %**, passed. The budget is the
whole run's wall time; the driver's share of it is ~2 % locally (renderer-dominated) and unknown officially (4 replicas/GPU × 2 rollouts).
So driver time can grow roughly 4–5× before it alone eats the margin — k=5 batched (≈1 trunk + 50 small steps, on 1 of 5 Drive calls)
should fit comfortably — but the acceptance test is the **wall-time delta**, not calls/s: S0 reports Drive mean at k = 1/5/8 and the
per-scene wall delta on the 20-scene run; adopt k only if the local per-scene wall delta is < 3 %. Levers if it is over:
`VAVAM_EULER_STEPS=6`, k=3, or sampling k>1 only when the route ahead is curved / the command is not "straight".

## 5. Cost / time estimate

Code ≈ 250 lines across 4 files + ~120 lines of tests: half a day. GPU: S0 ≈ 5 min + load test 5 min; S1 Boston ≈ 8 min, 100 ≈ 10 min;
S1b 3 × 10 min; S2 10 min; S3 31 min. Whole ladder ≈ 2 h of GPU if nothing surprises. Image rebuild only at S4.

## 6. Open risks (stated, not blocking)

- Selection introduces a systematic bias toward the map route; if the model's samples are already route-consistent the gain is small
  (S0 spread check catches this early).
- The Hermite bridge assumes the route start is reachable from the current heading; at a 40 m offset on very tight urban corners the
  reference can be optimistic — the heading term and the `chord` variant exist for this.
- Rear-end exposure from slow-downs is the known B2 cost; it is measured, not assumed, at S2.
- Official evaluator runs 2 rollouts per replica through one `_inference_lock`; k=5 must stay < 250 ms mean or the driver becomes the
  wall-clock bottleneck — S0 measures it on our GPU (H100 is faster, so this is conservative).


---

## 2b. Revised selector — port of CarPlanner's rule-augmented scorer  (2026-09-01)

Supersedes §2. Source: Zhang et al., *CarPlanner* (CVPR 2025) — PDF and our own implementation in
`reference/CarPlanner/`; the selector is `model.py:1381-1530`. Their paper won on nuPlan with a
**generation-selection** framework, and its selection half is structurally what B1+B4 needs.

### What their scorer does

```python
rule_score  = w_comfort·comfort + w_progress·progress + w_collision·collision + w_drivable·drivable
score       = w_rule·rule_score + w_mode·mode_scores          # 1 : 0.3, paper §A
safety_mask = (collision == 0) & (drivable == 0)              # HARD gate
selected    = argmax(score | safety_mask)                     # rank only among safe
if no safe candidate: emergency stop
```

Two structural points that neither our §2 nor the codex proposal had:

1. **Safety terms are used twice** — softly in the score *and* as a hard mask. Ranking happens
   only among candidates with zero violations. This is a stronger version of codex's "reject
   outliers from consensus": reject the *unsafe*, then rank the rest on preference.
2. **Progress must be normalised.** Their comment records the bug: without dividing by the max
   achievable horizon distance, *"progress dominates mode_scores by ~60×"*. Every term of ours
   must be scale-normalised or the weights below are meaningless.

### Term-by-term mapping

| CarPlanner | w | Ours | Available? |
|---|---|---|---|
| `mode_scores` — learned softmax over modes | 0.3 | **consensus** = `softmax(−dist_from_medoid)` | ✅ derived from the k samples; **no training** |
| `collision` — proximity to predicted agents | 1.0 | — | ❌ **no agent data reaches the driver** |
| `drivable` — distance to lane centrelines | 0.3 | **route agreement** — distance to the bridged reference (§2) | ✅ our proxy for the same idea |
| `comfort` — −mean jerk, finite differences | 0.1 | identical formula on our (k,6,2) | ✅ **port verbatim** |
| `progress` — final x ÷ max achievable | 0.5 | identical, normalised the same way | ✅ **port verbatim** |
| `safety_mask` — zero violations | hard | `route_violation == 0` (no point beyond `lane_max_dist` of the reference) | ✅ partial |
| emergency stop | — | **B8 decelerating fallback** | ✅ already planned |

**The substitution that keeps this training-free:** their `mode_scores` come from a learned
Transformer decoder. Ours come from the *agreement of k stochastic draws* — VaVAM's sampler is
already a learned prior, so measuring how tightly the draws cluster extracts its confidence
without training anything. Same role in the sum, no gradients.

**What we lose:** `collision`, their highest-weighted rule (1.0). Nothing in the driver-facing
protos carries actors. Our only substitute is sample disagreement (B2's slow-down trigger), which
is weaker and unproven — codex is right to flag that spread is *not* established as a collision
predictor. Do not claim otherwise until S2 measures it.

### Our scoring function

```
plausible   = finite ∧ within dynamic limits
route_viol  = fraction of the 6 points further than lane_max_dist from the reference
safe        = plausible ∧ (route_viol == 0)

rule_score  = w_comfort·comfort + w_progress·progress + w_drivable·(−route_viol)
score       = w_rule·rule_score + w_mode·consensus − w_disc·discontinuity_from_last
selected    = argmax(score | safe);  if none safe → B8 decelerating fallback
```

Starting weights — **theirs, not invented**: `w_rule 1.0`, `w_mode 0.3`, `w_comfort 0.1`,
`w_progress 0.5`, `w_drivable 0.3`, `lane_max_dist 3.0 m`. `w_disc` has no CarPlanner analogue
(they enforce consistency by construction, holding the mode fixed across the rollout) — start at
0 and set it from the S0 switching rate.

### What this changes about S0

S0 was going to *discover* the weighting. It now **validates a published one**, which is a
cheaper and better-grounded experiment. From one k=5 capture with selection off:

| Measure | Decides |
|---|---|
| median endpoint spread | **kill switch** — under 0.5 m there is nothing to select |
| spread of `dist_from_medoid` | whether the consensus term has any dynamic range |
| does route-argmin coincide with a medoid outlier? | whether the safety mask is load-bearing or inert |
| jerk distribution across candidates | whether `w_comfort 0.1` is too small to matter here |
| tick-to-tick argmin switching rate | `w_disc` |
| p50/p95 latency and VRAM at k=1/3/5/8 | k, and whether adaptive k is needed |

### Implementation order

1. `predict_k` in `vavam_policy.py`, **per-session RNG** (a global call counter breaks
   reproducibility when 2 rollouts share `_inference_lock`)
2. Extend `selection.py`: `comfort`, normalised `progress`, `consensus`, `safe` mask,
   `discontinuity`; keep every guard returning index 0
3. Extend `tests/test_selection.py`: each new term monotone and bounded; safety mask excludes
   violators; all-unsafe returns the fallback signal; weights at defaults reproduce the §2 ranking
   on the existing synthetic cases
4. Driver wiring, inert defaults
5. S0 → the table above → set `w_disc`, confirm or adjust the ported weights
6. S1 on `navtest_local_boston` (62 % wrong-lane), then the 100

Offline first: `reference/CarPlanner/diag_rule_selector.py` ("*diagnose whether the rule-augmented
selector is overriding correct mode choices*") is the diagnostic we want, already written for the
same question; adapt it rather than starting fresh.
