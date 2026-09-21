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

### Local 400-scene model comparison — 2026-09-21

Saved aggregates use the same 400 scene IDs (`navtest_local400`) and configured
simulation timing. These are historical local comparisons, not reruns under
identical software revisions or predictions of official leaderboard scores.

| Model | Scene score ↑ | Zero-score scenes ↓ | Distance to GT, m ↓ | At-fault distance, km ↑ |
|---|---:|---:|---:|---:|
| WA-JEPA S4 | **0.9302** | **24** | 1.24 | **10.68** |
| WA-JEPA S2 | 0.9247 | 26 | 1.36 | 5.40 |
| Route follower | 0.8896 | 41 | 2.07 | 0.62 |
| VaVAM + μP | 0.8813 | 46 | 2.35 | 0.90 |
| Stock VaVAM | 0.8493 | 60 | 3.57 | 0.58 |
| **GTRS-Dense** | **0.8424** | **61** | **4.07** | **0.85** |
| Py123d-0014 | 0.8420 | 33 | **1.17** | 1.14 |
| Go-straight starter | 0.6192 | 104 | 2.33 | 0.47 |

At-fault distance means average kilometres between at-fault incidents (higher
is better). GTRS completed 400/400 scenes and 4,000 neural calls with no inference
errors, cached plans or fallbacks. Its 61 zero scores were attributed to 46
lateral corridor exits and 15 at-fault collisions; these are primary failure
causes, not counts of every overlapping metric flag. It achieved 321 full scores
versus Py123d's 292, but also more zeros (61 versus 33).

Conclusion: unchanged GTRS-Dense does not improve on our strongest local
baselines. Route conditioning and controller tracking warrant investigation;
neither is an established fix. S12 is omitted because its aggregate was not
available at the expected path.

GTRS used the supplied ResNet reward checkpoint and default progress-enhanced
scorer as a host process, not a hardened submission container. See
[GTRS setup](alternative_models/gtrs_dense/README.md). Local artifacts are in
`alternative_models/gtrs_dense/artifacts/20260921T092412Z/` and are intentionally
excluded from Git along with weights and trajectory vocabulary assets.

### Documentation index

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
