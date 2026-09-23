# Bounded broader sweep — 2026-09-22

Authorized local tests only. Frozen neural weights, unchanged simulator/scorer,
no image build, no upload, no official or warm-up submission.

`run_sweep.py` uses the exact 24 IDs from the first screen. It runs a new baseline
and 25 one-variable variants (624 development rollouts total):

| Knob | Default | Candidate values |
|---|---:|---|
| Longitudinal position weight | 2 | 0.5, 4, 8 |
| Lateral position weight | 1 | 0.25, 3, 8 |
| Heading weight | 1 | 0.25, 3, 8 |
| Acceleration weight | 0.1 | 0, 0.5, 2 |
| Steering-change weight | 5 | 0.5, 2, 9 |
| Acceleration-change weight | 1 | 0.1, 3, 8 |
| Tracking penalty start index | 10 | 0, 5, 15 |
| Predicted yaw | False | True |
| Stabilization previous-plan weight | 0 | 0.05, 0.15, 0.25 |

All controller weights are inside the documented 0–10 range; horizon indices
are inside 0–19. Gain values are verified against both resolved configuration
files before each rollout job. Stabilization guards are held fixed.

## Predeclared progression

- Coarse eligibility: mean paired score improvement >= 0.005, with no new
  per-scene at-fault collision or corridor-exit flag relative to baseline.
  This is a development heuristic, not a statistical significance claim.
- Select the strongest eligible setting per knob; test up to six two-knob
  combinations from the best four distinct knobs.
- Repeat baseline and up to two highest-scoring eligible candidates. A candidate
  must again pass the paired gate to proceed.
- If repeat-confirmed, evaluate baseline and finalists on the already frozen
  150-scene unseen-log validation list, only if all assets exist in the active
  runtime asset root. Do not modify membership to fit available data. At launch
  all 150 assets were missing from that root; this does not mean they are absent
  from Seagate. Report this separately; do not claim holdout validation happened.
- No final promotion is automatic. Existing 313-scene final holdout stays unused.

This 24-scene sample contains eight historical corridor failures, eight partial
scores and eight successes, with no dedicated collision stratum. Zero observed
collisions cannot establish broad safety. Many trial configurations increase
selection bias; independent validation is essential. Official scorer parity is
not established.

The detached runner serializes GPU work under the global evaluation lock, records
source hashes, image identity, manifests, paired metrics, logs and configs,
checks free space before each arm, and stops on infrastructure/planning failures.
No recursive cleanup of saved artifacts is performed. Estimated coarse duration
is around two hours based on the prior ~4.3 minutes per 24-scene run; combinations
and repeats take additional time.
