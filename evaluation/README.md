# Local public scene setup — 2026-09-18

**Later update, 2026-09-18 14:32 IST:** the user authorized the full 1,085-scene
expansion. A detached tmux download/extraction job is now started on Seagate; see
[monitoring and restart instructions](downloads/2026-09-18-seagate/README.md).
The inventory and readiness statements below are the pre-download snapshot, not
live status. No evaluations have been launched, and v2 selection remains pending.

Status: **scene selection frozen and config loading checked; new assets not staged;
no simulation, inference, training or submission run.** This fixes the scene-selection
part of the local-evaluation plan, not scorer/runtime parity with the board.

## Frozen suites

The names retain the existing `py123d_` prefix, but the same lists are for paired
comparisons of Py123D, WA-JEPA and any other policy. Do not generate a separate
favorable split for each model.

| Suite | Scenes | Source logs | Basic assets present | Purpose |
|---|---:|---:|---:|---|
| `py123d_development400` | 400 | 13 | 400 | Existing development/regression sample |
| `py123d_validation` | 150 | 19 | 0 | First candidate-selection sample on new local logs |
| `py123d_validation_pool` | 589 | 19 | 0 | Full pool behind compact validation; includes those 150 |
| `py123d_holdout` | 313 | 12 | 0 | Reserved final check; do not tune on it |
| `py123d_seen_log_extension` | 183 | 7 | 0 | Additional clips on already-exposed logs; not independent holdout |
| `py123d_public_full` | 1,485 | 44 | 400 | Public universe; overlaps all other suites |

Only development400 + validation_pool + holdout + seen_log_extension are a
disjoint partition of 1,485. The 150-scene validation suite is nested in its pool.

| City | Old development | Compact validation | Validation pool | Holdout | Seen-log extension | Public full |
|---|---:|---:|---:|---:|---:|---:|
| Las Vegas | 100 | 81 | 246 | 108 | 26 | 480 |
| Boston | 100 | 40 | 249 | 89 | 27 | 465 |
| Pittsburgh | 100 | 29 | 94 | 116 | 10 | 320 |
| Singapore | 100 | 0 | 0 | 0 | 120 | 220 |

Singapore has only two source logs in this public universe; both are already in
development. Retain its old scenes as regression checks, but do not label the
120 additional Singapore clips an unseen-log test. The new validation and holdout
are independent of development **by local source log**, not necessarily by geography,
date, route, or model-training exposure.

## Selection and provenance

- Canonical public list: upstream checkout `alpasim-upstream-20260916`, commit
  `7611632f17a623a10564f4648c778ebb18079735`, `navtest_full.yaml`.
  Its scene-list file is byte-identical to the older active runtime's public list.
- Public YAML SHA-256:
  `b77adfa9b91b29a3b8600bc785048e98e9a83390260bfed7e4d91aeda6ff767f`.
- Exposure audit: 46 saved result summaries plus 53 resolved worker configs,
  including unfinished/failed runs. Their union is the same 400 scenes/13 logs.
  Hashes and paths of every exposure source are in `public-suite.json`.
- Group by full source-log timestamp and vehicle ID, not recording-window suffix.
  Read authoritative city from each MTGS scene config and retain its hash.
- Preserve the pre-existing generator seed `20260911`. Hash-order unused logs
  within each city; reserve approximately 60% for validation and the rest for
  holdout. Select 150 clips round-robin over the validation logs. This balances
  logs, **not cities or the unknown private distribution**.
- Never use model scores or downloaded-asset availability to choose membership.
  Neither downloading nor refreshing inventory changes the frozen lists.
- Manifest SHA-256:
  `a2a150d4eb139db0cbfa7d1cfa37a8eff701db34fff8264034c0433ab2f36b64`.

Files:

- `public-suite.json`: immutable scene metadata, provenance and suite memberships.
- `configs/nuplan_scenes/*.yaml`: Hydra groups, with `test_suite_id: null` and
  `limit_to_first_n: 0` explicitly set.
- `scene-lists/*.txt`: exact scene IDs for future selective asset staging.
- `asset-inventory.json`: dated initial inventory, **not live readiness status**.

## Safe checks (no evaluator launched)

From `/home/skr/Downloads/alpasim_challenge`:

```bash
python3 -m unittest discover -s tools/tests -v
python3 tools/eval-suite.py
python3 tools/eval-suite.py --check-suite py123d_validation
```

The last command currently exits **1**, correctly, because 150/150 validation
scenes lack rendering assets. Exit 0 means basic files exist and scene metadata
matches the frozen hashes. It does **not** certify rendering, complete referenced
foreground assets, cache versions, inference health or official scorer parity.
Malformed/unknown suites are errors (exit 2).

To save a later inventory without overwriting the manifest or old inventory:

```bash
python3 tools/eval-suite.py --inventory-output evaluation/asset-inventory-after-staging.json
```

Use a new filename for each snapshot. `--data-root /absolute/staged/root` can check
another fully assembled data root without changing membership. A new root must
contain `navtest/configs` and `navtest/assets`; cache compatibility is a separate
check. Never rerun `--write` to update asset status: it refuses to replace a frozen
manifest. Deliberate future versions need a separate `--output` directory and
their own exposure audit.

Checks performed today: 10 unit tests passed; all six generated groups were loaded
with Hydra's compose API and verified against the manifest (including real null
suite IDs and zero scene limits); Python compilation and `git diff --check` passed.
No simulator service was imported or started for these tests.

## Asset staging: the remaining decision

The existing root is `/home/skr/alpasim-challenge/nuplan-track`. All 1,485 scene
configs exist. Rendering assets are missing for 1,085 scenes, including all compact
validation and holdout scenes. Do not replace missing scenes with whatever happens
to be downloaded: keep the split fixed and mark it incomplete until ready.

Disk snapshot: `/` about 58 GiB free; `/media/skr/storage` about 74 GiB;
`/media/skr/SeagateHub1` about 1.8 TiB. The external Seagate drive can accommodate
the remaining public assets; neither SSD has space for the full remainder.

The organizer publishes [15 compressed asset shards](https://huggingface.co/datasets/OpenDriveLab/AlpasimChallenge2026_nuplan_track/tree/main/MTGS_asset/navtest/assets),
not individual scene downloads. Prior staging consumed shards 001, 007, 009 and
014. The other 11 listed archives total roughly **356 GB compressed**, using the
rounded online sizes; expanded size has not been measured. Budget about **450 GB
expanded plus headroom**, or additional archive space if retaining compressed copies.
The old runbook's approximately 330 GB expanded estimate should not be relied on.

Recommended order after choosing download scope:

1. Stage to a **new dedicated directory** on Seagate, leaving the current root,
   its caches, and old 400 assets unchanged. Do not run the old relocation helper.
2. Either retain just the fixed 150 validation scenes or stage all missing public
   assets for later use. Selective extraction saves disk space, but without a
   verified shard/member index it may still need to download/scan many large
   archives. Do not assume 150 scenes implies a small network transfer.
3. Pin the dataset revision and archive identities at download time; retain a
   receipt and actual member inventory. Never infer exact shard membership solely
   from filename sorting or the historical city estimates.
4. Validate extraction paths, use temporary per-shard/per-scene staging, and
   promote only complete content. Preserve existing files; no blind overwrite.
   Assemble a runtime-readable root and verify every symlink target is also
   accessible inside the relevant containers before any simulation.
5. Rerun the fixed-suite preflight and save a new inventory. Stage holdout assets
   freely, but do not inspect model outcomes or tune on the reserved holdout.

**No download, relocation, deletion, cache replacement or runtime change was made
in this step.** Download scope was requested separately (validation first versus
the full remainder). There is no background downloader running.

## Gates before the first actual comparison

These are follow-up work, not completed by selecting scenes:

- Match the current organizer scorer/runtime and confirm cache provenance,
  including the road-area/off-road fixes described in
  `../UPSTREAM-REVIEW-2026-09-18.md`.
- Integrate the generated config directory into the chosen runtime's Hydra search
  path and the launcher preflight. The existing `tools/run-eval.sh` still assumes
  groups live inside the old runtime; it has **not** been modified or launched.
  Do not use it with a new group until this integration is done.
- Audit speed, turning, traffic and progress-opportunity coverage from local
  metadata/cache without consulting candidate scores. Today's split only audits
  city/source-log/date metadata, not these behavioral strata.
- When experiments are explicitly authorized, compare unchanged policies on the
  exact same validation clips/configuration. Require complete rollouts and
  zero unaccounted planning failures; inspect per-city/per-log and failure-mode
  results, with source-log clustered paired uncertainty.
- Treat this as a broader public robustness check, never a reconstructed private
  set or a fitted local-to-PCS/rank conversion. Freeze the final candidate before
  using the holdout; tuning after that consumes the holdout.
