# Cosmos3-Edge driving adaptation: training-readiness report

Follow-up, 2026-09-19: saved initial ASL camera observations enabled a separately
authorized [ten-sample local head fit](LOCAL-HEAD10-RESULT.md). That run found an
ego-velocity consistency problem. It does not establish continuous footage
availability or invalidate this earlier raw-image inventory.

Audit completed **2026-09-18 18:09 UTC / 23:39 IST**. Scope: local metadata,
asset availability, protected splits and a proposed feature interface. No model
inference, training, simulation, evaluation or new download was launched.

## Decision

**Proceed with preparation, but visual-policy training is not ready to start.**
The inspected storage contains substantial nuPlan labels and image references,
but no matching camera images. The proposed causal Cosmos feature extractor also
needs implementation and validation. Neither more training time nor the pending
public-evaluation download resolves those two prerequisites automatically.

The recommended adaptation is:

1. Establish eligible, image-backed training clips and freeze their split.
2. Validate a causal feature tap from Cosmos3-Edge.
3. Freeze the backbone and learn a small ego-state/route-conditioned waypoint head.
4. Add LoRA or selective unfreezing only if held-out results justify it.

Odyssey's driving example reports a **frozen world model**, a learned small policy
and **20 hours of simulated driving data**. That is not a claim of 20 GPU-hours
or evidence that unrestricted backbone fine-tuning is necessary. We can borrow
the adaptation principle, not assume the same results or unpublished recipe.
[Odyssey's announcement](https://odyssey.systems/introducing-odyssey-3).

## 1. Footage and metadata inventory

The audit queried **7,048 extracted SQLite databases**, with zero query errors,
and inspected the directory of a ZIP containing another **562 databases**.

| Collection | DB windows | Source logs / dates | Camera-reference span hours | Verified usable RGB + labels |
| --- | ---: | ---: | ---: | ---: |
| Boston train | 1,647 | 234 / 39 | 79.19 | 0 h |
| Pittsburgh train | 1,560 | 204 / 25 | 107.25 | 0 h |
| Singapore train | 2,396 | 343 / 30 | 146.60 | 0 h |
| Official nuPlan validation; protected | 1,381 | 142 / 10 | 93.99 | 0 h |
| nuPlan mini; quarantined | 64 | 52 / 21 | 7.21 | 0 h |
| Vegas train archive; not extracted | 562 | 85 / 8 | Not queried; 102.01 nominal h from filenames | 0 h |

Extracted training collections cover **333.05 hours of front-camera timestamp
spans**, before training exclusions. This is metadata coverage, **not downloaded
footage**. It is computed by merging overlapping timestamp ranges within each
source log. Internal gaps and history/future target margins have not been
subtracted. Archive hours use recording-window filenames, a weaker measure.

There are **11,983,593 front-image references in the three extracted training
collections**, and 15,627,999 across all extracted collections. These are database
references, not verified unique images; collections can overlap. All matching
front-image file counts are zero in the inspected media roots.

### Exact storage locations

Common legacy prefix:
`/media/skr/SeagateHub1/autoresearch/autoresearch-paper/paper/dataset`

- Boston: `<legacy>/nuplan-extracted/data/cache/train_boston`
- Mini: `<legacy>/nuplan-extracted/data/cache/mini`
- Pittsburgh: `/media/skr/SeagateHub1/nuplan_cities/pittsburgh/data/cache/train_pittsburgh`
- Singapore: `/media/skr/SeagateHub1/nuplan_cities/singapore/data/cache/train_singapore`
- Official validation: `/media/skr/SeagateHub1/nuplan_cities/val/data/cache/val`
- Vegas archive: `/media/skr/SeagateHub1/nuplan_zips/nuplan-v1.1_train_vegas_5.zip`

Media indexing covered `nuplan_cities`, `nuplan_zips`,
`<legacy>/nuplan-extracted` and `<legacy>/nuplan-v1.1`. Directory symlinks were
not followed. **This is not a claim that no images exist elsewhere on the disk.**
If the recently downloaded camera dataset is in another folder, add that exact
root and re-check its references before purchasing or downloading anything else.

## 2. Missing assets and checks still needed

nuPlan stores image filenames in the database and the pixels separately under
`sensor_blobs/<recording_window>/CAM_F0/<token>.jpg`; a large `.db` collection
does not establish camera availability.
[nuPlan dataset layout](https://github.com/motional/nuplan-devkit/blob/master/docs/dataset_setup.md).

For example, this referenced image was absent from the inspected roots:

```text
2021.08.18.18.32.06_veh-28_00049_00111/CAM_F0/c55bb5b1aeca5ba5.jpg
```

The [missing-assets inventory](artifacts/training-readiness-20260918/missing-front-assets.csv)
records the missing front-image count, an example filename and proposed split
for every extracted database. It is a per-database inventory, not a fully
materialized list of all missing image filenames.

Other findings:

- All 7,048 databases describe eight camera channels and a 1920×1080 front camera.
  Front-camera calibration blobs and required ego-pose/state columns are present.
  Blob contents, coordinate semantics and numerical state quality are unvalidated.
- Roadblock IDs are populated in 81,757 of 85,444 scene records. Presence does not
  prove that the runtime-equivalent navigation route can be reconstructed.
- Nonempty map files for all four cities exist under
  `<legacy>/nuplan-extracted/nuplan-maps-v1.0`. Routing compatibility is untested.
- The Vegas ZIP is **136.37 GB decimal / about 127.0 GiB** and contains 562 `.db`
  files plus two directories, **no images**. Extracting its roughly 229.77 GB of
  contents would add metadata, not solve the missing-camera problem. Only its
  central directory was inspected, not a full decompression/CRC verification.
- Existing Pittsburgh/Singapore `.pt` caches were not deserialized and are not
  counted as camera footage. Their names or sizes are insufficient evidence.

Start with matching **front-camera assets for eligible training logs**, not all
eight cameras or public holdout logs. Actual download size remains unknown until
the relevant sensor-archive manifests are identified; database size cannot give
a reliable image-download estimate. Once located, check decode success, exposure
timing, calibration, continuity and four-second target coverage. Count unique
usable time intervals, not repeated/overlapping clips.

## 3. Protected splits and leakage controls

The existing [public evaluation manifest](../evaluation/public-suite.json) was
unchanged throughout the audit. Its SHA-256 is:

```text
a2a150d4eb139db0cbfa7d1cfa37a8eff701db34fff8264034c0433ab2f36b64
```

The proposed training exclusion list protects:

- All **1,485 public navtest scenes**, their **44 source logs**, and their **nine
  city/date groups**. This includes the heavily used development400.
- All **142 source logs** represented in the local official nuPlan validation set.
- All **52 mini source logs**, conservatively quarantined because of overlap and
  uncertain prior use. These counts overlap; they are not additive.

Concrete leakage finding: **10 mini database windows belong to nine public
navtest source logs**. Randomly splitting mini clips would not provide an
independent training/evaluation boundary. Exclude matching source logs across
every collection, not just those ten filenames.

After exclusions, the candidate metadata pool contains **6,082 windows across
856 source logs**, representing **427.81 nominal recording hours**, including
the unextracted Vegas archive. These are still not train-ready footage hours.

The saved [protected-split proposal](artifacts/training-readiness-20260918/protected-splits.json)
hash-ranks whole city/date groups with seed `20260918` and reserves approximately
20% of dates per city for pilot validation:

| Proposed role | DB windows | Source logs | Nominal recording hours |
| --- | ---: | ---: | ---: |
| Pilot training | 4,631; 390 archive-only | 653 | 325.20 |
| Pilot validation | 1,451; 154 archive-only | 203 | 102.61 |

This split is **proposed, metadata-only and not activated**. Date allocation is
not an exact 80/20 split of hours. It is city/date-group-disjoint and
source-log-disjoint; it is not globally calendar-date-disjoint across cities.
It does not certify geographically disjoint routes or unknown pretraining/private
evaluation exposure. Assertions checked that both pilot roles avoid protected
source logs and each other.

The public evaluator's existing development/validation/holdout split has not
been rewritten. Its validation and holdout are log-disjoint, not necessarily
date-disjoint. Keep the 313-scene public holdout sealed during tuning. Use the
new training-side validation for frequent model selection; later public
closed-loop validation remains a separate gate.

## 4. What the Seagate download supplies

The tracked job at
`/media/skr/SeagateHub1/alpasim-navtest-expansion-20260918` downloads **AlpaSim
public-evaluation rendering assets**, not the matching raw training-camera
collection above. Do not train on these protected evaluation scenes.

At the audit snapshot, 2026-09-18 23:39 IST:

- Old evaluation root: basic assets present for 400 scenes.
- Seagate expansion: basic assets present for another 794 scenes.
- Combined availability: **1,194 / 1,485**, with 291 missing.
- Tracked downloader status: eight of eleven shards complete, `part012.tar.gz`
  in progress. The existing background job was left running unchanged.
- Compact validation assets: 134/150; holdout assets: 288/313.

These are dated presence checks for config, scene dictionary, road-height map
and background checkpoint, **not render tests or a completed combined runtime
root**. Download progress can change after the snapshot. If the user means a
separate newly completed sensor download, its folder still needs to be identified.
See the [full snapshot](artifacts/training-readiness-20260918/evaluation-assets-snapshot.json).

## 5. Proposed Cosmos interface and training scope

Full design: [FEATURE-INTERFACE.md](FEATURE-INTERFACE.md).

The first research gate is obtaining **causal world-generator features** without
generating an entire future video. The inspected generator has internal hidden
states, but its current public output does not expose them. Observation packing,
diffusion timestep/mask semantics and single-pass usefulness are unproven. A
feature hook alone does not prove this works.

The separate Cosmos visual-reasoner path is an alternative, explicitly labelled
as such. A vision-encoder-only policy is another ablation, not equivalent to
using the world-generator backbone. Correct native weight loading, feature shape
and absence of randomly initialized missing layers must be checked first.

Proposed policy contract:

- Three causal front observations around t−1.0, t−0.5 and t, with actual exposure
  timestamps, masks and calibrated transforms.
- Current ego motion plus sparse route points matching authorized runtime inputs.
- Frozen Cosmos features feeding a small temporal/route-conditioned head.
- Forty future planar poses at 0.1-second spacing, in the current rear-axle frame;
  the driver inserts the current pose for the existing 41-pose response.
- Supervise future expert poses only as targets. Never feed future images or the
  dense expert trajectory back as observations/navigation.

Start with waypoint and heading losses, then modest speed/acceleration consistency
terms. Compare state/route-only and vision-only controls on identical data to
establish whether Cosmos representations add value. Balance sampling across
cities/dates, speeds, stops and turns after measuring actual clip availability;
do not recreate the old evaluation sample's concentration in training.

The local GPU has approximately **24 GiB**. Full Adam training of the measured
3.37B-parameter generator would require about **37.7 GiB for BF16 weights,
BF16 gradients and FP32 optimizer moments alone**, before activations or VAE.
That arithmetic assumes conventional full-parameter Adam without offload,
sharding or compressed states; it is not a measured training peak. Frozen-feature
head training is the sensible first candidate, but its memory and speed are also
unmeasured. Twenty GPU-hours remains a planning reference, not a limit.

NVIDIA's documented training configurations are multi-GPU, and its available
DROID action-policy example uses robot joint targets rather than nuPlan driving
waypoints. They are implementation references, not a ready-made single-GPU AV
fine-tuner.
[Training documentation](https://github.com/NVIDIA/cosmos-framework/blob/c23e51f2f157ae3e51cfcd86ebfb5464850894f2/docs/training.md),
[action-policy example](https://github.com/NVIDIA/cosmos-framework/blob/c23e51f2f157ae3e51cfcd86ebfb5464850894f2/docs/action_policy_droid_posttrain.md).

The existing generator's ~2.48-second call time and zero-score compatibility
scene do not predict the performance of this unbuilt feature-head policy.
Conversely, full generation fitting locally does not establish competition
compliance: the challenge documents 16 GiB per driver and concurrent rollouts,
with throughput limits. Measure the complete adapted policy before claiming fit.
[Challenge requirements](https://github.com/NVlabs/alpasim/blob/e2e_challenge/e2e_challenge/README.md#submission-image-requirements-and-constraints).

## 6. Next actions, in order

1. **Resolve the camera-data location.** If no separate sensor download exists,
   identify the exact matching CAM_F0 archives for the protected-split-eligible
   logs and prepare a size/download plan. Do not redownload metadata blindly.
2. **Build and validate the sample contract on CPU.** Check image/ego timestamps,
   frame transforms, calibration, causal navigation provenance, split membership
   and usable interval duration. Begin with a diverse pilot, not every DB.
3. **Implement the feature interface and authorize a bounded GPU probe.** Strict
   checkpoint loading, causal finite features, memory and end-to-end latency are
   gates. No claim that observation-only generator features already work.
4. **Train the small head first**, with a tiny overfit sanity check followed by
   unseen-log/date validation and matched ablations. Choose compute from measured
   throughput and learning curves, not Odyssey's data-hour figure.
5. **Consider selective backbone adaptation** if the head-only result plateaus
   and held-out evidence supports it. Re-measure resources after any LoRA or
   unfreezing change; invalidate cached features when backbone weights change.
6. **Check closed-loop behavior and evaluator parity before submitting.** Real
   nuPlan images and rendered AlpaSim observations can differ. Expert imitation
   alone does not guarantee recovery after drift, progress or leaderboard gains.
   Any later recovery-data collection must use training scenes, not the holdout.

No training or experiment was started by this report. The next immediate blocker
is matching training RGB, alongside the code-level feature feasibility work.

## Audit evidence and verification

- [Machine-readable summary](artifacts/training-readiness-20260918/audit-summary.json)
- [Extracted DB inventory](artifacts/training-readiness-20260918/database-inventory.csv)
- [Archive inventory](artifacts/training-readiness-20260918/archive-inventory.csv)
- [Missing camera assets](artifacts/training-readiness-20260918/missing-front-assets.csv)
- [Protected split proposal](artifacts/training-readiness-20260918/protected-splits.json)
- [Read-only audit script](audit_training_readiness.py)
- [Five passing CPU helper tests](test_training_readiness.py)

The audit used SQLite read-only connections and `query_only`, no pickle/torch
deserialization, no archive extraction and no model execution. Raw DBs were not
fully checksummed; archive payload integrity and image semantics remain untested.
Existing model/evaluator code and the public manifest were not changed by this
audit. Reproduction requires a **new** output directory:

```bash
python3 cosmos3/audit_training_readiness.py --output cosmos3/artifacts/training-readiness-NEW
python3 -m unittest discover -s cosmos3 -p test_training_readiness.py -v
```
