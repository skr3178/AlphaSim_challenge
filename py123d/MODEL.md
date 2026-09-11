# py123d_garage `resnet34_v0.1.0` — technical reference

**What it is:** the checkpoint behind py123d-garage's nuPlan board **ranks 2–3 (official PCS ~1470)**.
Apache-2.0, 248 MB, publicly downloadable. Cloned locally at `py123d/checkpoints/resnet34_v0.1.0/`.

Companion document: [FINDINGS.md](FINDINGS.md) — the experiment that ran this checkpoint through our harness
and proved our local mean-scene-score metric is inverted.

---

## 1. Identity and provenance

| | |
|---|---|
| file | `model_0014.pth`, 247,950,835 bytes, sha256 `d536614c8157381a…` |
| released with | `py123d_garage` v0.1.0 (`288d34c` = v0.1.1 clone) |
| licence | **Apache-2.0** (code, weights, and the `py123d` data library) |
| board tags using it | `014-nuplan-0014-v1` (PCS **1470**, rank 2), `017-nuplan-0014-v1` (PCS **1456**, rank 3) |
| NOT released | `model_0062`, behind their rank-1 entry `007-nuplan-0062-v1` (PCS 1600) |
| paper | 123D: *Unifying Multi-Modal Autonomous Driving Data at Scale*, Dauner et al. 2026, arXiv 2605.08084 |

The `-0014-` in their board tags is the epoch number in the filename — that is how we matched the public
checkpoint to their board entries.

---

## 2. Architecture — latent TransFuser, 61.9M parameters

Parameter breakdown from the state dict (738 tensors):

| module | tensors | params |
|---|---:|---:|
| `backbone.image_encoder` (ResNet-34) | 216 | **21.30M** |
| `backbone.lidar_encoder` (ResNet-34) | 216 | **21.30M** |
| `planning_decoder.transformer_decoder` | 110 | 9.47M |
| `backbone.transformers` (TransFuser fusion) | 140 | 8.69M |
| `backbone.{lidar_channel_to_img, img_channel_to_lidar}` | 16 | 0.70M |
| `center_net_decoder` (4 heads) | 20 | 0.20M |
| `bev_semantic_decoder` | 3 | 0.04M |
| **total** | **738** | **61.9M** |

### The "latent" trick — why a LiDAR encoder exists but no LiDAR is consumed

`backbone_config.latent: True`. The second ResNet-34 branch is fed a **learned latent BEV grid**, not a point
cloud. The two-stream TransFuser architecture is preserved, cross-attention and all, but **inference is genuinely
camera-only**. Half the parameters (21.3M) are a BEV feature extractor operating on learned input.

### Key hyper-parameters (`config.yaml → policy_config.transfuser_config`)

```
backbone: image resnet34 + lidar resnet34, image_encoder_pretrained=True, freeze_backbone=False
  TransFuser fusion:      n_layer 2, n_head 4, block_exp 4, dropout 0.1 (embd/resid/attn)
planning decoder:         6 BEV cross-attention layers, 8 heads, token_dim 256, predict_yaw=True
BEV grid:                 x 0→64 m, y −32→+32 m, 4 px/m  (256×256 cells)
```

---

## 3. Inputs and outputs

### Inputs

| input | detail |
|---|---|
| **cameras** | 3 — nuPlan `PCAM_L0/F0/R0`; PAI `FTCAM_L0/F0/R0`. Stitched to **1024 × 256**, JPEG q95 in cache |
| **target point** | **ONE point at 45.0 m** arc-length along the route (`required_target_point_distances_m: [45.0]`), normalised by [50, 50] |
| **ego velocity** | `use_velocity: True`, `max_speed_mps: 25.0` |
| camera augmentation | `camera_augmentation_probability: 0.0` (off) |

### Outputs

```
trajectory_horizon_us   4_000_000   →  4 s
trajectory_interval_us    500_000   →  0.5 s  ⇒ 8 waypoints
predict_yaw             True
```

The 0.5 s cadence matches the nuPlan track's 2 Hz contract exactly.

### Auxiliary heads — trained, weights retained, all loss weights 1.0

- **BEV semantics** — 6 classes, 64 feature channels, downsample 4 / upsample 2
- **CenterNet box detection** — 4 class groups: `VEHICLE` · `PERSON` · `TWO_WHEELER` ·
  `TRAFFIC_SIGN+BARRIER+TRAFFIC_CONE+GENERIC_OBJECT`; 12 yaw bins, ≤90 boxes, confidence 0.3
- **disabled**: perspective semantics (`use_semantic: False`), depth (`use_depth: False`,
  weight 1e-5)

These force the backbone to learn explicit spatial structure — where agents are and what is drivable — rather
than regressing waypoints from pixels alone. A plausible contributor to its tight trajectory tracking.

---

## 4. 🔑 Route conditioning — the most transferable idea here

Our drivers consume the AlpaSim route as a **discrete command** (WA-JEPA: LEFT/STRAIGHT/RIGHT from a lateral
threshold; VaVAM the same). py123d uses a **continuous 2-D target point**, and the pipeline is worth copying.

From `evaluation/alpasim/help/driver_service.py`:

1. **`submit_route`** stores the incoming waypoints as a rig-frame polyline
   (`route_polyline_rig_xy`).
2. **Prepend the ego origin** if the first waypoint is farther than `route_resolution_m` (0.1 m):
   `route = vstack([zeros((1,2)), route])`. This closes the ~40 m gap created by
   `route_start_offset_m: 40.0`, so arc-length is measured **from the ego**, not from the first waypoint.
3. **`_extend_route(route, max(distances) + 2.0)`** — extrapolates along the final heading (estimated over a
   1 m look-back) when the route is shorter than 47 m. Docstring: *"Extends the route along its final heading so
   target points keep their trained distance near the clip end."* This keeps the conditioning in-distribution at
   the end of a clip, instead of silently shortening the target distance.
4. **`_rig_to_local_xy`** into the local frame, then **`_resample_route`** at **0.1 m** uniform arc-length
   (cumulative-distance interpolation, degenerate/zero-length segments dropped).
5. **`get_target_points`** interpolates that polyline at exactly 45.0 m of arc length, expressed in the
   **rear-axle frame**, and raises `InsufficientRouteError` rather than fabricating a point if the route is too
   short.

**Why this matters for us.** The AlpaSim route arrives ~40 m ahead and NaN-padded. A 45 m arc-length sample sits
just past that, in the usable window. Crucially, **training and evaluation share this exact recipe**
(`NavigationConditioning.from_scene` is used by both), so there is no train/test conditioning mismatch — a
failure mode we hit with VaVAM's μP shapes and WA-JEPA's step count.

Contrast with our own `command_from_route` (§6.46): a 5 m Euclidean gate that the 40 m offset made completely
inert, reducing an information-rich polyline to one of three symbols.

---

## 5. Training recipe

**Not distilled. Not RL. Plain imitation learning (behaviour cloning) plus supervised perception.**

```
15 epochs · bf16-mixed · 8 GPUs × 2 nodes (16 total) · global batch 64 (16/device)
lr 3e-4 · weight decay 0.01 · amsgrad · grad clip 1.0 (norm) · seed 0
```

### Data — public only

| source | split | source weight |
|---|---|---:|
| nuPlan | `nuplan_train` | 4.0 |
| nuPlan | `nuplan_val` | 4.0 |
| PhysicalAI-AV | `physical-ai-av_train` | 1.0 |
| PhysicalAI-AV | `physical-ai-av_val` | 1.0 |

≈ **46 % nuPlan per batch**. **No nuPlan test split** — and the public `navtest` benchmark is drawn from
nuPlan test (`dataset.name == "nuplan_test"`), so the public benchmark is genuinely held out for them.
Whether the *private* official set shares that provenance is unknown to us; no evidence either way.

### Loss weights — verified, no teacher signal

```
trajectory 1.0 · bev_semantic 1.0 · center_net_{heatmap,wh,offset,yaw_class,yaw_res,velocity} 1.0
semantic 1.0 (head disabled) · depth 1e-5 (head disabled)
```

Searched for `distil` / `teacher` / `kd` / `reward` / `critic` keys: **none**. The only "teacher" is the human
who drove the log.

### Two stages (per the model card)

1. **Perception pretraining** — planning decoder **off**, BEV-semantic + CenterNet auxiliary heads on.
2. **Planning posttraining** — planning decoder on, initialised from epoch-14 pretraining weights with
   `initial_weights_strict=false`.

The released file is **epoch 14 of 15** of stage 2.
*Minor inconsistency:* this `config.yaml` reports `initial_weights_file: None` despite the card describing a
warm start — most likely a local path stripped before release. Not worth over-reading.

---

## 6. Measured behaviour on our 400-scene set

Full table in [FINDINGS.md](FINDINGS.md). The essentials:

| | py123d-0014 | WA-JEPA s2 (ours, submitted) |
|---|---:|---:|
| local mean scene score | 0.8420 | **0.9247** |
| **`dist_to_gt_trajectory`** | **1.17** | 1.36 |
| at-fault collisions | 9 | **2** |
| zero-score scenes | 33 | **26** |
| distance driven / scene | 25.6 m | 27.0 m |
| **OFFICIAL PCS** | **~1470 (rank 2)** | **986 (rank 6)** |
| wall time, 400 scenes | **1963 s (4.4 s/scene)** | 3350 s (8.4 s/scene) |

It **takes more risk and tracks tighter**, and on the official distribution that trade is strongly correct.
It is also ~1.7× faster per scene than WA-JEPA at 62M vs 787M parameters, so throughput is a non-issue.

---

## 7. Could we train this ourselves?

**From scratch: not realistically.**

| | theirs | ours |
|---|---|---|
| GPUs | 16 (8 × 2 nodes) | 1 × RTX PRO 4000 Blackwell, 24 GB |
| schedule | 15 epochs pretrain + 15 posttrain | — |
| data | nuPlan + PAI, both splits, in 123D format | not downloaded |

~16× less compute against a 30-epoch two-stage schedule ⇒ weeks-to-months, monopolising the GPU we need for
evaluation. The data is the harder blocker: nuPlan in 123D format carries ~1,174 h of sensor logs at 10 Hz with
embedded JPEG cameras and LAZ lidar — multi-terabyte even with 5 of 8 cameras excluded. We have 1.8 TB free on
SeagateHub1 and 87 GB on storage.

**Finetuning their checkpoint: plausible.** Their card gives the recipe, and
`scripts/training/nuplan/latent_transfuser/posttrain.sh` derives per-GPU batch size from visible devices, so one
GPU works unmodified:

```bash
scripts/training/nuplan/latent_transfuser/posttrain.sh \
    initial_weights_file=outputs/checkpoints/resnet34_v0.1.0/model_0014.pth \
    initial_weights_strict=true
```

`initial_weights_strict=false` is required if any head is changed (BEV classes, detection classes). A feature
cache must be built first (`docs/training.md`, `docs/cache.md`).

**The open question is what we would finetune *toward*.** Continuing on nuPlan train/val repeats what they
already did with less compute. Improvement needs a signal about where their model is weak on the **private**
official distribution, which we have measured exactly once. Training is not our bottleneck — knowledge is.

---

## 8. Files in the checkpoint folder

```
model_0014.pth      237 MB   state dict, epoch 14 of posttraining
config.yaml          10.7 KB  training config; evaluation replays its policy_config
sensor_rig_0.yaml    98.6 KB  nuPlan train rig   ← use this for the nuPlan track
sensor_rig_1.yaml    72.4 KB  nuPlan val rig
sensor_rig_2.yaml    35.3 KB  Physical AI AV train rig  (PAI track only)
sensor_rig_3.yaml    12.0 KB  Physical AI AV val rig
README.md             6.3 KB  model card: recipe, usage, finetuning
```

Each rig is exported from a **single log** of its source and assumed representative of the whole source — the
card explicitly warns *"which might be not true"*. `sensor_rig_0.yaml` carries
`log_name: 2021.05.12.19.36.12_veh-35_00005_00204`.

---

## 9. Runtime and integration notes

- **Image base** `nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04` — **CUDA 12.8, so it runs on our Blackwell
  (sm_120) GPU**, unlike the cu124 sample-submission images which cannot be smoke-tested locally.
- **Entrypoint honours `ALPASIM_DRIVER_HOST` / `ALPASIM_DRIVER_PORT`** (defaults `0.0.0.0:6789`), so our
  `run-eval.sh` drives it unmodified.
- Driver config `garage_transfuser.yaml`: `device: cuda`, `image_decode_device: cpu`, `max_batch_size: 16`.
- `route_resolution_m: 0.1` (evaluation-side route resampling).
- Python ≥3.10 <3.14 · torch ≥2.8 <2.9 · torchvision ≥0.23 <0.24 · **numpy ≥2.1 <2.3** (the one conflict with
  our alpasim venv, which has 2.5.2 — resolved inside their image, so no host changes needed).
- Startup log to assert on: `Driving py123d_garage.policy.transfuser.transfuser_policy:TransfuserPolicy with
  /opt/checkpoint/model.pth`.

---

## 10. What is worth taking from this

1. **The 45 m continuous target point + `_extend_route` tail extrapolation** — directly applicable to any driver
   we run, and strictly more informative than a 3-way command. Section 4 has the full recipe.
2. **Auxiliary perception supervision** (detection + BEV semantics) as a way to force spatial grounding in a
   small backbone.
3. **The benchmark is an imitation benchmark.** `progress_clipped_rel` is progress *relative to the recorded
   human*; `dist_to_gt_trajectory` is *distance from the recorded human*. A model trained to imitate is directly
   optimising the eval metric — which is why 62M parameters of behaviour cloning beat 787M of world modelling by
   ~480 PCS.
4. **This checkpoint is our best available reference point**: known official score, best measured d2gt, fast, and
   permissively licensed.
