# Local-only frozen-Cosmos driving-head test

Follow-up: the separately authorized [corrected-state matched ablation](ABLATION-RESULT.md)
has now completed. It preserved this run unchanged and found no unseen-log
position-error advantage from Cosmos features at the ten-sample scale.

Completed 2026-09-19. **Numerical head training passed; ego-state consistency
needs correction before scaling or deployment.** Exactly ten real examples and
100 optimizer updates were used. No further fit, simulator evaluation, submission,
backbone update or data download was run as part of this test.

## What this establishes

The full local Cosmos3-Edge generator transformer and VAE can supply frozen
features to a small trainable waypoint head. The head receives finite gradients,
changes its parameters, reduces training error and survives checkpoint reload
with identical predictions. This is **head adaptation, not fine-tuning Cosmos
weights**, and is not evidence of generalization, safe closed-loop driving or
leaderboard improvement.

The broad frozen-backbone/learned-policy idea is the intended adaptation
principle. This experiment does not reproduce Odyssey's private recipe and uses
no Indian-road data: the ten examples come from Boston (2), Pittsburgh (3),
Singapore (3) and Vegas (2).

## Measured result

All errors below are on the **same ten training examples**, not a holdout.
ADE averages Euclidean position error over 40 targets at 0.1–4.0 seconds;
FDE measures position error at 4.0 seconds.

| Check | Before fitting | After 100 head updates |
| --- | ---: | ---: |
| Composite training loss | 7.7014 | 0.5330 |
| Training ADE | 13.0038 m | 1.4192 m |
| Training FDE at 4 s | 26.6671 m | 3.2629 m |
| Lateral position MAE | 7.2687 m | 0.3254 m |
| Longitudinal position MAE | 8.6579 m | 1.3461 m |
| Heading MAE | 50.6522° | 5.3509° |

- Ten distinct scenes exported; ten image-feature calls succeeded.
- Frozen transformer/VAE loading: no missing, unexpected or mismatched keys;
  no backbone gradients or parameter-version changes during feature extraction.
- Trainable head: 815,235 parameters, 51 parameter tensors changed.
- AdamW, learning rate 0.0003, batch size 10, seed 20260919, 100 updates on CPU.
- Saved-head reload: maximum prediction difference **0.0**.
- **61 CPU tests passed**. Synthetic unit-test updates are separate from the
  exactly 100 updates performed on real samples.

Black formatting and Ruff's focused syntax/undefined-name checks passed. The
full configured Ruff check still reports import-order and dictionary-style
findings; this is not a claim of a clean full lint run. Source files were not
restyled after fitting merely to change that status and recorded source hashes.

Training used cached features, so Cosmos was not loaded into the head-training
process. The measured optimization/metrics loop took 1.91 s on CPU; this is not
end-to-end wall time including source export, feature extraction or saving.

The actual feature-cache run loaded the checkpoint in 3.99 s and completed in
5.04 s with a warm filesystem cache. Sampled model-process peak was **8.11 GiB**
(seven samples; not a hard bound), versus 7.76 GiB torch allocated peak. The
first image took 427 ms and subsequent images about 45–48 ms, including JPEG
loading/preprocessing and synchronous feature copying. These are not complete
driver or concurrent-rollout latency measurements. The earlier independent
[non-fitting probe](FEATURE-PROBE-10.md) has its own timing scope and cold load.

## Two important data findings

### Route padding: fixed for export

The saved runtime route uses a finite prefix followed by all-NaN vector rows as
padding. The first strict export rejected that padding. The reader now masks
only trailing all-NaN rows; it still rejects partial NaNs, infinities, interior
padding and wholly invalid routes. Regression tests cover these cases.

The corrected export has 3–10 real route points per example. The original
failed-export record is retained rather than overwritten.

### Ego velocity: unresolved, limits interpretation of this fit

The exporter consumed logged `dynamic_states` as rig-frame ego velocity, in
line with the current protobuf's stated convention. However, in **9/10 examples**,
the logged XY velocity differs by more than 1 m/s from causal motion derived
from the received ego poses. All pose differences used timestamps 0 and 17,000
microseconds, available before the prediction request; no future target was
used to construct that diagnostic input.

For the first Boston example:

| Velocity source | Forward | Left |
| --- | ---: | ---: |
| Logged dynamic state, consumed directly | 4.845 m/s | −7.270 m/s |
| Received-pose difference in current rear-axle frame | 8.402 m/s | 0.045 m/s |

The exact cause—source convention, historical runtime or another conversion—is
not established. No guessed rotation was applied and no corrected-data refit
was run. A 17 ms pose difference is also a diagnostic estimate, not a validated
deployment velocity estimator. The saved fit's velocity-consistency loss and
constant-motion residual parameterization use the suspect logged values.
Consequently, decreasing loss does not certify a physically correct state
interface. This finding alone also does **not** establish the cause of the
earlier WA-JEPA local/leaderboard discrepancy.

For a more meaningful analytic comparison, constant velocity derived from the
past received poses gives **1.5362 m ADE / 4.2185 m FDE**, versus the fitted head's
1.4192 m / 3.2629 m. The head improves ADE on only **3/10 individual examples**.
This small aggregate training-set difference is not evidence that Cosmos
features help; a state/route-only learned ablation and independent data remain
necessary. The earlier raw-velocity baseline's 14.37 m ADE is misleading and
must not be used as evidence of a large model advantage.

## Scope, splits and provenance

The user explicitly requested ten real samples and confirmed local head-only
scope. The separate [local authorization](pilots/local-head10-v1/AUTHORIZATION.md)
and [ten-scene manifest](pilots/local-head10-v1/manifest.json) record that scope.
Competition training-data eligibility remains **unverified**; every run stage
records `submission_allowed: false`. This does not block the authorized local
test or require a token, but this fitted checkpoint is not a submission candidate.

Each example is the expert-aligned initial observation at 17,000 microseconds,
inside the 500,000-microsecond priming window. All 40 future target poses are
finite and separated from causal model inputs. Only the current camera image
exists for each example; both older history slots are masked. This is ten
isolated observations, not continuous driving footage or temporal-policy training.

The original eight pilot scenes plus two deterministic additions use the same
four source logs. All **207 public scenes from those logs** must now be treated
as training-exposed for this head or candidates derived from it. The recorded
589-scene validation pool (including compact150) and 313-scene holdout have no
source-log overlap and were not evaluated. Exclusion enforcement in the main
evaluator remains pending; an old400/full1485 average would not be independent.

Original manifests are unchanged:

- Public suite SHA-256:
  `a2a150d4eb139db0cbfa7d1cfa37a8eff701db34fff8264034c0433ab2f36b64`.
- Original conditional eight-scene manifest SHA-256:
  `58d3c4e5c5fc28eb5329e3514a0812d18c50e069bcff6f9170d22ae36349186a`.
- Separate local ten-scene manifest SHA-256:
  `1ae99e1644dc5bc0e7317333bfe51c989e49a2d968cb450c1d7b58d9599c3f4d`.

## Saved artifacts

Run directory: [local-only-head10-v1](artifacts/local-only-head10-v1/README.md).

- [Training report](artifacts/local-only-head10-v1/head/training.json).
- [Fitted head](artifacts/local-only-head10-v1/head/head.safetensors), SHA-256
  `0b00274928c7f6a1c1bd47e65f975b26f67747f4a293773f653e0bda3ac7f535`.
- [Frozen feature-cache report](artifacts/local-only-head10-v1/features/cache.json).
- [Corrected export manifest](artifacts/local-only-head10-v1/samples-route-mask-v2/dataset.json).
- [Authoritative diagnostic summary](artifacts/local-only-head10-v1/diagnostics-checked/summary.json).
- [Loss plot](artifacts/local-only-head10-v1/diagnostics-checked/training-loss.png).
- [Ten training trajectories](artifacts/local-only-head10-v1/diagnostics-checked/training-trajectories.png).

The plots compare predictions with recorded targets, not executed vehicle paths.
Some predictions remain jagged; controller readiness is not established.
The diagnostic plots were generated using the existing AlpaSim environment;
the inherited Matplotlib in the Cosmos environment was incompatible with its
NumPy version. No packages were changed to generate these plots.

## Next step, not executed

1. Trace and validate the logged ego-state convention; implement a versioned,
   causal state adapter with the same transforms in training and deployment.
   Add real-log consistency tests, including velocity and yaw rate, instead of
   guessing a rotation or taking future-target derivatives as inputs.
2. After separately authorizing another bounded run, repeat the ten-sample fit
   with corrected inputs and compare a state/route-only head under the same
   budget. Preserve this run as the original diagnostic.
3. Before scaling, obtain permitted continuous image-backed training clips,
   enforce source-log exclusions and measure held-out performance. Neither a
   long training job nor backbone unfreezing is justified by this test alone.
