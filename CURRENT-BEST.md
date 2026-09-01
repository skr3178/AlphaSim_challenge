# CURRENT BEST — single source of truth for "what are we submitting / comparing against"

Update this file whenever the candidate, the baseline, or the eval standard changes. Everything else
(SETUP-NOTES, LOCAL-PLAN, strategy) is history or method; this is the *state*.

_Last updated: 2026-08-31 16:00 IST_

## 1. On the leaderboard (what the world sees)

| | |
|---|---|
| Image | `…/teams/team-lucifer:vavam-stock-20260829` — the VAVAM sample **as shipped** (no μP shapes, gain 1.00, no seed) |
| Submission id | `6ba9c546-377a-437d-bafd-64de8892392e`, nuPlan track, Aug 29 |
| Official | **PCS 1592.2, rank #8 / 20**, at-fault dist 1.62 km, dist_to_gt 3.05 m, throughput 2265 / 2485 s |
| Local (same 400 scenes as below, original preset) | 0.49 km at-fault dist, 7.0 % at-fault, progress 1.07 |

**Throughput record for §1 (fetched 16:50):** `observed_wall_time_s 2265` vs `limit_wall_time_s 2485` → margin 220 s (**9 %**), passed. Every
future candidate must not add more than ~9 % to official wall time — see `ROUTE-SELECTION-PLAN.md` §4b.

## 2. Candidate #2 (what we intend to submit next)

| | |
|---|---|
| Config | **VaVAM-B + μP base shapes, gain ×1.00** (seed off, warm-up 3 — neither affects driving) |
| Local image (cu128, for our GPU) | `alpasim-e2e-vavam-driver:local-mup` |
| Submission image (cu124, as-shipped base) | `alpasim-e2e-vavam-driver:submit-mup` (id `bbe3a0af`, built 15:53) — **pushed 16:45 as** `696254625193.dkr.ecr.us-east-1.amazonaws.com/teams/team-lucifer:vavam-b-mup-20260831b`, digest `sha256:d24a7a78…` (manifest verified). Supersedes `vavam-b-mup-20260831` (pre-patch build) |
| Evidence so far | frozen 300 (3 cities): 1.11 km vs 0.51 stock, at-fault 3 % vs 6 % · screen 100 (4 cities, seeded): 0.75 km, 4 raw at-fault |
| **Confirm gate — PASSED 16:24** | `confirm400-mup-g100` (400 scenes, 4 cities, seed 1234, `dev_fast2`, 31 min) paired vs stock B on the **same 400** (`local300-vavam` + `sg100-vavam-submitted`): at-fault **13 vs 20** (−7; noise ±4/400; 13 removed, 6 new), rear 1 vs 5, corridor exits 33 vs 40, wrong-lane 28 % vs 34 %, dist_to_gt **2.35 vs 3.50 m**, lateral 1.37 vs 1.83, progress_clipped **1.020 vs 1.053 (−3.1 %)**, at-fault km 0.90 vs 0.63. Drive 103 ms mean, driver VRAM 2.7 GiB |
| Decision | Gate met; user gave go 16:40. Pushed. **Submit attempted 16:48 → HTTP 403 `Competition status is CLOSED; expected one of OPEN`** (also on `ecr-login`; `limits` shows status CLOSED, 4/5 August slots remaining). The Aug 31–Sep 6 downtime closes the API, not just the queue. **Action when it reopens:** `uv run --no-sync python e2e_challenge/competitor_cli/alpasim_challenge.py submit --track nuplan <URI above>` (or the ChallengeClient POST if `docker manifest inspect` still fails) — fresh token needed (12 h expiry) |
| Known risk | official scorer rewards speed; μP drives closer to human speed (SymPhi's μP+g1.20 scored < stock). Answered only by submitting |

## 3. Rejected this round (don't revisit without new evidence)

| Variant | Why |
|---|---|
| μP × 1.05 / × 1.10 | paired seeded screen: +3 collisions each, +0.4 / +1.1 m drift, ≤ +0.03 progress — monotonic loss |
| VaVAM-L + μP | worse driving than B on the same 300 (8 % at-fault vs 3 %), 107 ms/call |
| Stock B + gain (SymPhi's recipe) | gain on the μP-*broken* model is a different regime; we fix the model instead |

## 4. Eval standard (how every number above was produced)

| | |
|---|---|
| Preset | `+e2e_challenge_nuplan=dev_fast2` (CAM_F0 only, no eval video, 2 rollouts / stack) — 4.2 s/scene, validated 286–291/300 identical vs slow |
| Screen | `navtest_local100` (25 / city), seed 1234 → ~10 min incl. warm-up |
| Confirm | `navtest_local400` (100 / city), seed 1234 → ~30 min |
| Baseline for comparisons | stock B on the same group (300: `local300-vavam`; 400 combined: `local300-vavam` + `sg100-vavam-submitted`) |
| Noise floor | ±3 at-fault incidents / 300 scenes (±2 / 100). Read progress and dist_to_gt (continuous) with at-fault (count) |
| Launcher | `~/alpasim-challenge/logs/run-eval.sh IMG NAME GROUP dev_fast2` with `DRIVER_ENV="VAVAM_OUTPUT_GAIN=1.00 VAVAM_SEED=1234"` |

## 5. Quota / clock

**Check 2026-09-01 10:15 IST (fresh token, valid until 22:12 IST / 16:42 UTC):** status still **CLOSED**; September quota reset to **5/5**
(the notice's "three during soft-open" has not been applied yet); team history = 1 submission (stock B, SUCCEEDED). Candidate #2 is
staged in ECR, nothing queued. Re-check `limits` each session; submit the moment it says OPEN.

August: 1 of 5 used, 4 remaining, nominally expire **00:00 UTC (05:30 IST Sept 1)** — but the API is **CLOSED** as of 16:48 IST Aug 31 (403 on submit and ecr-login), so the remaining August slots are unusable unless it reopens before midnight UTC. CLI token valid until 22:41 IST (`session_expires_at 17:11 UTC`). Downtime Aug 31 – Sep 6: re-check `limits` daily; submit candidate #2 the moment status is OPEN.

Official notice (HF Space, fetched 16:52): downtime is "tentatively 2026-08-31 to 2026-09-06 … while we move to the **final scene sets** and
incorporate recent bug fixes"; "organizers will **rerun the top existing submission from each team** to seed the refreshed leaderboard"
(our stock-B `vavam-stock-20260829` gets re-scored on the new scene set — the 1590 number will change); submission limits "will change
from five to **three** submissions during the soft-open period" (so September may hold only 3 slots — spend them on confirmed winners only);
public leaderboard closes **2026-10-31**, final results **2026-11-15**. No quota carry-over is mentioned: August's 4 unused slots are gone.

## 6. Next after candidate #2 is decided

**Route-aware sample selection (B1+B4) + conditional slow-down (B2), never early termination (B7)** — full plan with staged gates in
`ROUTE-SELECTION-PLAN.md` (written 2026-08-31 16:40, not implemented). Each stage through the same ladder, compared to **candidate #2**
as the baseline. Three exploration findings that reshape it: the route the driver gets starts **40 m ahead** (`route_start_offset_m: 40`),
k flow samples come from **one batched call** (GPT trunk KV-cached), and the driver receives **no obstacle data** (brake must key on
sample disagreement / curvature / failure, not on actors).
