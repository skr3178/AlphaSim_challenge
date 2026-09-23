# Offline Cosmos3-Edge driving-head pipeline

Latest follow-up: [ABLATION-RESULT.md](ABLATION-RESULT.md) records a separate
corrected-state, two-arm local test: ten training examples, nine unseen source
logs, 100 updates per arm. The new causal state adapter bypasses suspect legacy
dynamic-state inputs; it does not repair the upstream runtime or certify noisy
deployment state. The Cosmos arm had worse unseen-log position error. Use
`python -m cosmos3.run_ablation` for this role-separated protocol; the original
generic fitting command rejects its mixed train/evaluation manifest.

There are now **73 passing CPU tests**. The single-head status and proposed
competition-conditional commands below describe the earlier stage; its original
artifacts and eligibility gate remain unchanged. Use the linked ablation result
for the latest corrected-state measurements and negative transfer finding.

Updated 2026-09-19. **Local-only ten-sample head fit completed; no new simulator
run or submission.** See [LOCAL-HEAD10-RESULT.md](LOCAL-HEAD10-RESULT.md): 100 head
updates on frozen full-checkpoint features, exact checkpoint reload, 61 passing
CPU tests. Logged ego velocity is inconsistent with received-pose motion in
9/10 samples and needs correction before further fitting or deployment.

Follow-up: the requested data-use check was attempted on 2026-09-19 and remains
unresolved for competition use. The subsequent explicit local-only authorization
enabled a separate ten-scene manifest, export, cache and fit; it does not settle
competition training-data eligibility or change the original eight-scene manifest.
See [the check record](pilots/real-driving-v1/DATA-USE-CHECK-20260919.md) for
sources, the required next input and a fresh disk/download inventory.

This implements the frozen-backbone stage of [FEATURE-INTERFACE.md](FEATURE-INTERFACE.md)
for the conditional eight-scene scope in [REAL-PILOT.md](REAL-PILOT.md), with a
separate explicit `--local-only` mode for the ten-example engineering test. It is not
a reproduction of Odyssey's unpublished training recipe or evidence of improved
driving. The original video/action compatibility results are a different path.

## What is now implemented

| Component | Implementation and evidence | Remaining check |
| --- | --- | --- |
| Source inventory | Ten local-only scenes have saved initial camera bytes, poses, routes and calibration | Continuous expert-aligned training footage |
| ASL exporter | Ten examples exported; causal inputs and future labels separated; pose alignment passed; trailing NaN route padding correctly masked | Logged ego-state convention and velocity consistency |
| Dataset/cache reader | Real exported dataset and cache validated against hashes, shapes, timestamps and masks | Physical state consistency beyond structural validity |
| Frozen generator tap | Full transformer and VAE strictly loaded; ten real images cached as 32×2048 tokens each; no backbone updates | Driving usefulness, multi-frame and full-driver performance |
| Driving head | Width-128, two-layer decoder; 815,235 parameters; loss 7.70 → 0.53 in the local fit | Correct state inputs, independent evaluation and useful smooth trajectories |
| Bounded runner | Exactly 100 real head updates; finite checks; saved checkpoint reload reproduces predictions exactly | Separately authorized corrected-state fit |
| CPU checks | **61 tests pass** across the Cosmos suite | Not a competition-throughput or driving-quality certification |

Code lives in [training/](training/); run it with `python -m cosmos3.training`.
The prototype feature tap passes a tiny randomly initialized instance of the
installed upstream Cosmos transformer on CPU. That tests token packing, feature
shape, finiteness and freezing, **not the pretrained representation**. Temporary
unit fixtures exercise two head optimizer steps; these are separate from the
100-update real local fit, and no unit-fixture checkpoint is a candidate.

## What the saved logs provide

Read-only report:
[pipeline-preflight-20260919.json](pilots/real-driving-v1/pipeline-preflight-20260919.json).
Sources are the first sorted saved rollout for each approved scene under
`/home/skr/alpasim-challenge/alpasim/runs/confirm400-mup-g100`. No model scores
were used to select them.

All eight first observations have front-camera bytes and matching observation
state. This may avoid an additional raw-image download for this tiny pilot.
It does **not** change the earlier audit of missing raw camera assets or turn
the downloaded public scene bundles into a large training-footage corpus.

The saved logs prime the vehicle on the expert path only through 0.5 seconds.
Their first request has `time_now_us=17000`, `time_query_us=517000`. Source
inspection identifies query time as the next control endpoint, not another
camera observation. Targets are anchored at `time_now_us + 0.1..4.0 seconds`;
query time must lie within the prediction's covered interval. Future images
are never used to fill the observation history.

The actual ten-scene local export yielded **one aligned initial example per
scene**, with the two older history slots masked. Its logged velocity inputs
still require diagnosis. This suffices for a numerical integration/learning
check, not temporal-policy training or a claim
about generalization. A larger run needs genuinely continuous expert-aligned
training observations on an agreed, permitted split.

## Interface and protections

The data path is:

`saved expert-aligned ASL -> separate inputs/labels -> frozen image features -> waypoint head`

- Inputs: observed `CAM_F0` at approximately t−1, t−0.5 and t; rear-axle-relative
  past poses, actual image ages/masks, `[v_forward, v_left, yaw_rate]`, and up to
  32 sparse navigation points from the logged driver route. No dense future
  trajectory is converted into navigation input.
- Images: letterbox to 256×448, RGB in [−1,1]; record original calibration and
  pixel transform. Calibration is provenance, **not explicit head conditioning**
  in this first prototype; semantic calibration validation is not certified.
- Features: three independently encoded images, each 32×2048 tokens, missing
  slots zero/masked. The frozen transformer receives clean observed-image tokens
  and a fixed prompt, without future/noisy/action tokens or a denoising loop.
  This new recipe is explicitly marked `validated_driving_encoder: false`.
- Output: 40 `[x,y,sin(yaw),cos(yaw)]` waypoints at 10 Hz in the current rear-axle
  frame. The head predicts residuals around observed constant-velocity/yaw-rate
  motion; this is a parameterization, not a silent fallback.
- Loss: masked position Huber + periodic heading + initial-velocity consistency.
  Initial/final losses use the **training samples**, not validation or holdout.
- Outputs refuse overwrite. Dataset, input, target, image and cache hashes are
  checked. Feature provenance includes local source/config hashes, loading
  diagnostics and weight-file size/mtime inventory; it does not rehash every
  checkpoint weight or constitute cryptographic weight attestation.
- The original 8-scene/4-log scope and 100-update cap are enforced in the
  competition-conditional mode. Separate local-only mode requires the exact
  10-scene manifest, explicit acknowledgement, at most 10 samples and 100 updates;
  it records `submission_allowed: false`. The original public and approval
  manifests are unchanged; approval-time readiness fields are historical.
- All 207 same-source-log public scenes are recorded as exclusions for a fitted
  candidate. The 589 validation pool (compact150 nested) and 313 holdout remain
  protected. **Evaluator integration of the candidate exclusions is still
  pending** and must precede any fitted-candidate evaluation. This is log-level,
  not date/geographic separation; the protected suites lack Singapore coverage.

## Reproduce the checks already run

From `/home/skr/Downloads/alpasim_challenge`:

```bash
CUDA_VISIBLE_DEVICES='' HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  PYTHONPATH=/home/skr/alpasim-challenge/alpasim/src/grpc \
  /media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python \
  -m unittest discover -s cosmos3 -p 'test_*.py' -v

/home/skr/alpasim-challenge/alpasim/.venv/bin/python \
  -m cosmos3.training preflight \
  --run-root /home/skr/alpasim-challenge/alpasim/runs/confirm400-mup-g100
```

`preflight` only reads metadata; it does not authenticate, load the model,
decode/export frames or certify readiness to train. Use `--output NEW_FILE`
to retain another report; existing files are never overwritten.

## Original competition-conditional commands — not executed

Local training has **no API-token requirement**. The separate outstanding issue
is the conditional approval to train on public-navtest scenes. The commands
below require a local review record referencing a saved current terms/organizer
statement and its SHA-256. The code validates the record, not the truth or legal
interpretation of its contents. It does not contact the challenge service.

An unreviewed template looks like this; do not change the decision merely to
bypass the check. A reviewer must establish permission for the stated scope.

```json
{
  "decision": "unreviewed",
  "scope": "training_on_approved_public_navtest_scenes",
  "pilot_manifest_sha256": "58d3c4e5c5fc28eb5329e3514a0812d18c50e069bcff6f9170d22ae36349186a",
  "reviewed_by": "",
  "reviewed_at_utc": "",
  "source_description": "",
  "evidence_file": "terms-or-organizer-statement.txt",
  "evidence_sha256": ""
}
```

The reviewed record requires `decision: permitted` and nonempty reviewer/date/
description fields. `evidence_file` must be relative to the record's directory
and match its hash. No such real permission record was created in this work.

After resolving that condition, run each stage separately and inspect its report
before proceeding. These are proposed output paths, not existing results:

```bash
/home/skr/alpasim-challenge/alpasim/.venv/bin/python \
  -m cosmos3.training export-asl \
  --source-report cosmos3/pilots/real-driving-v1/pipeline-preflight-20260919.json \
  --rules-evidence cosmos3/pilots/real-driving-v1/rules-review.json \
  --max-samples 64 \
  --output cosmos3/artifacts/real-driving-v1-samples

/media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python \
  -m cosmos3.training cache-features \
  --dataset cosmos3/artifacts/real-driving-v1-samples/dataset.json \
  --checkpoint /media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918/checkpoint \
  --rules-evidence cosmos3/pilots/real-driving-v1/rules-review.json \
  --device cuda --max-seconds 600 \
  --output cosmos3/artifacts/real-driving-v1-features

/media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python \
  -m cosmos3.training train-head \
  --dataset cosmos3/artifacts/real-driving-v1-samples/dataset.json \
  --cache cosmos3/artifacts/real-driving-v1-features/cache.json \
  --rules-evidence cosmos3/pilots/real-driving-v1/rules-review.json \
  --device cpu --steps 100 --batch-size 8 --max-seconds 300 \
  --output cosmos3/artifacts/real-driving-v1-head
```

For the separately authorized completed local run, each stage instead used
`--pilot cosmos3/pilots/local-head10-v1/manifest.json` before the subcommand and
`--local-only` after it, without
fabricating a rules review. Its export used `--max-samples 10`, and its fit used
`--steps 100 --batch-size 10`. Do not rerun it without a new bounded-run request;
the [result](LOCAL-HEAD10-RESULT.md) records a state-consistency issue to fix first.

The CLI forces Hugging Face/Transformers offline mode and uses local checkpoint
loading only. Training from cached features does not load the Cosmos backbone.
Original-pilot export is capped at 256 and fitting requires all eight scenes;
local-only export is capped at ten and fitting requires all ten scenes.
Time limits are checked between operations, not hard process deadlines. The GPU
allocator guard is 21 GiB for desktop headroom, **not** a competition-compliance
cap. Feature-cache reports now record sampled process VRAM as well as allocator
peaks; full resource/throughput checks and a runtime driver for this head remain future
work. Twenty GPU-hours is not the scope or budget of this sample pilot.

Stop on missing assets, rejected alignment, unexpected checkpoint keys,
nonfinite features/losses, or exceeded bounds. Do not silently substitute other
scenes, off-policy images, reasoner/vision-only features or random fallback
features to make the pipeline complete.
