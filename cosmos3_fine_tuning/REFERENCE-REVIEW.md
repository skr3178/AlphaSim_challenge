# SO-101 Cosmos3-Edge reference review

Reviewed 2026-09-21. Scope: clone and static review only; no installation,
checkpoint download, training, evaluation, or changes to our training pipeline.

## Provenance

- Repository: https://github.com/kabilankb/so101-cosmos-nano-policy
- Branch: `cosmos-edge`
- Reviewed commit: `104affa95346b9d0cdfcf3a77279c39fa77477ba`
- Local clone: `so101-cosmos-nano-policy/` (approximately 4 MB).
- Linked model: https://huggingface.co/kabilanKB/cosmos_edge_policy_so101
- The website fetches failed. Review used the successfully cloned source,
  bundled model card, resolved configuration, and saved smoke log. No model
  weights were downloaded and no reported benchmark was independently reproduced.

## Bottom line

Useful engineering reference, but not the same adaptation as our approved
frozen-Cosmos feature extractor plus driving head. It demonstrates an implemented
robot manipulation adaptation, not strong driving performance or proof that our
feature representation will generalize.

| Component | SO-101 reference | Our approved nuPlan pilot |
| --- | --- | --- |
| Starting point | Cosmos3-Edge-Policy-DROID, already adapted to manipulation | Base Cosmos3-Edge used as a frozen feature extractor |
| Trainable components | Rank-64 generation-attention LoRA plus native action projections/embedding | External 815,235-parameter waypoint head only |
| Visual processing | Native joint video/action generation path, two stacked camera views | Three separately encoded observed front images; temporal fusion in head |
| Outputs | 32 absolute six-joint targets at 30 Hz | 40 ego-frame trajectory poses at 0.1-second spacing |
| Corpus | Author reports 142 simulated robot episodes; 128 train, 14 validation | 24 acquired independent real nuPlan logs; proposed split still pending |
| Hardware | Author reports RTX PRO 6000 training, initially one GPU, later two | Previously verified approximately 24 GiB GPU; bounded head-only pipeline |

The saved smoke log confirms 112 LoRA-wrapped modules, 25,690,112 LoRA
parameters and 8,458,240 additional trainable parameters. Consequently this is
**not a completely frozen-backbone/head-only example**, even though original
base weights are frozen. Their TOML comments report about 26.1 GB peak at
microbatch 16; do not assume that configuration fits our GPU or transfer its
timing estimates to our very different method.

## References worth applying

1. **Training/serving contract parity.** Their serving code requires explicit
   action dimensions, embodiment, normalization, view ordering and frame rate.
   Our equivalent is image preprocessing/calibration, timestamps, rear-axle
   coordinate convention, state units, MAP route offset, target spacing and
   output interpretation. Save a fixed-input export-to-serving replay test.
2. **Real-versus-rendered observation checks.** Their simulator port found a
   major lighting difference and quaternion-order changes. This supports our
   existing captured-versus-MTGS comparison and camera/frame audit; it does not
   establish that either issue caused our leaderboard discrepancy. Avoid blindly
   applying their brightness or quaternion patch to AlpaSim.
3. **Verify the actual trainable path.** Their logs verify adapter insertion and
   optimizer membership. Keep our stronger head-only requirement: zero trainable
   generator/VAE parameters, optimizer containing only head parameters, finite
   gradients and changed head weights, checkpoint reload parity.
4. **Distinguish task metrics from training loss.** Their native loss combines
   modalities. We should report trajectory errors separately, retain the matched
   state/route-only and constant-velocity controls, and eventually check held-out
   closed-loop progress/collisions/corridor exits. A lower fit loss is insufficient.
5. **Select checkpoints on protected development data.** The deployment README
   reports 5/98 successes for iteration 6500 versus 1/100 for the final iteration
   7000 under its 25-second benchmark. These are low, small-sample, author-reported
   results, not a reliable advantage estimate. Do not assume the final checkpoint
   is best or tune repeatedly against the sealed evaluation set.

## Do not copy directly

- DROID-to-SO-101 domain-row transplantation transfers a manipulation action
  mapping. Robot joints do not share driving waypoint semantics; dimensional
  padding does not make that a justified driving warm start.
- Their flow-matching schedule, native action heads, LoRA and joint video loss
  belong to another training architecture. Applying them requires a separate
  proposal, interface implementation and user approval, not a small configuration
  change to our head-only runner.
- Jetson-specific compiler/cuDNN workarounds are not established requirements on
  our desktop GPU. Do not run their setup scripts against our existing environment.
- The bundled model card says later evaluations are pending, while the HIL README
  supplies later results. Recipe comments also retain older rank-32 descriptions;
  active TOML and the saved resolved configuration use rank 64. Pin the commit and
  distinguish historical prose from executable settings.

## Most important remaining uncertainty for us

Our `cosmos3/training/features.py` deliberately taps clean observed-image
`norm_moe_gen` features at 256x448 and pools them into 32 tokens per image.
It does not run the native action-generation path used here. The code explicitly
marks this as an unvalidated driving encoder. A functioning robot policy does
not validate that feature tap. The matched image-versus-no-image pilot remains
the decisive first test; increasing head size or copying robot hyperparameters
would not resolve this uncertainty by itself.

## Recommended next step

Continue the existing frozen-backbone pilot after explicit split approval:
validate/export the real corpus, perform the bounded feature/head smoke test,
fit matched visual and state/route-only heads, and inspect log-disjoint results.
If visuals help, proceed to a separately authorized small AlpaSim compatibility
test. If they do not, inspect feature informativeness and alignment before
spending on a larger run. No split was approved or activated by this review.

## Local source pointers

- [Training recipe](so101-cosmos-nano-policy/edge/cosmos-framework/recipe/action_policy_so101_edge_focus5_multi_1gpu.toml)
- [Post-training explanation](so101-cosmos-nano-policy/edge/cosmos-framework/docs/so101_edge_posttrain.md)
- [Saved smoke log](so101-cosmos-nano-policy/edge/brev/run-2026-09-16/home/smoke.log)
- [HIL, benchmark results and rendering fixes](so101-cosmos-nano-policy/edge/thor-hil/README.md)
- [Bundled model card](so101-cosmos-nano-policy/edge/huggingface/MODEL_CARD.md)
- [Our active pilot](../cosmos3/RAW-CAMERA-PILOT.md)
- [Our feature extractor](../cosmos3/training/features.py)
- [Our head](../cosmos3/training/head.py)
