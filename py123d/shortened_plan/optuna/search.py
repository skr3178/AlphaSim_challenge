"""Explicit reference/search stages. Default is a CPU-only preparation check."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

import optuna
from scipy.stats import qmc
from prepare import build, ROOT

HERE = Path(__file__).resolve().parent
RUNTIME_PYTHON = '/home/skr/alpasim-challenge/alpasim/.venv/bin/python'
FROZEN = HERE.parent / 'artifacts/split-validation-20260922T100233Z'
SPACE = dict(long_position_weight=(.1, 4., True), acceleration_weight=(.05, 5., True),
             rel_acceleration_weight=(.1, 10., True), trajectory_stabilization_blend=(0., .25, False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['check', 'references', 'search'], default='check')
    parser.add_argument('--total-trials', type=int, default=50, help='Total study budget, including 20 initial points')
    args = parser.parse_args()
    manifest = json.loads((HERE / 'development64.json').read_text())
    assert manifest == build(), 'Scene selection or assets changed'
    configs = json.loads((FROZEN / 'fixed-candidates.json').read_text())
    if args.stage == 'check':
        print('PASS: 64 scenes, assets present, protected logs excluded; no GPU work launched')
        return
    out = HERE.parent / 'artifacts/optuna-development64-v1'
    out.mkdir(exist_ok=True)
    source = out / 'source'
    if not source.exists():
        shutil.copytree(FROZEN / 'source', source)
    fingerprint = dict(manifest=manifest, space=SPACE, baseline=configs['baseline']['gains'],
                       source={str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts})
    encoded = json.dumps(fingerprint, sort_keys=True)
    record = out / 'fingerprint.json'
    if record.exists():
        assert record.read_text() == encoded, 'Study inputs changed'
    else:
        record.write_text(encoded)

    def evaluate(name, gains, blend):
        directory = out / name
        directory.mkdir(exist_ok=True)
        request = dict(output=str(directory), source=str(source), gains=gains, blend=blend,
                       scene_ids=manifest['scene_ids'], data_root=manifest['data_root'])
        req = directory / 'request.json'
        if req.exists():
            assert json.loads(req.read_text()) == request
        req.write_text(json.dumps(request, indent=2))
        result = directory / 'result.json'
        if not result.exists():
            with (directory / 'worker.log').open('a') as log:
                subprocess.run([RUNTIME_PYTHON, str(HERE / 'worker.py'), str(req)],
                               stdout=log, stderr=subprocess.STDOUT, check=True)
        return json.loads(result.read_text())

    if args.stage == 'references':
        for name in ('baseline', 'combo_2'):
            print(evaluate(name, configs[name]['gains'], configs[name]['stabilization_weight']), flush=True)
        return
    baseline = json.loads((out / 'baseline/result.json').read_text())
    assert (out / 'combo_2/result.json').exists(), 'Run both references before search'
    sampler = optuna.samplers.TPESampler(seed=42, multivariate=True, n_startup_trials=20)
    study = optuna.create_study(study_name='development64-v1', storage='sqlite:///' + str(out / 'study.db'),
                               direction='maximize', sampler=sampler, load_if_exists=True)
    if not study.trials:
        for point in qmc.LatinHypercube(d=4, seed=42).random(20):
            params = {}
            for (key, (low, high, log)), value in zip(SPACE.items(), point):
                params[key] = float(math.exp(math.log(low) + value * math.log(high / low)) if log
                                    else low + value * (high - low))
            study.enqueue_trial(params)

    def objective(trial):
        params = {k: trial.suggest_float(k, lo, hi, log=log) for k, (lo, hi, log) in SPACE.items()}
        gains = dict(configs['baseline']['gains'])
        blend = params.pop('trajectory_stabilization_blend')
        gains.update(params)
        result = evaluate('trial-' + str(trial.number), gains, blend)
        trial.set_user_attr('metrics', result)
        for metric in ('collisions', 'corridor_exits'):
            trial.set_constraint(metric, result[metric] - baseline[metric])
        return result['score']

    finished = sum(t.state.is_finished() for t in study.trials)
    assert not any(t.state == optuna.trial.TrialState.RUNNING for t in study.trials), 'Resolve interrupted RUNNING trial before resume'
    study.optimize(objective, n_trials=max(0, args.total_trials - finished))
    study.trials_dataframe().to_csv(out / 'trials.csv', index=False)


if __name__ == '__main__':
    main()
