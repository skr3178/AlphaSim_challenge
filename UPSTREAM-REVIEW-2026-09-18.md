# Challenge source review — September 18, 2026

## Result of fresh fetch

Successfully fetched `NVlabs/alpasim` branch `e2e_challenge` from GitHub.
The remote still ends at `7611632f17a623a10564f4648c778ebb18079735`
(September 15, Add Warmup Track #183). There are **no new commits or code
differences** relative to our September 16 checkout. Reused the clean detached
checkout `alpasim-upstream-20260916/`; no duplicate checkout was needed.

The active runtime and custom drivers were not changed. No evaluations,
experiments, tests, model downloads, dependency installs, or submissions ran.
This review checks the public branch, not the live server's deployment state.

## Hints from existing code and documentation

### 1. Policy/controller compatibility is an actionable diagnostic, not a proven cause

`e2e_challenge/CONTROLLER_TUNING.md` explicitly warns that finite, correctly
shaped trajectories can still be dynamically implausible. Extreme requested
braking can produce a zig-zagging MPC solution. The controller is not a
trajectory-repair or safety-filter system.

Our WA-JEPA `make_cached_plan` checks shape and finiteness and anchors eight
future points at 0.5-second spacing, but those checks do not establish
acceleration, curvature, or heading/position consistency.

The controller default `idx_start_penalty=10` with 0.1-second MPC spacing
suppresses tracking costs on the first ten horizon stages. This does NOT mean
the vehicle is uncontrolled for a second: later tracking costs, dynamics, and
other objective terms still influence present control. It is an existing
design choice, not a newly introduced bug.

Recommendation: inspect saved emitted plans against actual vehicle positions
at matching absolute timestamps. Separate a drifting reference from poor
tracking of a good reference before considering gains or trajectory repair.
Earlier saved failure analysis in LEADERBOARD-REVIEW.md shows gradual
divergence, not proof of an abrupt harsh-braking handover problem. Do not
introduce a blanket straight-line fallback or speed boost on this evidence.

### 2. Route conditioning remains a model-specific risk

The challenge's shared nuPlan route starts approximately 40 m ahead of ego.
WA-JEPA compresses that route to a categorical command; Py123D's downloaded
checkpoint uses a 45 m target point. These are different conditioning contracts,
not interchangeable adapter settings.

Our WA-JEPA navigation source already records that changing nominal lookahead
from 5 to 20 m is ineffective when the first supplied waypoint is about 40 m
away. A previous threshold variant was tested and rejected. Do not propose
that same tweak as a new upstream-inspired fix.

Current Garage adapter prepends the ego origin when appropriate and extends
nonempty routes before building target-point conditioning. It also catches
planning exceptions and can serve cached or straight-line fallback plans.
These mechanisms deserve review for empty/short routes and input distribution
differences, but their presence alone does not prove incorrect navigation.

### 3. Count actual policy execution, not only valid rollouts

`e2e_challenge/NAVSIM_MODEL_ADAPTATION.md` explicitly requires positive model
inference counts, zero inference errors, and inspection of cached-plan and
straight-fallback counts. A successful RPC/container run is insufficient.

Garage's `_replan` logs `failed to plan` and returns None on exceptions;
the outer path may still return a valid trajectory. This supports our earlier
finding of fallback-masked failures in the saved Py123D 400 run. It does not
establish that WA-JEPA had such failures or explain the entire ranking gap.

Recommendation: make model-success, cached-plan age, route availability, and
fallback counts explicit in future reports before interpreting model quality.

### 4. Timestamp alignment is already partly handled in WA-JEPA

The upstream adaptation guide calls for timestamp-matched dynamics and poses.
Our active WA-JEPA driver selects synchronized camera history, takes the ego
snapshot at the newest image timestamp, and anchors the plan at the reserved
image timestamp. Its ego snapshot uses matching RPC dynamics if available.
Important: when dynamics are missing, the active driver increments
`dynamic_state_fallback` and returns **zero velocity and acceleration**, not a
finite-difference estimate. That can present a moving vehicle as stationary
to the model if the branch is exercised. This is a concrete audit target,
not evidence that the branch was exercised in the official submission.
Searching the saved `wajepa-s2-400.driver.log` found no positive
`dynamic_state_fallback` counters; the displayed final counters were zero.
Thus the saved local log does not support this as an observed failure cause.

This inspection does not reveal an obvious missing timestamp anchor to patch.
It is not a full training/preprocessing parity audit or proof that every
runtime input arrives as expected. Camera order, crop, normalization, history
spacing/padding, and checkpoint contract still require exact parity checks.

### 5. Scoring alignment remains prerequisite

The September 14 off-road changes remain the material scoring update: road-area
loading, coordinate transforms, and repaired geometry checks must move together.
See UPSTREAM-REVIEW-2026-09-16.md. There is no newer scene-score formula,
controller implementation change, or public navtest replacement in this fetch.

## Priority for next work (not performed)

1. Align the complete local evaluator with the pinned upstream source.
2. Establish whether saved artifacts support corrected evaluation-only rescoring.
3. Audit model execution/fallback coverage and training-to-inference input parity.
4. Attribute saved failures using emitted-plan-versus-actual-motion comparisons.
5. Only then choose a narrow model/adapter/controller change for later testing
   on source-log-disjoint validation. Keep Py123D as the user's selected primary
   development direction; this review does not justify switching back to VaVAM.

No confirmed model fix was discovered. The strongest hints concern the
policy/controller interface and honest execution accounting, not a newly
released checkpoint or evidence of a different private source dataset.
