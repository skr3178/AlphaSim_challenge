# Independent raw-camera pilot acquisition — 2026-09-19

Acquisition is **stopped**. No training, GPU inference or evaluation was launched
by this acquisition task. Cosmos remains outside the acquisition process.

## Result

Dataset root:
`/media/skr/SeagateHub1/cosmos3-real-camera-pilot-20260919`

Exporter input: `acquisition-manifest.json` under that root. Read its `windows`
and `images` lists; **do not glob every JPEG on disk** because an incomplete
window is intentionally excluded from the manifest.

| Item | Verified result |
| --- | ---: |
| Complete front-camera windows / distinct source logs | 24 / 24 |
| Original captured JPEGs | 7,749 |
| Cities | Boston, Pittsburgh, Singapore |
| City/date groups | 5 |
| Nominal 1 Hz anchor upper bound, allowing 1 s history + 4 s future | 3,731 |
| Actually usable training examples | Pending exporter alignment/route checks |
| Original proposed training / validation source logs | 24 / 0 |
| Verified JPEG payload bytes | 1,471,227,589 |
| Conservatively charged compressed transfer bytes | 1,755,271,168 (1.635 GiB) |
| User-approved transfer cap | 21,474,836,480 bytes (20 GiB) |
| Total directory footprint at completion | 1,748,424,912 bytes |

The nominal anchor count is not a claim that all history/route/target examples
will pass export checks. It sums floor(window span minus five seconds), before
continuity, alignment and route validation. It is not 3,731 independent scenes.

## Data provenance and checks

- Public OpenScene revision: `a76f840b65e972bc45e56c2adced897498e9a026`.
- Archives: `openscene-v1.1/openscene_sensor_trainval_camera/`.
- Only the **first CAM_F0 directory** of selected archives was retrieved.
- Each saved JPEG matched an exact local SQLite `image.filename_jpg` reference.
- Every completed JPEG was decoded as 1920×1080 JPEG and SHA-256 hashed.
- Exposure timestamps and linked ego-pose timestamps are recorded per image.
- Existing `database-inventory.csv` `proposed_role` assignments were preserved.
- Public scene/source-log/city-date exclusions, official validation exclusions
  and mini quarantine were applied. No protected split file was modified.
- Eligibility is under the existing local exclusion rules; this is not a claim
  of organizer certification or knowledge of the private leaderboard selection.
- The full multi-gigabyte archives were not downloaded or checksum-verified.

The snapshot inventory and protected-split hashes are pinned in
`acquisition-plan.json`. Individual camera receipts are in `receipts/`.

## Coverage limitation: no original pilot validation footage

The initial 128-prefix pass acquired 19 training logs. A second pass extended
discovery to archive indices 0–511, reusing existing results and the same ledger.
There were 199 successful prefix reads among indices 0–199, 312 HTTP errors and
one timed-out prefix (195). No successful first-camera prefix matched an eligible
window assigned `pilot_validation` in the original proposal.

This is a limitation of the **inspected first-directory sample and matching local
metadata**, not evidence that OpenScene contains no validation footage. HTTP
error status codes were not persisted; missing archive indices are plausible
but were not separately verified. No further network requests are running.

Training acquisition stopped once its nominal size/log/city target was met.
The completed logs cover Boston 2021-09-15, 2021-10-01 and 2021-10-06;
Pittsburgh 2021-08-17; and Singapore 2021-10-11. This remains a small, date-limited
pilot, not broad real-world coverage.

If separately approved, a **new** pilot manifest could reserve the five Boston
logs from October 1 and October 6 as a date/log-disjoint development split:

| Prospective new role | Logs | JPEGs | Nominal 1 Hz anchor upper bound |
| --- | ---: | ---: | ---: |
| Training: remaining three city/date groups | 19 | 6,593 | 3,183 |
| Development: Boston October 1 and October 6 | 5 | 1,156 | 548 |

That choice has **not been activated by this acquisition task**. It would need a
new explicit manifest and rationale; it must not rewrite or silently reinterpret
the older proposed roles. Development would be Boston-only and should be reported
as such. No additional unique source logs from these two dates were found among
the eligible first-camera prefixes inspected.

## Incomplete files and accounting

Part 136 hit its 256 MiB compressed prefix bound before completing the first
camera directory. The 1,385 already decoded JPEGs (269,044,164 bytes) under
`sensor_blobs/2021.08.17.18.43.12_veh-43_01906_02722/CAM_F0/` remain recoverable
on disk but are **not included in the acquisition manifest or training counts**.
Nothing was deleted.

`transfer-ledger.jsonl` reserves a full request cap before network access and
records the actual reader count on completion. Interrupted/pre-reader requests
remain fully charged. Final charged bytes comprise 1,734,823,936 observed reader
bytes and 20,447,232 conservatively retained reserved bytes. Probes and the
incomplete camera transfer count against the same 20 GiB budget. There were no
hidden automatic retries or full-archive transfers.

## Reproducibility

Implementation: [acquire_raw_camera_pilot.py](acquire_raw_camera_pilot.py).
Safety tests: [test_acquire_raw_camera_pilot.py](test_acquire_raw_camera_pilot.py).
Three CPU tests passed: compressed-byte bound, interrupted-transfer accounting,
and archive traversal/unlisted-file/symlink rejection. Resume verifies recorded
JPEG hashes and immutable split membership before reusing completed windows.

Process log: `/tmp/cosmos3-real-camera-acquisition-20260919.log`.
Execution used tmux sessions `cosmos_raw_camera_20260919` and
`cosmos_raw_camera_extend_20260919`; both jobs completed. The earlier nohup
launcher exited before issuing requests and was replaced with tmux.

Per-image schema: `filename` relative to `sensor_root`, absolute `image_path`,
`timestamp_us`, `ego_pose_timestamp_us`, `bytes`, `sha256`. Each parent window
contains `metadata_database`, `window`, `source_log`, `city`, `date`,
`proposed_role`, `image_count`, `span_s`, and provenance. Use only completed
manifest windows in downstream exporters.
