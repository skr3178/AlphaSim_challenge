# All-city frozen-Cosmos driving-head pilot

Updated 2026-09-21 after the user requested training, validation and evaluation
coverage across all four cities and authorized proceeding with the data-gap audit
and targeted acquisition. This supersedes the Boston-only development split
proposal, not the immutable public-evaluation exclusions.

**Execution update:** the user subsequently approved the stepwise tests,
including the explicitly requested shared-date whole-log split. SSD staging
and split activation are complete; see [STEPWISE-RUN-20260921.md](STEPWISE-RUN-20260921.md).
The unresolved-choice paragraphs below document the earlier decision, not a
new approval requirement.

## Fixed scope

- Freeze the Cosmos3-Edge generator and VAE; train only the 815,235-parameter head.
- Use independent real nuPlan camera recordings with expert targets, not public
  challenge recordings as training data.
- Preserve all public source-log/city-date exclusions, official-validation log
  exclusions and mini quarantine. Preserve the old acquisition and split files.
- Keep the original shared 20 GiB cumulative camera-transfer cap. No submission.
- Do not launch a full benchmark before the split is resolved and engineering
  checks pass. Acquisition is not evidence of model quality.

## Audit and acquisition

Before expansion: 7,749 JPEGs from 24 source logs: Boston 14, Pittsburgh 8,
Singapore 2. All expected image paths and byte sizes matched on recheck.

**Completed:** both targeted Vegas downloads succeeded with no extension
failures. The combined manifest contains **9,359 verified images from 26 logs**:
Boston 14, Pittsburgh 8, Singapore 2 and Vegas 2. Cumulative conservatively
charged camera transfer is **1.963875 GiB / 20 GiB** (about 337 MiB additional).
The tmux job has finished; no training or evaluation job was launched.
The extension's two unit tests, three acquisition safety tests and 15 exporter
tests passed. The earlier original manifests/protection hashes remain unchanged.

The previous 199 successful archive-prefix probes already identify eligible
Vegas camera windows whose metadata is in the existing local Vegas ZIP.
Selected two distinct July 9 logs, parts 109 and 37, without further archive
discovery or downloading the full metadata archive:

- `2021.07.09.16.12.19_veh-26_06964_07035`
- `2021.07.09.15.53.28_veh-38_03528_04262`

Only those two local ZIP members are extracted (about 404.5 MiB combined).
Archive CRC, SQLite quick_check, exact recording identity, date and city are
checked before camera acquisition. Camera downloads verify exact DB membership,
JPEG decoding, dimensions and SHA-256. Each compressed request is capped at
384 MiB, so this extension can charge at most 768 MiB. The original ledger was
charged 1.635 GiB before this extension. Receipt hashes remain separate from the
old acquisition manifest; a new combined manifest references the old and new
camera files.

The first attempt stopped before network transfer because the local database
uses the legitimate `las_vegas` city alias rather than `us-nv-las-vegas-strip`.
Both aliases are now explicitly accepted. That failed attempt and local partial
metadata files are retained. The successful retry uses a new v2 directory.
The exporter also now recognizes inventory city `vegas` as map `las_vegas`.

Completed-job paths:

- Script: `cosmos3/extend_all_city_pilot.py`
- tmux: `cosmos_allcity_20260921_v2`
- Log: `/tmp/cosmos-allcity-20260921-v2.log`
- New receipts, plan, metadata and combined acquisition manifest:
  `/media/skr/SeagateHub1/cosmos3-real-camera-pilot-20260919/extensions/all-city-20260921-v2/`
- Images remain under the original `sensor_blobs` root, with new filenames;
  the original acquisition manifest is not overwritten.
- Use the new manifest's `status`, `windows`, and `extension_failures` to determine
  completion. Never include partial image folders by globbing the disk.

## Split decision that acquisition alone cannot resolve

The indexed eligible camera prefixes cover three Boston dates, but only one
Pittsburgh date (2021-08-17), one Singapore date (2021-10-11, just two unique
source logs), and one matched eligible Vegas date (2021-07-09).

This is a limitation of the inspected archive prefixes, not proof that the full
dataset lacks other dates. Repeating the same prefix search will not solve it.

Two honest choices before fitting:

1. A **whole-log-disjoint, same-date-allowed all-city pilot**: after the Vegas
   extension completes, allocate Boston 11 train/3 validation, Pittsburgh 6/2,
   Singapore 1/1 and Vegas 1/1 (19 train, 7 validation logs). Pick logs using a
   recorded deterministic seed independent of model scores, review footage
   duration/motion coverage, and report the very small Singapore/Vegas holdouts.
   This requires an explicit new split contract: the present reader requires
   city/date separation and must not silently be bypassed.
2. Retain strict city/date separation: locate and acquire other eligible dates
   before activating a split. This needs a different targeted archive-index/data
   acquisition strategy; no promise it fits the remaining allowance.

No new split is activated by this data acquisition. Ask the user whether the
first choice is acceptable before changing the strict split validation contract.

## Benchmark inventory

Read-only preflight confirms development400 has 100 scenes per city, 13 source
logs total, 400/400 basic assets present and no changed configuration hashes.
These are regression scenes previously used for model development; they are not
a pristine final test. Their logs remain excluded from new training.

The frozen independent public holdout has 313 scenes from 12 logs, covering
Boston, Pittsburgh and Vegas, not Singapore. Both Singapore public source logs
were already in development400. We cannot claim a four-city unseen-log public
holdout by relabeling neighbouring Singapore clips.

The separate Seagate expansion root currently passes basic file preflight for
313/313 holdout scenes, 144/150 compact validation scenes and 894/1,085 expansion
scenes overall. Old root provides the original 400. The expected final expansion
coverage receipt is absent; full 1,485-scene runtime readiness is not established.
No rendering, inference or score evaluation ran during these checks.

## Execution after split approval

1. Pin new split/provenance without modifying historical files; preserve source
   exclusions. Verify whole-log independence and disclose shared dates.
2. Export genuine three-frame histories, causal motion, sparse permitted MAP
   navigation and complete four-second targets; count accepted/rejected examples
   and unique footage intervals per city/log. Target roughly 2,000–5,000 training
   examples, subject to actual coverage, not duplication.
3. Short frozen-feature/head/checkpoint replay gate; verify all backbone/VAE
   gradients are absent and optimizer membership is head-only.
4. Train matched fresh visual and state/route-only heads; include a causal
   constant-velocity baseline. Use bounded ten-epoch settings and log-disjoint
   validation. Check both aggregate and per-city trajectory errors.
5. Only after compatibility checks, compare the resulting driver on the fixed
   development400 with matching simulator/scorer/controller settings and baseline
   provenance. Report scene score, progress, at-fault incident distance, GT
   distance, failures, timing and complete-driver peak VRAM under concurrency.
6. Keep the independent public holdout sealed for a separately approved final
   check. No automatic official submission or claims about private PCS.
