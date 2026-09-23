# Stepwise all-city frozen-Cosmos pilot — 2026-09-21

User authorization: "ok run these tests stepwise", following explicit confirmation
of the 19 training / 7 validation whole-log split allowing shared recording dates.
This is a local pilot, not a leaderboard submission or eligibility certificate.

## Stage 1 — SSD staging: passed

- SSD root: `/media/skr/storage/cosmos3-allcity-pilot-20260921`.
- 9,359 captured images, 26 selected metadata DBs and complete local checkpoint.
- 13,819,829,456 bytes copied (12.87 GiB), each copy SHA-256 verified.
- `staging-receipt.json` records every file, original and destination, size and hash.
- Seagate originals are retained. No model/data downloads were needed.
- `pilot-split.json` pins the new acquisition manifest, protected split hash,
  explicit authorization and deterministic SHA256 log selection seed 20260921.
- Boston 11/3, Pittsburgh 6/2, Singapore 1/1, Vegas 1/1 train/validation logs.
- The reader still rejects all protected public city/dates and source logs,
  official-validation logs, quarantined mini logs and cross-role log overlap.
  Shared dates are permitted only by the newly approved explicit split contract,
  and reported in validation output. Historical split manifests remain unchanged.
- 17 reader tests and 15 runner tests passed, including shared-date authorization
  and rejection checks. Synthetic test updates are not real pilot training.

## Stage 2 — CPU aligned export and independent reader: passed

- tmux session: `cosmos_export_v3_20260921`.
- Log: `/tmp/cosmos-export-v3-20260921.log`.
- Output: SSD root `/export-v3`.
- First attempt stopped after 1,798 examples at an empty MAP-route extension.
  The exporter now rejects that verified invalid-route case. The second attempt
  exposed a noncontiguous-coordinate bug in the new rejection check; it now uses
  the same runtime pose with a contiguous position array. All 16 exporter tests
  pass, including array layout and propagation of unrelated errors. Both failed
  outputs (`export`, `export-v2`) are retained and are not training datasets.
- Caps: 5,000 train / 1,000 validation examples; log quotas and real alignment
  checks determine actual counts. No duplicated examples to meet quotas.
- Three observed frames at approximately -1, -0.5, 0 seconds; causal state,
  sparse AlpaSim MAP route with 40m offset, complete 0.1–4s expert targets.
- A new independent reader pass is required after `export-v3/dataset.json` exists.
- Export completed with 2,666 training / 631 validation examples across all
  19 / 7 approved source logs. These are overlapping windows, not 3,297 scenes.
- Accepted examples by city:

  | City | Train | Validation |
  | --- | ---: | ---: |
  | Boston | 1,449 | 195 |
  | Pittsburgh | 1,026 | 220 |
  | Singapore | 125 | 73 |
  | Vegas | 66 | 143 |

- 130 attempted candidates were rejected by alignment/route checks, including
  exactly one verified empty route extension. Unvisited candidates after a log
  quota is met are not rejection failures. City coverage is uneven, especially
  Vegas; this is a pilot, not a balanced final training corpus.
- Latest combined regression suite: **49 passed**; Ruff checks passed.
- Independent reader passed all 3,297 examples and decoded/hash-checked their
  7,188 unique camera images. Source logs are disjoint between roles; recording
  dates are shared as explicitly approved. Protected source logs remain excluded.

## Stage 3 — engineering gate: passed

tmux `cosmos_smoke_20260921`; log `/tmp/cosmos-smoke-20260921.log`.

`python -m cosmos3.run_all_city_gates` validates the full exported corpus and
creates a fixed 16-example smoke subset: two examples for each city/role pair.
It then caches frozen features and trains matched visual/state-route heads with
10 epochs, batch 4 and no more than 100 updates per arm, verifying reload parity.
The generator and VAE never enter the head optimizer; no simulator is launched.

Files when complete: `data-validation.json`, `smoke-cache/cache.json`,
`smoke-fit/COMPLETED.json`, `SMOKE-PASSED.json` under the SSD root.

- 16 real examples, 8 train / 8 validation, 48 unique images: finite features.
- Full checkpoint loaded locally; frozen generator/VAE parameter versions
  unchanged and no backbone gradients. Peak sampled process VRAM 8.113 GiB.
- Feature stage including checkpoint load: 10.55 seconds (load: 7.94 seconds).
- Each 815,235-parameter head completed 20 updates with changed weights.
- Both best/final head checkpoints reload with exactly zero output difference.
- This tiny smoke run establishes engineering operation only. Its validation
  metrics are selection-biased and unstable: the final epoch was worse than
  the selected best epoch. Do not treat them as evidence of generalization.

## Stage 4 — bounded pilot: frozen feature cache passed

- tmux `cosmos_cache_pilot_20260921`.
- Log `/tmp/cosmos-cache-pilot-20260921.log`.
- Output SSD root `/full-cache`; 1,800-second feature-stage cap.
- Uses the validated `export-v3` corpus. No gradients or model updates occur
  during caching. Full matched-head fit must wait for successful cache checks.
- Completed 7,188/7,188 unique images in 346.80 seconds, including 7.89 seconds
  checkpoint loading. Mean image encoding operation: 46.89 ms (not end-to-end
  policy latency or competition throughput). Frozen parameter versions unchanged.
- Peak sampled model-process VRAM: 8.113 GiB; peak torch allocated: 7.763 GiB.

## Stage 5 — bounded matched-head pilot: completed

- tmux `cosmos_head_pilot_20260921`.
- Log `/tmp/cosmos-head-pilot-20260921.log`.
- Output SSD root `/pilot-fit`; 1,800-second cap per training arm.
- 2,666 train / 631 validation examples, 10 epochs, batch 32, 2,000-update cap
  per arm (840 updates expected if all epochs finish). Matched initial weights
  and batch order; optimizer updates only the head. Constant-velocity baseline
  also measured. Validation selects checkpoints and is not an unbiased test.
- Both arms completed 840 optimizer updates with identical initialization and
  batch order. Backbone not loaded during fitting. Best/final checkpoints for
  both arms reload with exactly zero prediction difference.
- Total fit-stage time: 76.27 seconds (visual arm 62.63s, state/route arm 13.08s;
  includes their validation and reload checks, excludes pre-fit data validation).
- Selected visual checkpoint: epoch 8 / step 672. State/route: epoch 6 / step 504.

### Validation results (631 examples; lower is better)

| Policy | Mean trajectory error / ADE (m) | 4s endpoint error / FDE (m) | Lateral MAE (m) | Heading MAE (deg) | Initial velocity error (m/s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Constant velocity | 1.1983 | 3.3036 | 0.3167 | 2.1221 | 0.0000 |
| Untrained visual head, same frozen Cosmos | 2.5738 | 3.7406 | 0.8477 | 61.4844 | 6.3781 |
| Trained state/route-only control, selected checkpoint | 1.1497 | 3.0756 | 0.2777 | 2.2225 | 1.5898 |
| Trained frozen-Cosmos visual head, selected checkpoint | 1.1923 | 3.0085 | 0.2863 | 2.6689 | 3.3221 |

Initial velocity error compares the first predicted displacement divided by 0.1s
with the causal current velocity. It measures prediction continuity, not an
independent ground-truth velocity score; constant velocity is zero by construction.
The untrained head is a random driving decoder, **not the native Cosmos policy**.

| Validation city | Examples | Cosmos ADE (m) | State/route ADE (m) | Constant-velocity ADE (m) |
| --- | ---: | ---: | ---: | ---: |
| Boston | 195 | 1.1447 | 1.1334 | 1.2020 |
| Pittsburgh | 220 | 1.2214 | 1.2058 | 1.2952 |
| Singapore | 73 | 1.4565 | 1.3702 | 1.4657 |
| Vegas | 143 | 1.0777 | 0.9731 | 0.9075 |

Conclusion: the pipeline runs and the head learns relative to its initialization,
but **visual added value is not demonstrated**. State/route-only has lower ADE
in all four validation cities. Cosmos improves FDE in aggregate, but only barely
beats constant velocity on ADE and has worse initial-velocity consistency.
These are single-seed, validation-selected open-loop results on overlapping
windows from seven logs with shared recording dates; no significance or
leaderboard generalization claim is justified.

The epoch-10 visual checkpoint has validation ADE 1.2608m (worse than the selected
epoch-8 checkpoint); both are retained. No hyperparameter search was performed.

Artifacts under the SSD root:

- `pilot-fit/COMPLETED.json`, `pilot-fit/protocol.json`.
- `pilot-fit/cosmos/metrics.json`, `pilot-fit/cosmos/best.safetensors`.
- `pilot-fit/state_route_only/metrics.json`, corresponding head checkpoints.
- `pilot-fit/constant-velocity.json`; per-arm update journals and reload hashes.

## Later stages

Stop before the full simulator benchmark. Next review the predicted first-step
continuity and visual-feature usefulness using this cached pilot. Do not call a
longer training run or a simulator score a foregone improvement. A deployment
path additionally needs a trained-head driver
adapter: the existing `compat_driver.py` calls the old native action generator,
not this learned head, and must not be used to claim evaluation of the new head.
The bounded pilot has completed. No simulator or 400-scene benchmark has run.

The earlier all-city plan remains at [ALL-CITY-PILOT-PLAN.md](ALL-CITY-PILOT-PLAN.md).
