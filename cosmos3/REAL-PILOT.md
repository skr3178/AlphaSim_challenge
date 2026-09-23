# Approved real-driving pilot — 2026-09-19

Latest separate local follow-up: [ABLATION-RESULT.md](ABLATION-RESULT.md) records
corrected causal state and two matched 100-update heads, tested once on nine
unseen development source logs. Cosmos features did not improve position error.
The original competition-conditional scope below remains historical and unchanged.

Original-pilot status: **split approved conditionally; competition training-data
eligibility still unverified**. A subsequent separate
[local-only ten-scene test](LOCAL-HEAD10-RESULT.md) used these eight scenes plus
two from the same four logs, with Cosmos frozen and 100 head updates. All 207
same-log scenes are now training-exposed for that head or derived candidates.
The numerical learning test passed, but velocity-input consistency needs fixing.

The original approval below is retained as history. The user approved
eight real development400 scenes, two per city, with a frozen Cosmos backbone
and at most 100 optimizer steps for a new waypoint head. Synthetic training was
not selected. No full evaluation, submission or full-backbone fine-tuning is
authorized by this pilot.

## Separate pending check: training-data permission

Local development and testing require **no token or authentication**. The offline
pipeline is implemented and CPU-tested; see [TRAINING-PIPELINE.md](TRAINING-PIPELINE.md).
Before fitting this conditional public-data pilot, record a reviewed local copy
of the applicable terms or organizer statement. There is no requirement to use
the challenge API if that evidence is available locally.

The read-only challenge CLI `terms show` request returned
`HTTP 401: Missing or expired session` on 2026-09-19 IST. The public README
describes navtest as local evaluation data but does not settle whether these
scenes may be used for training. No current full terms copy was found in the
searched project/log files. Older notes about public training data do not resolve
this navtest-specific question.

If a current local copy is unavailable and the challenge API is chosen to obtain
one, re-authentication is an optional retrieval route, not a training dependency.
Do not paste credentials into the conversation or accept new terms automatically;
viewing terms and accepting them are different operations.

From the challenge workspace, the existing CLI supports:

```bash
python3 alpasim-upstream-20260916/e2e_challenge/competitor_cli/alpasim_challenge.py auth-url
python3 alpasim-upstream-20260916/e2e_challenge/competitor_cli/alpasim_challenge.py configure-token
python3 alpasim-upstream-20260916/e2e_challenge/competitor_cli/alpasim_challenge.py terms show
```

The first command prints the official browser authentication URL. Open it, then
enter the returned token at the second command's local hidden prompt. No token
needs to appear in shell command arguments or chat.

## Frozen pilot scope

Exact eight scene IDs, scene config hashes, asset roots and all candidate-specific
exclusions: [pilot manifest](pilots/real-driving-v1/manifest.json).

| City | Training source log | Selected clips | Public scenes excluded for a fitted candidate |
| --- | --- | ---: | ---: |
| Boston | `2021.09.09.14.18.22_veh-48` | 2 | 57 |
| Pittsburgh | `2021.09.16.15.47.30_veh-45` | 2 | 12 |
| Singapore | `2021.10.06.07.26.10_veh-52` | 2 | 106 |
| Vegas | `2021.05.25.15.59.03_veh-30` | 2 | 32 |
| Total | 4 source logs | 8 | 207 |

Selection used a deterministic hash ordering before approval, not model scores.
The exact scenes are pinned; an unavailable scene must not be silently replaced.
All eight have the basic local simulator assets and unchanged scene configs.
This does not certify a working training data export or rendering pipeline.

The 589-scene validation pool (including compact150) and 313-scene holdout have
no source-log overlap with these four logs. This is not date/geographic separation,
and those protected suites contain no Singapore scenes.

The original public manifest and historical audit are unchanged. This new manifest
is a **conditional pilot-specific exception** to the earlier evaluation-only plan,
not blanket permission to train on public navtest. Its exclusion list is recorded
but **not yet wired into the evaluator**. Before evaluating any fitted candidate,
enforce it: an old400/full1485 average would mix training-exposed scenes with
independent ones. Actual exposure has now occurred in the separately authorized
local-only ten-scene fit; the old manifest remains unchanged as an approval record.

## Implementation status and next checks

The exporter, causal feature-tap prototype, dataset/cache reader, small waypoint
head and maximum-100-step loop now exist, with 61 passing CPU tests across the
Cosmos suite. The pilot manifest remains unchanged: its implementation-status
fields record the historical approval-time state, not this subsequent work.

A read-only [saved-log inventory](pilots/real-driving-v1/pipeline-preflight-20260919.json)
found initial camera bytes, ego poses, runtime routes and camera calibration for
all eight approved scenes. The separate ten-scene export subsequently decoded
and pose-aligned one example per scene within the 0.5-second priming window;
past frames were masked, not filled from future observations. That fit does
not establish physically consistent velocity inputs or competition eligibility.

Original competition-conditional sequence (not executed under this manifest;
see the separate local result for completed work):

1. Export real, synchronized observations/ego state/navigation/future labels from
   only the approved scenes. Use expert-aligned rendered observations; do not
   silently pair an off-reference rollout image with an incompatible expert
   future. Future trajectories are targets, never input features.
2. Validate the implemented causal world-generator feature tap on the actual
   local checkpoint. Keep backbone
   parameters frozen; do not substitute vision-only features without labelling
   and agreeing on that changed experiment.
3. Run the implemented head loop on the real exported samples. Unit fixtures
   already check coordinate/timestamp transforms, finite losses/gradients and
   freezing. Actual-checkpoint checks and a local-only fit subsequently completed
   under the separate ten-scene authorization, not this original rules gate.
4. Run at most 100 head optimizer steps; save provenance, initial/final loss,
   timing, VRAM and a separate head checkpoint. Training loss alone is not
   evidence of generalization or improved driving.

The original competition rules gate remains unresolved. Separately authorized
local-only fitting requires no token and did not claim competition permission.
This work did not restart, stop or otherwise change the dataset downloader.
