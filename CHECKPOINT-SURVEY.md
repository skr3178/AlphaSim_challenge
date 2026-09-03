# Open checkpoints usable for the AlpaSim nuPlan track — survey (2026-08-31)

Scope: every publicly downloadable, sensor-based driving policy trained on nuPlan / OpenScene /
NAVSIM (navtrain) that could plausibly sit behind `egodriver.EgodriverService`. Everything marked
**[verified]** was checked directly against the GitHub Releases API or the HF Hub API today (file
names + sizes). Scores are the authors' own numbers on NAVSIM `navtest` (PDMS = v1, EPDMS = v2)
or `navhard` (v2 two-stage) — none of them predict AlpaSim PCS.

## 0. What the contract actually gives a model

From `alpasim/src/grpc/alpasim_grpc/v0/egodriver.proto` and `NAVSIM_MODEL_ADAPTATION.md`:

| Available at inference | Not available |
|---|---|
| Up to 8 cameras (`CAM_F0 L0 L1 L2 R0 R1 R2 B0`), 1920×1080 RGB | LiDAR |
| Ego pose history + same-timestamp `DynamicState` (rig-frame velocity, acceleration) | HD map, lane graph |
| Route waypoints in rig frame (`submit_route`) → derivable high-level command | Tracked agents / boxes |
| Ground-truth trajectory (`submit_ground_truth`, not for use at inference) | Traffic-light state |

Hard limits: ≤ 0.1 s model work per `Drive`, ≤ 16 GiB VRAM, ≤ 40 GiB image, no network,
read-only rootfs, multiple concurrent replicas.

Consequences:
- **Any NAVSIM camera-only agent fits with an adapter.** The three-camera TransFuser-family
  contract (L0/F0/R0, command one-hot, velocity, acceleration) is already implemented in the
  sample submissions and reusable for anything with the same input signature.
- **Agents trained with a LiDAR branch (TransFuser, DiffusionDrive v1/v2, WoTE, GTRS-Dense
  "+L" configs) need either a camera-only checkpoint or retraining.** Check the training
  config before assuming a checkpoint is usable; the SimScale variants used in the samples are
  the camera-only (LTF-style) ones.
- **Privileged nuPlan planners (PDM-Closed/Open, PlanTF, PLUTO, Diffusion-Planner,
  Flow-Planner, CarPlanner) are excluded**: they consume map + agent tracks, which the driver
  never receives. Usable only with a full online perception stack, which no released checkpoint
  provides.

## 1. Tier A — already adapted for AlpaSim (zero adapter work)

| Model | Backbone / inputs | navtest EPDMS | navhard EPDMS | Ckpt | License | Notes |
|---|---|---|---|---|---|---|
| **VaVAM-S/B/L** (valeoai) | GPT-style video model on VQ tokens, 1 front cam, 8 frames | — (not evaluated on NAVSIM) | — | GitHub Releases v1.0.0, S 1.0 GB / B 1.75 GB / L 6.3 GB **[verified]** (see `VAVAM-CHECKPOINTS.md`) | code MIT, **weights research-only RAIL** | Trained on OpenDV + nuPlan + nuScenes. Stock B = **PCS 1590 (rank 6)**; rank 2 (`metamon`, 1720.7) and rank 3 (`symphi`) are VaVAM-based. |
| **SimScale LTF** (R34) | 3 cams, camera-only | 84.4 | 30.3 | `datasets/OpenDriveLab/SimScale/SimScale_ckpts/LTF/ltf_sim_{navtest,navhard}.ckpt` 225 MB **[verified]** | Apache-2.0 | `sample_submission_simscale_navsim_transfuser` |
| **SimScale DiffusionDrive** (R34) | 3 cams | 85.9 | 32.6 | `.../DiffusionDrive/diffusiondrive_sim_{navtest,navhard}.ckpt` 244 MB **[verified]** | Apache-2.0 | `sample_submission_simscale_navsim_diffusiondrive` |
| **SimScale GTRS-Dense R34** | 3 cams, 16 384-vocab scorer | 84.0 / 84.6 (expert / reward) | 46.1 / 46.9 | `.../GTRS_Dense/gtrs_dense_resnet_sim_{expert,reward}_{navtest,navhard}.ckpt` 269 MB **[verified]** | Apache-2.0 | `sample_submission_simscale_navsim_gtrs_dense`. **OpenDriveLab's own submission of this = PCS 1366 (rank 9)** — 220 below stock VaVAM. |
| **SimScale GTRS-Dense V2-99** | 3 cams | 84.8 | 47.7 / 48.0 | `.../GTRS_Dense/gtrs_dense_vov_sim_{expert,reward}_{navtest,navhard}.ckpt` 332 MB **[verified]** | Apache-2.0 | `sample_submission_simscale_navsim_gtrs_dense_vov_reward` (referenced in the adaptation doc) |
| **LTFv6** (LEAD, autonomousvision) | 1 stitched 256×1920 image, command, speed, accel | ~v1 baseline class | — | `ln2697/ltfv6-navsim/model_0060.pth` **[verified]** | Apache-2.0 | This is the "Latent TransFuser v6 policy developed for NAVSIM" that the upstream `alpasim` `transfuser` driver already speaks. Outputs in CARLA (left-handed) convention — conversion required. |

Leaderboard reality check (2026-08-30 pull, `leaderboard/SUMMARY.md`): the best non-VaVAM
NAVSIM-family entries visible on the board are GTRS-Dense at 1366 and a DrivoR attempt
(`team-vt`, `drivor-track2-…-cam4`) at **945 — below the straight-line starter (1000)**. That is
almost certainly an adapter/frame bug, not model quality, but it is the only public data point
for a ViT planner on this track.

## 2. Tier B — camera-only NAVSIM agents, small & fast, permissive license, adapter needed

Same 3-camera + ego-status contract as Tier A ⇒ reuse `driver.py` / `batch_worker.py` /
`preprocessing.py`; only `Policy.predict_batch` changes. All R34-class models are ≥ 45 FPS on a
single GPU and < 1 GB, so the 0.1 s / 16 GiB limits are not a concern.

| Model | Venue | Backbone / inputs | navtest PDMS / EPDMS | navhard | Ckpt | License |
|---|---|---|---|---|---|---|
| **DiffusionDriveV2** | arXiv 2512.07745 | R34; **trained 3×C + LiDAR** in NAVSIM — verify before use | 91.2 / 85.5 | — | `hustvl/DiffusionDriveV2`: `diffusiondrivev2_rl.ckpt` 235 MB, `diffusiondrivev2_sel.ckpt` 381 MB **[verified]** | MIT |
| **MeanFuser** | CVPR 2026 | R34, one-step MeanFlow, 59 FPS | 89.0 / 89.5 | — | Google Drive (README table) | Apache-2.0 |
| **BeyondDrive family** | ECCV 2026 | R34 hard-negative fine-tunes of: LTFv7 **89.8**, MeanFuser+BD **90.3**, DiffusionDrive+BD 89.2, WoTE+BD 89.2, LTF* 88.7, FlowPolicy 87.0 | v1 PDMS as listed | — | Google Drive (README table); "LTFv7" only exists here | Apache-2.0 |
| **WoTE** | ICCV 2025 | R34 + BEV world model, **3×C + L** | 88.3 / — | — | Google Drive | Apache-2.0 |
| **iPad** | arXiv 2505.15111 | R34 proposal-centric, camera | 91.7 EPDMS claimed (v2 navtest) | — | Google Drive folder | not stated |
| **DriveSuprim** | AAAI 2026 | camera-only; R34 / V2-99 / ViT-L | EPDMS 83.1 / 86.0 / 87.1 (v2 navtest); 93.5 PDMS best | — | `alkaid-2000/DriveSuprim/model_ckpt/drivesuprim_{r34,vov,vit}.ckpt` **[verified]** | Apache-2.0 |
| **HDP / DP-VLA base** | arXiv 2602.22801 | Florence-2 encoder + DiT, 10-step DPM-solver, "meets 10 Hz" | 88.6 / — | — | `ZhengYinan2001/DP-VLA/model.safetensors` 4.3 GB **[verified]** | MIT |
| **navsim_baselines** (TransFuser / LTF / EgoStatusMLP ×3 seeds) | NeurIPS 2024 | R34; TransFuser is 3×C+L, LTF camera-only | ~84 / — | — | `autonomousvision/navsim_baselines` **[verified]** | Apache-2.0 |

## 3. Tier C — stronger ViT / multi-camera planners (top of NAVSIM v2), adapter + budget check needed

These are the models with real headroom over the R34 family, and the only ones that natively
consume **more than the three front cameras** (relevant to backlog item B5). They need the
NAVSIM camera layout mapped onto AlpaSim's 8 logical IDs and a latency measurement on the
target GPU.

| Model | Venue | Backbone / inputs | navtest | navhard EPDMS | Ckpt | License / size | Budget risk |
|---|---|---|---|---|---|---|---|
| **DrivoR** | CVPR 2026 | ViT-S DINOv2 registers, **multi-cam** (`focus_front_cam=false`), 64 proposals + scorer | 93.1–94.6 PDMS | **48.3 → 54.6** (with 134k SimScale co-training) | GitHub Releases: `drivor_Nav2_10epochs.pth`, `nav2_30_epochs_with_134k_simscale_85ktrain_54.6.pth`, `drivor_Nav1_25epochs.pth`, … all 306 MB **[verified]** | Apache-2.0 | Low — ViT-S. Repo is Nav1-based; Nav2 eval needs the official navsim repo (issue #13). Needs `numpy==1.26.4`. |
| **TOAD** (on DrivoR) | arXiv 2606.07170 | Test-time CEM against DrivoR's frozen scorer, no retraining | 94.7 PDMS | **56.3** (current v2 SOTA) | code `valeoai/TOAD`; uses DrivoR ckpts | Apache-2.0 | CEM iterations add latency — must be measured against 0.1 s. |
| **CLOVER** | arXiv 2605.15120 | DINOv2 ViT-S generator + scorer (DrivoR lineage), closed-loop self-distillation | **94.5 / 90.4** | — | GitHub Releases `ckpt`: `stage1.ckpt` 306 MB, `stage2.ckpt` 420 MB **[verified]** | Apache-2.0 | Low. Official training code not yet released; inference + ckpt are. |
| **RAP-DINO** | ICLR 2026 | DINOv3-h16+ (888 M params), rasterisation-augmented | **93.8 PDMS** | v2 ckpt exists | `Lanl11/RAP_ckpts/RAP_DINO_navsimv{1,2}.ckpt` **[verified]** | Apache-2.0 | ViT-H at 0.1 s is marginal on a 4090; ~3.5 GB weights OK. |
| **Drive-JEPA** | arXiv 2601.22032 | V-JEPA ViT-L video encoder; perception-based and **perception-free single-front-cam** variants | 93.3 (93.7 pf) / 87.8 | — | HF *dataset* `LinhanWang/Drive-JEPA`: `drive_jepa_perception_{based,free}_agent_vitl*.ckpt` 3.7 GB **[verified]** | CC0 (as listed) | ViT-L over a frame stack; latency unmeasured. |
| **WA-JEPA** | arXiv 2608.20974 (Aug 2026) | V-JEPA 2.1 ViT-L/16 + 12-layer joint flow predictor (12 sampling steps); **4 cams L0/F0/R0/B0 @ 256×512, 4 history frames @ 2 Hz**, ego status `[cmd onehot(4), vx, vy, ax, ay]`; 8 waypoints @ 2 Hz (4 s) | 91.8 PDMS / **91.7 EPDMS** (10-seed σ 0.05) | — (not reported) | `AFARI-Research/WA-JEPA/model_state_dict.pt` 1.58 GB **[verified]** | Apache-2.0 (code + weights) | VRAM fine (~1.6 GB weights). Latency **unmeasured**: ViT-L over 16 frames + 12 flow steps per tick. **Only released model with zero-shot closed-loop evidence under neural rendering**: HUGSIM (3DGS, reactive agents, 436 scenes, no HUGSIM training) HD-Score **0.4462 vs DrivoR 0.3252 / LTF 0.2310**; NC 0.686 vs 0.522, TTC 0.612 vs 0.462, RC 0.569 vs 0.472 — i.e. fewer collisions and more route completion, exactly the ZOIB zero-branch levers. Ships `close_loop/hugsim_planner.py` (history buffer, 2 Hz striding, camera-slot/command/frame mapping) + `datasets/nav_command_infer.py` (command from trajectory geometry) — a near-template for an AlpaSim adapter (route waypoints → command). Note HUGSIM Comf 0.66 vs 0.94 for DrivoR: comfort is unscored here, but discontinuity was our `w_disc` topic. |
| **DVGT-2** | arXiv 2604.00813 | 1.8 B Vision-Geometry-Action, multi-view streaming, DINOv3 | 89.7 EPDMS | — | `RainyNight/DVGT-2/dvgt2.pt` 6.8 GB **[verified]** | not stated | 1.8 B + dense geometry head; latency likely > 0.1 s. |
| **GTRS official (NVlabs)** | CVPR'25 challenge winner | V2-99 @ 512×2048, camera-only; GTRS-Dense / GTRS-Aug / Hydra-MDP-img / DiffusionPolicy | — | 41.7 / 42.1 / 37.5 / 25.6 | `Zzxxxxxxxx/gtrs/{gtrs_dense_vov,gtrs_aug_vov,hydra_mdp_vov,gtrs_dp}.ckpt` (linked from README) | Apache-2.0 | Fine; the SimScale V2-99 variants (48.0) supersede these. |
| **SimWAM** | arXiv 2608.07468 (Aug 2026) | Wan2.2-5B video DiT (frozen prior) + 0.2–1 B action DiT, **1 front cam 384×672**, no future-frame generation at inference | **91.5 / 90.2** | 37.6 | `H-EmbodVis/SimWAM/weights/SimWAM.pt`, `SimWAM-RL.pt`, **`SimWAM-PAI-AV.pt`** — 12.0 GB each **[verified]** | code Apache-2.0, weights "other" | 12 GB checkpoint ⇒ ~12 GB bf16 resident + activations: **right at the 16 GiB line**. **Latency is the blocker, measured by the authors (paper Tab. 13, A100): 518 ms at 10 flow steps (90.3 PDMS), 297 ms at 5, 115 ms at 1 step (68.9 PDMS)** — the Wan2.2-5B encoder + VAE + T5 forward alone exceeds the 0.1 s tick. Conceptually the closest cousin to VaVAM with a far higher NAVSIM score, and it ships a PAI-AV checkpoint too, but not usable at 10 Hz without replacing the video expert. |

## 4. Not usable / not really released

| Model | Why not |
|---|---|
| **Hydra-MDP / Hydra-MDP++ / Hydra-NeXt** (NVlabs) | Official repo: "Delay in code and model release due to company policy". Only the image-only Hydra-MDP ckpt inside the GTRS repo exists. |
| **ResAD** (CVPR 2026) | `Duckyee728/ResAD-released` is a one-line stub; no code, no weights. |
| **Latent-WAM** (89.3 EPDMS) | Paper only; no repo found. |
| **WAM-Diff, Hydra-NeXt, SeerDrive, GoalFlow, SparseDriveV2, GraphWorld, …** | Numbers in tables, no verified weights. |
| **Alpamayo-R1-10B / Alpamayo-1.5-10B** (NVIDIA) | Supported AlpaSim driver, but trained on PhysicalAI-AV (not nuPlan), **min 24 GB VRAM**, OpenMDW-1.1 non-commercial, autoregressive reasoning ≫ 0.1 s. Would need INT4 + no-CoT mode to even fit. |
| **OneVL_NAVSIM** (xiaomi-research) | ~30 GB safetensors (≈ 15 B params); exceeds 16 GiB without aggressive quantisation. |
| **AutoVLA, OpenDriveVLA, DriveVLA-W0, ReCogDrive, AutoDrive-R²** | VLA models on 3–8 B VLMs; weights partially available (AutoVLA merged-LoRA on HF) but autoregressive decode does not meet 0.1 s; NAVSIM scores (≤ 87–88) below the R34 diffusion/flow family anyway. |
| **ReSim** (OpenDriveLab) | World model + Video2Reward, pretrained on OpenDV + NavSim + CARLA. Not a policy; possible test-time *scorer* only, and far too slow for 0.1 s. |
| **PDM-Closed / PlanTF / PLUTO / Diffusion-Planner / Flow-Planner** | Privileged inputs (map + agents) — see §0. |

## 5. Recommendations against the backlog

1. **Cheapest upside: CLOVER or DrivoR (+ TOAD) behind the existing GTRS-style adapter.**
   Both are ViT-S, ~300–420 MB, Apache-2.0, camera-only, and sit 6–15 EPDMS above anything
   currently on the board. DrivoR natively uses all NAVSIM cameras — the only released model
   that directly exercises B5 (side cameras). Budget: trivially inside 16 GiB; latency to
   measure but ViT-S + 64 proposals should be well under 0.1 s on a 4090.
2. **Keep VaVAM as the anchor** — it is the only model with measured PCS (1590 stock, 1720.7
   tuned by `metamon`), and the licence (research-only) is evidently acceptable to the
   organisers since they ship it as a sample.
3. **SimWAM — dropped 2026-09-01 on latency.** Same single-front-cam video-prior idea as VaVAM,
   91.5 PDMS, Apache-2.0 code, and a PAI-AV checkpoint, but the authors' own numbers (Tab. 13,
   A100) are 518 ms/prediction at the 10 steps the score needs and 115 ms even at 1 step: ~5× the
   stock-B driver. The binding gate is total wall time (official margin was 9 %, `strategy.md` §5),
   with the model replanning at 2 Hz sim time and 8 streams per GPU — so a ~5× slower driver is
   borderline-to-failing, not impossible. If ever revisited: 5 steps (297 ms), cached T5 command
   embeddings, CUDA graphs, fp8, then `capture/driver_loadtest.py --streams 8` vs stock B is the
   arbiter. Not worth a slot while WA-JEPA is untested (see 3b).
3e. **WA-JEPA 400-SCENE CONFIRM (2026-09-03) — 4 of 5 pre-registered gates pass; progress gate fails.**
   `wajepa-s2-400` (2 steps, 4 cams) vs `confirm400-mup-g100`, paired on navtest_local400, official
   rollouts[].score. VALIDITY 400/400, 0 inference failures.
   score **0.8813 -> 0.9247** (+0.0434) | at-fault **13 -> 2** | corridor 33 -> 24 | zeros 46 -> 26 |
   lateral med/p90 0.90/3.45 -> **0.50/2.64** | Drive 290 ms (48.6% of wall) | per-city at-fault
   pitt 6->0, boston 4->1, vegas 3->0, singapore 0->1.
   **Gate failed: mean progress 1.0204 -> 0.9565 (required >=0.989).** But the scoring-relevant count is
   TIED at 37/37 scenes below the 0.8 saturation threshold, and it is not the same 37 — only 9 overlap,
   28 dropped below and 28 different ones rose above (a real 28-for-28 exchange). The mean fell because
   233 scenes sit lower but still above 0.8, which is score-neutral. The peer session pre-registered the
   gate (SETUP-NOTES 6.31) with the rationale "a slower policy pushes more scenes under 0.8"; that
   mechanism did NOT fire. Adjudication left to them rather than retrofitted here.
   **Their other prediction resolved in favour:** 0-4 at-fault if the n=100 zero was real, 9-13 if noise
   -> landed at 2. The zero-collision result is real, not a lucky draw.
   **Limitation:** only one cand#2 draw exists at n=400, so there is NO noise bracket at this sample size.

3d. **WA-JEPA T1 SCREEN PASSED (2026-09-03) — clears the noise bracket on all three arms.**
   Paired on navtest_local100, official per-scene scores from `results-summary.json` rollouts[]:
   cand#2 draws 0.9067 / 0.8582 / 0.9064 (bracket [0.8582, 0.9067], spread 0.0485, = seed noise);
   WA-JEPA **12 steps 0.9667**, **4 steps 0.9493**, **2 steps 0.9499**. All three above the bracket top.
   **Zero at-fault collisions in all three arms** (300 scenes of driving) vs 3/7/3 for cand#2 and 6 for
   the route follower. Lateral med/p90: 0.63/1.76 (s12), 0.35/2.43 (s4), 0.42/2.38 (s2) vs cand#2 ~1.0/3.15
   and follower 0.67/2.29. Progress below 0.8 on 8/5/4 scenes vs cand#2 9 and follower 16 — i.e. it does
   NOT pay the follower's progress tax. Independently verified by a peer session from the same field.
   **2 steps dominates 4**: identical score at 295 ms vs 520 ms. Cost is the open risk, not quality:
   1516/520/295 ms per call = 104%/58.3%/38.9% of local wall vs cand#2's 103 ms/16.8%. Stock B used
   2265 s of a 2485 s official limit (9.7% margin), so even 2 steps is ~2.3x its driver burden —
   `capture/driver_loadtest.py --streams 8` and a 400-scene paired confirm are the gates before submitting.
   Videos: `viz/wajepa-s12-on-cand2-failures/` (53 clips, 44 pass / 6 partial / 3 corridor on the 15
   navtest_local100 scenes where cand#2 scored 0).

3c. **WA-JEPA integrated + T0-smoke PASSED (2026-09-03).** Additive package
   `e2e_challenge/sample_submission_wajepa` (driver cloned from the GTRS sample: 4 cams L0/F0/R0/B0,
   4-frame 2Hz history, ego-status+history-traj inputs, cached 4s plan) + preset `dev_fast2_wajepa`
   (dev_fast2 + 4 cameras) + image `alpasim-e2e-wajepa-driver:local`. VaVAM package untouched. Smoke:
   20/20 scenes, 200/200 inferences (10/scene = 2Hz gate), inference_error=0, straight_fallback=0,
   driver 33.7% of wall @ 4 steps, peak driver VRAM 5.2 GiB / GPU 14.2 GiB. Strict checkpoint load OK.
   **Latency-burden note:** inferences/scene is fixed at 10 by the 0.5s inference gate x 2Hz camera
   frames (frames are 2Hz local AND official). So the official 10Hz Drive loop only adds cheap cached
   serves between the same 10 inferences — mean per-call latency drops ~5x, but total driver wall
   burden does NOT. Screen by driver-share-of-wall per step-count (12/4/2), not per-call ms. Next: step
   screen on navtest_local100.

3b. **WA-JEPA (added 2026-09-01) is the strongest new candidate for the *closed-loop* problem specifically.**
   Its navtest score is in the same band as CLOVER/DrivoR, but it is the only checkpoint with a
   published zero-shot closed-loop result under Gaussian-splat rendering with reactive agents
   (HUGSIM), where it beats DrivoR by +0.12 HD-Score, mostly via collision rate and route
   completion. That is the closest public proxy for AlpaSim's MTGS loop. Two unknowns before
   committing: (a) tick latency on the target GPU — ViT-L × 4 cams × 4 frames + 12 flow steps;
   measure `plan()` from `close_loop/hugsim_planner.py` on dummy frames, and sweep
   `num_inference_steps` 12→4 if over 0.1 s; (b) no navhard number, so its synthetic-stage
   robustness is inferred from HUGSIM only. Adapter is mostly mapping: CAM_L0/F0/R0/B0 → its
   fixed camera-slot order, 10 Hz loop → 2 Hz history stride of 5, route waypoints → command via
   `nav_command_infer.py`, 2 Hz waypoints → resampled trajectory. Its HUGSIM doc lists the four
   silent-failure pitfalls (slot order, stride, command encoding, output frame) — same list applies.
4. **Skip DiffusionDriveV2 / WoTE unless a camera-only config is confirmed** — the NAVSIM
   defaults include the LiDAR branch and AlpaSim never sends LiDAR.
5. **On B6 (sim-domain fine-tune):** SimScale's 2.6 TB of MTGS-rendered pseudo-expert data
   (`synthetic_reaction_pdm_v1.0-*`, CC-BY-NC-SA) is the *legitimate* render-domain training
   set — it is derived from navtrain, not navtest. DrivoR's +6 EPDMS from co-training on it is
   the strongest published evidence that render-domain adaptation pays. That replaces the
   "fine-tune on locally rendered navtest" plan with a defensible one.
6. **Licence hygiene for the report** (from the challenge rules: "only publicly available
   datasets, annotations, and model weights"): everything in Tiers A–C qualifies; keep upstream
   LICENSE files, record SHA-256 of each checkpoint, `pretrained=False`, `strict=True`.

## Sources

- AlpaSim challenge page: https://nvidia-alpasime2eclosedloopchallenge2026.hf.space/
- NAVSIM: https://github.com/autonomousvision/navsim · baselines https://huggingface.co/autonomousvision/navsim_baselines
- Awesome list w/ scores: https://github.com/wjl2244/Awesome-End-to-End-Autonomous-Driving
- SimScale: https://github.com/OpenDriveLab/SimScale · https://huggingface.co/datasets/OpenDriveLab/SimScale
- VaVAM: https://github.com/valeoai/VideoActionModel/releases/tag/v1.0.0
- LTFv6 / LEAD: https://huggingface.co/ln2697/ltfv6-navsim · https://github.com/autonomousvision/lead
- GTRS: https://github.com/NVlabs/GTRS · Hydra-MDP: https://github.com/NVlabs/Hydra-MDP
- DiffusionDrive: https://github.com/hustvl/DiffusionDrive · V2: https://github.com/hustvl/DiffusionDriveV2 · https://huggingface.co/hustvl/DiffusionDriveV2
- MeanFuser: https://github.com/wjl2244/MeanFuser · BeyondDrive: https://github.com/wjl2244/BeyondDrive
- WoTE: https://github.com/liyingyanUCAS/WoTE · iPad: https://github.com/Kguo-cs/iPad
- DriveSuprim: https://github.com/William-Yao-2000/DriveSuprim · https://huggingface.co/alkaid-2000/DriveSuprim
- DrivoR: https://github.com/valeoai/DrivoR · TOAD: https://github.com/valeoai/TOAD · https://arxiv.org/abs/2606.07170
- CLOVER: https://github.com/WilliamXuanYu/CLOVER · https://arxiv.org/abs/2605.15120
- RAP: https://github.com/vita-epfl/RAP · https://huggingface.co/Lanl11/RAP_ckpts
- WA-JEPA: https://github.com/AFARI-Research/WA-JEPA · https://huggingface.co/AFARI-Research/WA-JEPA · https://arxiv.org/abs/2608.20974
- Drive-JEPA: https://github.com/linhanwang/Drive-JEPA · https://huggingface.co/datasets/LinhanWang/Drive-JEPA
- DVGT: https://github.com/wzzheng/DVGT · https://huggingface.co/RainyNight/DVGT-2
- SimWAM: https://github.com/H-EmbodVis/SimWAM · https://huggingface.co/H-EmbodVis/SimWAM
- HDP / DP-VLA: https://github.com/ZhengYinan-AIR/Hyper-Diffusion-Planner · https://huggingface.co/ZhengYinan2001/DP-VLA
- ResAD: https://github.com/Duckyee728/ResAD-released · Latent-WAM: https://arxiv.org/abs/2603.24581
- Alpamayo: https://huggingface.co/nvidia/Alpamayo-1.5-10B · https://huggingface.co/nvidia/Alpamayo-R1-10B
- OneVL: https://huggingface.co/xiaomi-research/OneVL_NAVSIM · AutoVLA: https://github.com/ucla-mobility/AutoVLA · DriveVLA-W0: https://github.com/BraveGroup/DriveVLA-W0
- ReSim: https://github.com/OpenDriveLab/ReSim
- nuPlan privileged planners: https://github.com/ZhengYinan-AIR/Diffusion-Planner · https://github.com/jchengai/pluto · https://github.com/jchengai/planTF · https://github.com/DiffusionAD/Flow-Planner
