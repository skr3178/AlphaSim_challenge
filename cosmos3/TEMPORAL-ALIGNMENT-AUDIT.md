# Later-frame expert-alignment audit — 2026-09-19

## Conclusion

**41 later observations pass the fixed temporal/alignment/data checks.** Each has three decoded front-camera observations at t−1.0, t−0.5 and t, a valid causal ego state and route, and a finite four-second recorded expert future. They come from 41 scenes, 12 source logs and all four cities.

This corrects the claim that the saved logs contain no usable temporal context. A small **local-only temporal pilot** can be prepared without another camera download. It does not establish a large, independent training corpus, organizer permission to train on these scenes, or a Cosmos driving advantage.

No real model inference, optimizer updates, simulator evaluation, rendering or downloads ran. No new scenes were assigned to training. The existing exporter still rejects post-priming samples; its safety/authorization gates were not relaxed.

## Scope and fixed protocol

Source: `/media/skr/storage/alpasim-runs/confirm400-mup-g100/rollouts`.

- Exactly one saved rollout for each of the 400 development scenes; no protected validation/holdout scenes.
- **4,000 Drive requests**, including **3,600 after the expert-priming interval**.
- All **4,400 front images decoded successfully**. Images and model-training arrays were not exported.
- Observations, received ego poses and route messages accumulated in ASL event order; later-received data cannot fill earlier model inputs.
- History selection uses the existing offsets and 100 ms maximum image age, with no duplicated or future frames substituted.
- Pose limits fixed before the full audit: **0.10 m translation / 0.01 rad rotation**. At every selected frame end, compare observed/true/expert rear-axle poses; also require true/expert agreement at exposure starts and ends. These are boundary checks, not a per-pixel shutter-motion validation.
- Require all **40 future targets at 0.1–4.0 s**; no clipping, extrapolation, shortening or shifting of the horizon.
- Extra diagnostic motion limits, also fixed before the full audit: **0.50 m/s** XY velocity difference and **0.05 rad/s** yaw-rate difference against expert motion over the same backward interval. These are conservative audit thresholds, not proven training tolerances. Expert-derived state is used only for this diagnostic, never supplied as a model input.
- Require current calibration presence/parseable pose, control-query coverage, a causal route anchor and the existing finite-prefix/trailing-NaN route contract.

## Cumulative result

Each row below adds its requirement to all preceding rows.

| Requirement | Remaining observations | Distinct scenes |
| --- | ---: | ---: |
| After priming | 3,600 | 400 |
| Full three-frame camera history | 3,200 | 400 |
| Full four-second recorded expert future | 400 | 400 |
| Valid causal state, route and calibration inputs | 398 | 398 |
| All history poses aligned to the expert | **41** | **41** |
| Exposure starts/ends also aligned | **41** | **41** |
| Backward-interval motion also consistent | **41** | **41** |

Of the 357 observations rejected at the history-pose stage, 292 exceeded the position limit and 253 exceeded the rotation limit; these counts overlap.

### Why the four-second horizon matters

Every saved expert reference ends at **5.500 s**. Full camera history first exists at **1.017 s**. That anchor still has four seconds of expert future, but the next anchor at **1.517 s** needs targets through **5.517 s**, which the ASL does not contain.

Consequently all 41 passing observations are anchored at **1.017 s**, with images at **0.017, 0.517 and 1.017 s**. This is one useful temporal example per passing scene, not a long training sequence.

Two additional later windows pass history-pose alignment at 1.517 s but lack the required future horizon. Their targets were not extrapolated by 17 ms to manufacture acceptance. Recovering longer verified expert labels from another original source would be separate work. Changing the prediction horizon would change the experiment, not merely fix a missing file.

## Diversity and leakage implications

| City | Passing temporal observations |
| --- | ---: |
| Vegas | 16 |
| Boston | 7 |
| Pittsburgh | 14 |
| Singapore | 4 |

There are 41 distinct image-triplet hashes. This is exact-byte triplet uniqueness, **not** proof of independent roads, non-overlapping source clips, or independent statistical examples.

Speed at the anchor is not limited to stopped traffic:

| Causal observed speed | Passing observations |
| --- | ---: |
| Below 0.5 m/s | 7 |
| 0.5–2 m/s | 3 |
| 2–8 m/s | 20 |
| At least 8 m/s | 11 |

Median speed is 4.283 m/s; range 0.080–12.290 m/s. Passing windows have maximum history position mismatch 0.0980 m and maximum rotation mismatch 0.009992 rad. Pose proximity alone still does not prove identical surrounding-agent state, unobstructed semantics, physically verified calibration, recovery supervision or safe control.

- **9 candidates** are in the **four already training-exposed Cosmos source logs**. They are not necessarily the original ten scene IDs. They could support a separately authorized tiny temporal pilot without widening the set of training-exposed logs.
- **32 candidates** are in **eight other development logs**. Keep them out of fitting if used for a log-disjoint comparison. They are development diagnostics, not a new sealed holdout; this audit and prior experiments already inform design decisions.
- All four Singapore candidates fall in an already training-exposed source log. The 32 other-log candidates therefore do **not** provide independent Singapore validation.
- Public-navtest training eligibility remains unresolved. Availability and alignment do not turn these public-evaluation scenes into competition-approved training data. No new permission record was created.
- Filtering for closeness to the expert preferentially keeps easy/well-followed states and does not supply recovery-from-drift examples.

## Artifacts and verification

Artifacts: [temporal-alignment-audit-20260919](artifacts/temporal-alignment-audit-20260919).

- [Fixed protocol](artifacts/temporal-alignment-audit-20260919/protocol.json).
- [Summary, source-log counts and rejection totals](artifacts/temporal-alignment-audit-20260919/summary.json).
- [All 4,000 per-request diagnostics](artifacts/temporal-alignment-audit-20260919/windows.json); filter `candidate: true` for the 41 passing windows. These are audit records, not a loadable training dataset.
- [Source ASL paths and SHA-256 hashes](artifacts/temporal-alignment-audit-20260919/sources.json).
- [Exact executed audit source](artifacts/temporal-alignment-audit-20260919/audit_source.py), whose hash matches `protocol.json`. The working source was subsequently Black-formatted without behavioral changes.

The public manifest hash remained `a2a150d4eb139db0cbfa7d1cfa37a8eff701db34fff8264034c0433ab2f36b64`. Source ASL size/mtime checks found no changes during the audit.

**87 CPU tests passed**, including 14 new synthetic audit tests. Unit fixtures exercise only synthetic data and are not additional real training runs. New tests check temporal availability, future-frame exclusion, pose/heading mismatch, true-view mismatch, exposure alignment, full-target coverage, causal state, invalid/future routes and angle wrapping. Focused Ruff syntax/undefined-name checks and Black formatting checks passed; this is not a full-project lint claim.

## Recommended next step — not executed

Prepare a **separate, bounded local-only temporal export** using the nine candidates from already training-exposed logs. Require an explicit new manifest and the audit's post-priming alignment checks; do not globally disable the existing exporter's priming safeguard. Preserve the 32 other-log candidates for development comparison.

Then, only with a separately scoped test, compare a temporal Cosmos head against a matched state/route-only head and a single-frame variant. Nine training examples remain an engineering pilot, not enough evidence to justify a long fine-tuning run. Do not download additional footage merely to repeat this small feasibility check; broader training would still need an eligible, more varied and continuous corpus.
