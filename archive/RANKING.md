# How the AlpaSim leaderboard actually scores you

Notes on the Policy Capability Score (PCS): what the number means, what it rewards, and
where the practical leverage is.

Two sources, kept distinct throughout:

- **[DOCS]** — the DriveIRT design docs, <https://ln2697.github.io/navhard-leaderboard-2/docs/>
  (Long Nguyen & Kashyap Chitta, rev. 2026-05-31, marked *work in progress*). **Mirrored
  locally** at `navhard-docs/` — plain text in `navhard-docs/txt/`, digest in
  `navhard-docs/SUMMARY.md`. Line refs below are into `txt/`.
- **[SOURCE]** — read directly from the AlpaSim repo (`e2e_challenge` @ `f012862`)
- **[MEASURED]** — derived from the live leaderboard. Current pull **2026-08-30**
  (`leaderboard/nuplan.json`, 60 submissions; `pai.json`). Prior snapshot preserved at
  `leaderboard/2026-08-29/`. Reproduce with `./fetch-leaderboard.py`.

---

> ## 🏁 We are on the board: rank 6 with a stock checkpoint
>
> `team-lucifer` / `vavam-stock-20260829` — **PCS 1590.36**, `avgDist` 1.621, `d2gt` 3.05,
> submitted 2026-08-29. **Sixth of 19 teams, with the unmodified VaVAM checkpoint and zero
> tuning.**
>
> This single data point resets several estimates in this document:
>
> | | Was assumed | Actually measured |
> |---|---|---|
> | Stock-VaVAM starting score | untested | **1590.36** |
> | Headroom from a working baseline | ~730 pts (1000 → 1731) | **~130 pts** (1590 → 1721) |
> | Value of all published output-shaping | unknown | ≤ 130 pts |
>
> It also confirms §10's argument empirically: **stock VaVAM lands within 10 points of the
> organizer's own reference policy** (`host/policy1` = 1600.00) with no work at all.

---

## 1. The headline: PCS is not an average of your scene scores

This is the single most important thing to internalise. **[DOCS]**

The leaderboard is an **Item Response Theory** model, the same machinery used to score
standardised exams. It treats the results as a matrix `X (S × N)` — S policies × N routes —
and jointly estimates three sets of latent parameters:

| Parameter | Meaning |
|---|---|
| `θₛ` | **ability** of policy s — "how good subject s is" |
| `βₙ` | **difficulty** of route n — "how hard item n is" |
| `αₙ` | **discrimination** of route n — "how sharply item n separates strong from weak" |

Your PCS is a rescaling of `θ̂ₛ = μ_theta,s`, the posterior mean of your ability.

The consequence: **routes are not weighted equally.** A route everybody passes carries
almost no information about you. A route with high `αₙ` that separates strong from weak
policies moves your `θ` far more. You cannot compute your own PCS from your own results
alone — it depends on how every *other* policy did on the same routes. Improving on scenes
where the field already succeeds buys you very little.

The docs are explicit that this is the point: naive averaging of the response matrix "has
well-known drawbacks," and joint modelling addresses them.

### ⚠️ The scoring is ASYMMETRIC — regressions cost more than gains [DOCS §1.1]

Verbatim from the source (`navhard-docs/txt/01_motivation.txt:39`):

> "A policy's estimated ability **rises quickly when it passes routes that the rest of the
> leaderboard fails, and falls harder when it stumbles on routes that the rest passes.**"

**Failing an easy scene hurts more than passing a hard scene helps.** This is the single most
tactically important sentence in the documentation, and it inverts the usual optimisation
instinct.

Consequences:

- **Never trade reliability for capability.** A change that wins two hard scenes but
  occasionally fails one easy scene can be **net negative**.
- **Track your zero-rate, not your mean.** The mean hides exactly the events the model
  punishes hardest.
- **Stochastic policies are penalised structurally.** A sampler that usually passes an easy
  scene but occasionally doesn't generates precisely the failures that cost most. Seed it or
  use a deterministic/medoid decode — note PAI rank 2 is literally `baseline-k5-medoid`, and
  rank 3 is `...-deterministic-bas`.

And the flip side (`:51`), which quantifies where effort pays:

> "pushing from 90 to 100 on an easy route barely moves the rank, while pushing from 40 to 50
> on a hard route moves it substantially."

---

## 2. The scale is pinned to two organizer baselines [MEASURED]

The docs never state how `θ` becomes a four-digit number. The leaderboard data answers it.

Two rows belong to `team_id = "host"` and carry **exactly round scores** — to full float
precision, which does not happen by accident in a continuous posterior:

| Track | Tag | PCS |
|---|---|---|
| nuPlan | `go_straight` | **1000.0** exactly |
| nuPlan | `policy1` | **1600.0** exactly |
| PAI | `policy1` | **1600.0** exactly |

So PCS is an **affine transform of `θ` anchored at two reference policies** — Elo-style
calibration. `policy1 = 1600` appears on *both* tracks, which is why scores are roughly
comparable across them.

**What this gives you, concretely:**

```
   ~123   degenerate submissions (worse than not moving)
   1000   ← do-nothing baseline: the straight-line starter kit
   1590   ← STOCK VaVAM, no tuning        (us, rank 6)
   1600   ← organizer reference policy    (host/policy1, fixed anchor)
   1721   ← current nuPlan ceiling        (two teams, tied)
```

### The anchor hypothesis is now proven, not inferred [MEASURED 2026-08-30]

Between the 08-29 and 08-30 pulls, **two new submissions arrived and nobody resubmitted** —
yet almost every team's score changed:

| Team | 08-29 | 08-30 | Δ |
|---|---|---|---|
| na-la / metamon | 1731.23 | 1720.72 | **−10.51** |
| team-foxhihi | 1626.82 | 1612.41 | **−14.42** |
| **host** | **1600.00** | **1600.00** | **+0.00** ← unchanged |
| cothlory | 1449.39 | 1436.89 | −12.50 |
| opendrivelab-org | 1377.34 | 1366.16 | −11.19 |
| team-mxr | 872.33 | 875.67 | +3.34 |

Every competitor moved. **The `host` anchor did not move at all** — to full float precision.
That is exactly what a two-point affine calibration predicts: the reference policies are
pinned, and everyone else's `θ` is re-estimated as the response matrix grows.

It also demonstrates §1 concretely: **your score is not a property of your submission.** It
changed by up to 14 points because *other people* submitted. Two extra rows in a
58-submission matrix re-fit every latent parameter.

**The docs predicted this exactly** (`navhard-docs/txt/01_motivation.txt:61`):

> "A number cited in March can change by June, not because the policy changed, but because
> **newer submissions re-anchored the route difficulties.** Reviewers cannot reproduce a cited
> ranking without knowing the leaderboard snapshot it came from."

They call it the **Moving Baseline** drawback. Our 08-29 → 08-30 measurement is an independent
confirmation of a documented property, not an anomaly.

### 🔒 Why the submission limit exists — and why decoys are off the table [DOCS §1.3]

The same section names an attack this scoring model admits:

> "An attacker can submit weak **decoy policies that fail on a chosen target route**. The fit
> then treats that route as harder than it is, and the attacker's primary submission, which
> passes the route, is rewarded with a higher ability estimate. […] **Submission limits and
> per-team identity verification mitigate this attack vector.**"

Two takeaways. First, the 5→3 submission cap is not arbitrary bureaucracy — it is the
documented countermeasure, so expect it to be enforced strictly. Second, this is named by the
authors as an **attack**; it is an integrity risk they are actively defending against, not a
tactic. Recorded so nobody rediscovers it and mistakes it for cleverness.

### Estimator sensitivity [DOCS §1.3]

> "The posterior […] requires many hyper-parameters, and the resulting ranking can shift under
> alternative hyper-parameters, **which also include the random seed.** […] there is no
> held-out ground-truth ranking to settle the disagreements."

So beyond the moving baseline, some of the ~1% drift may simply be re-fit noise. Another
reason not to read anything into single-digit gaps (§7).

### ⚠️ Consequence: PCS is non-stationary

Do not treat a recorded score as fixed. Rank ordering was preserved across this particular
re-fit, but magnitudes drifted ~1% and the drift was **not uniform** — `symphi` lost 2.31
while `team-foxhihi` lost 14.42. Comparisons across pulls need the same snapshot; that is why
`leaderboard/2026-08-29/` is archived rather than overwritten.

The starter-kit anchor is confirmed three ways: `host/go_straight` = 1000.0,
`team-aimm-alpha/smoke-*` = 1000.297, `zgca-team/starter-baseline-*` = 999.768 — all three
share an identical metric fingerprint (`avg_dist = 0.27835287112208`,
`dist_to_gt = 2.4724735582844`). That is the unmodified straight-line driver, i.e. exactly
what our local smoke test runs.

**So: submitting the working starter image scores ~1000 and lands mid-field (rank ~41 of 58
submissions).** Everything above 1000 is earned; below 1000 means you made things worse.

---

## 3. The per-scene score, exactly [SOURCE]

Everything above is the *aggregation* layer. The per-scene score that feeds it is computed
locally and is only 97 lines: `src/eval/src/eval/aggregation/scene_score.py`. It is short
enough to state completely:

```python
score = 0.0                                              # if ANY hard failure
      = min(clamp(progress_clipped_rel, 0, 1) / 0.8, 1)  # otherwise
      = 1.0                                              # if gt_dist_traveled_m < 5.0
```

Confirmed by `score_criteria` in our own passing run's `results-summary.json`:

```json
{
  "collision_at_fault":        "== 0",
  "offroad":                   "== 0",
  "left_corridor_laterally":   "== 0 (lateral corridor exit fails; passing the end of the recording does not)",
  "progress_score":            "min(clamp(progress_clipped_rel, 0, 1) / 0.8, 1.0)",
  "short_gt_distance_override":"progress_score = 1.0 when gt_dist_traveled_m < 5.0"
}
```

### Exactly three things score you zero

`_hard_failure_reason()` checks, in order:

1. `collision_at_fault != 0`
2. `offroad != 0`
3. `left_corridor_laterally != 0`

Any one of them returns `score = 0.0` outright — `progress_score` is still *reported*, but
discarded. Nothing else can produce a zero. Note the third: leaving the corridor **sideways**
fails, while driving past the end of the recording does **not** (that's handled by timestep
truncation). Running out of road ahead of you is safe; drifting out of it is not.

### ⭐ Progress saturates at 80% — this is the biggest lever

`progress_clipped_rel` is divided by a saturation threshold of **0.8** and capped at 1.0. So:

| Relative progress | Scene score |
|---|---|
| 0.40 | 0.50 |
| 0.60 | 0.75 |
| **0.80** | **1.00** ← maximum reached here |
| 0.95 | 1.00 |
| 1.00 | 1.00 |

**Matching 80% of the reference progress earns a perfect scene score. The remaining 20% is
worth literally nothing**, while every extra metre of speed raises collision and
corridor-exit risk — each of which zeroes the scene outright.

The optimal policy is therefore *deliberately conservative*: target ~80–85% of reference
progress and spend the entire remaining budget on never triggering the three failures. Speed
beyond that threshold is pure downside.

Our own smoke test lands right in this regime **[MEASURED]**: `dist_traveled` 56.9 m against
GT 65.7 m ≈ **87%** — already past saturation. The straight-line starter driver scores a
**perfect 1.0** on that scene. Its ~1000 PCS is not from mediocre scene scores; it's from
scoring 1.0 on easy scenes and 0.0 on the ones where it crashes.

### Why this maps onto ZOIB exactly

The local score is bounded in [0, 1] with a **point mass at 0** (three hard failures) and a
**point mass at 1** (progress ≥ 0.8), continuous in between. That is precisely the shape the
zero-and-one-inflated beta model exists to fit — the docs' "zeros = collision, off-road,
scene incompletion" and "ones = clean passes" are these two masses.

---

## 4. What produces a zero, and why zeros dominate

The response variable is modelled as **zero-and-one-inflated beta (ZOIB)** — confirmed by
`metric_algorithm: "zoib"` on every leaderboard row **[MEASURED]**. Three branches **[DOCS]**:

```
Pr(X = 0 | θ)  = σ(g⁰ₙ − αₙθₛ)                                    ← catastrophic failure
Pr(X = 1 | θ)  = σ(αₙθₛ − g¹ₙ)                                    ← clean pass
Pr(0<X<1)·p(x) = (1 − σ(g⁰ₙ−αₙθₛ) − σ(αₙθₛ−g¹ₙ)) · Beta(x; a, b)  ← partial credit
```

with `g¹ₙ = g⁰ₙ + softplus(g¹ʳᵃʷₙ)` enforcing `g¹ₙ > g⁰ₙ`.

Operationally **[DOCS]**:

- **Zero** = the route ended in "collision, off-road, scene incompletion"
- **One** = a "clean pass" with perfect safety
- **Interior** = partial success

Why the inflation exists: a plain Beta "cannot place finite mass on {0} or {1}," and forcing
it to fit boundary spikes drives it U-shaped and wrecks the interior fit. The mixture "peels
each spike off into its own branch."

### The practical reading

A zero is a **point mass**, not merely a low score. It is a categorically different event
from finishing badly, and it is drawn from a separate branch of the likelihood. Meanwhile
the docs note the inflation rates share the same `αₙ` as the interior branch, so they
"sharpen rather than override the ranking signal."

**Therefore: eliminating collisions, off-road events and incompletions outranks improving
trajectory quality.** A conservative policy that always finishes beats an aggressive one
that occasionally crashes, even if the latter looks better on average.

### ⚠️ Correction: lateral deviation *positively* predicts score [MEASURED]

An earlier revision of this document claimed `dist_to_gt_trajectory` was "near-orthogonal"
to PCS, citing a handful of rows. **That was cherry-picking and it was wrong.** Computed
across the full board:

| Population | n | Spearman(PCS, dist_to_gt) |
|---|---|---|
| All nuPlan submissions | 58 | **+0.656** |
| Excluding 3 collapsed rows (PCS > 500) | 55 | **+0.597** |
| Within `opendrivelab-org` (same framework, ablation grid) | 17 | **+0.953** |
| Within `symphi` (same VaVAM base) | 3 | **+1.000** |

The within-team figures are the telling ones: with the base model held fixed, lateral
deviation ranks PCS almost perfectly. `opendrivelab-org` at n=17 is not a small-sample fluke.

**Interpretation.** `dist_to_gt_trajectory` is *lateral* deviation from the logged path (our
smoke test: 0.15 m lateral vs 2.80 m longitudinal). Near-zero lateral deviation means the
policy is passively tracking lane centre — not steering, not avoiding, not maneuvering.
High deviation with no hard failure means the policy is actively driving.

**But do not optimise this metric directly.** It is a *symptom*, not a lever: a capable
policy produces high deviation, deviation does not produce capability. Adding noise to your
steering would raise `dist_to_gt` and cause `left_corridor_laterally` failures, which zero
the scene. The correct reading is diagnostic — **if your `dist_to_gt` is near 0.2, your
policy is passive and will score near the floor**, which is exactly where our straight-line
starter sits (0.15).

---

## 5. The second metric is unbounded and exponential

`avg_dist_between_incidents_at_fault` is handled by a separate log-normal IRT extension,
because it is non-negative, unbounded above and right-skewed **[DOCS]**:

```
log X_{s,n} ~ N(θₛ − βₙ, σ²)
E[X_{s,n}]  = e^(θₛ − βₙ + σ²/2)
```

Ability and difficulty act as a **log-ratio**. Each unit of ability multiplies expected
distance between infractions by ≈ e (2.718). The docs stress there is **no saturation
ceiling** — gains compound rather than plateau.

But **[MEASURED]** it is clearly the *secondary* sort key, not part of PCS. Ranks 1 and 2
have byte-identical PCS (`1731.2303708622494`) while their distances differ substantially
(3.358 vs 3.088). PCS is driven by the bounded ZOIB metric; this one separates ties.

---

## 6. The top of the board is saturated [MEASURED]

Two different teams, different images, **identical PCS to 17 significant figures**:

```
na-la    sub1                             1720.7150523295797   (was 1731.2303708622494 on 08-29)
metamon  vavam-route-cudagraph-v5-nuplan  1720.7150523295797   (identical, both pulls)
```

The tie **survived the re-fit** — both moved by exactly the same amount and remain identical
to full precision. Two independent policies tracking each other bit-for-bit across a model
re-estimation is strong evidence for saturation rather than coincidence.

A continuous posterior does not produce that by coincidence. The most likely reading: both
policies pass essentially every route cleanly, so the ZOIB "one" branch saturates and `θ`
hits the identifiability ceiling — beyond that the model cannot distinguish them.

Practically: **~1721 is the effective maximum on the current nuPlan scene set.** The race
for first is already decided on the tiebreaker.

Symmetrically at the bottom, `team-mxr` has three submissions pinned at exactly
`122.7582171988247` — a floor for policies that fail nearly everything.

---

## 7. When is a score gap real?

Ranks carry uncertainty and the docs quantify it **[DOCS]**: sample `θₛ ~ N(μₛ, σₛ²)`, rank
within each draw, take quantiles. Two policies are "statistically tied" when their rank
credible intervals overlap.

Key cautions:

- CI overlap is a **conservative** test — "two subjects can have overlapping rank CIs and
  still pairwise-dominate at well above the 95% level."
- What drives rank stability is the **gap between policies**, not absolute variance.
  Policies 0.1σ apart swap ranks across seeds; 3σ apart do not.
- **Crowded interior regions are unstable**; extreme ranks are stable.
- For borderline calls, **pairwise dominance probability `P(θᵢ > θⱼ)`** with multiple-
  comparison correction beats CI overlap.

**Applied here [MEASURED]:** ranks 23-25 (`team-andrew-fox`) differ by 0.33 PCS across three
submissions; ranks 47-48 (`team-vt`) by 0.26. Those are noise. Chasing single-digit PCS
gains is not a strategy — the mid-field is exactly the crowded region the docs warn about.

---

## 8. Local evaluation will mislead you

The docs' benchmark-compression section is a warning, not a recipe **[DOCS]**. Subset methods
(tinyBenchmarks, DISCO) achieve "80 to 99 percent" cost savings, but:

- They "break when evaluating models stronger than the calibration pool" — the
  **extrapolation frontier** problem, described as "fundamentally unsolved."
- Those methods target benchmarks of 10³-10⁵ items; navtest's ~1485 scenes are well below
  that range.

So a local subset tells you about *failures*, not about *rank*. Use local runs to hunt zeros
— collisions, off-road, incompletions — not to predict PCS. Your PCS depends on the other
58 submissions and cannot be computed locally at all.

---

## 9. What this implies for strategy

Ordered by expected payoff:

1. **Target ~80-85% of reference progress, not 100%.** The scene score saturates at
   `progress_clipped_rel = 0.8` (§3). Everything above that earns exactly zero additional
   score while strictly increasing collision and corridor-exit risk. This is the clearest
   free win on the board and it is a config/planner change, not a model change.
2. **Eliminate zeros.** Exactly three conditions zero a scene: `collision_at_fault`,
   `offroad`, `left_corridor_laterally` (§3). Point masses in the likelihood, not merely low
   scores. Engineering problem — guardrails, fallbacks, conservative defaults.
3. **Use `dist_to_gt` as a passivity alarm, not a target.** It correlates strongly with PCS
   (Spearman +0.95 within `opendrivelab-org`'s 17-submission grid), because a policy that
   maneuvers deviates laterally and a passive lane-follower does not. If yours sits near
   0.2 — where our starter driver is — you are lane-following, not driving. Do **not**
   inject deviation to game it: that triggers `left_corridor_laterally` and zeroes scenes.
4. **Beat 1000 before anything else.** That's the do-nothing anchor. Three teams are sitting
   on it having submitted the unmodified starter kit.
5. **Consistency over peak performance.** Ability is estimated across all routes; one
   catastrophic route is a zero from a separate branch and cannot be averaged away.
6. **Never regress an easy scene to win a hard one.** The model punishes stumbling on routes
   the field passes harder than it rewards passing routes the field fails (§1). Gate every
   change on **zero-rate**, not mean score.
7. **Make the policy deterministic.** Sampling variance produces exactly the failure the
   asymmetry punishes most. PAI ranks 2-3 are `baseline-k5-medoid` and `-deterministic-bas`.
8. **Ignore sub-1-point gaps.** Mid-field ordering is statistically unstable, and the docs
   note the ranking shifts under hyper-parameters and random seed alone.
9. **Expect diminishing returns near 1721.** The ceiling is already reached by two teams.

**Revised target [MEASURED 2026-08-30].** The "1000 → 1600" framing above is obsolete: stock
VaVAM already scores **1590.36** with no tuning (rank 6). The real contest is the **~130-point
band from 1590 to the ~1721 ceiling**, and every published technique in the field fits inside
it. Two calibration points for what that buys:

- `symphi`'s `gain105` reaches 1667.51 — **+77** over stock, from output shaping alone.
- `magma`'s `v4EMA` sits at 1587.83 — **−2.5 *below* stock**. Their EMA smoothing made things
  slightly worse.

That second one is the more useful lesson: **tuning is not monotonically helpful**, and with
~5 submissions you cannot discover that from the leaderboard. Validate locally against
`scene_score` before spending a submission.

---

## 10. Which base model — the case for VaVAM [SOURCE + MEASURED]

§9 says what to optimise. This says what to start from. The conclusion: **VaVAM, and the fit
is unusually good on the nuPlan track specifically** — two of the four reasons do not apply
to PAI at all.

### 10.0 ✅ Validated in production [MEASURED 2026-08-30]

This section was written as an argument. It has now been tested:

```
team-lucifer / vavam-stock-20260829
PCS 1590.36   avgDist 1.621   d2gt 3.05   →  rank 6 of 19 teams
```

**Unmodified checkpoint, no tuning, no output shaping.** For context in the same pull:

| | PCS | |
|---|---|---|
| Ceiling (na-la, metamon) | 1720.72 | tied, saturated |
| `symphi` `vavam-gain105-v1` | 1667.51 | VaVAM + shaping |
| `host/policy1` | 1600.00 | organizer reference |
| **stock VaVAM (us)** | **1590.36** | **no work** |
| `magma` `v4EMA` | 1587.83 | tuned — *below* stock |
| stock starter kit | ~1000 | do-nothing baseline |

Three things this settles:

1. **The predicted fit was real.** Stock VaVAM lands within 10 points of the organizer's own
   reference policy, from a checkpoint download.
2. **`d2gt` = 3.05 confirms §4's passivity diagnostic.** Stock VaVAM sits in the same lateral-
   deviation band as the leaders (3.03–3.48), not the passive floor (0.15–0.23). It is
   actively maneuvering out of the box.
3. **`magma`'s tuned `v4EMA` scores *below* stock VaVAM.** EMA smoothing was a net negative.
   Tuning is not monotonically helpful — see §9.

### 10.1 It matches the API socket with no adapter

The driver contract (`src/grpc/alpasim_grpc/v0/egodriver.proto`) delivers exactly:

| RPC | Payload |
|---|---|
| `submit_image_observation` | camera bytes + `logical_id` |
| `submit_egomotion_observation` | ego poses + dynamic states |
| `submit_route` | waypoints in rig frame |
| `submit_recording_ground_truth` | **disabled** — `send_recording_ground_truth: false` |

And critically, what it does **not** deliver: **no vectorized map, no lane graph, no agent
tracks, no ground truth.** Perception is the contestant's problem.

VaVAM is camera-native end-to-end — images in, trajectory out. Nothing to build in front
of it.

### 10.2 Pinhole-native — 546 lines of the sample are dead weight on nuPlan

From `e2e_challenge/sample_submission_vavam/README.md`:

> "The driver uses `camera_front_wide_120fov`, **rectifies f-theta images to the
> NuScenes-style pinhole view expected by VAVAM**"

VaVAM was trained on **nuScenes-style pinhole** imagery. PAI ships f-theta fisheye, so the
sample carries `rectification.py` — **546 lines, the largest file in the submission** —
purely to undistort.

**The nuPlan track ships 8 pinhole cameras natively.** That module is skipped entirely: no
remap grids, no interpolation loss, no per-frame CPU cost, 546 fewer lines of failure
surface. VaVAM's training format *is* this track's format.

### 10.3 2 Hz native — matches the nuPlan control loop exactly

From `vavam_challenge/trajectory.py`:

> "Between inferences we hand the controller the *same* cached path, just shorter: each
> Drive call samples the cached plan on a grid fixed to the plan's own clock"

VaVAM infers at **2 Hz**. PAI drives at **10 Hz**, so the sample infers at 2 Hz and serves
the intervening four `Drive` calls from cache — accepting up to 400 ms of plan staleness.

**nuPlan drives at 2 Hz** (`control_timestep_us: 500_000`). One inference per `Drive` call,
zero staleness, 5× fewer forward passes per scene. The latency pressure that pushed rank 2
to CUDA graphs is much weaker here.

### 10.4 Video pretraining buys closed-loop robustness

The deepest reason, and it explains the leaderboard's shape.

MTGS renders **novel viewpoints**. The moment a policy deviates from the logged path it sees
frames no camera ever captured. Models trained open-loop on logged frames have only seen
on-trajectory data and degrade precisely when it matters — and errors compound over a
rollout.

VaVAM's base (VaViM) is pretrained to **predict future video**, so it has learned scene
dynamics rather than a frame→action mapping, and extrapolates to unseen viewpoints far
better. That is exactly the capability closed-loop simulation demands.

**[MEASURED]** — the data agrees. `opendrivelab-org` swept **17** NAVSIM-style architectures
(`gtrs-dense` × {resnet, vov} × {reward, expert} × v2-v5, plus `ltf`, `diffusiondrive`) and
topped out at **1377**. VaVAM variants occupy **1587-1731**. A systematic architecture search
by the reference-implementation team lost to output-shaping on a video model.

### 10.5 The tuning surface is small

```
driver.py          606 lines
rectification.py   546 lines   ← skipped on nuPlan
trajectory.py      200 lines   ← plan caching, 5 s horizon
vavam_policy.py    162 lines   ← the model wrapper
```

**162 lines** is the policy surface. `symphi`'s 380-point swing between `vavam-brake-v1`
(1290.5) and `vavam-gain105-v1` (1669.8) lives in roughly that file — same base model, same
public checkpoint, different output shaping.

Checkpoints are public and shared across the field: `VAM_width_1024_pretrained_139k.pt` +
`VQ_ds16_16384_llamagen_encoder.jit`. PAI's rank 3 tag is literally
`vavam-b-139k-deterministic-bas` **[MEASURED]** — the same 139k weights.

### 10.6 An unexploited edge

The sample consumes **one** camera (front). The nuPlan track provides **eight** — `CAM_F0`,
`CAM_L0/L1/L2`, `CAM_R0/R1/R2`, `CAM_B0`. Every stock-VaVAM submission is discarding seven
feeds, which matters most for the failure modes that zero a scene: `left_corridor_laterally`
and side collisions (§3). Real headroom, but a model change rather than a config change.

### 10.7 Why not CarPlanner (or other nuPlan planners)

Recorded because the checkpoints are locally available and it is a tempting shortcut.

CarPlanner is a **privileged vector planner** — it consumes a lane graph, tracked object
boxes and ego state, i.e. nuPlan's assumption that perception is *given*. Per §10.1 this API
provides none of that. Using it would require building 3D detection plus online mapping from
8 camera feeds inside the ~0.1 s budget — the hardest and most expensive part of an AV stack,
bolted in front of a planner designed never to need it.

The checkpoints would not transfer either: weights trained on ground-truth vector inputs go
off-distribution when fed your own perception outputs, so retraining would be required
*after* building the perception stack. Separately, that work is on nuPlan v1.1 train splits
(Vegas/Pittsburgh/Singapore), disjoint from navtest.

**Verdict: relevant experience, not a reusable component.**

### 10.8 Caveat

Rank 1 (`na-la`, tag `sub1`) carries **no VaVAM marker** and is tied at the ceiling
**[MEASURED]**. Something else also saturates; the tag is opaque, so VaVAM is a
well-evidenced path, not the only one.

---

## 11. What we still don't know

- **The exact θ → PCS transform.** Two anchors (1000, 1600) are measured; the docs give no
  formula. Enough to interpret the scale, not to compute your own score.
- **Per-route `αₙ` and `βₙ`.** Not published. You cannot see which scenes discriminate, so
  you cannot target them.
- **The 1731.23 tie.** Read here as ZOIB saturation; an explicit cap is not ruled out.
- **How the two metrics combine.** PCS appears to be ZOIB-only with distance as tiebreaker,
  inferred from the rank-1/2 tie, not documented.
- **`legacy_score`** duplicates `avg_dist_between_incidents_at_fault` on every row
  **[MEASURED]** — the scoring changed at some point and the old metric is retained.

## 12. One caveat that overrides everything

The nuPlan dataset is **provisional**. Per the challenge page: "The nuPlan leaderboard will be
cleared and each team's best submission will be resubmitted by the organizers" when updated
data lands. Route difficulties `βₙ` and discriminations `αₙ` are estimated *from the current
scene set* — a new scene set re-fits every latent parameter. **Do not overfit to today's
ranking.**

---

### Sources

- DriveIRT docs: [index](https://ln2697.github.io/navhard-leaderboard-2/docs/) ·
  [§2 efficient evaluation](https://ln2697.github.io/navhard-leaderboard-2/docs/preliminary/02_efficient_evaluation.html) ·
  [§3 ranking](https://ln2697.github.io/navhard-leaderboard-2/docs/preliminary/03_ranking.html) ·
  [§4 mathematical models](https://ln2697.github.io/navhard-leaderboard-2/docs/preliminary/04_mathematical_models.html) ·
  [§8 ranking spread](https://ln2697.github.io/navhard-leaderboard-2/docs/preliminary/08_ranking_uncertainty_quantification.html) ·
  [§9 unbounded response](https://ln2697.github.io/navhard-leaderboard-2/docs/preliminary/09_unbounded_response.html) ·
  [§10 zero/one inflation](https://ln2697.github.io/navhard-leaderboard-2/docs/preliminary/10_zero_inflated_model.html)
- Live data: `leaderboard/*.json`, fetched 2026-08-29 via `fetch-leaderboard.py`
- Local scoring code: `alpasim/src/eval/.../scene_score.py`
