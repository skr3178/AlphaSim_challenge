# Isolated Optuna environment

Python 3.12.8, Optuna 5.0.0. All 13 dependencies are pinned with hashes in
`requirements.lock`; top-level requirements are in `requirements.in`.
No PyTorch/CUDA dependency. Existing simulator and model environments unchanged.

From workspace root:

```bash
source py123d/shortened_plan/optuna/.venv/bin/activate
python py123d/shortened_plan/optuna/smoke_test.py
```

Recreate using `uv venv --python 3.12.8` at this `.venv` path, then
`uv pip sync --python py123d/shortened_plan/optuna/.venv/bin/python py123d/shortened_plan/optuna/requirements.lock`.

Smoke test uses a disposable SQLite database and ten synthetic CPU trials to
exercise Latin hypercube initialization, multivariate TPE, `set_constraint`,
and study reload. Reload preserves trial history; it does not demonstrate
bit-identical sampler continuation after restart. A real objective is now wired
but has not yet been exercised on the GPU. No optimization has been launched.

Future integration should invoke the existing evaluator as a subprocess using
its own Python environment, serialize GPU runs with the existing lock, and
preserve configs, scene membership and failed-trial evidence. Keep real study
databases/results under the ignored parent `artifacts/` directory.

References: https://github.com/optuna/optuna and https://optuna.org/#paper

## Development64 integration

`development64.json` freezes 64 existing development scenes: 16 per city,
13 source logs. Selection is deterministic and independent of model scores.
All basic assets are present. Entire validation-pool and holdout source logs
are excluded. This does not add new source logs or prove maneuver coverage.
Singapore has no independent source logs left in the public protected splits.

Run from workspace root with this environment's Python:

```bash
python py123d/shortened_plan/optuna/search.py --stage check
# Explicitly launches two GPU evaluations, sequentially:
python py123d/shortened_plan/optuna/search.py --stage references
# Only after reviewing reference outcomes and runtime:
python py123d/shortened_plan/optuna/search.py --stage search --total-trials 50
```

The default check does not launch simulation. References are baseline and the
fixed combo_2 candidate. Real evaluations use the existing runtime Python and
Docker image; Optuna itself uses this isolated CPU environment. The worker
takes the shared GPU lock, refuses other running containers, and retains the
strict coverage/inference checks. Failures stop the search for inspection.

The search uses 20 Latin-hypercube initial points followed by up to 30 adaptive
TPE trials, four continuous variables, fixed remaining gains and frozen weights.
Safety constraints require collision and corridor counts not to exceed baseline
on these scenes; they do not guarantee safety or prevent bad configurations
from being tried. Per-scene safety regressions must also be reviewed before
promoting any candidate. No existing 24-scene scores enter this objective.

SQLite, source snapshot, input fingerprint, requests, logs and results live in
`../artifacts/optuna-development64-v1`. Successful evaluations can be reused;
interrupted RUNNING trials require explicit inspection/reconciliation before
resuming, and incomplete reference directories require inspection before retry.
Do not run concurrent search coordinators. Trial CSV is exported at normal
completion; SQLite retains completed trials even after failure.

Validation/top-three selection and the protected final holdout are deliberately
not launched by these scripts. Local scene score is not private leaderboard PCS.
