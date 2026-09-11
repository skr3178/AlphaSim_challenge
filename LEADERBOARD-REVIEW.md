# Leaderboard plan review — 2026-09-10

This review uses existing result JSONs, controller CSVs, per-timestep metric
parquets, run configurations, submission records, issue snapshots, and project
notes. No simulator, inference, experiment, evaluation, or submission was started.
The recommendations below revise the earlier plans; they are not implemented
policy changes.

## Recommendation

Use the unchanged VaVAM-B + μP, gain 1.00 candidate as the next official
comparison when submissions resume. It is an already-evaluated alternative to
WA-JEPA with different strengths, and the project records an uploaded submission
image. Verify its immutable registry digest and current submission compatibility
before using it. Reserve the other slot for a candidate with an attributable
improvement and acceptable runtime.

Continue developing WA-JEPA around its corridor failures. Downgrade the blanket
handover sanitizer from ROBUSTNESS-PLAN.md: the saved failures do not establish
that an abrupt handover is the principal problem. Keep basic trajectory validity
checks, but do not replace valid braking or turning plans with current-speed
straight motion merely because they exceed a comfort threshold.

VaVAM-μP is recommended for information gained on the current private set, not
because its higher raw progress proves it will beat WA-JEPA. The local results
still favor WA-JEPA overall. One official result for each family will compare
them on the same evaluation generation; it will not identify a general
local-to-private transfer function.

The September 10 history records two remaining monthly slots. This review did
not refresh quota or the live leaderboard.

## Recomputed evidence from saved results

These are the actual mean `rollouts[].score` values, not the historical proxy
or locally fitted PCS. At-fault and corridor columns are zero-score causes as
assigned by the scorer, whose failure reasons have a precedence order.

| Saved run | n | Mean scene score | Zero scores | At-fault zeros | Corridor zeros | Mean progress | Mean Drive ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| stock400-g100 | 400 | 0.84931 | 60 | 22 | 38 | 1.05535 | 103.9 |
| confirm400-mup-g100 | 400 | 0.88129 | 46 | 13 | 33 | 1.02038 | 102.8 |
| f3-follow-cv-400 | 400 | 0.88961 | 41 | 18 | 23 | 0.98839 | 104.6 |
| wajepa-s2-400 | 400 | 0.92470 | 26 | 2 | 24 | 0.95646 | 289.7 |
| wajepa-s4-400 | 400 | 0.93019 | 24 | 1 | 23 | 0.94722 | 511.2 |
| wajepa-s2-100 | 100 | 0.94993 | 5 | 0 | 5 | 1.00320 | 295.1 |
| wajepa-s12-100 | 100 | 0.96665 | 3 | 0 | 3 | 0.96575 | 1515.8 |

Sources: `/media/skr/storage/alpasim-runs/<run>/aggregate/results-summary.json`.
The `wajepa-s12-400` directory exists but has no completed aggregate; it cannot
be counted as a successful 400-scene confirmation.

S12 versus S2 on the same 100: two scenes improve, seven worsen, and 91 tie.
The two improvements repair corridor zeros; no new corridor zeros appear.
Its +0.01672 mean gain is promising but rests on two recoveries. S4 versus S2
on 400 improves mean by only +0.00549; the earlier paired analysis did not
establish separation beyond uncertainty.

WA-JEPA S2's 0.07530 loss from a perfect local mean decomposes exactly into:

- 0.06000 from 24 corridor zeros;
- 0.00500 from two at-fault zeros;
- 0.01030 from partial-score shortfalls on otherwise nonzero rollouts.

Thus corridor zeros account for about 80% of its local score deficit, and all
hard zeros account for about 86%. Raw progress above the scorer's saturation
threshold does not earn extra score. A low mean progress value alone does not
justify increasing speed.

The official S2 record remains 0.77478 mean scene score, PCS 986.45, rank 6 in
the saved board, and 1000/1000 valid scored rollouts. Official mean d2gt is
1.85358 m versus **1.35633 m locally**. Earlier comparisons to 0.50 m mixed the
official mean with a local lateral-error median.

## What the controller traces support

Recomputed from saved S2 metric parquets, using interpolation at the stated
times and all 351 perfect-score scenes as the comparison group:

| Group | n | Lateral error at 1.0 s | At 1.5 s | At 2.5 s | At 4.0 s |
|---|---:|---:|---:|---:|---:|
| Corridor failures | 24 | 0.029 m | 0.130 m | 1.042 m | 4.709 m |
| Perfect-score scenes | 351 | 0.012 m | 0.032 m | 0.130 m | 0.346 m |

Policy handover in the saved run config is at 0.5 s. This is predominantly
gradual divergence. Median minimum achieved acceleration after handover is
about -0.93 m/s² in corridor failures, versus -0.79 m/s² in perfect scenes;
none of those corridor scenes goes below -5 m/s². Early braking differs
between groups, but correlation alone does not establish an MPC swerve.

[Issue #152](https://github.com/NVlabs/alpasim/issues/152) remains a relevant
possible controller failure mode. These traces weaken the case for promoting
its proposed handover repair to our primary fix. Conversely, the notes'
claim that all controller involvement is conclusively refuted is too strong:
achieved steering matching commanded steering does not measure whether the
vehicle follows the planner's trajectory. An identical nonlinear controller
can respond differently to different planner outputs.

`plan_deviation` measures consecutive-plan disagreement, not controller tracking
error. Resolving the remaining attribution requires emitted plan versus actual
motion aligned in the same coordinate frame and at matching timestamps.

One concrete controller detail is confirmed in code: `idx_start_penalty=10`
with `dt_mpc=0.1` disables reference tracking cost over the first second of each
optimization horizon, while the policy replans every 0.5 s. This is worth
examining if reference tracking is implicated. It is not proof the setting is
wrong, nor permission to bundle an untested gain change into a submission.

## Changes to the earlier plans

| Earlier idea | Review disposition | Evidence or condition |
|---|---|---|
| Unchanged VaVAM-μP candidate | First official comparison | Complete 400-scene evidence; different behavior from submitted S2; upload recorded |
| WA-JEPA S12 | Retain as a candidate for later validation | Two repaired corridor zeros on 100; 400 incomplete; runtime not established officially |
| WA-JEPA S4 | Keep available; low priority for a scarce slot | Only +0.00549 on 400; similar failure profile to S2 |
| Broad handover sanitizer | Downgrade to a conditional hypothesis | Failures predominantly grow after a normal initial handover |
| Automatic straight fallback / mandatory positive progress | Remove as a general safety recommendation | Can override needed braking, stationary behavior, or turns; existing fallback also floors speed at 1 m/s |
| Route-command threshold changes | Park | `wajepa-fix-100` scores 0.93994; `wajepa-wjrule-100` 0.94990; no demonstrated repair of the five original corridor failures |
| Unconditional route geometry + model speed | Park in its present form | F3 adds five net at-fault zeros despite improving path metrics |
| Route-conditioned path selection with confidence checks | Conditional development option | Only after demonstrating usable online route evidence before drift; route starts about 40 m ahead |
| Output gain >1 for VaVAM-μP | Keep rejected | Existing gain screens lose scene score and increase path error |
| More VaVAM-L / broad sampling sweeps / local PCS fits | Low priority | Existing evidence does not establish a stronger candidate |
| New models or fine-tuning | Later reserve | Adds adaptation and validation work before exploiting the present failure evidence |

The F3 investigation already retracted its initial "under-braking" diagnosis.
Its new collisions implicated route/path errors in dense traffic. Copying a
speed profile onto another path can also invalidate the obstacle avoidance
assumptions behind that profile. Any revived hybrid must preserve visual path
choices when route confidence is insufficient; it cannot assume the lane-centre
route always matches the human path.

## Evaluation improvements that should remain in the plan

The public YAML contains 1485 scenes from **44 source logs on nine dates**.
The local 400 contains **13 source logs on four dates**, divided into 38 shorter
recording windows. Both "four recordings" in §6.52 and "38 source recordings"
in the report/runbook mislabel this hierarchy. **902 public scenes are from
source logs absent from our local 400**; 630 are on entirely absent dates.

Correct the report to use source-log grouping for both absolute and paired
uncertainty, while retaining window/date/city sensitivity views. Validate
scene/repeat keys so repeated rollouts are not silently collapsed into one
baseline row. No bootstrap interval covers the unknown private distribution.

Keep the official scorer formula and report separate score losses from
at-fault, corridor/offroad, and nonzero partial scores. Include both repaired
failures and new failures, with per-log breakdowns. Resolve city and log metadata
from configuration rather than extending the present four-date heuristic.

Pin the available official simulator/scorer/controller configuration, camera
contract, timing, driver digest, and data-cache version for each comparison.
[Issue #156](https://github.com/NVlabs/alpasim/issues/156) records an updated
nuPlan cache adopted for the private/final set; this review has not established
the provenance of our extracted local cache. A file timestamp alone is not a
checksum or version guarantee.

The local starter and official `go_straight_with_delay_v2` have not been shown
to be identical policies under identical runtime settings. Their different
scores cannot, by themselves, quantify dataset difficulty or collision risk.
The old stock submission and current WA-JEPA submission also belong to
different evaluation generations, so they do not establish opposite transfer
functions for the two model families.

## Staged work and submission decision

1. **Reconcile the decision record.** Use this review and the dated submission
   JSONs to retire stale PCS projections, quota claims, runtime limits, and
   unsupported causal claims in the older strategy/current-best files. Keep
   historical experiments identifiable rather than overwriting their outcomes.

2. **Nominate the unchanged μP image for the next official slot.** Confirm
   registry manifest versus local image identity and current protocol/settings;
   do not confuse the local image ID with its registry manifest digest. When
   the user resumes submissions, this gives a direct current-set alternative
   without combining unrelated changes. Its official superiority is unknown.

3. **Create a WA-JEPA failure manifest from the existing traces.** Focus on the
   15 corridor failures where μP succeeds, the nine shared corridor failures,
   the 24 μP corridor failures WA-JEPA repairs, and matched successful controls.
   Inspect every replan, not just handover. Compare planned and realized XY/yaw
   at common times, observed speed, time/frame transforms, route geometry,
   image/history availability, and candidate disagreement before divergence.
   Use ground truth for offline diagnosis only, never as a submitted policy input.

4. **Choose one fix according to the observed failure.** If the emitted plan
   already chooses the wrong path, prioritize conservative path selection or
   persistence using information actually available online. If the emitted
   path is correct but the vehicle departs from it, investigate trajectory
   timing/frame conversion and controller reference tracking. Apply feasibility
   repair only where discontinuity is demonstrated. Preserve legitimate stops,
   braking, and turns. Do not combine a new path policy, speed gain, and new
   controller gains in the same first comparison.

5. **When experiments are authorized later, use independent coverage.** First
   check the targeted failure manifest with successful controls, then assess
   the candidate on an untouched selection from previously unseen source logs.
   The old 400 is a regression/development set after this much tuning. Select
   new clips by log/city, initial speed, turning, traffic, and short/long progress
   conditions before looking at candidate outcomes. Broadening source diversity
   matters more than another repeat of the same 400 or an automatic full-suite run.

6. **Reserve the last recorded slot for evidence that generalizes.** Require
   fewer targeted hard zeros without a material safety or partial-score
   regression, including across independent logs. S12 can earn that slot if its
   corridor benefit extends beyond its two known recoveries and runtime passes.
   If μP wins officially, prioritize a demonstrated improvement to that family.

S2's official wall time is 1249.347 s against 3000 s. This invalidates the old
2485-second analysis but does **not** prove S12 passes: its measured local
driver time is approximately 5.2 times S2's, whereas the total-wall headroom is
about 2.4 times. Total runtime depends on model share, renderer work, batching,
and official contention. Treat both earlier categorical statements, "S12
fails" and "S12 comfortably passes," as unestablished under the new setup.

Organizer guidance in [issue #166](https://github.com/NVlabs/alpasim/issues/166)
also explains why private-set results and IRT ranking can differ from public
mean scores. The next plan should reduce demonstrated failure modes and use
official submissions to compare candidates; it should not promise a rank from
the local mean.
