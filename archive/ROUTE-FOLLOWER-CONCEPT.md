# Route-follower hybrid — concept, references, exact algorithm  (2026-09-01)

Pivot from "select among VaVAM samples" (S1/S1b: neutral safety, +2.7 % progress) to "the route geometry sets the lateral path;
the camera model only chooses speed". Rationale and board evidence: SETUP-NOTES §6.22. No training anywhere in this design.

```
route (accumulated, lane-centre) ──► reference path (0 → 80 m through the ego)   ◄── fixes the lateral path
                                        │
                                        ├── speed options: curvature cap · keep-speed · IDM-style brake ramps
                                        │
camera model (VaVAM-B, frozen) ────► longitudinal choice only (its predicted speed profile / lead-vehicle cue)
                                        │
                                        ▼
                               trajectory (path + timing) → simulator MPC
```

## 1. Reference implementations (all public, all inference-only)

| what | where | what to take |
|---|---|---|
| **PDM-Closed** — centre-line follower + IDM proposals, #1 on nuPlan closed-loop 2023 (Dauner et al., CoRL'23 "Parting with Misconceptions") | `autonomousvision/tuplan_garage` → `tuplan_garage/planning/simulation/planner/pdm_planner/pdm_closed_planner.py`, `abstract_pdm_closed_planner.py` | the architecture: one centre-line path, N proposals = lateral offsets × target speeds, roll out, rule-score, pick |
| path object: arc-length param, `project`, `interpolate`, `substring` | same repo, `utils/pdm_path.py` (`class PDMPath`) | reimplement in ~40 lines numpy (we cannot depend on nuplan-devkit) |
| IDM speed policy (batched): `fallback_target_velocity`, `speed_limit_fraction`, `min_gap_to_lead_agent`, `headway_time`, `accel_max`, `decel_max` | `proposal/batch_idm_policy.py` (`class BatchIDMPolicy`) | the speed update law and its default parameter set |
| proposal generation over (lateral offset, target speed) | `proposal/pdm_generator.py` (`PDMGenerator.generate_proposals`) | the loop structure; our version has 1 lateral offset (0) × 3–5 speeds |
| emergency brake (bounded decel ramp to 0) | `utils/pdm_emergency_brake.py` (`PDMEmergencyBrake`, `max_long_accel 2.40`, `min_long_accel −4.05`) | the decelerating fallback (replaces our ≥ 2 m/s straight line, B8) |
| NAVSIM port of the same planner (sensor-only benchmark, nearer our setting) | `autonomousvision/navsim` → `navsim/planning/simulation/planner/pdm_planner/*` | same files; confirms the design survives without privileged agents |
| pure pursuit / Stanley trackers (if we ever emit steering instead of a path — we don't; the sim's MPC tracks the path) | `AtsushiSakai/PythonRobotics` → `PathTracking/pure_pursuit/pure_pursuit.py`, `PathTracking/stanley_control/stanley_control.py` | the look-ahead geometry, useful for the "join current pose to the path" step |
| CarPlanner rule scorer (already ported) | `reference/CarPlanner/model.py:1381-1530`, our `selection.py` | reuse comfort/progress terms to rank *speed* options |

Rulings that make the design legal: organizers, forum 380855 (2026-08-24): "you can use all the information provided over the interface";
`send_recording_ground_truth` is off, so the *route* is the only path information — and it is the recorded trajectory projected onto lane
centres (`route_generator.py:355-377`), 40–80 m ahead, NaN-padded to 20 points, re-sent every 100 ms tick in the rig frame at that tick.

## 2. Exact algorithm (per session)

**State:** `path_local` — list of (x, y) in the *local* (world-fixed) frame, arc-length parameterised; `poses` (already kept);
`speed_mps` from `DynamicState.linear_velocity.x` (already kept); last emitted plan.

**A. Accumulate (every `submit_route`, 10 Hz, ~µs):**
1. Mask NaN waypoints; if < 2 remain, skip.
2. Transform rig → local with the pose at the route timestamp (same transform `trajectory.py::rig_offsets_to_local_positions` uses:
   `p_local = R(yaw) · p_rig + t`, yaw from `yaw_from_quat`). The pose arrives via `submit_egomotion_observation` *before* the route
   in the same tick (`policy.py:80-113`), so `latest_pose.timestamp_us == route.timestamp_us`.
3. Merge: project each new point onto the existing polyline; append points whose projection lies beyond the current end
   (arc-length monotone); for overlapping points average the lateral position (exponential weight, newest 0.3) to smooth
   the ±0.2 m jitter between ticks. Keep the last 150 m; drop points > 30 m behind the ego.
4. Resample to 1 m spacing; recompute cumulative arc-length `s`.
   *Cold start:* until the accumulated path reaches the ego (first ~40 m ≈ 3–4 s), bridge ego → first point with the existing
   cubic Hermite (`selection.py::reference_path`) — this is exactly the S0/S1 bridge, now used for its proper purpose.

**B. Lateral path (every `drive`, 10 Hz):**
1. Project the ego onto `path_local` → `s_ego`, cross-track error `e_y`, heading error `e_ψ`.
2. Reference for the next 5 s: `path_local` from `s_ego` to `s_ego + max(5 s · v, 30 m)`.
3. Join: if `|e_y| > 0.3 m` or `|e_ψ| > 5°`, blend from the current pose onto the path with a quintic/Hermite over
   `L_join = clip(2 · v, 8, 25) m` (pure-pursuit look-ahead rule); otherwise take the path directly. This is what keeps the MPC
   from a step input; the MPC itself only penalises 1.0–2.0 s ahead (`linear_mpc.py`, `idx_start_penalty 10`).

**C. Speed profile (the only decision left):** produce 3–5 candidate speed profiles `v_k(s)` over the 5 s horizon, all starting at
the current speed with `|a| ≤ 2.4 m/s²`, `|jerk| ≤ 2 m/s³`:
- `keep`: hold `v_0` (the sim starts the ego at the *recorded* state, so `v_0` is the human's speed at t = 0);
- `curvature cap`: `v ≤ sqrt(a_lat,max / κ(s))`, `a_lat,max = 3 m/s²`, κ from the path (finite differences over 5 m);
- `vavam`: the speed profile implied by VaVAM-B's chosen trajectory (arc-length increments of its 6 waypoints at 0.5 s) — the
  camera model's view of lead vehicles / lights / stop lines, **decoupled from its lateral wander**;
- `brake ramps`: −2 and −4 m/s² to zero (PDMEmergencyBrake shape), used only by the fallback and later by a lead guard.
Pick: `min(keep, curvature cap, vavam)` point-wise, i.e. never faster than any source says — first version; A/B the pure
`curvature cap` (no camera) against it. Progress saturates at 0.8 of the recording, so matching `v_0` already scores full.

**D. Emit:** poses at 10 Hz along the reference at `v(s)` for 5 s (`build_trajectory_from_plan` timing rules: speed = spacing),
yaw = path tangent, z = current z. Fill `debug_info` with the candidates (already plumbed).

**E. Fallbacks (never `terminate_session`):** no route yet → current VaVAM path (today's behaviour); VaVAM failure → route path
with `keep`/`curvature cap` (the follower does not need the model); path lost (route implausible for > 1 s) → last path +
−2 m/s² ramp.

## 3. What we reuse vs write

| reuse (exists, tested) | write (new, ~200 lines) |
|---|---|
| `submit_route` storage, NaN masking, frames (`driver.py`, `selection.py::_finite_route`) | `route_map.py`: accumulate/merge/resample (A) — pure numpy, unit-tested with synthetic routes and poses |
| `reference_path` Hermite bridge (`selection.py`) | `follower.py`: project/join/reference (B), speed profiles + min-combine (C) |
| `make_cached_plan` / `build_trajectory_from_plan` (`trajectory.py`) — timing → speed | `speed_from_trajectory()` — VaVAM waypoints → `v(s)` |
| `predict_k` + selector (keep at k=1 for the speed cue; selection off) | env knobs: `VAVAM_FOLLOW_ROUTE=1`, `FOLLOW_SPEED_SRC=min|curv|vavam|keep`, `FOLLOW_ALAT_MAX`, `FOLLOW_JOIN_M` |
| `run-eval.sh`, `snapshot.sh`, the 100/400 ladder, seed 1234 + 5678 | tests: cold-start bridge, merge monotonicity, e_y after 5 s of straight driving < 0.2 m, curvature cap on a 90° turn |

## 4. Validation (each ≈ 10 min on `navtest_local100`, `dev_fast2`, seed 1234; GPU single-tenant)

| run | expectation that makes or breaks the idea |
|---|---|
| F0 `curv` (route path, curvature-capped `v_0`, **no camera model**) | dist_to_gt **≤ 1.5 m** (from 2.7), corridor exits ≈ 0, wrong-lane ↓ sharply, progress ≥ 0.95; at-fault may go *up* on front collisions (no braking) — that is the residual the camera must fix. If dist_to_gt stays > 2 m the accumulation/frames are wrong: stop and debug offline on captured routes (`capture/`) |
| F1 `min` (route path, speed = min(keep, curv, vavam)) | at-fault ≤ candidate #2's (≤ 6/100) with F0's path metrics — the hybrid |
| F2 second seed (5678) of the better of F0/F1 | same direction |
| F3 400 scenes | confirm gate: ≥ 5 fewer at-fault than `confirm400-mup-g100` (13), progress ≥ 0.97 × baseline, no city regression, Drive ≈ 103 ms |
| ship | bake into `Dockerfile.submit-mup` → candidate #3; explicit go only |

**Sizing rule (from S1's identity control):** a 4 mm per-call numeric difference moved at-fault by 2 on 100 scenes, and a seed change by 4.
So F0/F1 are judged on the *continuous* path metrics (dist_to_gt, lateral dist, corridor exits, wrong-lane — expected effects 1–2 m and
5–8 events, far above the floor), never on a 1–2 incident at-fault delta; at-fault is read only at F3 (400 scenes, gate ≥ 5).

Cheap pre-check before any GPU time: replay captured Drive requests (`capture/captured/*/requests.jsonl`) through `route_map.py` and
plot the accumulated path against the ego trace — the frames must line up to < 0.5 m or nothing downstream is meaningful.

## 5. Risks, stated

- Stationary starts / red lights: a pure follower drives off; `vavam` speed source is the mitigation, measured at F1.
- Lane changes in the recording: the route (lane-centre projection) jumps laterally at the change point; the merge step averages
  across it — expect a smooth diagonal, which is what the human did anyway.
- Route implausible / off-map segments (`route_generator` raises on > 10 m off the recording): guard → fallback E.
- Spirit of "end-to-end": legal per organizers; the camera model stays in the loop for speed. Record it plainly in the report.
