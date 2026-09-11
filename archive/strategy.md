# Strategy — fast local iteration for the AlpaSim nuPlan track

Written 2026-08-31. Companion to `EVAL-RUNBOOK.md` (how to run), `RANKING.md` (why the score behaves this way),
`CURRENT-BEST.md` (live state) and `SETUP-NOTES.md` (what happened).
This file is the *operating strategy*: how we decide, how we measure, and how we spend submissions.

## 1. The constraint that shapes everything

- Official evaluation is the only source of the score (PCS), and it is rationed: **5 submissions/month
  (dropping to 3)**, ~45 min per evaluation, results visible only after the run.
- Therefore ideas must be **ranked locally** and submissions used only to **bank** a proven gain and to
  **calibrate** local → official.
- Local eval can rank; it cannot forecast. Same scenes, same simulator, same scorer code — but a
  different scene *sample* and no IRT fit against the field. Read local numbers as *ratios on
  identical scenes*, never as absolute PCS predictions.

## 2. Three-tier evaluation ladder

| Tier | Scene group | Scenes | Time (dev_fast) | Purpose | What it can decide |
|---|---|---|---|---|---|
| **T0 smoke** | one scene / `navtest_local20` | 1–20 | 1–3 min | "does it run, does it crash, is `img_is_black` 0" | nothing about quality |
| **T1 screen** | `navtest_local100` (25/city × 4) | 100 | **~7 min** (`dev_fast2`) | first look at an idea | kills bad ideas; flags promising ones. ±3 incidents noise → only trust ≥ 2× effects |
| **T2 confirm** | `navtest_local400` (100/city × 4) | 400 | **~28 min** (`dev_fast2`) | decision before a submission | ranks candidates within ~20–30 %; still noise below that |
| **T3 official** | 1,485 scenes, their H100 node | — | 45 min + queue | the score | everything — and it recalibrates the local yardstick |

Rules of the ladder:
1. **Never skip a tier upward.** T1 before T2, T2 before a submission.
2. **Identical scenes for any comparison.** A number is only comparable to another number on the *same*
   group with the *same* preset. The frozen `navtest_local` (300) series is history; new work is 400.
3. **Same seed for A/B pairs** once the seed knob exists; if a delta is < 2× the noise band, rerun with
   a second seed before believing it.
4. **Read three columns together**, never one: at-fault rate (zeros), progress vs human (speed),
   dist_to_gt (path). The official score rewards progress heavily and punishes at-fault zeros; a
   variant that improves safety by driving slower can *lose* officially (SymPhi's μP+g1.20: 1560 < stock 1588).

## 3. The fast preset — what it is and what it is not

> Exact YAML, timing/fidelity tables, launcher and scene-group inventory: **`EVAL-RUNBOOK.md`**.

`+e2e_challenge_nuplan=dev_fast` = `dev` + only `CAM_F0` requested + eval video off.
- Measured: **10.9 → 6.9 s/scene (1.58×)**, metrics code untouched, run dirs 7× smaller.
- Pixels the policy sees are identical (same CAM_F0 render). Eval scorers unchanged (`img_is_black`
  and video scorer both use CAM_F0).
- **Not a speedup of the GPU work**: MTGS builds its camera rig from the scene file and rasterises all
  8 views regardless (`plugins/mtgs/server/artifact_adapter.py:183-215`); we skip the encode/transport/
  eval of the other seven.
- Fidelity gate **passed 2026-08-31**: stock B on the frozen 300, slow vs fast — 26 vs 27 at-fault incidents,
  291/300 identical per-scene outcomes, progress identical. `dev_fast2` (2 rollouts in one stack) also passed (286/300 identical vs slow, 4.2 s/scene) and is the standard for screen *and* confirm.
- **Noise floor:** ±3 at-fault incidents / 300 scenes between identical configs. Effects < ~5 incidents/300 are not resolvable without seeds or repeats.
- Next lever, only if needed: `dev_fast2` (2 rollouts in one stack; no VRAM doubling) → ~1.6–1.8× more;
  or a local renderer patch to rasterise only requested cameras (larger, needs its own pixel check).
- **Never two simulator stacks on this GPU** — the renderer OOMs (measured). One stack, more rollouts.

## 4. What each run must report (the launcher prints these)

- `TIMING`: per-scene wall from the runtime's own timestamps, scene 1 excluded (gsplat JIT warm-up).
- `DRIVER`: Σ `Drive` time as **% of total wall** — the local proxy for the official throughput budget
  (a total-wall-time limit; stock B used 91 % of it, margin 9.7 %). Also peak VRAM (cap 16 GiB/replica).
- Aggregate: at-fault distance, at-fault %, wrong-lane %, dist_to_gt, progress, `img_is_black`.
- Per-city breakdown from the per-scene parquets when diagnosing (Boston = route-following stress,
  Vegas = dense straight boulevard, Pittsburgh = mixed, Singapore = sparse/easy, left-hand traffic).

## 5. Throughput is a gate, not a metric  (revised after the load test, §6.14 of SETUP-NOTES)

- The budget is **total wall time**; the driver's local share of wall is 2 % (slow preset) to ~20 % (`dev_fast2`) for the
  same B driver — the share depends on how fast the rest of the sim runs, so compare *ratios between drivers under the same
  preset*, and use demand-vs-capacity for the official question. Official demand is
  ~0.4 `Drive` calls/s per replica; the sample driver sustains ~10 calls/s (serialised, no batching).
  **B-class drivers have ~20× headroom** — throughput only becomes a gate for models an order of
  magnitude heavier or for multi-sample (medoid) inference without batching.

- Official: 16 replicas × 2 rollouts, 4 replicas per H100, 32 concurrent — the driver shares a GPU with
  3 copies of itself. Exceeding the wall-time limit = `FAILED`, slot burned, nothing on the board.
- Local check for any new driver: `capture/driver_loadtest.py --streams 8` against the driver alone
  (official contention shape). Compare **ratios** to stock B (which passed): a variant > ~1.2× slower
  per call needs mitigation (warm-up, fewer flow steps, CUDA graphs) before it is a candidate.
- Warm-up costs wall time only, never score (sim time is synchronous) — but at official scale it is
  16 replicas × slow first calls against a thin margin, so the driver should warm itself up at start.

## 6. Submission policy

- Submit to **bank** a T2-confirmed gain or to **calibrate** (one anchor per month is worth it), never
  to test an idea.
- Every submission is a calibration point: keep the (local T2, official) pair per image in SETUP-NOTES.
- Only images with a known throughput ratio ≤ ~1.1× of a passing image go out.
- Always: specific tag, push (free) → `submit --track nuplan`. The CLI's `docker manifest inspect`
  pre-check is broken on Docker 28.1.x; POST via its `ChallengeClient` after `buildx imagetools inspect`.
- Month boundary is UTC (evidence: all API timestamps `+00:00`); unused quota does not carry over.
- **The board only knows submitted images.** The final entry (2026-10-31) is chosen from what has been
  submitted, and the organizers **re-run it on the final scene set** — so a submission is a durable
  artefact, not a probe. Minimum to compete = 1 (done). Realistically 2-4 more over the competition.

## 7. Current position and next moves

> Live state (candidate, baseline, rejected variants, eval standard) is kept in **`CURRENT-BEST.md`** — update that file, not this section.

### Snapshot at 2026-08-31 (historical)

| Item | State |
|---|---|
| Baseline on the board | stock B, PCS 1592, #8 of 20 |
| Validated lever | **μP base shapes**: 0.51 → 1.11 km at-fault on 300 scenes, collisions halved, progress 1.05 → 1.01 |
| Known trap | speed is rewarded and SymPhi's μP+g1.20 scored below stock — so the μP candidate's official result is uncertain. **Gain is NOT the fix:** tested 2026-08-31 on the paired seeded 100-scene screen, μP × 1.05 / × 1.10 each *added* 3 collisions (removed none), drifted +0.4 / +1.1 m further off the path, gained ≤ +0.03 progress (median 0). SymPhi's 1588 → 1690 gain wins were on the μP-*broken* model (velocity field 4× too large) — a different regime. **Gain stays 1.00**; the risk is answered by submitting μP × 1.00 and reading the board (SETUP-NOTES §6.16, CURRENT-BEST §3) |
| Ruled out | VaVAM-L (worse driving, 100 % of calls > 0.1 s) · μP × 1.05 / × 1.10 (measured loss on every column) · stock + gain (fixing the model beats compensating for it) |
| Yardstick | 400 scenes, 4 cities, **`dev_fast2`** (4.2 s/scene) — fidelity gates passed: `dev_fast` 291/300, `dev_fast2` 286/300 identical outcomes vs slow |
| Confirm gate (16:24) | `confirm400-mup-g100` vs stock B, same 400 scenes: at-fault **13 vs 20**, rear 1 vs 5, dist_to_gt 2.35 vs 3.50 m, progress 1.020 vs 1.053 — **gate met**; ship on explicit go (SETUP-NOTES §6.17, CURRENT-BEST §2) |
| Next | route-aware sample selection (B1+B4) + conditional slow-down (B2), never early termination (B7) — staged plan in **`ROUTE-SELECTION-PLAN.md`** (S0 identity/spread check → Boston → 100 → 400), each against candidate #2 as baseline. Design corrections from code: route starts 40 m ahead; k samples are one batched call; no obstacle data reaches the driver |

---

## 8. The backlog as one ranked table

_Updated 2026-09-01 after candidate #2 and the route-selection exploration._
Live state is **`CURRENT-BEST.md`**; the B-series design is **`ROUTE-SELECTION-PLAN.md`**.

Evidence: **[M]** official board · **[L]** measured locally · **[D]** DriveIRT docs ·
**[I]** competitor tag · **[S]** repo/proto source.

| Group | ID | Status | Lever | Evidence | Gain | Risk | Cost |
|---|---|---|---|---|---|---|---|
| **A · submission line** | A1 | ✅ **DONE** | Driver patch: `VAVAM_OUTPUT_GAIN`, warm-up, fixed seed | [L] unseeded A/Bs unreadable at ±3/300 | made every later A/B readable | none | shipped |
| **A · submission line** | A2 | ⛔ **REJECTED** | ~~Gain A/B~~ — see N1 | superseded | — | — | — |
| **A · submission line** | A3 | ✅ **PUSHED** | Candidate #2 (μP, gain 1.00) built cu124, in ECR | [L] confirm400 gate **PASSED**: at-fault 13 vs 20, dist_to_gt 2.35 vs 3.50 m | banks μP | low | done |
| **A · submission line** | A4 | 🚧 **BLOCKED** | Submit candidate #2 | API returns `403 Competition status is CLOSED`; downtime Aug 31 – Sep 6 | — | — | re-check `limits` daily |
| **B · active work** | B1+B4 | ⬅ **NEXT — S0** | **Route-aware sample selection** — k candidates, pick the one agreeing with the map | [L] 28 % wrong-lane after μP · [M] rank-1 tag `vavam-route` | the main lever | med | ~½ day code, ~2 h GPU |
| **B · active work** | B2 | ⬅ **S2** | **Conditional slow-down** — keyed on **sample disagreement / curvature / inference failure** | [S] ⚠ driver receives **no obstacle data**; a "closing obstacle" brake is impossible | med | med — rear-end exposure, measured at S2 | in the same patch |
| **B · active work** | B8 | ⬅ **S2** | **Decelerating failure fallback** — replaces the 2 m/s straight line | [S] on inference failure the driver serves a stale plan then a 2 m/s straight line — **it cannot stop** | removes a floor-scoring path | low | `trajectory.py` §3c |
| **B · later** | B3 | ☐ | Temporal context 1 → 2–8 frames | [I] backbone trained on 8; sample uses 1 | potentially large | high — needs `@738050e` pin | days |
| **B · dropped** | B5 | ⛔ | ~~8 cameras instead of 1~~ | needs a fusion module + **retraining** — VaVAM's encoder takes one frame and the GPT trunk expects that token distribution. Out of scope: one 24 GB GPU, ~2 months, 3-5 submissions | — | — | — |
| **B · dropped** | B6 | ⛔ | ~~Sim-domain fine-tune on rendered frames~~ | only **navtest** assets are distributed → training on the eval set; and the dataset is being **replaced** | — | — | — |
| **B · dropped** | B7 | ⛔ **INVARIANT** | ~~`terminate_session` early exit~~ | [S] code zeroes on 3 conditions, incompletion not among them · ⚠ [D] DriveIRT §10 says it *is* — **unresolved**. B8 gets the same safety with no failure mode | — | not worth it | — |
| **C · tooling** | C1 | ✅ | `dev_fast2`, 20/100/400 groups, seeded launcher | 4.2 s/scene, 286–291/300 identical vs slow | — | — | — |
| **C · tooling** | C2 | ✅ | Driver load test, 8 streams | ~20× headroom | re-run per driver | — | — |
| **C · tooling** | C6 | ✅ | Official throughput readout | **2265 / 2485 s → 9 % margin**, passed | every candidate must stay inside it | — | — |
| **C · tooling** | C4 | 🚧 | Per-scene official metrics | private S3 bucket | needs organizers | — | — |
| **D · housekeeping** | D1 | ⚠️ **RISK** | Commit local changes to a branch | casadi pin, `Dockerfile.local*`, `dev_fast*`, scene groups, μP patch — **uncommitted** | protects days of work | — | minutes |
| **D · housekeeping** | D3 | ☐ | Rotate HF token | pasted into a chat transcript | — | — | minutes |
| **D · housekeeping** | D2 | ☐ | Delete ~28 GB `rollout.asl` | aggregates + parquets survive | disk | none | minutes |
| **D · housekeeping** | D4 | ☐ | File 4 upstream issues | editable install · casadi · CLI manifest · dropped μP shapes | goodwill | — | ~1 h |
| **D · housekeeping** | D5 | ☐ opt | Remaining 11 shards → Seagate | only if 400-scene A/Bs come out within noise | tighter CIs | none | ~12 h |
| **⛔ NEGATIVE** | N1 | ⛔ | ~~Output gain (any value > 1.00)~~ | [L] paired seeded screen: μP ×1.05 / ×1.10 each **+3 collisions**, +0.4 / +1.1 m drift, ≤ +0.03 progress. SymPhi's 1588→1690 was on the **μP-broken** model — a different regime | — | — | — |
| **⛔ NEGATIVE** | N2 | ⛔ | ~~VaVAM-L~~ | [L] 8 % at-fault vs B's 3 % on the same 300; 107 ms/call | — | — | — |
| **⛔ NEGATIVE** | N3 | ⛔ | ~~Global braking~~ | [M] SymPhi `vavam-brake-v1` **−302** | — | — | — |
| **⛔ NEGATIVE** | N4 | ⛔ | ~~EMA smoothing~~ | [M] magma `v4EMA` below our untuned stock | — | — | — |
| **⛔ NEGATIVE** | N5 | ⛔ | ~~Max safety via passivity~~ | [M] foxhihi `c1`: `avgDist` 6.01 (2× the leaders) → **1356** | — | — | — |
| **⛔ NEGATIVE** | N6 | ⛔ | ~~Architecture sweep~~ | [M] opendrivelab-org, 17 submissions, peaked **1377** | — | — | — |
| **⛔ NEGATIVE** | N7 | ⛔ | ~~Chase `dist_to_gt`~~ | [M] rank 1 has `d2gt` 0.98, lower than ours | a passivity alarm, not a lever | — | — |
| **🚫 OFF LIMITS** | X1 | 🚫 | ~~Decoy submissions~~ | [D] named an *attack*, DriveIRT §1.3 | — | — | — |
| **🚫 OFF LIMITS** | X2 | 🚫 | ~~Fingerprint scenes~~ | [S] `scene_id` stripped at eval "to avoid data leakage" | disqualification path | — | — |
| **🚫 OFF LIMITS** | X3 | 🚫 | ~~CarPlanner / vector planners~~ | [S] no map, no agent tracks in the API | — | — | — |
| **🚫 OFF LIMITS** | X4 | 🚫 | ~~Base image / arch bump~~ | [M] `8.9;9.0+PTX` JITs fine on sm_120 | — | — | — |
| **🚫 OFF LIMITS** | X5 | 🚫 | ~~Unverified submission~~ | [D] adds a row, teaches nothing | — | — | — |

### The selection criterion that now orders group B

**Does it need training?** With one 24 GB GPU, ~2 months and 3-5 submissions, levers that touch
only inference are worth disproportionately more than their raw upside suggests — they are
testable offline, reversible, and cost no GPU-days.

| Lever | Training? | Status |
|---|---|---|
| B1+B4 selection, B2 slow-down, B8 fallback | ❌ none — frozen checkpoint, ~250 lines of numpy | **active** |
| B3 temporal context | ❌ none — the backbone was *trained* on 8-frame context; the sample feeds 1 | later |
| B5 eight cameras | ✅ fusion module + retraining | **dropped** |
| B6 sim-domain fine-tune | ✅ and it would train on the eval set | **dropped** |

This is also why the CarPlanner scorer transfers but its *generator* does not: their learned mode
selector needs training, so we substitute sample-consensus for it — VaVAM's sampler already is a
learned prior, and measuring the agreement of k draws extracts its confidence for free.

### Three ratings this revision corrects

1. **A2/N1 — gain was wrong, and instructively so.** Earlier revisions ranked it the strongest
   lever on [M] evidence (SymPhi 1588 → 1690). Measured locally it *loses* on every column. The
   reason matters: **SymPhi's baseline was the μP-broken model** (velocity field 4× too large),
   so their gain was compensating for a defect we fixed instead. **A competitor's measured delta
   only transfers if their baseline matches yours.**
2. **B2 was specified impossibly.** "Conditional brake on closing obstacle" cannot be built —
   the driver-facing protos carry no actor or obstacle data at all. The implementable triggers
   are sample disagreement, route curvature, and inference failure.
3. **B4 was priced far too high.** "k× throughput" is wrong: `forward_inference` draws
   `randn((bsz,1,6,2))` in **one batched call** with the GPT trunk KV-cached, and inference runs
   on 1 of every 5 `Drive` calls. VRAM for the k× visual KV cache is the real constraint, not time.

### Sequencing

**B1+B4 → S0 is next**, per `ROUTE-SELECTION-PLAN.md` §4. S0 is behaviour-identical by
construction (selection off, row 0 of a seeded `randn((k,…))` equals the seeded `randn((1,…))`),
so it measures cost and **candidate spread** without changing driving. If median end-point
spread is below 0.5 m the samples are too similar for selection to help — **stop and switch to a
route-derived command** rather than proceeding to S1.
