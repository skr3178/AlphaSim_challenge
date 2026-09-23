# Corrected-state Cosmos feature ablation — 2026-09-19

**Completed: this first controlled test does not demonstrate a useful Cosmos
advantage on unseen source logs.** The Cosmos head fits the ten training examples
better, but has worse average position and endpoint error on nine unseen-log
examples than the otherwise identical head without image features. This is
evidence about this feature tap, head, data size and 100-update budget—not a
rejection of Cosmos or frozen-world-model adaptation in general.

No full simulator evaluation, new download, backbone update or submission ran.
Both heads remain local-only; competition training-data eligibility is unverified.

## Matched result

All errors are open-loop predictions against recorded expert targets, not
executed vehicle trajectories. Lower is better. ADE averages Euclidean position
error across 40 waypoints at 0.1–4.0 s; FDE is endpoint error at 4.0 s.

| Metric | Cosmos + state/route | State/route only | Causal constant velocity |
| --- | ---: | ---: | ---: |
| Training ADE, ten fitted examples | 1.153 m | 1.407 m | — |
| Unseen-log ADE, nine examples | **2.414 m** | **1.977 m** | **1.830 m** |
| Unseen-log FDE at 4 s | 5.800 m | 4.825 m | 5.538 m |
| Unseen-log lateral MAE | 1.215 m | 1.280 m | 1.271 m |
| Unseen-log longitudinal MAE | 1.677 m | 1.220 m | 0.803 m |
| Unseen-log heading MAE | 5.775° | 7.293° | 10.203° |

Adding Cosmos features increased unseen-log ADE by **0.437 m (22.1%)**, although
heading error was lower (5.775° versus 7.293°) and lateral error was slightly
lower (1.215 m versus 1.280 m). It improved ADE on only **2/9**
examples. The aggregate position regression is primarily longitudinal, not
evidence of uniformly worse predictions in every component.

An exploratory paired bootstrap over nine source logs (one scene per log,
10,000 resamples) gives a Cosmos-minus-state/route ADE interval of
**+0.168 to +0.733 m**. This is not a confirmatory population interval: there is
one initialization, ten training examples, nine evaluation examples and a
deliberately balanced-by-log convenience sample. No leaderboard inference follows.

## What was controlled

- Training: the same original ten examples, four source logs, with corrected
  causal ego state. No added training examples or selection using new outcomes.
- Evaluation: one SHA-256-ranked scene from each of the other nine development
  source logs, selected and pinned before model outcomes were available.
- Cities: training Boston 2 / Pittsburgh 3 / Singapore 3 / Vegas 2; evaluation
  Boston 2 / Pittsburgh 3 / Singapore 1 / Vegas 3. Training/evaluation source-log
  and image-byte-hash intersections are empty. These are not unseen cities/dates
  or guaranteed unseen Cosmos pretraining data.
- Architecture: identical 815,235-parameter waypoint heads. The control gets
  all-zero visual features; masks, positional tokens, observed history, ego state
  and runtime route are unchanged. Thus the control has no image information
  but retains the same architecture and parameter allocation, not a separately
  optimized lightweight policy. Its visual projection weights get no
  data-dependent signal from zero inputs.
- Initialization: identical state-dict hash
  `e07a9288ba92338dd4ec658e4934298895f1595c759035c9af4f78b7049e7b0f`.
- Optimization: seed 20260919, AdamW LR 0.0003, batch 10, the same full-batch
  permutation sequence, the same losses, **100 updates per arm / 200 total**.
  Both runs start fresh; neither resumes the earlier suspect-state checkpoint.
- Cosmos remains frozen, with the same clean-observation generator/VAE feature
  recipe in both training and evaluation caches. Each example has one current
  image, with both older history slots masked. This does not test continuous
  temporal learning or world-model rollout/planning.
- Both final checkpoints were saved before evaluation. Exactly one fixed
  post-training evaluation was run, with no checkpoint, seed or hyperparameter
  selection using its losses. No additional real optimizer updates followed.

The original protected validation/holdout suites were not used. The nine new
examples are development-set diagnostics unseen by these fitted heads, **not a
new sealed test set**. If their results guide future choices, treat them as
development validation, not independent final proof.

## Ego-state correction and its limits

The old exporter consumed logged `dynamic_states` directly as rig-frame state.
In these 19 saved examples, 18 have logged XY velocity differing by more than
1 m/s from causal received-pose motion. The current protobuf describes rig-frame
state, and current runtime source rotates local-frame vectors into the rig frame;
the saved run reports runtime 0.3.0 / gRPC minor 54 with unknown git revision.
The exact historical conversion responsible remains unresolved. This work did
not modify AlpaSim's runtime, organizers' code, WA-JEPA or the main evaluator.

The new versioned [state adapter](training/state_adapter.py) uses only the latest
two already-received rear-axle poses. Translation difference divided by elapsed
time is rotated into the current rig frame; relative rotation supplies angular
velocity. Invalid rigid transforms, missing/stale/too-close pose pairs and
implausible states fail rather than silently falling back. It ignores future
poses and never uses future targets or ambiguous logged dynamics as inputs.
The same callable is available for future driver integration; that integration
and runtime behavior have not yet been tested.

All 19 exports passed with no rejected samples. Here, each backward interval is
17 ms. As a **diagnostic only**, the estimates were compared with motion over the
next 100 ms reference interval: maximum XY difference **0.03993 m/s** and maximum
yaw-rate difference **0.001409 rad/s**. Future-label derivatives exist only in
the audit report; they were never written into model input arrays or features.
This establishes consistency for these expert-primed examples, not accuracy of
an instantaneous estimator under noisy deployment odometry. The legacy-source
discrepancy is avoided for this experiment, not globally explained or repaired.

This finding does not establish why WA-JEPA's historical leaderboard score
differed from its local score; that would require separately tracing its actual
state consumption and evaluator/runtime versions.

## Execution checks and resources

- All 19 feature calls succeeded; strict transformer/VAE loading had no missing,
  unexpected or mismatched parameter keys. Backbone parameter versions remained
  unchanged, with no backbone training.
- Sampled feature-process peak: 8.113 GiB for training cache and 8.121 GiB for
  evaluation cache. Sampling is not a hard VRAM bound or full-driver benchmark.
- Cache stages: 5.06 s and 2.68 s, including warm-filesystem checkpoint loads of
  3.99 s and 2.07 s. These are two serial loads of the same local checkpoint.
- CPU optimization/metrics loops: 1.91 s and 1.89 s. These exclude process startup,
  data export, feature extraction and artifact saving.
- Initial → final training losses: Cosmos 2.5069 → 0.4446; control 3.1473 → 0.5383.
- Both saved heads reload with maximum prediction difference **0.0**.
- **73 CPU tests pass**. Black formatting and focused Ruff syntax/undefined-name
  checks pass; this is not a claim of clean full-project lint.
  Tests cover state rotation, yaw wrap, timestamps/future exclusion, strict
  scene roles, fixed protocol, export and zero-feature control. Generic fitting
  refuses the mixed train/evaluation ablation manifest.

The trajectory plots show that both learned heads miss substantial curvature
in some turn examples and produce jagged waypoint sequences. The Cosmos head's
lower aggregate heading error does not establish controller-ready path geometry.

## Saved evidence

- [Pinned protocol and split](pilots/local-ablation-v1/manifest.json), SHA-256
  `8f1b2fea88ebc4c02580c8aafb27cb443cdc6466bb24e32907c4b14d807a3323`.
- [Local authorization](pilots/local-ablation-v1/AUTHORIZATION.md).
- [State audit](artifacts/local-ablation-v1/state-audit.json).
- [Unseen-log results and per-scene metrics](artifacts/local-ablation-v1/evaluation-result/summary.json).
- [Cosmos-head training report](artifacts/local-ablation-v1/fits/cosmos/training.json).
- [State/route-head training report](artifacts/local-ablation-v1/fits/state_route_only/training.json).
- [Training and comparison plot](artifacts/local-ablation-v1/plots/matched-comparison.png).
- [Nine unseen-log trajectory plots](artifacts/local-ablation-v1/plots/unseen-log-trajectories.png).
- [Artifact directory guide](artifacts/local-ablation-v1/README.md).

Checkpoints are under `fits/cosmos/head.safetensors` and
`fits/state_route_only/head.safetensors`. Their SHA-256 hashes are respectively
`be402313c169760f57d323ec5c17cc59bef3e30f00e66364ef627ebfb95c96a0` and
`8d6bf9b37a86cfde5cc1d5c45cecb9f35bbc63e56254c37e679a434e48159494`.
They are not packaged into a driver and must not be submitted.

The original public manifest, eight-scene conditional manifest, ten-scene local
manifest and earlier diagnostic checkpoint are preserved. All 207 public scenes
from the four training logs remain excluded from independent assessment of
these fitted heads and their derivatives. Source files have intentionally evolved
since the earlier report; saved source hashes describe each historical run.

## Decision and next work—not executed

The learning-pipeline hypothesis is supported; the driving-benefit hypothesis
is **not supported by this test**. Better training fit alongside worse unseen-log
position error is consistent with overfitting or an unsuitable feature/head
interface at this data scale; this test does not distinguish those causes.

Do not scale straight to a long Cosmos job or spend a submission based on this
result. The next useful step is a permitted, image-backed, more diverse training
pilot with continuous observations and more than ten independent examples.
Keep the corrected state contract and matched state/route control, use development
data for design choices, and reserve fresh logs for final checks. A smoother
constant-motion residual head and alternative feature normalization/taps are
testable ideas, not changes applied after seeing these nine outcomes. Backbone
unfreezing remains a separate decision, not a demonstrated requirement.
