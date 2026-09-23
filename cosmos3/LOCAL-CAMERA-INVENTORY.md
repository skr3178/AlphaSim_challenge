# Existing evaluation camera images — 2026-09-19

Follow-up: the [later-frame temporal audit](TEMPORAL-ALIGNMENT-AUDIT.md) has now
checked all 4,400 image decodes and all 4,000 saved Drive requests. It found
**41 later three-frame candidates** that pass fixed alignment, causal-input and
four-second-target checks. The initial-frame inventory below remains valid;
the old exporter's priming restriction is unchanged, not evidence that all
later frames are unusable.

## Correction and result

**We do have front-camera images for all 400 previously evaluated scenes.** The earlier missing-image inventory concerned raw camera files matching separate nuPlan training databases, not camera bytes embedded in saved simulator logs.

A read-only pass inspected every ASL under:

`/media/skr/storage/alpasim-runs/confirm400-mup-g100/rollouts`

| Check | Result |
| --- | ---: |
| Saved ASLs found and read | 400 / 400 |
| Front-camera messages | 4,400 |
| Messages containing image bytes | 4,400 / 4,400 |
| Stored front frames per scene | 11 |
| Interval between front frames | 500,000 us in all 4,000 adjacent pairs |
| Encoded front-camera bytes | 1,408,778,682 |
| Initial images fully decoded | 400 / 400 |
| Initial decoded resolution | 1920 x 1080 for all 400 |
| Declared expert priming duration | 500,000 us for every scene |
| Prediction requests within priming | One per scene |
| Full t-1.0, t-0.5, t history inside priming | None of those 400 requests |
| Initial routes with at least one finite XY point | 398 / 400 |
| Initial routes wholly invalid or empty | 2 / 400 |
| ASL parsing / initial-image decoding errors | 0 |

All 4,400 image payloads were present; only the 400 initial images were decoded in this pass. Counts are stored observations, not deduplicated training examples or unique footage hours. Presence of a finite route point alone does not establish a valid training route. A subsequent read-only pass checked the initial-request fields and alignment as follows; neither pass exported a training dataset.

### Follow-up: initial-sample input and target checks across all 400

| Check | Passed |
| --- | ---: |
| Front calibration announcement, nonzero dimensions, parseable camera pose | 400 / 400 |
| Same-time received ego pose | 400 / 400 |
| Causal received-pose state adapter (past/current inputs only) | 400 / 400 |
| Initial observed / true / expert alignment | 400 / 400 |
| Finite recorded expert targets at t+0.1 through t+4.0 s | 400 / 400 |
| Causal route anchor and existing sparse-route/padding contract | 398 / 400 |
| All six checks together | **398 / 400** |

Alignment uses the existing exporter limits of 0.10 m translation and 0.01 rad rotation. The state adapter's successful checks establish finite, plausible backward-difference estimates, not accuracy under deployment noise. Calibration presence/pose parsing is not independent physical calibration validation. The two failures are wholly invalid routes; no route was fabricated to make them pass.

This establishes **398 initial single-frame candidates before deduplication, training-role allocation and eligibility checks**. It does not authorize fitting them, activate new splits, certify their competition eligibility, or supply past image history. The earlier ten training / nine diagnostic exports remain the only examples used in Cosmos head experiments.

The separate `py123d-0014-400` run also has 400 ASLs (3.82 GiB total), but its camera contents were not scanned in this inventory. The scanned one-camera run totals 1.353 GiB including non-image messages.

## Why this does not automatically supply continuous expert training

The ASLs hold **rendered observations along an evaluated policy's rollout**, not a raw expert-camera recording. After the initial priming interval, the tested policy can differ from the recorded expert in position, heading and speed. Pairing those later images with the original recorded future without checking that mismatch can introduce incorrect imitation labels.

The current exporter deliberately accepts only expert-primed observations. Under that rule, these logs offer 398 initial candidates passing the audited input/alignment/target checks, still subject to deduplication and split/eligibility decisions—not 4,400 ready-to-train examples. Their earlier camera-history slots are absent.

Later observations are not categorically useless: some may remain aligned, or could support separately designed recovery or self-supervised objectives. Those require their own checks and labels; the existing exporter must not simply relax its priming guard to inflate sample count.

## What can be done without a new image download

- Reuse the already authorized ten training samples and nine diagnostic samples; their artifacts are preserved.
- For a separately scoped larger local-only image/head pilot, select a source-log-disjoint subset of initial observations and validate each candidate before exporting. Reading this inventory did not assign any new scene to training.
- Continuous expert-path rendering from existing assets is another possible data-collection route, but would be a new renderer job and would still need an appropriate training split and data-use decision. No such job ran here.

The original protected evaluation split stays unchanged. Existing fitted heads and their derivatives already exclude all 207 public scenes from the four training logs. Public-navtest training eligibility remains unresolved; availability of rendered pixels is not organizer permission to train on them.

## Separate camera-data source investigation

For a competition-oriented larger pilot, match front-camera frames to independent training logs, avoiding public/validation/holdout source logs and the recorded mini quarantine.

- The [nuPlan setup guide](https://github.com/motional/nuplan-devkit/blob/master/docs/dataset_setup.md) places raw images under `sensor_blobs/<recording-window>/CAM_F0/` and describes its account/terms download flow. No account or terms were changed.
- [OpenScene](https://github.com/OpenDriveLab/OpenScene) is a 2 Hz redistribution of nuPlan sensor data. Its [download guide](https://github.com/OpenDriveLab/OpenScene/blob/main/docs/getting_started.md) links the official Hugging Face camera archives; this is a potential source of matching observed image histories, not proof of current-challenge eligibility.
- The public camera listing returned 200 `trainval` archive entries and 32 `mini` archive entries. Individual archives are multi-GB and are not front-camera-only packages. A small selected-log pilot needs archive-to-log mapping and matching local metadata before bulk transfer. Do not download all archives or use the quarantined mini split solely for convenience.

Small in-memory archive-prefix probes found matching independent training windows in parts 0, 3 and 10. The acquisition helper `cosmos3/download_camera_pilot.py` has passed its local metadata/split preflight for those three windows; its `--download` mode has **not** been run. No new training, neural inference, simulation, evaluation, bulk camera download or dataset reassignment was performed during this inventory.
