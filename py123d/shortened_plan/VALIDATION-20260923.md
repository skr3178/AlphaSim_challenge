# Controller-search validation — September 23, 2026

Frozen Py123d model; no neural-network training. Trial numbers below are
one-based (trial 26 is Optuna trial 25).

## Matched validation results

| Configuration | Scenes | Mean scene score | At-fault collisions | Corridor exits |
|---|---:|---:|---:|---:|
| Baseline | 141 | 0.852322 | 1 | 7 |
| Earlier combo_2 | 141 | 0.854933 | 1 | 7 |
| Optuna trial 26 | 141 | 0.856707 | 1 | 8 |
| Optuna trial 21 | 141 | 0.855303 | 1 | 8 |

Both Optuna candidates completed 1,410 planning calls without inference
failures. Both introduced a corridor exit on
`2021.06.03.18.47.39_veh-35_00503_00777-a454e18ca33d5cb7`.
Trial 26 improved 23 scene scores and worsened eight; trial 21 improved 25
and worsened four (comparison tolerance 1e-6).

This is a partial matched validation subset, excluding three baseline route
generation failures and six untested scenes from the planned 150. It is not
an official leaderboard estimate or the protected final holdout.

## Development search and conclusion

36 of the requested 50 trials completed on 64 development scenes; the next
trial failed with a CUDA renderer error around a PC interruption. Completed
results were retained. The search has not been resumed. GPU computation passed
after reboot; both candidate validation runs then completed.

Development baseline: 0.824308. Trial 26: 0.864259; trial 21: 0.857994.
The development gains transferred only weakly, with an additional validation
corridor failure. Neither is a clear safety-preserving upgrade.

Recommended next step: a bounded saved-trace audit of corridor failures and
low-progress cases, checking route inputs, predicted trajectories and executed
motion before further tuning or training. No additional experiments implied.

Raw artifacts remain local under
`artifacts/optuna-validation141-20260923T045114Z/` and
`artifacts/optuna-development64-v1/`. Plot scripts and lightweight chart
snapshots are versioned; checkpoints, datasets and raw rollouts are excluded.
