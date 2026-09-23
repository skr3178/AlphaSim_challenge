# Plan B — AlpaSim model, dataset and targeted-fix strategy

Saved: 2026-09-18. Workspace: `/home/skr/Downloads/alpasim_challenge`.

**Execution update, 2026-09-18 14:32 IST:** the user subsequently authorized all
1,085 missing public scene assets to be downloaded to Seagate. The detached tmux
job has started; see [download status and controls](evaluation/downloads/2026-09-18-seagate/README.md).
This supersedes the pending-download decision below. The v2 split, runtime
integration, model experiments and submissions remain pending. Historical status
sections below describe the state when this plan was originally saved.

## 1. Objective and working decisions

Build a stronger nuPlan-track submission by improving the reliability of local
comparisons first, then making one evidence-backed model/adapter change at a time.
The goal is robust closed-loop driving, not maximizing an unreliable local score
projection or assuming that a world-model architecture must outperform imitation
learning.

Agreed direction:

- **Primary development model: the downloaded Py123D Garage checkpoint.** Use its
  unchanged implementation as the starting point, not an automatic scored submission.
- **Comparison/control: unchanged WA-JEPA S2**, preserving the submitted model,
  adapter and inference configuration. Retain its demonstrated strengths rather
  than discarding it on architectural grounds.
- **First fix: diversify and validate the local scene set.** The next proposed
  revision is city/date-aware, not merely a larger collection of neighboring clips.
- **Then align the evaluator and execution checks**, before interpreting new
  paired model results.
- **Then test one narrow change at a time.** Full training from scratch, broad
  parameter sweeps and an unvalidated ensemble are not the first steps.

This document records a plan, not authorization to execute every step. Do not
start downloads, model inference, simulation/evaluation, training, image pushes
or submissions without the relevant go-ahead. Saving this file launches none.

This plan supersedes conflicting recommendations in older notes: VaVAM is not
the current primary direction; a blanket trajectory sanitizer is not a confirmed
fix; and neither local mean score nor trajectory distance is a proven predictor
of private PCS.

## 2. What the evidence does and does not establish

The historical WA-JEPA S2 local mean scene score was about 0.9247 on 400 scenes,
versus about 0.7748 in its earlier official evaluation. The downloaded Py123D
checkpoint scored about 0.8420 locally, while associated Py123D board entries
performed better officially. These observations motivate a better validation
design; they do not isolate one cause or prove exact checkpoint/image identity
between our local run and someone else's board entry.

Separate three possible contributors:

1. **Scene selection:** the old sample has limited log/date coverage and has
   repeatedly informed our model and adapter decisions.
2. **Evaluation implementation:** subsequent upstream off-road fixes affect
   geometry loading and scoring. The active local runtime has not yet been
   migrated. Those later fixes do not, by themselves, explain the original gap.
3. **Policy execution and adaptation:** preprocessing, route conditioning,
   timestamps, batching, fallback behavior and controller tracking can change
   what actually gets evaluated.

Do not infer private geographic/date/traffic composition from a rollout count,
leaderboard ordering or a strong go-straight baseline. In particular, 1,000
rollouts does not establish 1,000 distinct scenes. A broader public test remains
a proxy, not a reconstruction of the private suite.

## 3. Model strategy

### Primary: Py123D Garage latent TransFuser

Local checkpoint:
`py123d/checkpoints/resnet34_v0.1.0/model_0014.pth`.
Retain its accompanying `config.yaml` and nuPlan `sensor_rig_0.yaml`; pin hashes
of these files and the eventual container digest for every comparison.

The released model card describes:

- camera-only latent TransFuser with a ResNet-34 image backbone;
- three camera views, ego velocity and a route target point 45 m ahead;
- eight future poses with yaw, at 0.5-second spacing over four seconds;
- public nuPlan and Physical AI AV train/validation data;
- perception pretraining with BEV-semantic and object-detection supervision,
  followed by imitation-based planning posttraining.

These are useful task-specific design choices, not proof of universal superiority
or access to private evaluation annotations. Its BEV/detection heads learn from
labels during training; they do not receive ground-truth road/object labels as
ordinary challenge-time inputs.

First establish input-contract and execution correctness for the unchanged
checkpoint. Resubmitting an organizer/reference checkpoint unchanged is not our
default winning strategy. Our prospective contribution must be a measured
improvement, with a clear ablation against that baseline.

### Control and alternatives

- Keep WA-JEPA S2 unchanged for the first comparison on the corrected setup.
- Keep WA-JEPA S4/S12 as conditional inference-budget candidates. Historical
  S12 evidence covers only 100 completed scenes; the 400-scene run was incomplete.
  Neither its generalization benefit nor official throughput is established.
- Keep VaVAM as a reserve, not the next automatic submission or another broad
  tuning campaign.
- Consider targeted fine-tuning only after a reproducible failure and a suitable
  training signal have been identified. Use separate training data; do not train
  on the reserved evaluation clips/logs/dates.

Historical `py123d/MODEL.md` and `py123d/FINDINGS.md` contain stale rank claims and
overconfident transfer conclusions. Prefer the actual checkpoint model card,
config, saved outputs and later review corrections. A matching epoch/tag alone
does not authenticate someone else's complete submission artifact.

## 4. Dataset strategy: diversify collection conditions, not just clip count

### Verified coverage

The old 400 are **not all from one date**. They contain 100 scenes per city,
but only one collection date per city:

| City | Date in the old 400 | Other dates in public navtest |
|---|---|---|
| Las Vegas | 2021-05-25 | 2021-06-03, 2021-06-28 |
| Boston | 2021-09-09 | 2021-08-30, 2021-09-29 |
| Pittsburgh | 2021-09-16 | 2021-08-16: only 12 scenes from one log |
| Singapore | 2021-10-06 | None |

Old sample: **400 scenes, 13 source logs, four dates**.
Full public navtest: **1,485 scenes, 44 source logs, nine dates**.
There are **902 scenes on 31 locally unused logs**, including **630 scenes on
five dates absent from the old sample**. Different logs can still share roads or
collection conditions; a new date is also not a guarantee of different behavior.

"Unused/unseen" here refers to our local development/evaluation history. It is
not a claim that a pretrained model never encountered related data in training.

### Existing v1 setup — preserve as an immutable record

| Suite | Scenes | Logs | Status |
|---|---:|---:|---|
| Development | 400 | 13 | Existing assets; regression/development use |
| Compact validation | 150 | 19 | Selected; rendering assets missing |
| Validation pool | 589 | 19 | Includes compact validation |
| Holdout | 313 | 12 | Separate logs; rendering assets missing |
| Extra clips on exposed logs | 183 | 7 | Not independent validation |

These live in [evaluation/public-suite.json](evaluation/public-suite.json), with
Hydra configs and scene lists under `evaluation/`. The 150-scene selection spans
six dates, but is log-balanced rather than date-balanced. Validation and holdout
share dates, although they do not share source logs. Do not call v1 date-disjoint.

### Proposed v2 — design before downloading or observing new model scores

1. **Keep the old 400 for regression.** Do not relabel them as fresh validation
   or include their repeated tuning history in an independence claim.
2. **Reserve the final holdout first.** Where public coverage allows, reserve
   whole previously unused city/date groups, including all their source logs.
   A date-held-out stress test must stay out of tuning; it cannot simultaneously
   be used to maximize date coverage in validation.
3. **Select compact validation hierarchically:** city, then collection date,
   then source log, then clips. Target roughly 150 scenes initially; finalize
   quotas from the available metadata rather than asserting the old counts will
   survive the new partition. Limit domination by a single date or log.
4. **Audit behavioral coverage without candidate scores:** initial speed,
   stops/moving starts, straight/left/right/curved paths, traffic density and
   progress opportunity. Use a small number of predeclared bins to avoid a sparse
   cross-product. Inspect route/location overlap where metadata permits.
5. **Report distinct generalization questions:** new logs on familiar dates,
   new collection dates, and known-scene regressions. Do not pool these silently
   into one apparently representative number.
6. **Handle coverage limits honestly.** Singapore has no fresh date or source
   log available in this public universe; retain its regression panel separately.
   Pittsburgh's alternate date is only one log/12 scenes, so it cannot provide
   strong multi-day statistical evidence by itself.
7. **Write a new version**, for example `evaluation/v2/`, with seed, selection
   rules, explicit memberships, hashes and exposure history. Preserve v1 and
   record why v2 changed. Do not keep reseeding until a model looks better.

Date balancing is a robustness design, not an estimate of the organizer's
unknown city/date weights. Do not force the ranking to match historical board
results by altering sample weights or choosing a favored metric.

### Asset staging

All public scene configs are present, but only 400 scenes have the basic checked
rendering assets. Staging scope remains a user decision: selected validation
assets first, or the full public remainder for later use.

The earlier disk snapshot found roughly 1.8 TiB free on
`/media/skr/SeagateHub1`, versus about 58/74 GiB on the two SSD filesystems.
Recheck space before a transfer. Use a new dedicated staging directory; do not
relocate, overwrite or delete the existing runnable root and caches.

Assets are bundled in large archives. Selective extraction can save storage but
may still require scanning/downloading many shards. The remaining archives were
estimated at about 356 GB compressed from rounded published sizes; expanded
storage is not yet measured. Pin dataset revision/checksums, verify actual shard
membership, retain download receipts and validate container-visible paths.
Do not substitute conveniently downloaded clips for missing selected clips.

## 5. Evaluator and reporting gates

Before any new model-quality comparison:

1. Pin a reviewed organizer-compatible runtime/scorer/controller configuration,
   preserving our current environment and custom driver changes separately.
   The September 18 source review used upstream `7611632`; the relevant off-road
   source changes are in `0bb4c4b`. These are recorded review references, not a
   claim about a freshly checked live deployment.
2. Apply the complete off-road correction: road-area loading, exterior/hole
   coordinate transforms, and repaired polygon/query handling. Enabling only
   one component is insufficient. Verify cache provenance separately.
3. Integrate the frozen scene groups into Hydra and the launcher's preflight.
   The legacy `tools/run-eval.sh` currently assumes configs in the older runtime;
   standalone config loading does not mean launch integration is complete.
4. Require exact scene/repeat coverage and real model-execution counts. Report
   planning exceptions, cached-plan reuse/age, straight fallbacks, missing
   dynamics and route availability. A valid trajectory/RPC or successful
   container does not prove the intended neural policy ran on every update.
5. Preserve the official scene-score definition. Report collisions, off-road,
   corridor failures, progress and full `dist_to_gt_trajectory` separately.
   Do not mix full-distance means with lateral-error medians or replace the
   scorer with a metric selected because it orders two historical models nicely.
6. Use exact paired clips/repeats for comparisons, source-log grouped uncertainty
   and city/date sensitivity views. Show repaired failures and new failures,
   worst groups and lower-tail outcomes, not just the global mean.
7. Record model/config/image hashes, manifest hash, simulator/scorer versions,
   cache provenance and timing/batching settings alongside every future result.

No fitted local PCS, rank projection or bootstrap interval should be presented
as covering uncertainty about the unknown private scene distribution.

## 6. Candidate tweaks — test only after diagnosing the relevant failure

Each candidate needs one stated hypothesis, an unchanged baseline, one isolated
change and a revert path. These are options, not a bundle to apply automatically.

| Priority / candidate | Evidence to obtain first | Narrow intervention if justified |
|---|---|---|
| Input/adapter parity, either model | Compare training/inference camera order, crop, calibration, frames, timestamps, history, velocity and route construction | Correct the demonstrated mismatch; do not change unrelated model behavior |
| Execution integrity, especially Garage | Attribute planning exceptions and fallback-masked successes in saved logs | Repair the exception/input path; expose fallback counters and plan age |
| WA-JEPA batch-dependent randomness | Compare identical inputs alone, in batch 2 and at different positions/orders | Make sampling per-request/session reproducible without relying on private scene IDs, if output changes are confirmed |
| Route conditioning | Inspect empty/short/padded routes and wrong-path selections before divergence | Fix only verified frame/target construction errors; retain the checkpoint's trained conditioning contract |
| Trajectory/controller interface | Align emitted XY/yaw/timestamps with actual motion; distinguish a bad reference from poor tracking | Repair verified timing/yaw/continuity defects or tune one controller parameter, not both at once |
| WA-JEPA S4/S12 | Confirm benefit on independent paired scenes and measure relevant throughput/batching | Change inference steps only; retain S2 as control |
| Perception-assisted selection, later | Show a useful offline upper bound, then verify predicted geometry quality and latency | Use camera-predicted BEV/objects to rank or gate candidate trajectories conservatively |
| Targeted Garage fine-tuning, later | Identify a reproducible failure and separate training examples addressing it | Fine-tune a limited component from the released checkpoint; retain held-out logs/dates and safety checks |

Important qualifications:

- The WA-JEPA code resets an inference generator and draws batch-shaped scene
  noise before trajectory noise. That makes batch invariance an audit target,
  not a confirmed explanation of the official score gap.
- Saved WA-JEPA corridor failures show gradual divergence. They do not justify
  applying an unconditional harsh-braking sanitizer, speed boost or straight-line
  fallback. Preserve legitimate stops, braking, turns and obstacle avoidance.
- Do not repackage already-rejected route-threshold changes as a new fix. The
  supplied route starts well ahead of ego; copying a distant centerline is not
  a substitute for seeing immediate obstacles or choosing the correct path.
- Py123D tutorial BEV/road/object annotations are dataset supervision. They cannot
  simply be appended to an unchanged WA-JEPA input contract. Ground truth may be
  used for offline diagnostics only; a submitted hybrid must use permitted online
  observations and predictions, not evaluator/private annotations or scene lookup.
- Predicted perception is fallible; current object boxes alone do not establish
  future collision safety. A hybrid needs uncertainty, motion and compute checks.
- Full training from scratch is out of the initial scope. Limited fine-tuning is
  a fallback option, not a prerequisite for establishing a correct baseline.

## 7. Execution sequence and decision gates

1. **Dataset design:** finalize and save the metadata-only v2 split; verify group
   separation, coverage and immutable provenance. No model outcomes are needed.
2. **Assets and evaluator:** after staging approval, assemble assets and complete
   evaluator/cache/launcher alignment. Start with non-simulation unit/config checks.
3. **Unchanged baselines:** when experiments are authorized, first perform a small
   integrity check, then a paired compact validation comparison of Garage and S2.
   Do not jump directly to a full 1,485-scene sweep.
4. **Diagnose and change one thing:** use saved traces and targeted failures with
   successful controls. Test one candidate tweak against its own unchanged model.
5. **Promote only robust improvements:** look for fewer hard failures and useful
   progress/tracking gains without a meaningful safety or cross-group regression.
   Predeclare any tolerances; do not accept a gain explained by skipped inference,
   missing scenes, scorer changes or a single repeatedly tuned log.
6. **Final holdout:** freeze the candidate before evaluating reserved logs/dates.
   If holdout results prompt another change, that holdout has been consumed and
   must no longer be described as untouched.
7. **Submission gate:** recheck live rules, remaining quota, deployment version,
   resource limits and immutable image identity. Use warmup for operational
   compatibility if appropriate; the reviewed warmup offers completion status,
   not a scored model-selection signal or proof of full-run throughput. Submit
   only with separate authorization and a documented improvement rationale.

This sequence aims to spend scarce submissions on credible candidates. It does
not promise a particular PCS, rank or competition win.

## 8. Status at handoff and immediate next action

Completed before this document was saved:

- Metadata/exposure audit: 46 summaries and 53 resolved worker configs, including
  unfinished runs, identify the same old 400 scenes/13 logs.
- Frozen v1 manifests, scene lists, Hydra configs and initial asset inventory.
- Ten metadata-only unit tests and loading checks for all six v1 configs.
- Date audit establishing the one-date-per-city limitation and v1 date overlap.

Not completed:

- v2 city/date-aware allocation and behavioral coverage audit;
- new rendering-asset downloads/staging;
- runtime/scorer/cache alignment and launcher integration;
- any new baseline evaluation, tweak experiment, training or submission.

**Immediate next proposed implementation: create and review `evaluation/v2/`
without overwriting v1, then choose the download scope.** Do not interpret this
saved plan as an instruction to start a background transfer or evaluation.

## 9. References and resumption

- [Current scene setup and readiness](evaluation/README.md)
- [Frozen v1 scene manifest](evaluation/public-suite.json)
- [Latest saved upstream review](UPSTREAM-REVIEW-2026-09-18.md)
- [Three-part off-road correction](UPSTREAM-REVIEW-2026-09-16.md)
- [Earlier failure analysis](LEADERBOARD-REVIEW.md): useful evidence; its model
  priority and submission-quota statements are historical, not current decisions.
- [Released checkpoint model card](py123d/checkpoints/resnet34_v0.1.0/README.md)
- [Released checkpoint configuration](py123d/checkpoints/resnet34_v0.1.0/config.yaml)
- [Historical model notes](py123d/MODEL.md) and [local-run notes](py123d/FINDINGS.md):
  apply the cautions above; do not inherit their causal/transfer claims wholesale.

Resume with:

> Read `/home/skr/Downloads/alpasim_challenge/Plan_B.md`, then
> `evaluation/README.md` and the September 18 upstream review. Continue with the
> city/date-aware v2 scene design first. Preserve the old 400 as development and
> keep v1 immutable. Py123D Garage is primary; unchanged WA-JEPA S2 is the control.
> Do not download, run inference/evaluations, train or submit without my go-ahead.
