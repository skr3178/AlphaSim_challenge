# AlpaSim 2026 leaderboard snapshot

Fetched **2026-08-29T12:55:20** from `nvidia/AlpasimE2EClosedLoopChallenge2026` via `gradio_client`.

- **nuPlan**: 58 submissions, 18 distinct teams
- **PAI**: 100 submissions
- Primary metric: `policy_capability_score` (order `ranked`, algorithm `zoib`)
- All entries `status=SUCCEEDED`, backend `direct-p5`

## nuPlan — best submission per team

| # | Team | PCS | AvgDist@Fault | dist_to_gt | Tag | Submitted |
|---|---|---|---|---|---|---|
| 1 | NaLa (`na-la`) | **1731.2** | 3.358 | 0.980 | `sub1` | 2026-07-15 |
| 2 | 메타몽 (`metamon`) | **1731.2** | 3.088 | 2.649 | `vavam-route-cudagraph-v5-nuplan-20260715` | 2026-07-15 |
| 3 | SymPhi (`symphi`) | **1669.8** | 1.669 | 3.476 | `vavam-gain105-v1` | 2026-08-27 |
| 4 | Team foxhihi (`team-foxhihi`) | **1626.8** | 1.624 | 3.031 | `nu-driver-b1` | 2026-07-30 |
| 5 | Host (`host`) | **1600.0** | 1.681 | 3.071 | `policy1` | 2026-06-16 |
| 6 | Team Magma (`magma`) | **1589.2** | 1.521 | 3.057 | `v4EMA` | 2026-07-30 |
| 7 | Cothlory (`cothlory`) | **1449.4** | 3.895 | 0.563 | `v1` | 2026-07-02 |
| 8 | OpenDriveLab-Org (`opendrivelab-org`) | **1377.3** | 1.800 | 3.742 | `simscale-gtrs-dense-resnet-reward-v5` | 2026-08-08 |
| 9 | Team Andrew S (`team-andrew-fox`) | **1166.2** | 0.568 | 2.439 | `accelfix-batch01` | 2026-07-30 |
| 10 | VF-Team (`vf-team`) | **1105.5** | 9.558 | 1.070 | `v2.1` | 2026-08-19 |
| 11 | Fox (`fox`) | **1091.9** | 1.244 | 1.780 | `v1p6` | 2026-07-01 |
| 12 | Team RCY (`team-rcy`) | **1064.6** | 0.235 | 3.655 | `rcy-nu-1` | 2026-07-28 |
| 13 | Team AIMM alpha (`team-aimm-alpha`) | **1000.3** | 0.278 | 2.472 | `smoke-20260728-1` | 2026-07-28 |
| 14 | ZGCA-TEAM (`zgca-team`) | **999.8** | 0.278 | 2.472 | `starter-baseline-20260813` | 2026-08-13 |
| 15 | Team VT (`team-vt`) | **944.3** | 0.778 | 0.692 | `drivor-track2-20260730-smokepass-cam4-0b776bf` | 2026-07-30 |
| 16 | CAN (`team-can`) | **902.9** | 1.069 | 0.481 | `v2` | 2026-08-11 |
| 17 | Rick G NTU (`rick-g-ntu`) | **897.1** | 1.164 | 2.921 | `ensemble-e11-v3` | 2026-08-12 |
| 18 | mxr (`team-mxr`) | **872.3** | 1.010 | 0.230 | `v1` | 2026-07-08 |

## The starter-kit floor

3 submissions share an identical fingerprint (`avg_dist=0.278353`, `dist_to_gt=2.472474`) — the unmodified straight-line starter driver:

| Team | PCS | Tag |
|---|---|---|
| Team AIMM alpha | 1000.297 | `smoke-20260728-1` |
| Host | 1000.000 | `go_straight` |
| ZGCA-TEAM | 999.768 | `starter-baseline-20260813` |

**Reference points:** starter kit ≈ **1000 PCS**. Top of board = **1731.2**. So the achievable gain over the baseline is ~**731 points**.
