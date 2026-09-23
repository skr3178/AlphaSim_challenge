# Shortened Py123d implementation

## Screening launched 2026-09-22

`run_screen.py` runs two one-scene smoke arms, then six paired 24-scene arms:
baseline, four one-variable MPC variants, stabilization 0.15 alone. No neural
training or full-400 run. The smoke stabilization arm also uses lateral weight
1.5 only to verify gain wiring; it is not used to infer isolated improvement.

The 24 IDs are selected deterministically before execution: two historical
corridor failures, two partial scores and two successes per city. City grouping
uses the existing public-scene date mapping; this is not a new metadata audit.
This deliberately outcome-stratified sample is for development only, not a
representative or independent benchmark. It contains no dedicated collision
stratum, so a clean safety result here is insufficient for promotion.

Run folder: `artifacts/20260922T060953Z/`. `status.json` records current stage;
each arm saves resolved simulator/controller configs, logs and `result.json`.
`COMPARISON.md` is updated after every completed screening arm. Source is copied
into an immutable-by-convention snapshot with SHA-256 inventory before startup.
The job holds the shared evaluation lock and cleans only its own containers.
It stops on missing coverage, planning failures or smoke filter nonactivation.

The existing Docker image is used with the snapshot mounted read-only; this is
a local experiment, not submission-container certification. Finalist packaging
and held-out testing remain separate steps. Runtime/scorer parity with the
current official service has not been established.

No training or temporal neural adapter. The existing checkpoint and Docker image
are unchanged. Implementation is in the local `../py123d_garage` checkout;
the old Docker image will NOT use it without a source mount or new image build.
Existing predicted-yaw changes are preserved and remain a separate ablation.

## Trajectory stabilization

Hydra configuration: `stabilization_previous_weight=0.0` (default, disabled).
First proposed isolated candidate: `stabilization_previous_weight=0.15`, with
`use_predicted_yaw=false` and default controller gains.

The previous session-specific plan is interpolated at the new plan's absolute
timestamps. Both plans already use the same rollout-local coordinate frame.
The current pose and nonoverlapping tail stay unchanged; yaw uses wrapped angular
differences. No cross-session history or extrapolation is used. History older
than 0.75 seconds, position disagreement above 0.75 m, heading disagreement above
0.2 radians, or initial old-plan speed exceeding new-plan speed by 0.2 m/s bypasses
blending. These conservative experimental thresholds are not validated safety
guarantees; braking later in the horizon and path feasibility still need checking.

## MPC candidates

`gains/` contains the published default and four one-variable changes: lateral
weight 1.5, heading weight 1.5, steering-change weight 3.5 or 6.5. All values are
within the published CLI ranges. These are hypotheses, NOT optimized gains.
Submit-time JSON uses the official `--controller-gains` option. For local runs,
the same keys must be mapped to the runtime controller configuration and the
resolved configuration verified before execution. No local sweep is launched here.

## Evaluation gates

1. Audit saved Py123d prediction versus executed-motion failures and actual
   rollout durations. The historical baseline includes 20 planning failures on
   two all-NaN-route scenes (see `../IMPROVEMENT-PLAN.md`). Count neural failures,
   not just successful RPCs.
2. Run baseline and one-variable MPC arms on a fixed small development subset,
   with stabilization disabled. Keep scene IDs, controller and runtime provenance.
3. Test stabilization separately against default gains, then combine only if
   individual improvements justify it.
4. Evaluate finalists on untouched source recordings with collision/corridor,
   progress and scene score reporting. Do not tune on that holdout.
5. Build a distinct candidate container and validate it before warm-up. No
   official submission is authorized by this implementation step.

CPU tests cover opt-out identity, temporal/local-frame alignment, unchanged
anchor/tail, nonmutation, stale/reversed history, disagreement, slowdown guard
and angular wraparound, alongside the existing predicted-yaw regression tests.
