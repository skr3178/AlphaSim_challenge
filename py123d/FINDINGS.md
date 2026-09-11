# py123d_garage as a known-good reference — and what it proved about our local evaluation

**Date:** 2026-09-11 · **Run:** `runs/py123d-0014-400` · **Status:** complete, 400/400, 0 inference failures

---

## Why we ran it

Our local evaluation had stopped predicting the official leaderboard. WA-JEPA scored **0.9247** on our
400-scene local set — the best of any arm we had built — and then scored **PCS 986, rank 6 of 11** officially,
*below a go-straight baseline*. We could not tell whether the local set was merely unrepresentative or
actively misleading, because we had never measured a model whose official score we already knew.

py123d_garage gave us exactly that: **`model_0014.pth` is public, Apache-2.0, and is the checkpoint behind
their board ranks 2–3 (official PCS ~1470).** Running it through our own harness turns an open question into a
controlled test, for the cost of one GPU hour and no submission slot.

---

## The result

All seven arms on the **identical 400 scenes** (`navtest_local400`), same scorer, same simulator contract:

| model | mean score | zeros | ones | at-fault | corridor | atf km | **d2gt** | lat d2gt | progress | dist/scene | OFFICIAL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| starter (go-straight) | 0.6192 | 104 | 218 | 22 | 82 | 0.47 | 2.33 | 1.72 | 0.764 | 25.8 | — |
| stock VaVAM | 0.8493 | 60 | 335 | 22 | 38 | 0.58 | 3.57 | 1.83 | 0.964 | 31.8 | 1592 *(old board)* |
| cand#2 (stock + μP) | 0.8813 | 46 | 329 | 13 | 33 | 0.90 | 2.35 | 1.37 | 0.947 | 29.2 | — |
| route follower | 0.8896 | 41 | 323 | 18 | 23 | 0.62 | 2.07 | 1.20 | 0.925 | 28.0 | — |
| **WA-JEPA s2** | **0.9247** | 26 | 351 | 2 | 24 | 5.40 | 1.36 | 0.96 | 0.910 | 27.0 | **986 (rank 6)** |
| WA-JEPA s4 | 0.9302 | 24 | 348 | 1 | 23 | 10.68 | 1.24 | 0.90 | 0.905 | 26.7 | — |
| **py123d-0014** | **0.8420** | 33 | 292 | 9 | 24 | 1.14 | **1.17** | 0.98 | 0.835 | 25.6 | **~1470 (rank 2)** |

`d2gt` = `dist_to_gt_trajectory` (mean over scenes, lower is better). `atf km` = avg distance between at-fault
incidents. Local numbers are **not** comparable to official ones in level — only in ordering.

### The headline

**Our local mean scene score ranks the known-better model BELOW the known-worse one: −0.0827, paired, at 4.81 σ.**

That is not noise. It is confident and backwards.

---

## Which local metrics survive the test

The test a metric must pass: py123d (official ~1470) must rank above WA-JEPA (official 986).

| metric | py123d | WA-JEPA | verdict |
|---|---:|---:|---|
| mean scene score | 0.8420 | 0.9247 | ❌ INVERTED |
| **`dist_to_gt_trajectory`** | **1.167** | **1.356** | ✅ **CORRECT** |
| `lateral_dist_to_gt_trajectory` | 0.977 | 0.961 | ❌ INVERTED |
| clipped progress | 0.835 | 0.910 | ❌ INVERTED |
| `dist_traveled_m` | 25.60 | 27.00 | ❌ INVERTED |
| hard-failure rate | 0.0825 | 0.0650 | ❌ INVERTED |
| fraction scoring exactly 1.0 | 0.730 | 0.878 | ❌ INVERTED |

**One metric of seven transfers.** Note that the *lateral* component inverts — it must be the full
trajectory distance. We had been quoting the lateral figure throughout the project.

### Corroboration from the official board

The current nuPlan board is ordered almost perfectly by tracking tightness:

| official d2gt | PCS | rank | entry |
|---:|---:|---:|---|
| 0.77 | 1600 | 1 | py123d-garage `007-nuplan-0062-v1` |
| 0.81 | 1470 | 2 | py123d-garage `014-nuplan-0014-v1` ← **this checkpoint** |
| 1.18 | 1456 | 3 | py123d-garage `017-nuplan-0014-v1` |
| 1.18 | 1369 | 4–5 | Host `go_straight_with_delay_v2` |
| **1.85** | **986** | **6** | **Lucifer AI `wajepa-s2-20260904`** |
| 2.30 | 971 | 7 | Host `policy5` |

Local d2gt reproduces the direction: py123d **1.17** < WA-JEPA **1.36**.

---

## Why it happens

The scorer is **byte-identical** between our local runs and the official evaluation (`scene_score.py` verified
unchanged across `f012862` → `cd713e0`). So the divergence is not the scoring — it is the **scenes**.

**Our 400 scenes reward caution. The official private set rewards imitation.**

py123d wins officially while losing locally because it takes *more* risk (9 at-fault vs WA-JEPA's 2; 33
zero-score scenes vs 26) but tracks the recorded human line *tighter* (1.17 vs 1.36). On a collision-rich
sample the risk costs more than the tracking earns. On the official set — where a go-straight policy scores
**0.8194**, so there is little to collide with — the tracking is nearly all of it.

### The generalisable principle

**Crash-based scores are strongly scene-dependent**: whether you collide depends on what hazards happen to be
present. **Tracking error is weakly scene-dependent**: how far you drift from the recorded line is mostly a
property of the policy.

So on an unrepresentative sample, tracking-type metrics survive and crash-type metrics do not.
*When the test set is not representative, prefer metrics weakly coupled to scene content.*

---

## How much to trust this

**Moderately. Not highly.**

- The transfer claim rests on **n = 2** — two models with official scores on the current board. Two points
  ordering correctly happens by chance half the time.
- It is strengthened by the board's internal ordering across **11 entries**, but that is official-d2gt against
  official-PCS on the same data — not proof that *local* d2gt predicts *official* PCS.
- It gives **ordering, not calibration**. Local d2gt 1.17 became official 0.81; local 1.36 became official
  1.85. The direction holds; the mapping does not.

Treat `dist_to_gt_trajectory` as a strong working hypothesis that is far better supported than mean scene
score — which is actively refuted — and re-test it whenever a new official data point arrives.

---

## What changes

1. **Select on `dist_to_gt_trajectory`** (full distance, not lateral). This supersedes the open metric question
   in SETUP-NOTES §6.49–§6.51.
2. **Candidate #2 is withdrawn as the next submission.** At d2gt **2.35** it is barely better than the
   go-straight starter (2.33) on the only metric that transfers, and clearly worse than WA-JEPA (1.36).
   Submitting it would most likely have spent a slot to confirm a regression.
3. **The route follower deserves reconsideration.** At **2.07** it beats candidate #2 and stock. It was parked
   on an IRT fit built from the inverted signal (§6.38).
4. **WA-JEPA s4 (d2gt 1.24) is tighter than s2 (1.36)** and, per §6.44, its latency passes comfortably — the
   throughput analysis that ruled it out used stale limits.
5. **py123d's checkpoint is the strongest asset we hold**: best measured d2gt, 62M parameters, 4.4 s/scene
   (≈1.7× faster than WA-JEPA), Apache-2.0, with a known official score to anchor against. Their docs include a
   finetuning recipe.

---

## Reproducing this run

```bash
# 1. Build their driver image with the nuPlan sensor rig (NOT the PAI rig)
cd py123d/py123d_garage
CK=/home/skr/Downloads/alpasim_challenge/py123d/checkpoints/resnet34_v0.1.0/model_0014.pth
CHECKPOINT_FILE=$CK SENSOR_RIG_FILE=$(dirname $CK)/sensor_rig_0.yaml TAG=nuplan-0014 \
  bash scripts/alpasim_submission/build_docker_image.sh

# 2. Run it through our harness on the 400-scene set
cd /home/skr/alpasim-challenge/alpasim
setsid nohup ~/alpasim-challenge/logs/run-eval.sh \
  py123d-garage-alpasim:nuplan-0014 py123d-0014-400 navtest_local400 dev_fast2_3cam \
  > ~/alpasim-challenge/logs/py123d-0014-400.log 2>&1 < /dev/null &
```

**Setup notes**
- `lib/alpasim/alpasim` is a symlink to a git worktree at their pinned commit `cd713e0`, needed only so their
  build script can build the `alpasim-grpc` wheel. Created with
  `git worktree add /media/skr/storage/alpasim-cd713e0 cd713e0` — shares the object store, ~280 MB.
- `dev_fast2_3cam` is a local preset we added (CAM_L0/F0/R0 at 1920×1080, 500 ms), mirroring their own
  `nuplan_3cam.yaml`.
- Their image is built `FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04` — **CUDA 12.8, so it runs on this
  Blackwell (sm_120) GPU**, unlike the cu124 sample-submission images which cannot be smoke-tested here.
- Their entrypoint honours `ALPASIM_DRIVER_HOST` / `ALPASIM_DRIVER_PORT`, so `run-eval.sh` works unmodified.
- Verified before running: checkpoint SHA inside the image matches our local copy (`d536614c8157381a`), and
  the baked rig is `sensor_rig_0.yaml` (nuPlan, `log_name: 2021.05.12.19.36.12_veh-35_00005_00204`).

**Timing:** 1963 s wall for 400 scenes, 4.4 s/scene mean — about 1.7× faster than WA-JEPA.

---

## Provenance and licensing

- `py123d_garage` @ `288d34c` (v0.1.1), `py123d` @ `2a75cb6` (v0.7.0), checkpoints from
  `kesai-labs/py123d_garage_pretrained_checkpoints` — **all Apache-2.0**.
- The project describes itself as *"the reference starting point for the Alpasim E2E Challenge 2026, with
  pretrained baselines to build on"*, so using it is its intended purpose.
- `kesai-labs` also authors `drive-irt`, the algorithm computing the leaderboard PCS, and co-authors the
  AlpaSim simulator paper with the NVIDIA staff running the challenge (see SETUP-NOTES §6.53–§6.54). They
  compete as team `py123d-garage`. Recorded as context, not as an allegation — they released the rank-2/3
  checkpoint publicly, which is the opposite of withholding an advantage.

## Related

**[MODEL.md](MODEL.md)** — full technical reference on the checkpoint itself: architecture, the 45 m
route-conditioning recipe, training data and losses, and whether we could train it ourselves.

## Related

SETUP-NOTES §6.53 (the repos and what they are) · §6.54 (their submission volume vs our quota) ·
§6.55 (this finding) · §6.49–§6.51 (the official result that prompted it)
