# Active captured-camera, frozen-Cosmos head pilot

Started 2026-09-19, following the user's explicit request to train/adapt the
driving policy. This is the active execution handoff, supplementing
[CURRENT-TRAINING-SETUP.md](CURRENT-TRAINING-SETUP.md).

**2026-09-21 update:** the user requested all-city train/validation coverage.
See [ALL-CITY-PILOT-PLAN.md](ALL-CITY-PILOT-PLAN.md) for the targeted Vegas
extension and the unresolved date-versus-log split choice. The Boston-only
proposal below is historical and has not been activated.

**Latest checkpoint:** acquisition finished; **7,749 verified original JPEGs
from 24 logs across three cities**, with **1.635 GiB** conservatively charged
against the 20 GiB cap. See [acquisition audit](RAW-CAMERA-ACQUISITION-20260919.md).
No real-data GPU extraction or head fitting has started. A newly requested
whole-log/date development split awaits user approval (details below).

## Current decision needed

The archive-prefix search did not find camera windows from the earlier
metadata-only proposal's validation dates. This does not establish that such
images are absent from all archives. Do not keep downloading unrelated imagery
or silently relax exclusions.

Proposed **new pilot split**, not yet activated:

- Development validation: all five acquired Boston logs from **2021-10-01 and
  2021-10-06**, 1,156 images, approximately 548 nominal 1 Hz anchors before checks.
- Training: the remaining **19 logs**, 6,593 images, approximately 3,183 nominal
  anchors across Boston, Pittsburgh and Singapore before checks.
- Boston is the only city covered by this proposed development set; it cannot
  establish cross-city validation performance for Pittsburgh or Singapore.
- None of the acquired images has been used for fitting. Preserve original
  acquisition receipts and the historical split proposal. If approved, create
  a separate explicit pilot-split file bound to their hashes; the exporter and
  reader support this without editing the original files.
- All protected public-evaluation, official validation and mini source-log/date
  exclusions remain enforced regardless of the pilot assignment.

The user has been asked to choose this split or retain the old proposal and
locate different validation footage. **Do not infer approval from the download
authorization.**

## Approved scope

- Keep the full Cosmos3-Edge generator **and VAE frozen**. Train only the existing
  **815,235-parameter driving head**. No LoRA, selective unfreezing or backbone
  optimizer state.
- Check for existing matching data before downloading. The fresh bounded
  inventory found nuPlan training DBs but no matching captured images in the
  inspected metadata/sensor roots. Other identified camera collections were
  Waymo, nuScenes and KITTI. The single real-camera comparison JPEG is protected
  public-test data, not the training corpus.
- The user approved acquisition of missing independent nuPlan/OpenScene front
  images to Seagate, with a **20 GiB total compressed-transfer cap**. Do not
  download all camera views or the full dataset. Keep historical public/official
  validation and mini exclusions intact; do not train on the 1,485 public
  evaluation scenes or their source logs.
- Implement the missing raw-camera exporter and bounded scalable training path.
  Local training authorization is not an organizer eligibility certificate.
  New heads remain local research artifacts until eligibility and deployment
  compatibility are established. No submission or full AlpaSim evaluation.

## First useful scale

Target **2,000–5,000 valid training anchors** from at least 12 independent source
logs, plus approximately **500 development-validation anchors** from at least
four other logs. Seek Boston, Pittsburgh and Singapore coverage and varied
motion after validating actual files. This is a practical pilot, not a claim of
leaderboard-sufficient data. If acquisition or alignment produces less coverage,
report the shortfall instead of duplicating examples or weakening splits.

Sample at no more than approximately 1 Hz. Each anchor needs three genuine
front images around t−1, t−0.5 and t, causal state/history, sparse allowed
navigation and a full four-second expert target. Neighboring windows overlap:
example count is not independent footage duration. Count unique usable intervals
and report city/log coverage after export.

## Execution stages

1. **Inventory and acquisition:** match exact JPEG identities to read-only nuPlan
   DB image records, decode 1920×1080 files, hash them, retain receipts and use a
   persistent conservative byte ledger. Archive prefix discovery and retries
   count toward the cap. Preserve original image bytes.
2. **CPU export/validation:** use a new captured-data protocol, not the old
   ASL-expert-priming exporter. Keep current/history observations causally
   available, transform poses to the runtime rear-axle/yaw frame, interpolate
   expert targets without extrapolation and enforce whole-log/city-date roles.
3. **Navigation parity:** reproduce the actual sparse AlpaSim MAP route algorithm
   with its 40 m starting offset. The simulator itself derives navigation from
   map-matched recorded geometry. Record that permitted navigation provenance;
   never directly provide the dense timed 0–4 s target as a model input.
4. **Integrated small check:** validate a small set through export, frozen
   feature extraction, head updates and checkpoint reload before scaling. This
   is an engineering test, not a generalization claim.
5. **Feature cache:** local full checkpoint only, frozen/eval/no-grad generator
   and VAE. Deduplicate each observed JPEG+recipe representation and store
   `[32,2048]` features per image; gather three image records per anchor. No
   generated future frames or labels enter feature computation.
6. **Matched fit:** fresh initialization, approximately 10 epochs, batch 32,
   AdamW at 3e-4, maximum 2,000 optimizer updates per arm and one hour per arm.
   Compare Cosmos visual features against the same head with zero visual
   features, retaining identical state/route/history information. Include a
   causal constant-velocity reference. These are initial bounded settings, not
   a pretraining/convergence promise.
7. **Report:** training and log-disjoint development ADE/FDE, lateral/longitudinal
   and heading error, initial-motion consistency, coverage, timings and frozen
   invariants. Reload saved head weights and verify minibatched predictions.
   Training-set improvement alone is insufficient.

No full-dataset GPU batch: validation and checkpoint replay are minibatched;
cached features are lazy-loaded rather than accumulated without bounds.

## Hardware and locations

Read-only GPU check: NVIDIA RTX PRO 4000 Blackwell, 24,467 MiB total, approximately
369 MiB in use at the check. Sandbox-only `nvidia-smi` failed; an authorized
read-only host check succeeded. This is hardware availability, not a training
throughput measurement.

- Images/receipts: `/media/skr/SeagateHub1/cosmos3-real-camera-pilot-20260919`
- Acquisition progress: `acquisition-manifest.json` under that root; do not
  mistake image acquisition status for a validated/exported training dataset.
- Persistent transfer ledger: `transfer-ledger.jsonl` under that root.
- Download sessions: `cosmos_raw_camera_20260919` and the bounded extended-prefix
  pass `cosmos_raw_camera_extend_20260919`; both have finished.
- Download log: `/tmp/cosmos3-real-camera-acquisition-20260919.log`.
- Frozen checkpoint: `/media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918/checkpoint`.
- Model Python: `/media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python`.
- DB/map Python: `/home/skr/alpasim-challenge/alpasim/.venv/bin/python`.

The first `nohup` launch did not persist through the execution environment; the
job was relaunched and verified in `tmux`. Use its actual session/progress rather
than the obsolete first PID.

## Code ownership / current status

- `acquire_raw_camera_pilot.py`: completed capped acquisition; three safety tests
  passed. One incomplete directory is retained but excluded from the manifest.
- `training/raw_dataset.py`: separate hash-checked causal reader; 16 CPU tests
  pass, including explicit pilot activation without altering historical roles.
- `training/export_raw.py`: implemented raw DB/image exporter. **15/15 actual raw
  anchors** across three cities passed a CPU construction check: six straight,
  five turning and four stopped examples. One saved route was reconstructed with
  the same finite/padding mask and **0.000014424 m maximum coordinate error**.
  That is one MAP algorithm-parity check, not full deployment certification.
  **14 exporter CPU tests passed** with unrelated environment pytest plugins
  disabled (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`). Diagnostic provenance is saved
  in [diagnostic.json](artifacts/raw-export-cpu-diagnostic-20260919/diagnostic.json).
- `training/raw_runner.py`: deduplicated frozen-feature cache, lazy loading,
  matched head-only fits and minibatched exact checkpoint replay implemented;
  15 CPU tests passed. GPU integration on this raw corpus is still pending.
- Combined reader/runner/historical pipeline regression invocation: **103 CPU
  tests passed**. An initial invocation omitted the legacy test-directory import
  path; rerunning with the correct `PYTHONPATH` passed without changing old code.

Next after split approval: pin its authorization/provenance, export and reopen
the actual dataset, measure accepted/rejected counts and usable unique coverage,
cache frozen features, run at most 100 head updates per arm as the integrated
engineering gate, then start fresh matched runs up to the bounded ten-epoch
scope if the gate passes. No source weights will be updated. Do not count CPU
synthetic unit-fixture updates as successful real-camera policy training.
