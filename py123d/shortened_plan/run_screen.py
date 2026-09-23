"""Sequential, locked local screening. No training, image build, push or submission."""
import argparse
from collections import Counter
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time

import yaml

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'py123d/shortened_plan'
RUNTIME = Path('/home/skr/alpasim-challenge/alpasim')
SOURCE = ROOT / 'py123d/py123d_garage'
IMAGE = 'py123d-garage-alpasim:nuplan-0014'
PORT = 6797
ARMS = [('baseline', 0), ('lateral_15', 0), ('heading_15', 0), ('steering_35', 0), ('steering_65', 0), ('stabilization', .15)]


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def select():
    spec = importlib.util.spec_from_file_location('report', ROOT / 'tools/eval-report.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = json.loads((RUNTIME / 'runs/py123d-0014-400/aggregate/results-summary.json').read_text())['rollouts']
    chosen = []
    for city in ('boston', 'pittsburgh', 'singapore', 'vegas'):
        pool = sorted([r for r in rows if mod.city_for(r['clipgt_id']) == city], key=lambda r: r['clipgt_id'])
        buckets = [('corridor', lambda r: r.get('failure_reason') == 'left_corridor_laterally'),
                   ('partial', lambda r: 0 < r['score'] < 1), ('success', lambda r: r['score'] == 1)]
        for category, predicate in buckets:
            matches = [r for r in pool if predicate(r)]
            assert len(matches) >= 2, (city, category)
            # Spread source recordings where available; selection is frozen before new results.
            a = matches[0]
            b = next((r for r in matches[1:] if mod.recording_for(r['clipgt_id']) != mod.recording_for(a['clipgt_id'])), matches[1])
            for r in (a, b):
                chosen.append(dict(scene=r['clipgt_id'], city=city, category=category, historical_score=r['score']))
    assert len({r['scene'] for r in chosen}) == 24
    return chosen


def run_arm(output, source, name, weight, ids, gains, smoke=False, predicted_yaw=False,
            data_root='/home/skr/alpasim-challenge/nuplan-track', extra_mounts=()):
    directory = output / name
    directory.mkdir()
    run = directory / 'simulation'
    prefix = 'py-screen-' + output.name.lower() + '-' + name.replace('_', '-')
    driver_name = prefix + '-driver'
    compose = None
    cid = None
    start = time.monotonic()
    try:
        command = ['docker', 'run', '-d', '--name', driver_name, '--init', '--gpus', 'all',
                   '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--read-only',
                   '--pids-limit', '1024', '--memory', '32g', '--cpus', '8',
                   '--tmpfs', '/tmp:rw,nosuid,nodev,size=2g', '--tmpfs', '/run:rw,nosuid,nodev,size=64m',
                   '-p', f'127.0.0.1:{PORT}:{PORT}',
                   '--mount', f'type=bind,source={source},target=/screen-source,readonly',
                   '-e', 'PYTHONPATH=/screen-source/src', '-e', f'ALPASIM_DRIVER_PORT={PORT}',
                   IMAGE, f'use_predicted_yaw={str(predicted_yaw).lower()}', f'stabilization_previous_weight={weight}']
        save(directory / 'driver-command.json', command)
        cid = subprocess.check_output(command, text=True).strip()
        for _ in range(120):
            try:
                with socket.create_connection(('127.0.0.1', PORT), timeout=1): break
            except OSError:
                time.sleep(1)
        else: raise TimeoutError('driver port never opened')
        env = dict(os.environ, ALPASIM_DRIVER_HOST='localhost', ALPASIM_DRIVER_PORT=str(PORT),
                   ALPASIM_NUPLAN_ROOT=str(data_root))
        command = [str(RUNTIME / '.venv/bin/alpasim_wizard'), '+e2e_challenge_nuplan=dev_fast2_3cam',
                   'scenes.scene_ids=[' + ','.join(ids) + ']', 'scenes.limit_to_first_n=0', 'scenes.test_suite_id=null',
                   'runtime.simulation_config.n_rollouts=1', 'runtime.simulation_config.n_sim_steps=200',
                   'eval.allow_aggregation_with_failed_rollouts=false', 'eval.video.render_video=false',
                   f'wizard.log_dir={run}', 'wizard.run_method=NONE']
        command += [f'controller.gains.{k}={v}' for k, v in gains.items()]
        with (directory / 'config.log').open('w') as log:
            subprocess.run(command, cwd=RUNTIME, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
        cfg = yaml.safe_load((run / 'wizard-config.yaml').read_text())
        assert cfg['scenes']['scene_ids'] == ids
        assert cfg['controller']['gains'] == gains
        assert yaml.safe_load((run / 'controller-config.yaml').read_text())['gains'] == gains
        compose = ['docker', 'compose', '-p', prefix, '-f', str(run / 'docker-compose.yaml')]
        if extra_mounts:
            override = {'services': {service: {'volumes': [f'{p}:{p}:ro' for p in extra_mounts]}
                                    for service in ('runtime-0', 'renderer-0')}}
            (run / 'data-mounts.yaml').write_text(yaml.safe_dump(override))
            compose += ['-f', str(run / 'data-mounts.yaml')]
        with (directory / 'simulator.log').open('w') as log:
            subprocess.run(compose + ['up', '--pull', 'never', '--no-build', '--exit-code-from', 'runtime-0'],
                           cwd=run, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=3600)
        driver_log = subprocess.check_output(['docker', 'logs', cid], stderr=subprocess.STDOUT, text=True)
        (directory / 'driver.log').write_text(driver_log)
        summary = json.loads((run / 'aggregate/results-summary.json').read_text())
        rows = summary['rollouts']
        assert len(rows) == len(ids) and {r['clipgt_id'] for r in rows} == set(ids)
        assert (directory / 'simulator.log').read_text().count('Session COMPLETED') == len(ids)
        failures = driver_log.count('failed to plan')
        calls = len(re.findall(r'screen_plan session=', driver_log))
        stabilized = len(re.findall(r'stabilized=1', driver_log))
        assert failures == 0, f'{failures} planning failures; stop rather than scoring fallbacks'
        assert calls >= len(ids), 'missing successful planning telemetry'
        assert len(set(re.findall(r'screen_plan session=(\S+)', driver_log))) == len(ids)
        result = dict(arm=name, scenes=len(ids), score=sum(r['score'] for r in rows)/len(rows),
                      collisions=sum(r['metrics']['collision_at_fault'] for r in rows),
                      corridor_exits=sum(r['metrics']['left_corridor_laterally'] for r in rows),
                      progress=sum(r['metrics']['progress_clipped_rel'] for r in rows)/len(rows),
                      d2gt=sum(r['metrics']['dist_to_gt_trajectory'] for r in rows)/len(rows),
                      planning_calls=calls, planning_failures=failures, stabilized_calls=stabilized,
                      wall_seconds=time.monotonic()-start, gains=gains, stabilization_weight=weight,
                      predicted_yaw=predicted_yaw)
        save(directory / 'result.json', result)
        return result
    finally:
        if compose:
            subprocess.run(compose + ['down', '--timeout', '10'], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=60)
        if cid:
            with (directory / 'driver.log').open('w') as log:
                subprocess.run(['docker', 'logs', cid], stdout=log, stderr=subprocess.STDOUT)
            subprocess.run(['docker', 'rm', '-f', cid], stdout=subprocess.DEVNULL, check=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--select-only', action='store_true')
    args = parser.parse_args()
    selected = select()
    if args.select_only:
        print(json.dumps(selected, indent=2)); return
    lock = open('/home/skr/alpasim-challenge/logs/.run-eval.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert not subprocess.check_output(['docker', 'ps', '-q'], text=True).strip(), 'Other containers running'
    with socket.socket() as s: s.bind(('127.0.0.1', PORT))
    assert shutil.disk_usage(ROOT).free > 10*1024**3
    output = HERE / 'artifacts' / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output.mkdir(parents=True)
    print('ARTIFACTS=' + str(output), flush=True)
    save(output / 'selection.json', selected)
    source = output / 'source'
    shutil.copytree(SOURCE / 'src', source / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    save(output / 'source-sha256.json', {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()})
    gains = {n: json.loads((HERE / 'gains' / (n + '.json')).read_text()) for n, _ in ARMS if n != 'stabilization'}
    save(output / 'gains.json', gains)
    status = dict(status='running', current=None, results=[], official_parity=False,
                  image_id=subprocess.check_output(['docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}}'],text=True).strip())
    try:
        # A known development scene; smoke uses nondefault gains AND stabilization.
        smoke_id = '2021.05.25.14.24.08_veh-25_04059_04203-5395d42cc65e5c06'
        for n,w in [('smoke_baseline',0), ('smoke_stabilization',.15)]:
            status['current']=n; save(output/'status.json',status)
            r=run_arm(output,source,n,w,[smoke_id],gains['lateral_15'] if w else gains['baseline'],True)
            if w and not r['stabilized_calls']:
                raise RuntimeError('Smoke filter never activated; inspect guards before screening')
        for name,weight in ARMS:
            status['current']=name; save(output/'status.json',status)
            result=run_arm(output,source,name,weight,[r['scene'] for r in selected],gains.get(name,gains['baseline']))
            status['results'].append(result); save(output/'status.json',status)
            lines=['# Py123d development screening', '', 'Outcome-stratified development sample; not a leaderboard estimate.', '',
                   '| Arm | Score | At-fault scenes | Corridor exits | Progress | D2GT m | Plans | Stabilized |', '|---|---:|---:|---:|---:|---:|---:|---:|']
            for r in status['results']:
                lines.append(f"| {r['arm']} | {r['score']:.4f} | {r['collisions']:.0f} | {r['corridor_exits']:.0f} | {r['progress']:.4f} | {r['d2gt']:.3f} | {r['planning_calls']} | {r['stabilized_calls']} |")
            (output/'COMPARISON.md').write_text('\n'.join(lines)+'\n')
            print('COMPLETED '+name,flush=True)
        status['status']='completed'
    except BaseException as e:
        status.update(status='failed',error=repr(e)); raise
    finally:
        save(output/'status.json',status)


if __name__ == '__main__': main()
