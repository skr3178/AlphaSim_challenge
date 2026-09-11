# AlpaSim E2E Closed-Loop Challenge 2026 — team Lucifer AI (nuPlan track)

Working notes, tooling and our submission-code changes. **Start with [CURRENT-BEST.md](CURRENT-BEST.md)** (what is submitted / staged,
the eval standard, quota), then [SETUP-NOTES.md](SETUP-NOTES.md) §6.48–§6.52 for the current state of play.

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
| [CURRENT-BEST.md](CURRENT-BEST.md) | **Start here.** What is submitted / staged, against what baseline, what is the quota? |
| [SETUP-NOTES.md](SETUP-NOTES.md) | The running log. Numbered §6.x sections, newest last — every result, defect and correction. |
| [EVAL-RUNBOOK.md](EVAL-RUNBOOK.md) | How do I run a local evaluation? (scene sets, presets, launcher) |
| [METRICS.md](METRICS.md) | What does this metric or abbreviation mean? |
| [LEADERBOARD-REVIEW.md](LEADERBOARD-REVIEW.md) | Post-reset board review and the next-submission recommendation (09-10). |
| [ROBUSTNESS-PLAN.md](ROBUSTNESS-PLAN.md) | Proposed robustness work. Its trajectory-sanitiser premise is refuted (§6.52); its eval decision-support half stands. |
| [SKR.md](SKR.md) | The user's own working notes. |
| [archive/](archive/README.md) | Superseded plans and reference docs, with a note on why each was retired. |
| [issues/](issues/) | Local mirror of all NVlabs/alpasim GitHub issues (`tools/sync-issues.sh` to refresh). |

_`LOCAL-PLAN.md`, `SHARDS-RUNBOOK.md`, `STATUS.md`, `link.md` were merged into the above on 2026-09-01
(backup in `.doc-backup-20260901/`)._
