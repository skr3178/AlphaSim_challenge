# Robustness plan: WA-JEPA → nonlinear MPC

## Situation

The local `navtest_local400` result is valid evidence for that public sample,
but it is not a prediction of the current submission board.  The public suite
has 1,485 scenes while the current official evaluation reported 1,000 valid
rollouts, so the board is using a private set with an unpublished composition.
Do not fit a local-to-official score offset or synthesize a local PCS.

The most useful local evidence is paired and mechanism-specific: compare two
policies on the same clips and ask whether a change reduces a known failure
mode without regressing safety or progress.

## Leading mechanism

AlpaSim issue #152 documents a nonlinear-MPC failure mode: a trajectory with
harsh braking can cause a lateral swerve that artificially reduces forward
progress.  The associated starter-kit fix (PR #153) changed the trajectory
source to use current speed; it did not replace the nonlinear controller.

WA-JEPA currently accepts all eight predicted poses directly in
`wajepa_challenge/trajectory.py:make_cached_plan()` and interpolates them to
the emitted controller trajectory.  Its straight-line fallback already uses
the current speed, but a fresh model plan has no equivalent continuity or
dynamic-feasibility guard.  This is a plausible explanation for the observed
local corridor failures and the weaker private-board progress score; it is not
proof without private per-scene traces.

Primary references:

- https://github.com/NVlabs/alpasim/issues/152
- https://github.com/NVlabs/alpasim/pull/153

## Recommended policy change

Implement a trajectory sanitizer/safety gate between WA-JEPA prediction and
the nonlinear MPC.  Treat predicted geometry as a suggestion rather than an
unconditional controller command.

For each fresh plan:

1. Start from the current ego pose, heading, and velocity.
2. Derive segment speed, longitudinal acceleration, jerk, curvature, and
   heading/steering-rate from the model poses.
3. Enforce configurable conservative bounds, including monotonic forward
   arc-length progress.
4. Blend the first 0.5–1.0 seconds smoothly from the current-speed,
   current-heading path to the feasible model geometry.
5. Recompute yaw from the sanitized XY positions rather than retaining a
   potentially inconsistent predicted yaw sequence.
6. When the model trajectory remains infeasible, emit the already-existing
   current-speed straight fallback for that update.

The guard must be minimally invasive: retain a feasible model plan after the
short handover window rather than substituting go-straight for every plan.
The aim is to avoid abrupt brake/swerve commands while retaining WA-JEPA's
trajectory accuracy and collision avoidance.

## Local evaluator/report changes

Do **not** alter the local scene scorer or replace its score with a synthetic
private-board metric.  `tools/eval-report.py` already reports the official
per-rollout scene-score inputs and correctly states that PCS cannot be
calculated locally.

Improve decision support instead:

1. Make the recording-block confidence interval the primary uncertainty for
   go/no-go decisions.  Clips from the same source recording are correlated.
2. Apply the same recording-block resampling to paired score deltas; the
   current paired bootstrap and sign test use clips as independent units.
3. Print public-suite coverage explicitly: selected clips / 1,485 public
   scenes, source-recording count, city counts, and an explicit statement that
   the official 1,000-rollout private mix is unknown.
4. Add a handover-risk table, grouped by initial speed and predicted
   first-segment braking/acceleration, jerk, curvature, and plan-to-plan
   discontinuity.  For each group report scene score, zero rate, corridor
   exits, at-fault incidents, progress, and dist-to-GT.
5. Record the per-plan telemetry needed for that table at the driver boundary:
   observed ego speed, raw and sanitized first-segment speed, minimum implied
   acceleration, maximum jerk/curvature, blend or fallback reason, and plan
   replacement discontinuity.

This turns local evaluation into a detector for controller-sensitive plans;
it does not claim to reproduce the private board.

## Selection criteria

Use exact paired public clips to compare the sanitizer against the current
policy.  Prefer robustness to a small improvement in the public mean.

Required gates:

- corridor exits and at-fault incidents do not increase;
- zero-score count and worst recording/city improve or remain neutral;
- the lower tail of scene score improves, not only the mean;
- high handover-risk bins show fewer lateral failures;
- progress and dist-to-GT do not meaningfully regress;
- fallback/blend activation rate is logged, bounded, and explainable.

Do not run a full evaluation solely to produce a new absolute score projection.
First validate the sanitizer offline against saved plan/controller traces and
use the enhanced report for a focused paired stress A/B when evaluation is
appropriate.

## Priority order

1. Instrument the driver and evaluator report for handover-risk telemetry.
2. Implement the trajectory sanitizer and current-speed safety gate.
3. Inspect saved traces/offline outputs for feasibility and trigger behavior.
4. Run a focused paired stress test later, then use the existing public suite
   only as supporting evidence for a submission decision.

Secondary ideas such as S12 or controller-gain changes may complement this
work, but neither guarantees that a model plan is dynamically continuous at
the MPC handover.  The trajectory interface guard is the first change to test.
