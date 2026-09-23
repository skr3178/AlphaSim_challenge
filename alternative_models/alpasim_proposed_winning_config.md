# Proposed AlpaSim 2026 Competition Configuration

## Goal

Build the strongest practical submission for the NVIDIA AlpaSim E2E Closed-Loop Challenge 2026 using a single 24 GB GPU, without full-scale training.

The current leaderboard suggests that the strongest public family is **py123d-garage**, whose best variants occupy the top positions with Policy Capability Scores around **1700–1800+**. The proposed strategy is therefore to start from the public py123d-garage model rather than train a new planner from scratch.

## Recommended Base Model

**py123d-garage public camera-only Latent TransFuser / ResNet-34 checkpoint**

Why this base:

- It is open source and publicly usable.
- Public pretrained weights are available.
- It is already designed around the same AlpaSim / nuPlan-style closed-loop setting.
- The backbone is relatively lightweight compared with large VLA models.
- The leaderboard strongly suggests that this model family is currently the most competitive.
- It is realistic to fine-tune small parts of it on a single 24 GB GPU.

## Proposed Configuration

```text
CAM_L / CAM_F / CAM_R
        |
        v
Frozen py123d-garage visual encoder
        |
        v
Per-frame latent features
        |
        +-------------------------------+
        |                               |
        v                               v
Current-frame feature            Short feature history
                                  t-1 ... t-4 / t-5
        |                               |
        +---------------+---------------+
                        |
                        v
              Small temporal module
          GRU or 2-layer Transformer
                        |
                        v
           Existing trajectory decoder
                        |
                        v
      Optional lightweight trajectory scorer
                        |
                        v
        Temporal trajectory smoothing/filter
                        |
                        v
            Tuned AlpaSim controller
                        |
                        v
                    AlpaSim
```

## 1. Freeze the Expensive Backbone

Keep the ResNet-34 / Latent TransFuser visual backbone frozen.

Only train small components such as:

- temporal fusion module;
- final trajectory/planning layers;
- optional trajectory-ranking head.

This keeps VRAM and training-time requirements low enough for a 24 GB GPU.

Where possible, precompute visual features once and train on cached latent sequences rather than repeatedly running the image encoder during training.

## 2. Add Short-Term Temporal History

The strongest py123d-garage leaderboard variants are named:

- `044-hist01-0062-v1`
- `044-hist02-single-0062-v1`
- `044-hist05-single-0062-v1`
- `044-hist10-single-0062-v1`

Their scores suggest a useful pattern:

| Variant | PCS |
|---|---:|
| hist01 | 1747 |
| hist02 | 1790 |
| hist05 | **1806** |
| hist10 | 1704 |

Assuming the tags correspond to temporal history length, the apparent sweet spot is approximately **2–5 history steps**, while a much longer history may hurt.

Therefore the first temporal experiments should be:

- history = 1;
- history = 2;
- history = 5;
- optionally history = 8 or 10 as an ablation.

A small GRU should be tested first because it is simple and cheap. A 2-layer temporal Transformer is the next logical experiment.

## 3. Focus Training on Failure Cases

Do not fine-tune broadly over the entire dataset.

Run the current model over local closed-loop validation / navtest scenarios and identify the cases responsible for most score loss.

Example failure categories:

- hesitation / low progress;
- vehicle stuck;
- missed turns;
- incorrect route choice;
- excessive braking;
- slow following behavior;
- difficult intersections;
- unprotected turns;
- cut-ins;
- poor recovery after small trajectory errors.

Construct a compact fine-tuning set heavily weighted toward these failures.

The objective is not to relearn basic driving. It is to correct the small number of closed-loop behaviors that dominate leaderboard losses.

## 4. Preserve Lucifer AI's Existing Safety Strength

Lucifer AI's current leaderboard result is approximately:

- PCS: 1028
- average scene score: 0.762
- at-fault distance: 0.626

The high at-fault distance indicates that safety is not the main weakness.

Therefore the new model should prioritize:

- better scene completion;
- more progress;
- less hesitation;
- better route following;
- better recovery;

while trying to preserve the current safety margin.

Do not optimize only for fault avoidance, because the leaderboard shows that very safe policies can still have low PCS.

## 5. Controller Optimization

Treat controller parameters as a separate optimization problem.

Potential parameters to search:

- steering proportional gain;
- steering derivative gain;
- lookahead distance;
- speed tracking gain;
- braking threshold;
- maximum acceleration;
- maximum deceleration;
- curvature-dependent speed reduction;
- trajectory smoothing strength.

Use lightweight black-box optimization such as:

- Optuna;
- CMA-ES;
- Bayesian optimization.

The objective should combine scene score, route progress, collision avoidance, and stuck penalties rather than maximizing safety alone.

## 6. Add Temporal Trajectory Smoothing

Do not necessarily execute every predicted trajectory independently.

Blend the new prediction with the previous shifted prediction:

```text
P_final =
alpha * P_new
+ (1 - alpha) * P_previous_shifted
```

Test several values of `alpha`.

This may reduce frame-to-frame steering oscillation and improve closed-loop consistency at almost no computational cost.

Additional constraints can be applied before control:

- maximum curvature;
- acceleration limit;
- jerk limit;
- heading continuity.

## 7. Add a Stuck / Recovery Mode

A simple recovery system may give meaningful closed-loop gains without neural-network training.

Possible triggers:

- commanded movement but near-zero ego speed for several frames;
- repeated almost-identical trajectories;
- excessive braking for too long;
- rapidly oscillating steering;
- heading or route disagreement.

Once triggered, the policy could:

- select an alternative trajectory;
- reduce smoothing temporarily;
- increase progress bias;
- use a special recovery trajectory/controller profile.

This is especially attractive because rare catastrophic or stuck states can disproportionately hurt closed-loop capability.

## 8. Optional Trajectory Ranking Head

If additional improvement is needed, add a small GTRS-style trajectory scorer.

Generate perhaps:

- 4;
- 8;
- 16

trajectory candidates.

Then use a tiny scoring network to rank them based on:

- visual/latent scene features;
- recent history;
- predicted progress;
- smoothness;
- collision or boundary risk;
- route consistency.

Train the scorer using pairwise ranking:

```text
good trajectory > bad trajectory
```

This can be done with a very small model and does not require retraining the visual encoder.

## Practical Experiment Order

1. Reproduce the public py123d-garage checkpoint unchanged.
2. Establish local closed-loop baseline.
3. Add history = 2.
4. Add history = 5.
5. Compare GRU vs 2-layer temporal Transformer.
6. Tune controller parameters.
7. Add trajectory smoothing.
8. Add stuck/recovery logic.
9. Mine remaining failure scenarios.
10. Fine-tune only temporal/planner layers on hard cases.
11. Add an 8–16 candidate trajectory scorer only if the simpler configuration plateaus.

## Why This Configuration

This strategy is preferred over WAM-Flow, HDP, large VLA models, or full DiffusionDrive retraining because:

- the py123d-garage family already dominates the challenge leaderboard;
- it has a publicly available pretrained implementation;
- the strongest leaderboard variants appear to benefit substantially from short temporal history;
- the model is small enough to modify with a single 24 GB GPU;
- most components can remain frozen;
- training can be performed on cached latent features;
- controller and trajectory post-processing improvements require little or no GPU training;
- targeted failure-case fine-tuning is much cheaper than full training;
- the approach directly optimizes closed-loop behavior rather than only open-loop trajectory metrics.

## Target Architecture

The recommended competition configuration is therefore:

**py123d-garage ResNet-34 / Latent TransFuser  
+ 2–5 frame latent history  
+ small GRU or temporal Transformer  
+ lightly fine-tuned trajectory head  
+ hard-case training  
+ temporal trajectory smoothing  
+ stuck/recovery logic  
+ optimized AlpaSim controller  
+ optional lightweight trajectory scorer**

This is the most realistic path toward closing the gap to the current ~1800 PCS py123d-garage leaders while remaining compatible with a single 24 GB development GPU.
