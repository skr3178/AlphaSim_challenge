# Codex proposal — path from stock VaVAM to a top leaderboard entry

Date: 2026-09-01

## Recommendation

Stay with VaVAM as the primary policy and focus first on inference-time improvements. A 24 GB local GPU is sufficient for the proposed inference experiments and later parameter-efficient tuning, while the official 16 GiB-per-replica and throughput constraints make full-model expansion risky.

The recommended sequence is:

1. Submit the validated VaVAM-B + μP, gain 1.00 candidate as an independent calibration point.
2. Develop consensus-constrained, route-aware multi-sample trajectory selection.
3. Compare short temporal context against a frozen CLOVER/DrivoR adaptation.
4. Attempt LoRA or action-head fine-tuning only if the inference-time approaches plateau.

Do not combine the μP candidate with unvalidated route selection or slowdown before its first official submission. A clean result is needed to measure the value of later changes.

## Idea-ranking system

Ideas are scored using these weights:

- 30% likely leaderboard impact
- 25% supporting evidence
- 20% fit for available hardware and development time
- 15% robustness on unseen final scenes
- 10% latency and implementation risk

| Rank | Idea | Score | Assessment |
|---|---|---:|---|
| 1 | Consensus-constrained route sampling (B1+B4) | 84/100 | Best combination of evidence, cost and relevance to current failures |
| 2 | Temporal context: increase from one frame to 2–4 frames (B3) | 73/100 | High potential because VaVAM is video-trained but the sample driver uses one frame |
| 3 | Frozen CLOVER or DrivoR adaptation | 67/100 | High ceiling without training, but meaningful domain and adapter risk |
| 4 | Decelerating inference-failure fallback (B8) | 64/100 | Cheap and safe, but useful only when inference failures occur |
| 5 | Conditional slowdown (B2) | 57/100 | Plausible safety benefit, but sample disagreement is not proven to predict collisions |
| 6 | Multi-camera VaVAM (B5) | 53/100 | Potentially valuable but requires substantial architecture work and may introduce distribution shift |
| 7 | Action-head LoRA or other PEFT | 48/100 | Feasible on 24 GB; reliable training data and closed-loop transfer are the limiting factors |
| 8 | SimWAM checkpoint adaptation | 41/100 | Interesting model but too close to official memory and latency limits |
| Reject | Output gain above 1.00, VaVAM-L, global braking, EMA smoothing | <25/100 | Existing local or leaderboard evidence is negative |

The μP candidate is not ranked as an experiment because it has already passed the local confirmation gate. It is a submission action.

## Proposed trajectory selector

Pure minimum-route-cost selection is too risky. The route begins about 40 m ahead, while the predicted trajectory covers only the nearer horizon, and the selector has no direct obstacle representation. A route-aligned candidate could therefore be an unsafe stochastic outlier.

Use this selection order instead:

1. Reject non-finite and dynamically implausible trajectories.
2. Compute candidate consensus and identify the medoid region.
3. Reject candidates that are excessive outliers from that consensus.
4. Within the plausible set, score agreement with the bridged route reference.
5. Penalize discontinuity from the previously selected plan.
6. Enforce a minimum-progress constraint.
7. Use progress along the route as the final tie-breaker.

Start with adaptive `k=3`. Increase sampling only for turns, ambiguous route commands or high uncertainty. This limits latency and VRAM while retaining most of the potential selection benefit.

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
2. Confirmed consensus-constrained route selector.
3. The best confirmed independent candidate: temporal VaVAM or frozen CLOVER/DrivoR.

Conditional slowdown should take the third slot only if it produces a clearer paired improvement than both alternatives.

## Immediate housekeeping

Before implementation work:

- preserve the current dirty worktree in a recoverable branch or snapshot;
- rotate the Hugging Face token recorded as exposed in the project notes;
- reconcile the documentation state: `selection.py` and its tests exist, while `ROUTE-SELECTION-PLAN.md` says the feature is not implemented; the driver integration remains absent;
- recheck the final challenge topology, controller settings and submission limits after the rules/configuration freeze.

## Bottom line

The highest-value path is:

**bank μP → hybrid medoid/route trajectory selection → temporal VaVAM or frozen CLOVER/DrivoR → PEFT only if necessary.**

This ordering maximizes information gained per submission while keeping the main experiments within the available GPU budget.
