# Seagate public-navtest expansion download

Started: 2026-09-18 09:02 UTC / 14:32 IST, at the user's explicit request.
This is a detached **asset download/extraction job only**. No inference,
simulation, training, warmup or official submission is scheduled after it.

## Scope and space

- Target: **1,085 additional public scenes**, complementing the existing 400.
- Immutable plan: [plan.json](plan.json).
- Dataset: `OpenDriveLab/AlpasimChallenge2026_nuplan_track`.
- Pinned revision: `6b3569897bd9c4f999d8aa856bb4f9e4aaa96c3c`.
- Shards: 002, 003, 004, 005, 006, 008, 010, 011, 012, 013, 015.
- Exact compressed transfer: **356,239,308,815 bytes = 356.24 GB = 331.77 GiB**.
- Keep the verified archives for recovery. Allow approximately **800–850 GB extra
  total space**, including estimated expanded assets and headroom. Expanded size
  is not yet measured; actual per-shard extracted byte counts go into receipts.
- Seagate had 1,957,700,943,872 bytes free at preflight (about 1.96 TB / 1.78 TiB).
  The script reserves at least 30 GiB free while downloading/extracting.

The pinned public API's sizes and LFS SHA-256 metadata were checked before launch:
https://huggingface.co/api/datasets/OpenDriveLab/AlpasimChallenge2026_nuplan_track/tree/6b3569897bd9c4f999d8aa856bb4f9e4aaa96c3c/MTGS_asset/navtest/assets

## Destination

New dedicated directory:

`/media/skr/SeagateHub1/alpasim-navtest-expansion-20260918/`

Contents:

- `archives/`: resumable `.part` downloads and retained SHA-256-verified tarballs;
- `staging/`: temporary extraction, restricted to safe regular files/directories;
- `data/navtest/assets/`: completed additional public scenes;
- `data/navtest/configs/`: copies of the existing 1,485 scene configs, checked
  against their frozen hashes;
- `receipts/`: verified archive identities, member sizes and actual scene lists;
- `status.json`: current process/phase/shard, updated during transfers;
- `coverage.json`: final exact scene-ID coverage check, produced after all shards.

The old root `/home/skr/alpasim-challenge/nuplan-track`, its 400 assets and its
trajdata cache are unchanged. Old archives in `alpasim-nuplan-track-hf` are also
untouched. The new directory is **not yet an assembled runtime root**: combined
mounts and cache/scorer compatibility remain separate work. A completed transfer
does not certify simulation readiness.

The historical shard exclusions are checked indirectly by final exact coverage:
success requires all 1,085 requested scenes in the new root and 1,485 public
scenes available across the old/new roots. A discrepancy stops the job with an
error rather than claiming success from the number of downloaded archives.

## Monitor from any terminal

```bash
tail -f /home/skr/Downloads/alpasim_challenge/evaluation/downloads/2026-09-18-seagate/download.log
```

Or inspect the process state:

```bash
python3 -m json.tool /media/skr/SeagateHub1/alpasim-navtest-expansion-20260918/status.json
tmux -L alpasim-downloads list-sessions
```

The dedicated tmux session is `navtest-expansion` on server `alpasim-downloads`.
The launcher returned and the session was verified alive, with bytes arriving in
`part002.tar.gz.part`. The status/log, not this document, shows current progress.
Output is redirected to the persistent log, so attaching to tmux is not required.

## Pause and restart

To interrupt this download job without touching any other tmux session:

```bash
tmux -L alpasim-downloads send-keys -t navtest-expansion C-c
```

Wait for that session to exit before restarting. Resume using the same launcher:

```bash
bash /home/skr/Downloads/alpasim_challenge/tools/start-navtest-download.sh
```

The launcher does nothing if its tmux session already exists. A separate file
lock prevents duplicate workers. Partial archives resume using HTTP byte ranges;
completed shards with matching receipts/files are skipped. Interrupted extraction
can resume from its verified archive. Corrupt archives or altered completed files
are preserved and reported for inspection, not silently overwritten/deleted.

Closing this terminal or detaching from tmux does not stop the process. Keep the
computer awake, networking available, and Seagate mounted. **Power-off/reboot does
not automatically restart it**; run the launcher again after the disk is mounted.

## Validation before launch

Nine synthetic-archive/download tests passed, alongside the ten existing scene
manifest tests (19 total). They cover path traversal, forbidden links/devices,
selective extraction, interrupted promotion, changed-file detection, archive
checksums, completed partials, byte-range resume invocation and low-disk refusal.
Python compilation, launcher shell syntax and whitespace checks also passed.

This download does not select or expose model results on any held-out scenes.
The city/date-aware v2 split remains pending and must preserve the v1 manifest.
