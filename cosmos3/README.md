# Cosmos3-Edge full-generator feasibility check

**Active real-camera pilot:** [RAW-CAMERA-PILOT.md](RAW-CAMERA-PILOT.md).
Acquisition completed: 7,749 verified images from 24 independent logs, within
the approved 20 GiB transfer cap. The new frozen-feature/head-only pipeline is
implemented; proposed pilot validation assignment awaits approval. No raw-camera
head fit has run. Historical evaluation exclusions remain intact.

**Current training setup and next-step handoff (2026-09-19):**
[CURRENT-TRAINING-SETUP.md](CURRENT-TRAINING-SETUP.md) consolidates the head-only
procedure, inputs, tensor shapes, status checklist and remaining gates. The
accepted direction is **real-camera-first training on independent nuPlan logs**,
with Cosmos frozen, a learned head and a matched state/route-only control.
Validate on separate real recordings and separate AlpaSim scenes. Matching raw
images, the new manifest and raw-camera/DB export still need preparation; no
raw-camera head fit has run. The 41 aligned rendered temporal candidates remain
optional diagnostics, not the primary training corpus. Older reports retain
their historical results; "real samples" there means saved-rollout examples,
not necessarily physically captured camera images.

**Real versus rendered example, 2026-09-19:**
[Side-by-side view](artifacts/real-vs-mtgs-pair-20260919/comparison.html) and
[matching method / visual findings](artifacts/real-vs-mtgs-pair-20260919/README.md).
One captured nuPlan front-camera JPEG is paired with the saved initial MTGS
observation. Scene-matched, not pixel-exact: timestamps differ by 12.115 ms and
camera calibration differs. Diagnostic only; no training or evaluation ran.

**Latest matched comparison, 2026-09-19:** [ABLATION-RESULT.md](ABLATION-RESULT.md).
After correcting ego-state inputs, two identical heads received 100 updates each
on ten samples. On nine unseen source logs, Cosmos features gave **2.414 m ADE**,
versus **1.977 m without visual features** and **1.830 m constant velocity**.
Cosmos fitted training data better but did not improve unseen-log position error
in this tiny test. No full evaluation, backbone update or submission ran.

**Earlier local-only fit:** [LOCAL-HEAD10-RESULT.md](LOCAL-HEAD10-RESULT.md)
records ten real samples and 100 updates of an 815k-parameter waypoint head on
frozen full-Cosmos features. Training loss fell 7.70 → 0.53 and training ADE
13.00 → 1.42 m; checkpoint reload matched exactly. **Logged ego velocity disagrees
with received-pose motion in 9/10 samples**, so state validation is required
before scaling. This is not a validated driving policy or submission candidate.

**Earlier full-checkpoint test:** [FEATURE-PROBE-10.md](FEATURE-PROBE-10.md)
records 10/10 finite real-image feature calls, clean parameter loading, 41 ms
warmed mean per image and 8.11 GiB sampled peak process VRAM. Cosmos remained
frozen; no optimizer steps or training-data export occurred.

**Engineering work:** [TRAINING-PIPELINE.md](TRAINING-PIPELINE.md)
documents the implemented offline ASL exporter, frozen-generator feature tap,
dataset reader and waypoint-head training loop. All 73 CPU tests pass. The
separately authorized local-only ten-sample export, feature cache and fit have
completed. Trailing route padding is masked. The subsequent ablation uses
consistent causal pose-derived state; the cause of the legacy velocity fields
remains unresolved. The original conditional eight-scene manifest is unchanged.

**Original conditional scope:** [REAL-PILOT.md](REAL-PILOT.md) records the
eight-scene pilot and same-log evaluation exclusions. Training-data permission
remains unconfirmed. Local engineering does not require a login or token; a
reviewed local terms/organizer statement can resolve the separate rules question.

**Earlier readiness audit:** [TRAINING-READINESS.md](TRAINING-READINESS.md) audits the
local training data, missing camera assets and protected splits. The proposed
frozen-backbone/head-first adaptation is specified in
[FEATURE-INTERFACE.md](FEATURE-INTERFACE.md). The tiny local-only fit does not
establish availability of a larger continuous training-footage corpus.

**Previous compatibility check:** a one-scene closed-loop AlpaSim check has
now completed. **10/10 neural calls succeeded, no fallback; local scene score
0 due to lateral corridor exit.** See [COMPATIBILITY.md](COMPATIBILITY.md) for
the result, adapter assumptions, logs and reproduction. This was not a full
evaluation or submission.

Date: 2026-09-18. The original commands below perform bounded local hardware/API
checks, **not** AlpaSim evaluation, training, or leaderboard submission. The
separate compatibility runner is documented in the follow-up linked above.

**Completed measurements:** see [FEASIBILITY.md](FEASIBILITY.md). Full generation
runs locally. Reduced-resolution peak process VRAM was 10.86 GiB with ~2.64 s
per 4-second prediction; the larger AV-shaped test used 16.54 GiB and 21.87 s.

## Pinned assets and isolation

- Checkpoint: `nvidia/Cosmos3-Edge`, revision
  `344d602b128d1bbdacb43b08d0a3626f46343e29`.
- Model destination:
  `/media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918/checkpoint`.
- Download manifest (file sizes and published LFS SHA-256):
  `/media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918/download-manifest.json`.
- Diffusers: commit `344d6e7300716ff245d5941bc1fe3e95ad8cd1c3`.
- Separate environment:
  `/media/skr/storage/cosmos3-edge-feasibility-20260918/venv`.
  Uses Python 3.11.15 and read-only access to the existing `hilda` environment's
  system site packages, including PyTorch 2.11.0+cu128 / torchvision 0.26.0+cu128.
  New packages are installed only into the new venv; the base environment is unchanged.
- Local GPU: RTX PRO 4000 Blackwell, 24467 MiB, driver 595.84, compute capability 12.0.
- No quantization, CPU offload, or changes to existing AlpaSim/WA-JEPA/Py123D environments.
- Existing `../cosmos` links to older `/home/skr/Cosmos`; it is **not** used here.

The full snapshot is about 9.18 GB. The official generator pipeline uses the
generative MoT (including its text tower) and VAE; it is not a reasoner-only
pipeline. The separate vision encoder is included in the downloaded snapshot but
is not an additional component of the generator pipeline. Actual loaded component
parameter counts and devices are recorded, rather than treating disk size as VRAM.

## Boundaries and interpretation

Competition constraints checked from the organizer README: 16 GiB per driver,
40 GiB image, offline inference, two concurrent rollouts per replica, and a 0.1 s
model-work target enforced through total evaluation throughput.

The full Diffusers pipeline accepts a single sample per call (a prompt list is
collapsed to its first entry). Concurrent calls on the same stateful scheduler
are not safe. The two-client probe therefore measures queueing with one shared
model, not batch-2 or parallel GPU execution. It cannot certify full competition
throughput or packaging compliance.

The AV `policy` API conditions on the first image and predicts future video plus
9D action vectors. This checks a causal API path, unlike inverse dynamics on an
already-observed future clip. The base model is not a proven route-conditioned
nuPlan policy. Raw actions must not be treated as metric AlpaSim poses without
checking normalizers, coordinate conventions, and timing.

Inputs are **only the first clean camera observation** from two saved public-development
ASL logs (one straight road, one turn), extracted by `prepare_inputs.py`.
The evaluation videos were inspected and rejected because they contain score
panels and trajectory overlays; no such annotated image is fed to the model.
The probe does not supply future
frames, ground truth, private scenes, full camera calibration, numerical route
waypoints, or a numerical ego-state adapter. Generic text instruction is not a
substitute for the missing driving conditioning. Source paths and hashes are
recorded in each result.

The checkpoint's released `model_index.json` configuration is preserved,
including its disabled optional safety checker. These tests use benign driving
imagery; they do not install or benchmark separate guardrail models.

## Commands

Download/resume (never starts inference):

```bash
/media/skr/storage/conda_envs/hilda/bin/python -u cosmos3/download_checkpoint.py
```

Extract clean first-frame inputs once, using the existing AlpaSim protobuf reader
environment without modifying it:

```bash
/home/skr/alpasim-challenge/alpasim/.venv/bin/python cosmos3/prepare_inputs.py
```

After download, load-only or one minimal 16-action / 2-denoising-step smoke request:

```bash
/media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python -u cosmos3/profile_edge.py --profile load
/media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python -u cosmos3/profile_edge.py --profile smoke
```

Bounded driving-shaped profile: small smoke warm-up, one 4-second AV policy
request (40 steps at 10 Hz), then two simultaneous incoming requests executed
through a shared queue. Standard action-example denoising count is 30; the 256
resolution tier is a reduced-cost test, not a quality-equivalent substitute for
the published AV example at 480.

```bash
timeout 900 /media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python -u cosmos3/profile_edge.py --profile driving --steps 30 --resolution 256
```

The torch allocator has a 21 GiB safety cap to preserve desktop headroom. This is
**not** a 16 GiB compliance cap. Reports include allocated/reserved torch peaks
and separately sampled process VRAM from `nvidia-smi`, queue/compute/response
times, output shapes, finiteness, errors, and raw action arrays. Model runs are
offline (`local_files_only=True`, HF/Transformers offline flags).

Results appear in `artifacts/<UTC timestamp>_<profile>/results.json`.

One higher-resolution AV-shaped probe (includes a 2-step warm-up, then 60 actions
at 10 Hz with 30 denoising steps) was also run:

```bash
timeout 300 /media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python -u cosmos3/profile_edge.py --profile canonical --steps 30 --resolution 480
```

The final large shard was resumed with `finish_download.py` after its original
HTTP transfer proved slow. All completed weight files were verified by
`verify_checkpoint.py`. Do not rerun the downloader for the completed snapshot;
use the verification script to check integrity.

## Primary sources

- [Model card and files](https://huggingface.co/nvidia/Cosmos3-Edge)
- [Full-generator action API](https://github.com/NVIDIA/cosmos/blob/main/cookbooks/cosmos3/generator/action/README.md)
- [Diffusers environment](https://github.com/NVIDIA/cosmos/blob/main/cookbooks/cosmos3/README.md#diffusers)
- [Challenge constraints](https://github.com/NVlabs/alpasim/blob/e2e_challenge/e2e_challenge/README.md#submission-image-requirements-and-constraints)
