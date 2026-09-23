"""Fixed validation of human-numbered Optuna trials 26 and 21; no search."""
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess

os.environ.setdefault('MPLCONFIGDIR', '/tmp/alpasim-validation-plots')
import polars as pl
import yaml
from eval.aggregation.processing import aggregate_and_write_metrics_results_txt
from eval.aggregation.modifiers import RemoveTimestepsAfterEvent
from eval.aggregation.scene_score import score_rollout
from eval.schema import SceneScoreConfig
import run_screen as screen


def main():
    previous = screen.HERE / 'artifacts/split-validation-20260922T100233Z'
    sim = previous / 'available144_baseline/simulation'
    paths = sorted(p for p in sim.glob('rollouts/*/*/metrics.parquet') if (p.parent / '_complete').exists())
    ids = sorted(p.parent.parent.name for p in paths)
    assert len(ids) == len(set(ids)) == 141
    study = screen.HERE / 'artifacts/optuna-development64-v1'
    configs = {f'trial_{n}': json.loads((study / f'trial-{n-1}/result.json').read_text()) for n in (26, 21)}
    out = screen.HERE / 'artifacts' / ('optuna-validation141-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir()
    print('ARTIFACTS=' + str(out), flush=True)
    state = dict(status='starting', current=None, results=[], scenes=141,
                 scope='Same completed baseline subset; three route failures and six untested scenes excluded')
    screen.save(out / 'scene_ids.json', ids)
    screen.save(out / 'fixed-candidates.json', configs)
    screen.save(out / 'status.json', state)
    try:
        with open('/home/skr/alpasim-challenge/logs/.run-eval.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert not subprocess.check_output(['docker', 'ps', '-q'], text=True).strip(), 'Other containers running'
            cfg = yaml.safe_load((sim / 'eval-config.yaml').read_text())
            processed = aggregate_and_write_metrics_results_txt(pl.concat([pl.read_parquet(p) for p in paths]),
                additional_modifiers=[RemoveTimestepsAfterEvent(pl.col('dist_to_gt_trajectory') >= cfg['aggregation_modifiers']['max_dist_to_gt_trajectory'])])
            base = {}
            for row in processed.df_wide_avg_t.to_dicts():
                base[row['clipgt_id']] = dict(score=score_rollout(row, SceneScoreConfig(**cfg['scene_score'])).score, metrics=row)
            screen.save(out / 'baseline-partial.json', base)
            source = out / 'source'
            shutil.copytree(study / 'source', source)
            # Verify model adapter source matches the earlier baseline snapshot.
            for p in source.rglob('*.py'):
                assert p.read_bytes() == (previous / 'source' / p.relative_to(source)).read_bytes(), p
            mounts = tuple(Path(p) for p in ('/home/skr/alpasim-challenge/nuplan-track',
                '/media/skr/SeagateHub1/alpasim-navtest-expansion-20260918/data'))
            assert all(p.exists() for p in mounts)
            for name, config in configs.items():
                assert shutil.disk_usage(screen.ROOT).free > 8 * 1024**3
                state.update(status='evaluating', current=name)
                screen.save(out / 'status.json', state)
                result = screen.run_arm(out, source, name, config['stabilization_weight'], ids, config['gains'],
                    predicted_yaw=config['predicted_yaw'], data_root=previous / 'runtime-data', extra_mounts=mounts)
                rows = json.loads((out / name / 'simulation/aggregate/results-summary.json').read_text())['rollouts']
                assert {r['clipgt_id'] for r in rows} == set(base)
                delta = [r['score']-base[r['clipgt_id']]['score'] for r in rows]
                result['paired'] = dict(delta=sum(delta)/len(delta), better=sum(d>1e-6 for d in delta),
                    worse=sum(d < -1e-6 for d in delta),
                    new_safety_flags={k:[r['clipgt_id'] for r in rows if r['metrics'][k]>0 and base[r['clipgt_id']]['metrics'][k]==0]
                                      for k in ('collision_at_fault', 'left_corridor_laterally')})
                screen.save(out / name / 'paired-result.json', result)
                state['results'].append(result)
                screen.save(out / 'status.json', state)
                print(json.dumps(result), flush=True)
            state.update(status='completed', current=None)
    except BaseException as exc:
        state.update(status='failed', error=repr(exc))
        raise
    finally:
        screen.save(out / 'status.json', state)


if __name__ == '__main__':
    main()
