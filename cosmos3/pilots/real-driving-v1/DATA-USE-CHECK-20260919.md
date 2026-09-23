# Data-use check and local availability — 2026-09-19

## Outcome: unresolved; later stages not started

The user requested this order: resolve training-data eligibility, export and
validate the eight approved scenes, then run a short full-checkpoint feature
test. **The first condition has not been established.** No sample export,
feature extraction, GPU inference, head fitting, evaluation or submission was
started in this check. No terms were accepted and no login/token was changed.

This is an evidence record, **not a permission record**. No `rules-review.json`
with a `permitted` decision has been created. The conditional pilot manifest and
its hashes remain unchanged.

## Evidence reviewed

1. The current public [challenge README](https://github.com/NVlabs/alpasim/blob/e2e_challenge/e2e_challenge/README.md)
   describes `navtest` as the local public evaluation set. The inspected text
   does not explicitly settle whether contestants may train on its scenes or
   rendered observations. It is not evidence of either a blanket training
   permission or a definitive prohibition.
2. The current [CLI documentation](https://github.com/NVlabs/alpasim/blob/e2e_challenge/e2e_challenge/competitor_cli/README.md)
   says competition terms are provided after authentication. It separates
   viewing terms from accepting them.
3. The read-only command below was retried using the existing CLI configuration:

   ```bash
   python3 alpasim-upstream-20260916/e2e_challenge/competitor_cli/alpasim_challenge.py terms show
   ```

   Result: `HTTP 401 {"error": "Missing or expired session"}`. The terms text
   was not obtained. No credentials were printed or requested in chat.
4. Local `SETUP-NOTES.md` around line 2783 contains a historical summary that the
   nuPlan track requires public training resources. That summary concerns use
   of a pretrained baseline, not explicit eligibility of these public evaluation
   scenes. It is not a complete, current terms copy and does not resolve this
   narrower question.
5. The public [dataset card](https://huggingface.co/datasets/OpenDriveLab/AlpasimChallenge2026_nuplan_track/blob/main/README.md)
   describes evaluation assets and a dataset license. Dataset availability or
   licensing alone does not establish competition training-split eligibility.
6. Public-source searches did not produce a current, authoritative statement
   permitting training on these exact public-navtest scenes. GitHub issue #152
   was unavailable to the web reader (404); no conclusion was drawn from it.

## What would resolve it

Supply a saved current terms file or an organizer statement addressing training
on public `navtest` scenes, including rendered observations and expert labels.
Alternatively, authenticate locally to retrieve the private terms; viewing them
does not require accepting a replacement version. Do not send credentials in
chat. A current terms file may still require organizer clarification if its
training/test-split requirements are ambiguous.

Suggested question, **not sent**:

> May nuPlan-track entrants train or fine-tune on the publicly released AlpaSim
> navtest scenes, including rendered camera observations and expert trajectories,
> if those source logs are excluded from their own independent local evaluation?
> Or must training use separate nuPlan/OpenScene training logs?

Local export and model execution themselves do not technically require a
challenge token. The pause follows the explicitly conditional pilot scope; it
is not a claim that the local software needs authentication.

## Fresh answer to the missing-data question

Read-only asset presence checks on 2026-09-19:

| Collection | Basic assets present | Total |
| --- | ---: | ---: |
| Original development scenes | 400 | 400 |
| Additional scenes on Seagate | 894 | 1,085 |
| Combined public scenes | 1,294 | 1,485 |
| Compact validation | 144 | 150 |
| Validation pool | 518 | 589 |
| Holdout | 313 | 313 |

**191 public scenes still lack basic assets across the old and new roots.**
Checks cover config, scene dictionary, road-height map and background checkpoint;
they do not certify rendering, all foreground assets or a combined runtime root.

The expansion job has receipts for 9 of 11 shards. `part013.tar.gz.part` is
21,996,957,696 bytes of a 31,683,669,758-byte archive; `part015` has no receipt.
The last saved status update is 2026-09-19 00:59:54 IST, while the partial archive
was last modified at 01:00:04 IST. The recorded worker PID is absent and the
dedicated tmux server/session is absent. `coverage.json` does not exist. **The
download is incomplete and was not running at this check**, despite the stale
status file saying `downloading`. The cause of the stop was not established.
No restart or download modification was made.

The four raw-training media roots from the earlier readiness audit were indexed
again, with no traversal errors and zero camera image files found:

- `/media/skr/SeagateHub1/nuplan_cities`
- `/media/skr/SeagateHub1/nuplan_zips`
- `/media/skr/SeagateHub1/autoresearch/autoresearch-paper/paper/dataset/nuplan-extracted`
- `/media/skr/SeagateHub1/autoresearch/autoresearch-paper/paper/dataset/nuplan-v1.1`

Directory symlinks were not followed, archive contents were not re-audited, and
this is not an exhaustive claim about every other disk folder. These roots still
do not provide a verified raw-image training corpus. The separate saved-ASL
inventory located camera bytes for all eight pilot scenes, but those samples
remain unexported and unvalidated. The incomplete expansion does not itself
prevent use of those existing eight logs once their data-use condition is met.
