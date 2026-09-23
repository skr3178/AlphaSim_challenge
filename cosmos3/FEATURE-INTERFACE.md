# Proposed Cosmos3-Edge driving-policy interface

Latest follow-up: the [corrected-state ablation](ABLATION-RESULT.md) replaces
ambiguous logged ego state with a versioned causal received-pose adapter for
this experiment. Identical heads with/without Cosmos features were compared on
nine unseen logs; the Cosmos arm had worse position error. The original
representation-benefit hypothesis is not validated at this tiny data scale.

Earlier single-head status, 2026-09-19: **ten-sample local head fit completed, Cosmos frozen; ego-state
consistency needs correction**. The [result](LOCAL-HEAD10-RESULT.md) records 100
updates, falling training loss and a 9/10 logged-velocity discrepancy. No
held-out or closed-loop driving benefit is established. See
[FEATURE-PROBE-10.md](FEATURE-PROBE-10.md) for measured scope and limitations and
[TRAINING-PIPELINE.md](TRAINING-PIPELINE.md)
for implementation choices and remaining checks, and
[TRAINING-READINESS.md](TRAINING-READINESS.md) for the earlier data audit. This is a Cosmos adaptation
proposal, not a claimed reproduction of Odyssey's private model or recipe.

Follow-up, 2026-09-19: [REAL-PILOT.md](REAL-PILOT.md) records a user-approved,
conditional eight-scene exception to the earlier public-data exclusion policy.
That original competition-conditional manifest remains unchanged and requires
confirmation of training-data rules. A separately authorized local-only
ten-scene fit has now used those eight scenes plus two from the same four logs;
all 207 same-log scenes are training-exposed for that head and derived candidates.

## Objective and adaptation stages

Use pretrained Cosmos representations to learn a state- and route-conditioned
driving policy. Stage A freezes the backbone and learns a small temporal/action
head. Stage B may add low-rank adapters or unfreeze selected upper blocks only if
held-out results justify it and the training memory probe passes. Full-generator
fine-tuning is not the default. Twenty GPU-hours is a planning reference, not a
hard limit, convergence target or required stopping time.

Odyssey reports keeping its world model frozen and learning a small driving
policy using 20 hours of driving **data**. It does not publish evidence that
20 GPU-hours suffice or that the same feature interface works for Cosmos.
[Primary announcement](https://odyssey.systems/introducing-odyssey-3).

## Which Cosmos features? Keep the distinction explicit

The loaded Diffusers generator and the standalone visual reasoner are different
execution paths of the checkpoint. The existing compatibility run loaded the
generator plus VAE; it did not run the separate vision-encoder/reasoner path.

| Feature path | Proposed tap | What it would test | Status |
| --- | --- | --- | --- |
| World-generator features | Observation-token hidden states from the frozen MoT, after the decoder stack and before modality output projections | Whether the world-generator representation supports a compact driving head | Ten frozen full-checkpoint image calls passed; 41 ms warmed mean and 8.11 GiB sampled process peak for this serial probe. Driving usefulness and full-driver performance remain unverified |
| Cosmos visual-reasoner features | Final hidden states after visual encoder, projector and Edge language backbone | A lower-compute Cosmos-representation policy baseline | Source API exists; correct checkpoint remapping/loading and hardware performance untested |
| Vision-only ablation | SigLIP2/projector features before the language/world backbone | Whether a generic visual representation explains the gain | Not equivalent to using the full Cosmos world model |
| State/route-only ablation | Same head with visual tokens removed | Whether gains actually come from speed and navigation inputs | Required control, not the intended final policy |

**Start with a code-level feasibility check of world-generator feature access.**
Do not assume a single denoising pass on a clean observation is a validated
encoder. If it needs expensive multi-step generation or cannot preserve a causal
input contract, evaluate the reasoner path as an explicitly named alternative;
do not silently relabel it as an Odyssey-style world-generator reproduction.

Local source evidence: the installed `Cosmos3OmniTransformer.forward` constructs
`last_hidden_state` after `_run_decoder_stack`, but its public output returns
modality predictions, not those features. The new prototype hooks `norm_moe_gen`
and spatially pools its clean-image token features to 32 tokens per frame.
Diffusers commit: `344d6e7300716ff245d5941bc1fe3e95ad8cd1c3`.

For the alternative path, NVIDIA's native `Cosmos3EdgeModel` has visual,
projector and language-model components and returns hidden states. Its model
registration is framework-owned. Using `get_image_features` alone would stop
before the language backbone and is **not** the same feature choice.
[Pinned model implementation](https://github.com/NVIDIA/cosmos-framework/blob/c23e51f2f157ae3e51cfcd86ebfb5464850894f2/cosmos_framework/model/generator/reasoner/cosmos3_edge/modeling_cosmos3_edge.py),
[registration](https://github.com/NVIDIA/cosmos-framework/blob/c23e51f2f157ae3e51cfcd86ebfb5464850894f2/cosmos_framework/model/generator/reasoner/cosmos3_edge/__init__.py).

The local config sets hidden width **2048** for the backbone, **1152** for the
vision tower, and projector output width **2048**. These are configured widths,
not measured feature tensors. Token count depends on the exact preprocessing,
resolution and feature tap; it must not be hard-coded from the old video output.

## Proposed sample and tensor contract

All choices below are initial design values, not empirically optimized settings.
Keep training and deployment transforms identical and versioned.

| Field | Proposed representation | Rule |
| --- | --- | --- |
| Sample identity | source log, recording window, city/date, current timestamp, split hash | Identity is used for provenance/splitting, never a learned policy input |
| Observation history | `CAM_F0` at approximately t−1.0, t−0.5, t seconds; `[B,3,3,H,W]` before native preprocessing | Select latest available exposure ending at/before each cutoff; retain real timestamps and missing-history masks |
| Calibration | camera intrinsics, sensor-to-rig transform and image preprocessing transform | Validate stored calibration and coordinate conventions; no assumed shared calibration across vehicles |
| Visual features | `[B,K,N,2048]`, or packed equivalent, plus masks/timestamps | Frozen/no-grad in Stage A; use only current/past observations, no future GT tokens |
| Ego state | `[v_forward,v_left,yaw_rate]`, masks and recent relative ego poses | Convert from dataset coordinates into current rear-axle frame; derive only from causally available state |
| Navigation | up to 32 sparse route points `[B,M,2]` in current rig frame plus valid mask | Match the route information actually delivered by AlpaSim; no dense future expert trajectory disguised as route |
| Learned head | projection to ~256 dimensions, compact temporal/route fusion and horizon queries | Exact size subject to latency/memory probe; train this first |
| Output | 40 future `[x,y,sin(yaw),cos(yaw)]` points at 0.1–4.0 s | Metres/radians in current rear-axle frame; initial pose at time t is inserted by driver, not predicted |
| Training target | recorded future ego poses expressed in that same frame | Future GT is loss supervision only; never passed to feature extractor or policy input |
| Validity | frame/history/route/target masks | Do not interpolate across recording breaks or manufacture missing future targets |

The current driver can then transform predicted rig poses into the expected
local frame and emit 41 timestamped planar poses, preserving the existing
four-second interface. Horizon coverage, query timestamp, finite values and yaw
normalization must be validated before returning a response.

For a general raw-data exporter, route construction remains a requirement: databases contain scene
roadblock IDs, but those are not automatically identical to the sparse runtime
route. Use the same authorized route construction as deployment and verify its
provenance. Do not extract exact future waypoints from the label and feed them
back as navigation conditioning. The implemented saved-ASL exporter instead uses
the sparse route actually supplied to the driver and retains its timestamp and
provenance. Missing/short routes need masks and training
coverage, not an unlogged exception or silent fallback.

## Losses and useful checks

- Start with masked waypoint Huber loss and periodic heading loss.
- Add speed/initial-velocity consistency and modest acceleration/jerk penalties;
  tune weights using training-validation only, never the sealed public holdout.
- Report lateral and longitudinal errors separately, predicted starting speed
  versus observed speed, and errors by city/date/speed/turn category.
- A low waypoint loss is not evidence of safe closed-loop driving. Expert-only
  imitation may fail to recover from drift; any later recovery-data collection
  must use training scenes and needs separate authorization.
- Compare the same head and data budget with state/route only, vision only,
  and the selected Cosmos feature path. A constant-velocity sanity baseline also
  catches incorrect timestamps/scale. The ten-sample report includes a causal
  pose-based constant-velocity comparison; learned ablations remain unrun.

## Leakage, cache and runtime controls

1. Use the protected source-log/date manifests before sampling overlapping clips.
   Do not train on development400, any public `navtest` scene, official validation
   data, or the proposed pilot-validation city/dates, except the exact conditional
   eight-scene pilot in [REAL-PILOT.md](REAL-PILOT.md) or the separately authorized
   [local-only ten-scene test](LOCAL-HEAD10-RESULT.md). This is not competition
   training permission. The 207 same-source-log exclusions must be enforced
   before evaluating the fitted head or any derived candidate.
2. Key feature caches by input image hashes, actual timestamps, preprocessing,
   calibration, checkpoint revision, feature tap/layer, and split-manifest hash.
   Never put future labels into the cached feature computation.
3. Cache per-frame features only if that tap is truly per-frame. Joint temporal
   or route-conditioned features require the entire causal context in the key.
4. Freeze backbone weights and disable stochastic model layers for feature
   extraction. If Stage B unfreezes weights, invalidate the frozen feature cache.
5. Clear all recurrent/cached state between simulator sessions; isolate concurrent
   sessions. A single serial smoke run does not establish competition throughput.
6. Measure preprocessing + encoder + policy-head p50/p95 latency, total process
   VRAM, cold-start cost and two-session behavior before a submission claim.
   Existing ~2.48 s generation latency is not the latency of this new policy.

## Decision gates before training

- Matching RGB assets are available, decodable, time-aligned and sufficiently
  continuous for history and future supervision; duration measured on **unique**
  usable intervals, not the sum of overlapping training clips.
- Small CPU tests establish dataset-to-rig conversion, timestamp pairing,
  calibration semantics and absence of future-data leakage.
- A separately authorized short GPU probe proves strict weight loading, finite
  causal features, no unexpected random/unloaded layers, memory and latency.
- A tiny head-only overfit check is followed by held-out comparison. Escalate to
  LoRA/selective unfreezing only on evidence; remeasure memory and inference cost.
- Before any leaderboard comparison, complete the existing local runtime/scorer
  parity work. The current compatibility scorer is not certified organizer parity.

NVIDIA's available action-policy SFT recipe is a useful example of state-plus-
vision action learning, but its documented DROID task uses robot joint targets,
not nuPlan waypoints. It is not a drop-in AV fine-tuner.
[Official action-policy recipe](https://github.com/NVIDIA/cosmos-framework/blob/c23e51f2f157ae3e51cfcd86ebfb5464850894f2/docs/action_policy_droid_posttrain.md).
