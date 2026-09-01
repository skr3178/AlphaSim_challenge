# Codex proposal — path from stock VaVAM to a top leaderboard entry

Date: 2026-09-01

Revised after the route-generator and leaderboard-forensics review.

## Recommendation

Stay with VaVAM, but separate **trajectory geometry** from **trajectory timing**. The latest evidence moves direct route use ahead of sampler tuning: the route should provide lateral geometry, while VaVAM supplies the distance-versus-time profile and remains the fallback when route confidence is poor. A 24 GB local GPU is sufficient because this is principally a geometry and inference change, not retraining.

The recommended sequence is:

1. Submit the validated VaVAM-B + μP, gain 1.00 candidate as an independent calibration point.
2. Clarify whether temporal route accumulation is permitted specifically on the nuPlan track.
3. Develop accumulated route geometry + VaVAM timing; use a current-window route follower if accumulation is unavailable.
4. Improve the route-derived command as the cheap, non-accumulating fallback.
5. Compare temporal context against persistent-mode/medoid decoding and a frozen CLOVER/DrivoR adaptation.
6. Attempt LoRA or action-head fine-tuning only if the inference-time approaches plateau.

Do not combine the μP candidate with unvalidated route selection or slowdown before its first official submission. A clean result is needed to measure the value of later changes.

## Revised idea-ranking system

Ideas are scored using these weights:

- 30% likely leaderboard impact
- 25% supporting evidence
- 20% fit for available hardware and development time
- 15% robustness on unseen final scenes
- 10% latency and implementation risk

| Rank | Idea | Score | Assessment |
|---|---|---:|---|
| 1 | **Accumulated route geometry + VaVAM timing** | 92/100 | Directly targets lateral drift, wrong-lane and corridor failures; best current explanation of the leading profiles |
| 2 | **Current-window route follower + VaVAM timing** | 81/100 | Avoids accumulation uncertainty, but must infer the missing 0–40 m path |
| 3 | **Better route-derived command** | 77/100 | Cheap and low risk compared with the current single-waypoint ±3 m threshold |
| 4 | **Temporal context: 2–4 frames** | 72/100 | Should improve motion and obstacle understanding without retraining |
| 5 | **Persistent latent modes + medoid decode** | 65/100 | Attacks stochastic instability at its source and is stronger than a discontinuity penalty |
| 6 | **Frozen CLOVER or DrivoR adaptation** | 61/100 | High theoretical ceiling, but meaningful AlpaSim domain and coordinate-conversion risk |
| 7 | **Decelerating inference-failure fallback** | 53/100 | Sensible robustness feature with limited upside unless failures occur |
| 8 | **Action-head LoRA or other PEFT** | 46/100 | Feasible on 24 GB; training-data transfer and overfitting are the dominant risks |
| 9 | **Conditional slowdown** | 39/100 | No reliable collision-risk signal and a meaningful risk of losing progress |
| Retire | **Further `w_disc` tuning** | 18/100 | It reduced geometric churn but changed too few scene outcomes to be a leaderboard lever |
| Retire | **Pure route-cost sample selection** | 31/100 | It cannot repair a route-blind candidate set and may select route-aligned outliers |
| Reject | Output gain above 1.00, VaVAM-L, global braking, EMA smoothing | <25/100 | Existing local or leaderboard evidence is negative |

The μP candidate is not ranked as an experiment because it has already passed the local confirmation gate. It is a submission action.

### Why the ranking changed

The route-generator code establishes that the map route is built from the recorded ego trajectory's lane sequence and that the recorded waypoints are projected onto lane centres. The runtime resamples that route relative to the current ego and drops the first approximately 40 m. This makes the route an unusually strong geometric signal even though it lacks timing.

The leading nuPlan profiles are consistent with this mechanism:

- NaLa combines approximately twice stock VaVAM's at-fault spacing with about three times tighter path following while retaining progress. A route/path follower with a separate speed policy is a strong explanation, although the implementation is not public.
- `vavam-route-cudagraph-v5` strongly suggests that route geometry entered the VaVAM control loop and that CUDA graphs managed its throughput. The tag is evidence, not proof of the precise implementation.
- The cautious path-hugging entries show the failure mode to avoid: geometric safety without sufficient progress scores poorly.

The completed `w_disc` sweep reinforces the change. Increasing the weight reduced plan-to-plan endpoint movement, but only a few scene outcomes changed and the effect remained at the numerical/seed noise floor. Continuity was therefore a symptom rather than the principal cause. The current selector still chooses only among trajectories produced by a route-blind sampler; if no candidate follows the route, no weighting can create the missing trajectory.

### Rules caveat

The public organizer response allowing accumulation says **“for the PAI track”**. It does not explicitly authorize the same mechanism for nuPlan. Accumulation should be developed behind a flag, but it should not be submitted until the organizers confirm that retaining and fusing route observations is permitted on nuPlan and will remain valid for final evaluation.

## Proposed route-geometry controller

The primary design factors path geometry from speed:

```text
geometry = accumulated/fused route centreline
timing   = VaVAM cumulative trajectory distance at each 0.5 s
output   = points on the route at those cumulative distances
```

Implementation outline:

1. Store each route window with its matching ego pose and timestamp.
2. Transform each window from its timestamp-specific rig frame into a persistent rollout frame.
3. Fuse overlapping windows into an ordered, smoothed route spline while rejecting foldbacks and poor-overlap segments.
4. Transform the fused spline back into the current ego frame for each planning tick.
5. Compute VaVAM's cumulative arc-length profile and sample the route spline at those distances.
6. Converge smoothly from the ego's current cross-track offset instead of snapping directly to the lane centre.
7. Enforce curvature, acceleration, jerk and progress bounds.
8. Fall back to unmodified μP VaVAM until the route history provides confident near-field coverage and whenever the fused route is inconsistent.

The route contains geometry but not the recorded speed profile. Consequently, “follow the route at recorded speed” is not directly implementable. VaVAM timing is the preferred first speed policy because it preserves visual responsiveness and the baseline's progress characteristics.

Three initial arms isolate the source of any gain:

| Arm | Geometry | Timing | Purpose |
|---|---|---|---|
| R0 | VaVAM | VaVAM | μP baseline |
| R1 | Current-window Hermite bridge | VaVAM | Tests direct route geometry without accumulation |
| R2 | Accumulated/fused route | VaVAM | Full route-geometry hypothesis, conditional on nuPlan permission |

R2 should not advance unless it produces a substantial path improvement, fewer wrong-lane/corridor events, progress of at least 95% of μP, no material increase in front collisions, and stable bounded-curvature plans. Offline route/pose replay and visualization should precede GPU simulation.

## Secondary trajectory-selector branch

This branch is now secondary to the route-geometry controller. Pure minimum-route-cost selection is too risky: the route begins about 40 m ahead, the prediction covers only the nearer horizon, and the selector has no direct obstacle representation. A route-aligned candidate could therefore be an unsafe stochastic outlier.

Use this selection order instead:

1. Reject non-finite and dynamically implausible trajectories.
2. Compute candidate consensus and identify the medoid region.
3. Reject candidates that are excessive outliers from that consensus.
4. Within the plausible set, score agreement with the bridged route reference.
5. Prefer persistent/correlated latent modes over penalizing discontinuity after sampling.
6. Enforce a minimum-progress constraint.
7. Use progress along the route as the final tie-breaker.

Start with a medoid-only control and persistent or correlated latent noise. Increase sampling only for turns, ambiguous route commands or high uncertainty. Further `w_disc` tuning is retired unless new evidence shows that discontinuity predicts scene failures.

Random-number generation should be maintained per session rather than through one global inference-call counter. Otherwise concurrent-session scheduling can change which rollout receives each noise sample and weaken reproducibility.

## Decision gates

### Multi-sample diagnostic

Continue with trajectory selection only when:

- median endpoint spread is meaningfully above approximately 0.5 m;
- repeated samples produce useful route and heading diversity;
- concurrent throughput remains close to the passing single-sample baseline;
- official peak-memory requirements can be met below 16 GiB per replica.

If candidate spread is too small, stop the sampling branch and promote improved route-command derivation to the top priority.

### Route-selection screen

The selector should first demonstrate:

- fewer wrong-lane events or lower route deviation;
- no increase in at-fault incidents;
- no material progress loss;
- stable choices rather than rapid sample-to-sample plan switching.

### Confirmation gate

Before submission, the 400-scene paired comparison should show approximately:

- at least five fewer at-fault incidents;
- progress loss no greater than 3%;
- no meaningful increase in rear collisions;
- no route-specific regression concentrated in one city;
- end-to-end throughput sufficiently close to the already passing baseline.

The proposed `k=5 < 250 ms` mean-latency threshold is not sufficient. The official target is around 0.1 seconds of model work per `Drive`, and concurrent queueing matters. Compare total throughput, p95 latency and queue delay against stock and μP under the closest available contention pattern.

## Secondary experiments

### Temporal context

Test two frames first, then four. Do not jump directly to eight. Measure memory and latency before simulation quality. Temporal context is intended to improve dynamic understanding, lead-vehicle response and motion consistency rather than merely route following.

### Frozen alternative planner

CLOVER or DrivoR is the preferred independent model branch because the checkpoints are small and require no full retraining. Treat published NAVSIM scores only as screening evidence; they do not predict AlpaSim PCS. Verify camera geometry, coordinate conventions, trajectory timing and controller compatibility before judging policy quality.

### Conditional slowdown

Test slowdown only after establishing a route-selection winner. It should use hysteresis and a progress floor and should activate only under strong, persistent uncertainty. Do not assume that high sample spread automatically implies collision risk.

### Failure fallback

The decelerating fallback is sensible defensive engineering, but its leaderboard value depends on observed inference failures. Keep it isolated so that it can be enabled without changing normal successful predictions.

## Fine-tuning position

Do not prioritize full retraining. If inference-time improvements plateau, use parameter-efficient tuning of the action expert, small adapters, or a lightweight candidate reranker. Train only on legitimate public training resources such as `navtrain`-derived or SimScale training data, never distributed evaluation assets.

A 24 GB GPU can support carefully configured PEFT, but the larger risks are data distribution, overfitting and proving a closed-loop gain. Fine-tuning should earn its place through a frozen validation split and the same paired evaluation ladder used for inference changes.

## Conservative submission allocation

Assuming only three valuable submission opportunities:

1. VaVAM-B + μP, gain 1.00.
2. Confirmed route-geometry/VaVAM-timing hybrid.
3. The best confirmed enhancement to that hybrid: temporal context, a legitimate image-derived lead-risk guard, persistent-medoid decoding, or a frozen alternative planner.

Conditional slowdown should take the third slot only if it produces a clearer paired improvement than every alternative and preserves progress.

## Immediate housekeeping

Before implementation work:

- preserve the current dirty worktree in a recoverable branch or snapshot;
- rotate the Hugging Face token recorded as exposed in the project notes;
- reconcile the documentation state: `selection.py` and its tests exist, while `ROUTE-SELECTION-PLAN.md` says the feature is not implemented; the driver integration remains absent;
- recheck the final challenge topology, controller settings and submission limits after the rules/configuration freeze.

## Bottom line

The highest-value path is:

**bank μP → clarify nuPlan route accumulation → route geometry with VaVAM timing → temporal/lead-risk enhancement → PEFT only if necessary.**

This ordering maximizes information gained per submission while keeping the main experiments within the available GPU budget.
