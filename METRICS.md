# Metrics & abbreviations — AlpaSim nuPlan track

Reference sheet. What decides the score, what is only diagnostic, and what every piece of
shorthand in `archive/strategy.md` / `archive/RANKING.md` / `EVAL-RUNBOOK.md` / `SETUP-NOTES.md` means.

Written 2026-08-31. Sources: `scene_score.py` and the proto (repo), DriveIRT docs
(`navhard-docs/`), and the live leaderboard (`leaderboard/`).

---

## 1. The causal chain

```
YOU CONTROL                 →  PER-SCENE            →  AGGREGATION        →  PUBLISHED
progress_clipped_rel           scene_score ∈ [0,1]     IRT / ZOIB fit        PCS      ← ranks you
collision_at_fault             0 if any hard fail      θ, β, α estimated     avgDist  ← tiebreaker
offroad                        else min(p/0.8, 1)      jointly across        d2gt     ← NOT scored
left_corridor_laterally                                the whole field
gt_dist_traveled_m
```

The exact per-scene function (`src/eval/src/eval/aggregation/scene_score.py`, 97 lines):

```python
score = 0.0                                              # if ANY hard failure
      = min(clamp(progress_clipped_rel, 0, 1) / 0.8, 1)  # otherwise
      = 1.0                                              # if gt_dist_traveled_m < 5.0
```

**You cannot compute PCS locally**, even with all 1,485 scenes — it depends on every other
team's per-scene results. Locally you compute the *input*, never the output.

---

## 2. The four metrics that decide the outcome

| Rank | Metric | Why it dominates | Direction |
|---|---|---|---|
| **1** | **Zero-rate** — % of scenes hitting any of the 3 hard failures | Zeros are a *separate branch* of the likelihood, not merely low scores | ↓ minimise |
| **2** | **% of scenes below `progress_clipped_rel` = 0.8** | The only continuous term, and it **saturates at 0.8**. Above that, extra speed earns nothing and adds collision risk | ↓ minimise |
| **3** | **`avgDist`** | The tiebreaker — and the entire gap between the plateau (~1.6) and the ceiling (~3.1–3.4) | ↑ maximise |
| **4** | **Easy-scene regressions** | The asymmetry: failing a scene the field passes costs more than passing one it fails | zero tolerance |

**One line:** *stop crashing, clear 80 % progress, never regress an easy scene.*

### The three hard failures — nothing else zeroes a scene

`_hard_failure_reason()` checks, in order:

1. `collision_at_fault != 0`
2. `offroad != 0`
3. `left_corridor_laterally != 0` — leaving the corridor **sideways**. Driving past the end of
   the recording does **not** fail (handled by timestep truncation)

⚠ **Unresolved:** DriveIRT §10 also lists "scene incompletion" as a zero, but the local code
does not check it. See `archive/strategy.md` **B7** — untested, and the sources conflict.

---

## 3. Diagnostics — read these, don't optimise them

| Metric | Reads as | Our value |
|---|---|---|
| `wrong_lane` % | route-conditioning quality | 30–62 % per city (Boston worst) |
| `d2gt` | **passivity alarm.** ~0.2 = lane-following, ~3.0 = maneuvering | 3.05 |
| `min_distance_to_obstacle_m` | braking headroom | 3.2 m at front collisions |
| `min_distance_to_lane_boundary_m` | corridor-exit margin | — |
| `img_is_black` | render sanity — must be 0.0 | 0.0 ✅ |
| `duration_frac_20s` | completion proxy | — |
| `driver_drive_rpc_duration_mean_s` | latency — **unscored**, a throughput gate only | 0.0966 s |
| `collision_{front,lateral,rear}` | failure-mode breakdown | front 6–8 % |
| `progress` vs `progress_rel` vs `progress_clipped_rel` | raw ratio / relative / **the one scene_score uses** | 0.867 / 0.953 / **0.953** |

**Never optimise `d2gt`.** It correlates with PCS (Spearman +0.95 within one team's ablation
grid) because capable policies maneuver — but rank 1 has `d2gt` 0.98, *lower* than ours.
Injecting deviation triggers `left_corridor_laterally` and zeroes scenes.

---

## 4. Abbreviations

### Scoring

| Term | Meaning |
|---|---|
| **PCS** | **Policy Capability Score** — the ranking metric. A rescaling of IRT ability `θ` |
| **avgDist** | `avg_dist_between_incidents_at_fault` — km between at-fault incidents. The declared tiebreaker; unbounded, log-normal |
| **d2gt** | `dist_to_gt_trajectory` — **lateral** deviation from the logged path, metres. Present in the API, **absent from `score_columns`**, so invisible on the website |
| **ADS** | **Average Driving Score** — the naive per-route mean that DriveIRT explicitly **rejects** |
| **PDMS / EPDMS** | Predictive Driver Model Score — NAVSIM-lineage predecessors |
| **min_ADE** | minimum Average Displacement Error — PAI's scoring metric; computed on nuPlan runs but unused |
| **legacy_score** | exact duplicate of `avgDist` — the pre-PCS metric, retained for continuity |

### The statistical model

| Term | Meaning |
|---|---|
| **IRT** | **Item Response Theory** — policies are *subjects*, routes are *items*; the machinery used to score standardised exams |
| **MIRT** | Multidimensional IRT — DriveIRT §11. **Proposed, not deployed**; the live board is unidimensional |
| **ZOIB** | **Zero-and-One-Inflated Beta** — the response model. Confirmed by `metric_algorithm: "zoib"` on every leaderboard row |
| **θ** (theta) | **ability** of a policy — "how good subject *s* is". PCS is a rescaling of this |
| **β** (beta) | **difficulty** of a route — "how hard item *n* is" |
| **α** (alpha) | **discrimination** — "how sharply item *n* separates strong from weak". Why routes are not weighted equally |
| **g⁰, g¹** | ZOIB inflation gates — the point masses at 0 (catastrophic failure) and 1 (clean pass) |
| **Moving Baseline** | DriveIRT §1.3: your score changes when *others* submit. Measured — 17 of 18 teams moved with no resubmissions |
| **anchor** | `host/go_straight` = 1000.0 and `host/policy1` = 1600.0, fixed to full float precision. They pin the scale |

### Stack & environment

| Term | Meaning |
|---|---|
| **MTGS** | **Multi-Traversal Gaussian Splatting** — the nuPlan-track renderer |
| **NRE** | NVIDIA neural reconstruction — the PAI-track renderer |
| **PAI** | **Physical AI** — the other track (f-theta cameras, 10 Hz, internal scenes) |
| **VaViM / VaVAM** | the video model / the action model built on it — our base. Checkpoint `VAM_width_1024_pretrained_139k.pt` |
| **μP** | **maximal update parametrization** — the base-shape fix the sample drops. Our validated lever: 0.51 → 1.11 km at-fault |
| **navtest** | the 1,485-scene evaluation split (4 cities: Vegas 32 % / Boston 31 % / Pittsburgh 22 % / Singapore 15 %) |
| **shard** | `part0NN.tar.gz` — ~100 scenes each, 15 total, ~31 GB download / ~38 GB extracted |
| **sm_89 / sm_120** | CUDA compute capability — Ada (RTX 4090) / Blackwell (ours). The renderer builds for `8.9;9.0+PTX`; sm_120 works via PTX JIT |
| **direct-p5** | the official evaluation backend — AWS **p5** = 8 × H100 80 GB. GPUs 0–3 renderer, 4–7 driver |
| **ECR** | AWS Elastic Container Registry — where a submission image is pushed. Specific tag only, never `latest` |

### Our internal shorthand

| Term | Meaning |
|---|---|
| **T0 / T1 / T2 / T3** | eval ladder — smoke (1–20) / screen (100, ~7 min) / confirm (400, ~28 min) / official (1,485) |
| **R1 / R2 / R3** | asymmetry rules — variance is the enemy · gate on zero-rate not mean · never regress an easy scene |
| **G1–G4** | goals — beat 1600 · take rank 3 · reach the ceiling · win outright |
| **A / B / C / D** | backlog groups — next submission / policy levers / tooling / housekeeping |
| **N· / X·** | proven-negative (don't) / off-limits (won't) |
| **[M] [L] [D] [I] [S]** | evidence — official board / local measurement / DriveIRT docs / competitor tag / repo source |
| **dev_fast2** | our fast preset — CAM_F0 only, video off, 2 rollouts in one stack, 4.2 s/scene |
| **noise floor** | ±3 at-fault incidents per 300 scenes between identical configs. Effects below ~5/300 are unresolvable without seeds |

---

## 5. Reference values (2026-08-31)

| | Value |
|---|---|
| Our position | **PCS 1592, #8 of 20** — stock B, one submission |
| Ceiling | ~1721, two teams **tied to 17 significant figures** (saturated) |
| Organizer reference | `host/policy1` = **1600.00** exactly, unchanged across re-fits |
| Do-nothing baseline | `host/go_straight` = **1000.00** exactly |
| Progress saturation | `progress_clipped_rel` ≥ **0.8** → scene score 1.0 |
| Short-scene override | `gt_dist_traveled_m` < **5.0 m** → scene score 1.0 |
| VRAM cap | **16 GiB per replica** (4 replicas × 16 = 64 of an 80 GB H100) |
| Latency | target 0.1 s/`Drive`; **unscored** — enforced as a per-track wall-time budget. ~20× headroom measured |
| Submissions | 5/month, dropping to 3. Month boundary is **UTC** |
