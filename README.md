# AlpaSim E2E Closed-Loop Challenge 2026 — team Lucifer AI (nuPlan track)

Working notes, tooling and our submission-code changes. **Start with [CURRENT-BEST.md](CURRENT-BEST.md)** (what is submitted / staged,
the eval standard, quota) and [ROUTE-SELECTION-PLAN.md](ROUTE-SELECTION-PLAN.md) (next round).

| | |
|---|---|
| **Docs** | one file per question — see the table below |
| `alpasim-mods/` | our modifications to `NVlabs/alpasim@e2e_challenge` — see its README for how to re-create the working tree |
| `tools/` | eval launchers (`run-eval.sh IMG NAME GROUP PRESET`), queue scripts, `snapshot.sh` (sync + commit + push) |
| `capture/` | driver capture / load-test / stage visualiser tools |
| `leaderboard/` | public board snapshots (JSON/CSV) |
| `download-shards.sh`, `fetch-leaderboard.py`, `alpasim-setup-4090.sh` | data + setup tooling |

Not in git (see `.gitignore`): model weights and HF caches, nuPlan data, `runs/` and logs, captured frames (`capture/captured/`),
result images (`viz/`), the mirrored DriveIRT docs (`navhard-docs/`), and the unmodified upstream clones
(`NVlabs/alpasim@f012862`, `valeoai/VideoActionModel@738050e` — pinned, not copied).

Commit discipline: `tools/snapshot.sh "what changed"` after every milestone, so each commit is a consistent restore point of notes + code.

### The docs — one file per question

| File | Question it answers |
|---|---|
| [CURRENT-BEST.md](CURRENT-BEST.md) | **Start here.** What are we submitting, against what baseline, what's the quota? |
| [strategy.md](strategy.md) | What do we do next, and how do we decide? (§8 = the ranked backlog) |
| [EVAL-RUNBOOK.md](EVAL-RUNBOOK.md) | How do I run a local evaluation? (scene sets, presets, launcher) |
| [RANKING.md](RANKING.md) | Why does the score behave this way? (IRT/ZOIB, anchors, the asymmetry) |
| [METRICS.md](METRICS.md) | What does this metric or abbreviation mean? |
| [ROUTE-SELECTION-PLAN.md](ROUTE-SELECTION-PLAN.md) | How is the in-flight B1/B2/B4 change designed? (retire on ship) |
| [SETUP-NOTES.md](SETUP-NOTES.md) | What happened, and what broke? (defects 0-7, every measurement) |
| [CHECKPOINT-SURVEY.md](CHECKPOINT-SURVEY.md) · [VAVAM-CHECKPOINTS.md](VAVAM-CHECKPOINTS.md) | Model/checkpoint reference |

_`LOCAL-PLAN.md`, `SHARDS-RUNBOOK.md`, `STATUS.md`, `link.md` were merged into the above on 2026-09-01
(backup in `.doc-backup-20260901/`)._
