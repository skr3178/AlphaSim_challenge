# Recovery and frozen validation run

## Revised scheduling at user's request

The original combined job (PID 432251) was stopped deliberately with its partial
archive preserved. Its old `status.json` saying `recovering` is stale.

- Preparation-only recovery: PID 433525, artifacts
  `artifacts/validation-20260922T100233Z/`; no automatic evaluation handoff.
- Concurrent evaluation: PID 433533, artifacts
  `artifacts/split-validation-20260922T100233Z/`.
- Start with a smoke check and the fixed three candidates on available144.
- Wait for verified recovery, run the same candidates on missing6, then merge
  all 150 per-scene rows. Do not average batch averages. Candidate settings and
  validation membership are unchanged. Results remain partial until both batches
  complete. No promotion or tuning based on the first batch.

The two jobs are detached. Evaluation uses the shared GPU lock; preparation
uses the dataset download lock. Recovery targets are exposed read-only to the
simulator after they exist. Old scene assets and the 313-scene holdout are untouched.

Authorized scope: recover six missing scenes from the 150-scene validation list,
assemble a separate runtime root, evaluate baseline and two repeat-confirmed
finalists. No new parameter search, training, submission or final-holdout use.

Detached job launched at 2026-09-22 09:59 UTC, initial PID 432251.
Artifacts: `artifacts/validation-20260922T095904Z/`.
Launcher log: `validation-launch-20260922T095904Z.log`.

1. Resume pinned shard 013 from 21,996,957,696 / 31,683,669,758 bytes on Seagate.
2. Verify full archive SHA-256. Extract only the six missing validation scenes
   into `/media/skr/SeagateHub1/alpasim-validation-recovery-20260922/`.
   Stop if that shard does not contain all six; do not silently download other shards.
3. Check all 150 against required basic assets and verified extraction receipts
   (member sizes). This is not a fresh per-file content hash audit of old assets.
4. Assemble workspace `runtime-data` with symlinks to asset roots and old caches;
   expose backing data roots read-only inside simulator containers. Do not modify
   the existing 400-scene runtime root or old cache.
5. Run one validation-scene smoke check, then 150 scenes for each fixed arm:
   baseline; longitudinal weight 0.5 + acceleration weight 2.0; acceleration
   weight 2.0 alone. All other settings default, stabilization and predicted yaw off.
6. Save logs/configs/paired results and stop on missing coverage or planning errors.

The 150 IDs and candidate settings are frozen before evaluation. All validation
source logs are checked disjoint from the original development400 source logs.
This does not establish disjointness from the checkpoint's training data, and
does not certify current official-runtime parity. Reserved final holdout remains
untouched. Evaluation starts automatically only after preparation and smoke gates.
