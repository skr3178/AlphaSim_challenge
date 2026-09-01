# AlpaSim E2E Closed-Loop Challenge 2026 — team Lucifer AI (nuPlan track)

Working notes, tooling and our submission-code changes. **Start with [CURRENT-BEST.md](CURRENT-BEST.md)** (what is submitted / staged,
the eval standard, quota) and [ROUTE-SELECTION-PLAN.md](ROUTE-SELECTION-PLAN.md) (next round).

| | |
|---|---|
| `*.md` | living notes: `SETUP-NOTES.md` (everything tried, defects 0–7, measurements), `LOCAL-PLAN.md`, `strategy.md`, `RANKING.md`, `METRICS.md`, `CHECKPOINT-SURVEY.md`, `VAVAM-CHECKPOINTS.md`, `SHARDS-RUNBOOK.md` |
| `alpasim-mods/` | our modifications to `NVlabs/alpasim@e2e_challenge` — see its README for how to re-create the working tree |
| `tools/` | eval launchers (`run-eval.sh IMG NAME GROUP PRESET`), queue scripts, `snapshot.sh` (sync + commit + push) |
| `capture/` | driver capture / load-test / stage visualiser tools |
| `leaderboard/` | public board snapshots (JSON/CSV) |
| `download-shards.sh`, `fetch-leaderboard.py`, `alpasim-setup-4090.sh` | data + setup tooling |

Not in git (see `.gitignore`): model weights and HF caches, nuPlan data, `runs/` and logs, captured frames (`capture/captured/`),
result images (`viz/`), the mirrored DriveIRT docs (`navhard-docs/`), and the unmodified upstream clones
(`NVlabs/alpasim@f012862`, `valeoai/VideoActionModel@738050e` — pinned, not copied).

Commit discipline: `tools/snapshot.sh "what changed"` after every milestone, so each commit is a consistent restore point of notes + code.
