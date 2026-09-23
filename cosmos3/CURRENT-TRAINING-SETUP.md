# Cosmos3-Edge driving-head training setup

Updated: **2026-09-19**. Workspace: `/home/skr/Downloads/alpasim_challenge`.

This is the current handoff for our training procedure, inputs, evidence and remaining work. Older reports linked below preserve their original experiments. Saving this document does **not** authorize or start training, downloads, simulation or submission.

**Active follow-up:** the user has now explicitly approved frozen-backbone,
head-only training and up to 20 GiB of missing captured-camera acquisition, after
checking existing data. See [RAW-CAMERA-PILOT.md](RAW-CAMERA-PILOT.md) for the
bounded execution scope and current progress. Earlier pending-download statements
below describe the preceding snapshot; protected evaluation splits remain intact.

## 1. Approach and current decision

**Keep Cosmos3-Edge frozen and train a small driving head.** We are adapting a pretrained representation, not fine-tuning Cosmos backbone weights or training a world model from scratch.

**Primary training direction: real-camera-first.** Build the main corpus from independent nuPlan training recordings with matching captured front-camera images and recorded expert trajectories. [OpenScene](https://github.com/OpenDriveLab/OpenScene) redistributes nuPlan sensor data at 2 Hz, potentially matching our half-second history spacing; exact timestamps, coverage and local metadata correspondence still require validation.

The agreed order is:

1. Establish an independent, image-backed real-driving training corpus.
2. Validate timestamps, calibration, causal state, runtime-compatible navigation and future targets; preserve whole-log splits and check competition eligibility.
3. Train only the head and compare against a matched state/route-only control.
4. Validate on both held-out real recordings and held-out AlpaSim scenes.
5. Consider aligned simulator training or recovery examples only when measured failures justify them.

This supersedes the earlier proposal to make the nine training-side rendered temporal candidates the immediate next training run. The 41 audited rendered candidates remain optional engineering diagnostics, not the primary training corpus. No new corpus, split, download or run is activated by this decision.

```text
Three captured front-camera images from one real driving recording
    -> frozen Cosmos generator + VAE -> cached image features
    -> small driving head, also given causal ego motion/history and sparse route
    -> 40 future positions and headings

Matching recorded expert future -> training loss only; never a model input
Validation -> separate real recordings AND separate AlpaSim scenes
```

Begin with a bounded real-camera pilot once its data and scope are ready. Do not start a long job simply because the numerical pipeline runs. Odyssey reports **20 hours of simulated driving data**, not 20 GPU-hours; its driving backbone stayed frozen. Our approach borrows that frozen-backbone/learned-policy principle, not its unpublished recipe or an established convergence budget. [Primary announcement](https://odyssey.systems/introducing-odyssey-3).

### Why real-camera-first, without ruling out simulation

The demonstrated problem in our saved rollouts is **observation–target mismatch**, not measured renderer inaccuracy. An evaluated policy can drift away from the human's recorded state even with a perfect renderer. Re-expressing the old expert future in the shifted ego frame does not establish valid recovery supervision.

| Source | Role in this plan |
| --- | --- |
| Captured cameras + matching recorded expert trajectories | Primary training data, after timestamp, frame, route and split validation |
| Expert-path renders with matching ego/actor states and labels | Possible later supplement; not inherently invalid because the images are rendered |
| Arbitrary policy-rollout renders + unchanged recorded expert future | Not accepted indiscriminately; require alignment checks or separately validated recovery labels |

The challenge's nuPlan track uses MTGS rendering, so real-to-rendered appearance transfer and closed-loop behavior still need evaluation. Real-camera training is not a guarantee of leaderboard transfer. [Organizer track description](https://github.com/NVlabs/alpasim/blob/e2e_challenge/e2e_challenge/README.md#nuplan--mtgs).

## 2. Components and local locations

| Component | Current setup |
| --- | --- |
| Pretrained model | `nvidia/Cosmos3-Edge`, pinned revision `344d602b128d1bbdacb43b08d0a3626f46343e29` |
| Local checkpoint | `/media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918/checkpoint` |
| Frozen components | Full generator transformer and VAE; no backbone gradients or optimizer updates |
| Feature recipe | `cosmos3-generator-clean-image-v1`; clean observed-image features, not generated future video |
| Feature extraction | Images encoded independently; temporal fusion happens in the head |
| Image preprocessing | RGB, bilinear letterbox to **256×448**, black padding, normalized to **[−1,1]** |
| Feature representation | **32 spatial tokens × 2,048 channels per image** |
| Head | **815,235 trainable parameters**, width 128, two transformer-decoder layers, four attention heads |
| Head output | 40 future `[x, y, sin(yaw), cos(yaw)]` poses at 10 Hz, covering **0.1–4.0 s** |
| Parameterization | Learned corrections to a causal velocity/yaw-rate baseline; not a hidden fallback |
| Model environment | `/media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python` |
| ASL/data-audit environment | `/home/skr/alpasim-challenge/alpasim/.venv/bin/python` |
| Primary training sources | Independent nuPlan training DBs + matching captured `CAM_F0` images; final roots/windows/manifest pending |
| Raw-data inventory and exclusions | [TRAINING-READINESS.md](TRAINING-READINESS.md) and [protected-splits.json](artifacts/training-readiness-20260918/protected-splits.json) |
| Optional rendered diagnostic rollouts | `/media/skr/storage/alpasim-runs/confirm400-mup-g100/rollouts` |

The feature tap is an experimental representation, not a validated driving encoder. The older generative-action AlpaSim smoke test is a **different path**, not a test of this learned head.

## 3. Required data and tensor interface

Shapes below are **per example**, before adding a batch dimension. Positions are metres in the current rear-axle frame; angles/rates use radians and seconds.

| Field | Contents / shape | Rule |
| --- | --- | --- |
| Camera observations | Captured `CAM_F0` images at approximately **t−1.0, t−0.5, t** for primary training | Match image identities/exposure timestamps to the same recording; never repeat or borrow future images to fill history; label any rendered diagnostic source explicitly |
| Frozen image features | `[3, 32, 2048]` | Derived solely from observed images using the pinned feature recipe |
| Ego state | `[3]`: forward velocity, leftward velocity, yaw rate | Use past/current poses only, with the versioned causal adapter; raw-DB ingestion must reproduce the runtime frame/timing contract |
| Ego history | `[3, 4]`: relative x, y, sin(yaw), cos(yaw) at image timestamps | Express every history pose relative to the current rear axle |
| History validity | Boolean `[3]` | Full temporal candidates require `[true, true, true]`; old single-frame pilots had missing past slots masked |
| Image ages | `[3]` | Compute from exposure timestamps, not nominal 2 Hz alone; the audited rendered triplets had `[1.0, 0.5, 0.0]` seconds |
| Navigation route | Up to 32 XY points, padded to `[32, 2]`, plus Boolean `[32]` mask | Raw recordings need a validated runtime-compatible route from allowed navigation/map information, not the future target trajectory; saved ASLs use the route actually supplied to the driver |
| Calibration | Camera model, intrinsics, sensor/rig transform, image dimensions and preprocessing transform | Preserve provenance and verify consistency; calibration is not an explicit numerical input to the current head |
| Expert targets | `[40, 4]`, plus Boolean `[40]` mask | Recorded expert poses at t+0.1…t+4.0 s, transformed into the same current frame; supervision only; validate pose sampling/interpolation independently of camera frequency, with no extrapolation over missing future coverage |
| Identity/provenance | Scene, source log, timestamps, role, hashes and recipe versions | Used for checks/splits, never learned identifiers |

LiDAR, all eight camera views, BEV semantic labels and object-detection labels are **not required for this initial head-only setup**. They would be additional modeling choices, not missing prerequisites for the implemented head.

Do not use the suspect legacy logged velocity fields directly or derive model-input velocity from future expert targets. Use [state_adapter.py](training/state_adapter.py) consistently; deployment integration/noisy-odometry validation remain pending.

The raw-camera/DB exporter and runtime-compatible route construction are **not implemented/validated by the existing ASL exporter**. Camera files alone do not close these gaps. Calibration, source-pose reference point and timestamp semantics must be checked before treating real recordings and runtime inputs as interchangeable.

## 4. What data is available now

✅ = checked within the stated scope; ⚠️ = limited/partial; ⏳ = pending.

### Primary real-camera corpus — preparation pending

| Status | Requirement | Current evidence |
| --- | --- | --- |
| ✅ | Local nuPlan metadata inventory | Training DBs and camera references identified; paths and coverage are in [TRAINING-READINESS.md](TRAINING-READINESS.md) |
| ⚠️ | Matching captured front-camera files | Earlier audit found none matching those DBs in its inspected roots; this is not a claim that no images exist elsewhere. Recheck chosen source roots before downloading |
| ⚠️ | Small camera-acquisition option | [download_camera_pilot.py](download_camera_pilot.py) passed metadata/split preflight for three independent training windows; `--download` has not run |
| ⏳ | Activated real-camera training/validation manifest | Exact windows, whole-log roles, diversity, source hashes and run scope still need pinning |
| ⏳ | Raw-camera/DB export and interface parity | Verify history, state, calibration, route and future-target construction; no training-ready raw-camera dataset/cache exists from this work |
| ⏳ | Competition eligibility | Check the intended training sources and current rules before treating a trained head as submission-eligible |

The metadata inventory is not downloaded footage or verified usable training hours. Count usable unique intervals only after files, timing, history/future margins and exclusions are validated. OpenScene's nominal 2 Hz does not prove any particular window is complete.

### Existing rendered data — retained for diagnostics

| Status | Requirement | Current evidence |
| --- | --- | --- |
| ✅ | Saved rendered front images | All **400** initial images decoded; all **4,400** saved front frames decoded in the temporal audit |
| ✅ | Initial single-frame data | **398/400** initial observations pass input/alignment/target checks; two routes are invalid |
| ✅ | Full temporal candidate data | **41 examples from 41 scenes** pass three-frame history, state/route, expert alignment and full four-second-target checks |
| ✅ | Candidate array construction | Follow-up read-only check reconstructed input/target arrays in memory for all **41**; shapes, masks, timestamps and finite values passed |
| ✅ | Candidate calibration structure | All **41** had matching 1920×1080 RGB dimensions, finite positive pinhole focal lengths, in-image principal points and parseable camera poses |
| ⚠️ | Calibration / deployment semantics | Structural checks do not independently certify physical calibration or noisy deployment state |
| ⏳ | Optional rendered temporal manifest | Earlier nine training-side / 32 other-log proposal is **not activated** and is no longer the primary next training step |
| ⏳ | Exported temporal dataset and feature cache | **Not created**; the 41 records are audit candidates, not a loadable training dataset |
| ⏳ | Competition training-data eligibility | Unresolved for public-navtest-derived training; existing fitted heads remain **local-only** |

### Why 41 rather than 400?

All 400 saved rollouts contain camera sequences. The issue is agreement between the **evaluated policy's viewpoint/motion** and the **recorded human expert's future**, not simply missing pixels.

1. There are 3,600 post-priming Drive requests; 3,200 have all three camera-history frames.
2. Saved expert references end at **5.500 s**. Full history begins at **1.017 s**, so only that anchor per scene also supports the required four-second future. The next anchor, 1.517 s, needs labels through 5.517 s, outside the saved reference.
3. That leaves 400 candidate anchors, reduced to 398 by route/input checks.
4. Require history poses within **0.10 m / 0.01 rad** of the expert, including true/observed pose comparisons and exposure-boundary checks. Only **41** pass. All 41 also pass the additional **0.50 m/s / 0.05 rad/s** backward-interval motion checks.

Each passing example uses images at **0.017, 0.517 and 1.017 s**, with expert targets through **5.017 s**. Thresholds were fixed before the audit; no future-label extrapolation was used. Rejected scenes are not invalid evaluations; they simply fail this conservative imitation-data filter.

The 41 examples span four cities and 12 source logs, but remain a tiny, selection-biased development sample. Filtering for expert agreement does not supply recovery-from-drift supervision or establish poor renderer fidelity. They do not represent the availability of temporal examples in a separate real-camera training corpus.

## 5. Splits and data-use boundaries

- Select the primary corpus from independent training recordings, respecting [recorded exclusions](artifacts/training-readiness-20260918/protected-splits.json), protected public/official validation source logs and the mini quarantine. Do not move the 400 evaluation scenes into training simply because camera files are found.
- Assign train/development-validation/final-holdout roles at whole-source-log level before fitting. Keep overlapping clips, dates/routes where practical, and corresponding real/rendered versions out of opposing roles; stratify development coverage across cities and driving conditions.
- A source log used for real-camera training cannot count as independent AlpaSim validation. Seal final holdouts across both domains and keep repeatedly inspected diagnostics labelled as development data.
- Start the new real-camera head from a pinned fresh initialization by default. Existing heads or derivatives retain their historical training-exposure exclusions; real imagery does not erase those exposures.
- **9 temporal candidates** are from the four logs already exposed to Cosmos head training. They are not necessarily the original ten scene IDs.
- **32 temporal candidates** are from eight other development logs. Keep them out of fitting if used for log-disjoint comparison. They are development diagnostics, not a sealed final test.
- All four passing Singapore examples are in an already training-exposed log; the 32 other-log examples do not provide independent Singapore validation.
- All **207 public scenes** from the four original training logs remain training-exposed for fitted heads and their derivatives. Candidate-specific exclusions still need integration into the main evaluator.
- Keep the existing protected validation/holdout suites untouched. Do not randomly split nearby frames or overlapping scenes across training and evaluation.
- User authorization for a local experiment is not organizer permission for competition training. Local execution itself needs **no token**; submission eligibility is a separate unresolved question.
- Do not silently broaden the original eight-scene, ten-scene or matched-ablation manifests. The real-camera pilot, or any optional rendered temporal diagnostic, needs its own explicit scope and manifest.

## 6. Procedure, in order

### Step 1 — Pin scope and sample roles

Select a small, diverse set of independent nuPlan training windows and separate real-camera validation logs, respecting the exclusions above. Locate matching captured images first; if absent, agree on a bounded acquisition scope and destination before running a download. OpenScene is a candidate source, not a requirement to download every archive. Record source revisions/hashes, data-use status, sample roles and a bounded experiment budget. No new manifest is activated yet.

### Step 2 — Validate and export real-camera temporal examples

Match captured camera filenames/tokens and timestamps to the correct nuPlan recording. For each anchor, validate three actual past/current images, calibration and preprocessing, causal ego state/history, runtime-compatible route and the full four-second expert future. Check coordinate origins, heading conventions, velocities and any interpolation with independent consistency checks. Targets remain separate from inputs. Reject missing coverage or invalid routes rather than fabricating replacements.

**Implementation work remains:** add a separately versioned raw-camera/DB export path that produces the existing tensor contract with explicit source type and provenance. The current [ASL exporter](training/export_asl.py) is expert-priming-only and is not a raw-camera reader. Preserve its guard and historical manifests; implementing a rendered post-priming exporter is optional diagnostic work, not a prerequisite for primary real-data training.

### Step 3 — Validate the persisted dataset before GPU work

Reopen the exported images/arrays using the dataset reader. Check file hashes, source type, roles, unique identities, frame ages, masks, finite values and coordinate conventions. Report accepted/rejected counts, usable unique footage duration, city/log/maneuver coverage and train/validation overlap checks. Fail on missing data; do not substitute a different scene or fabricate a route. This stage has not run for a raw-camera pilot; the prior 41-candidate in-memory checks apply only to saved rendered observations.

### Step 4 — Extract/cache frozen Cosmos features

Load only the local checkpoint with strict parameter-key checks. Freeze generator and VAE, use evaluation/no-grad mode, encode each observed image independently, and cache `[3,32,2048]` features with preprocessing and source provenance.

Check finite features, absent gradients, unchanged backbone parameter versions, memory and timings. Never reuse an incompatible single-frame cache by repeating its current-frame features into history slots. The earlier measurements were single-image calls, not a completed three-frame driver benchmark.

### Step 5 — Train only the waypoint head

Start from a pinned initialization. Feed image features, ego state/history, masks, ages and sparse route to the head; compute loss against separate expert targets.

Current implemented loss:

```text
position Smooth-L1
  + 0.20 × periodic heading loss
  + 0.01 × initial-velocity Smooth-L1
```

The completed matched single-frame pilot used **AdamW, learning rate 0.0003, batch 10, seed 20260919 and 100 updates per arm**. These are historical settings, not an approved budget/batch size for the new real-camera pilot. Keep the 0.82M head as the baseline initially; changing capacity at the same time would confound the data-source comparison. The generic current runner caps head fitting at 100 updates; any larger scope needs a deliberate change and authorization.

Track loss components, finite gradients, changed head parameters and frozen backbone invariants. Save `head.safetensors` plus configuration/provenance and verify identical predictions after reload. Decreasing training loss is an engineering check, not proof of useful driving.

### Step 6 — Compare on held-out real recordings

Use log-disjoint real-camera development validation with fixed data, initialization and optimization budgets for the candidate and controls:

1. Temporal Cosmos features + state/route/history.
2. Same head with zero visual features, retaining the same nonvisual information and masks.
3. A single-frame variant and causal constant-velocity sanity baseline where appropriate.

Report ADE, four-second FDE, lateral/longitudinal error, heading error, per-scene changes, smoothness and initial-motion consistency. Break down by source log, city and driving condition where sample size permits. Require evidence that visual inputs help beyond state/route alone. Do not tune on a supposed sealed holdout or infer leaderboard PCS from tiny open-loop metrics.

### Step 7 — Validate on separate AlpaSim scenes

After data/interface checks and a useful open-loop signal, integrate the **feature/head policy** into a driver using matching state/route/image transforms. Add the current pose to form the intended 41-pose controller trajectory, preserve timestamps and isolate concurrent sessions. Use AlpaSim source logs excluded from real-camera and rendered training. This explicitly tests real-to-rendered transfer as well as closed-loop control.

First check one/few scenes for interface correctness, then a predeclared small paired comparison with an explicit run scope. Report progress, corridor/road departures, collisions, trajectory/controller consistency and inference/fallback counts alongside complete-driver latency, cold start, memory and concurrency. Match local evaluator/runtime versions before broader comparisons. The earlier 2.48 s generative-action smoke test does not establish this head's speed or driving quality. No full evaluation is authorized by this plan.

### Step 8 — Scale real data; supplement with simulation only for measured gaps

If the head improves log-disjoint results and bounded driving checks, enlarge the independent real-camera corpus deliberately. Prioritize missing city, route, speed and maneuver coverage rather than repeating the same few clips for a fixed number of hours.

Only consider simulator training if diagnostics identify a specific appearance, recovery or interaction gap. Expert-path rendering must align ego and surrounding-agent states with the targets; off-expert recovery requires a validated teacher/relabeling procedure from the actual simulated state. Transforming an old expert trajectory alone is not that procedure. Measure any supplement against the real-only baseline on both validation domains, with source-log separation unchanged.

The 41 existing rendered candidates remain optional compatibility/diagnostic material under their own scope. The camera-acquisition helper has only passed preflight; downloads, real-camera export, fitting, rendering and evaluations remain separate explicit next-run decisions. Cosmos stays frozen throughout this plan; older suggestions of LoRA/unfreezing are not part of the accepted scope.

## 7. Completed experiments and their limits

| Completed check | Result | What it does not establish |
| --- | --- | --- |
| Frozen full-checkpoint features | Strict loading, finite features, approximately 8.12 GiB sampled process VRAM | Full three-frame driver resource compliance |
| Ten-example head learning | Finite updates, lower training error, exact checkpoint reload | Generalization or safe driving |
| Corrected-state matched ablation | On nine other-log examples: Cosmos ADE **2.414 m**, no-vision head **1.977 m**, constant velocity **1.830 m** | No demonstrated Cosmos position-error advantage at this scale |
| Temporal data audit | **41** candidate triplets satisfy fixed checks; **87 CPU tests** passed | Temporal head training, feature caching or closed-loop performance |

The completed fits used actual saved-rollout examples with **simulator-rendered current images**, not raw captured-camera training data; older image slots were masked. **No three-frame driving-data head fit or raw-camera head fit has run.** No Cosmos backbone fine-tuning has run. The current evidence supports pipeline feasibility, not a competitive policy. Older reports sometimes call these non-synthetic-test examples "real samples"; that does not mean their camera pixels came directly from physical cameras.

## 8. Implementation and evidence index

| File / directory | Role |
| --- | --- |
| [contracts.py](training/contracts.py) | Tensor, timestamp, route, role and authorization checks |
| [state_adapter.py](training/state_adapter.py) | Causal received-pose motion estimator |
| [export_asl.py](training/export_asl.py) | Existing rendered-ASL expert-priming-only exporter; not a raw-camera exporter |
| [dataset.py](training/dataset.py) | Hash-checked input/target/cache readers |
| [features.py](training/features.py) | Frozen generator feature tap and image preprocessing |
| [head.py](training/head.py) | Waypoint head and loss |
| [runner.py](training/runner.py) / [CLI](training/__main__.py) | Preflight, feature cache, bounded head training and checkpoint checks |
| [audit_temporal_alignment.py](audit_temporal_alignment.py) | Read-only later-frame audit; does not activate training |
| [TEMPORAL-ALIGNMENT-AUDIT.md](TEMPORAL-ALIGNMENT-AUDIT.md) | Latest temporal-data results and limits |
| [Temporal audit artifacts](artifacts/temporal-alignment-audit-20260919) | Protocol, source hashes, all candidate/rejection records and summary |
| [LOCAL-CAMERA-INVENTORY.md](LOCAL-CAMERA-INVENTORY.md) | Existing images, initial-sample checks and separate-data distinction |
| [ABLATION-RESULT.md](ABLATION-RESULT.md) | Latest completed saved-rollout head/control comparison |
| [TRAINING-READINESS.md](TRAINING-READINESS.md) | Historical raw-camera/metadata inventory and storage roots; older unfreezing suggestions are superseded |
| [protected-splits.json](artifacts/training-readiness-20260918/protected-splits.json) | Existing source-log exclusions and proposed metadata splits; not an activated new training manifest |
| [download_camera_pilot.py](download_camera_pilot.py) | Bounded camera acquisition helper; preflight passed, download not run |
| [TRAINING-PIPELINE.md](TRAINING-PIPELINE.md) | Earlier implementation details and historical conditional commands |
| [FEATURE-INTERFACE.md](FEATURE-INTERFACE.md) | Original design rationale, including later-stage ideas not implemented |

To inspect the CLI without running a stage:

```bash
cd /home/skr/Downloads/alpasim_challenge
/home/skr/alpasim-challenge/alpasim/.venv/bin/python -m cosmos3.training --help
```

There is intentionally no "run the real-camera pilot" command here yet: selected image availability, manifest, authorization, raw-data exporter, route/interface validation and persisted dataset checks are pending. Do not invoke old ASL fitting commands as if they target raw recordings or the 41 temporal candidates.

## 9. Resume instruction

> Resume Cosmos3-Edge frozen-backbone/driving-head work in `/home/skr/Downloads/alpasim_challenge`. Read `cosmos3/CURRENT-TRAINING-SETUP.md`, `cosmos3/TRAINING-READINESS.md`, `cosmos3/LOCAL-CAMERA-INVENTORY.md` and `cosmos3/ABLATION-RESULT.md`. The accepted direction is real-camera-first: independent nuPlan training recordings with matching captured front-camera images, validated causal state/history, route and expert future. Keep Cosmos frozen and train only the head, with a matched state/route-only control. Validate on separate real recordings AND separate AlpaSim source logs. The 41 rendered temporal candidates are optional diagnostics, not the primary training corpus. Next establish a bounded real-camera pilot manifest and image availability, then implement and validate raw-camera/DB export. Preserve old artifacts, protected splits and authorization gates. No raw-camera pilot is exported or trained. Do not download, train, evaluate or submit without an explicitly agreed next-run scope.
