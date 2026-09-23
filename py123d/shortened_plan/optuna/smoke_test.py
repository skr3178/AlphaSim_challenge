"""CPU-only synthetic test. Never imports or launches AlpaSim."""
import tempfile
from pathlib import Path

import optuna
from scipy.stats import qmc


def objective(trial):
    x = trial.suggest_float('x', 0., 1.)
    y = trial.suggest_float('y', 0., 1.)
    trial.set_constraint('synthetic_limit', x + y - 1.5)
    return -((x - .3)**2 + (y - .4)**2)


def main():
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    assert optuna.__version__ == '5.0.0'
    with tempfile.TemporaryDirectory(prefix='optuna-env-check-') as folder:
        storage = 'sqlite:///' + str(Path(folder) / 'synthetic.db')
        sampler = optuna.samplers.TPESampler(seed=42, multivariate=True, n_startup_trials=4)
        study = optuna.create_study(study_name='synthetic-only', storage=storage,
                                   direction='maximize', sampler=sampler)
        for x, y in qmc.LatinHypercube(d=2, seed=42).random(4):
            study.enqueue_trial({'x': float(x), 'y': float(y)})
        study.optimize(objective, n_trials=8)
        resumed = optuna.load_study(study_name='synthetic-only', storage=storage,
                                   sampler=optuna.samplers.TPESampler(seed=43, multivariate=True))
        resumed.optimize(objective, n_trials=2)
        assert len(resumed.trials) == 10
        assert all(t.state == optuna.trial.TrialState.COMPLETE for t in resumed.trials)
        assert resumed.best_trial.params['x'] + resumed.best_trial.params['y'] <= 1.5
    print('PASS: Optuna 5.0.0; Latin hypercube; constrained multivariate TPE; SQLite reload; 10 synthetic CPU trials')
    print('No simulator, checkpoint, GPU work, or real tuning study was started.')


if __name__ == '__main__':
    main()
