"""Bounded local host-policy probe and one-scene closed-loop diagnostic.

Not a hardened-container test or official-scorer equivalence claim.
"""
import datetime
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

import yaml

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / 'alpasim-upstream-20260916/e2e_challenge/sample_submission_simscale_navsim_gtrs_dense'
RUNTIME = Path('/home/skr/alpasim-challenge/alpasim')
PYTHON = '/media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python'
SCENE = '2021.05.25.14.24.08_veh-25_04059_04203-5395d42cc65e5c06'
PORT = 6796


def main(full400=False):
    lock = open('/home/skr/alpasim-challenge/logs/.run-eval.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if subprocess.check_output(['docker', 'ps', '-q'], text=True).strip():
        raise RuntimeError('Other Docker workloads are running; refusing interference')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', PORT))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = ROOT / 'alternative_models/gtrs_dense/artifacts' / stamp
    output.mkdir(parents=True, exist_ok=False)
    run_dir = output / 'simulation'
    name = ('gtrs-full400-' if full400 else 'gtrs-smoke-') + stamp.lower()
    scene_ids = yaml.safe_load((RUNTIME / 'src/wizard/configs/nuplan_scenes/navtest_local400.yaml').read_text())['scenes']['scene_ids'] if full400 else [SCENE]
    assert len(scene_ids) == len(set(scene_ids)) == (400 if full400 else 1)
    (output / 'scene_ids.json').write_text(json.dumps(scene_ids, indent=2) + '\n')
    report = {'status': 'starting', 'scene': None if full400 else SCENE, 'expected_rollouts': len(scene_ids), 'max_sim_steps': 200 if full400 else 20,
              'driver_mode': 'host process, supplied policy/adapter unchanged',
              'official_parity': False, 'output': str(output),
              'runtime_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=RUNTIME, text=True).strip()}
    def save():
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    save()
    print('ARTIFACTS=' + str(output), flush=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               PYTHONPATH=f'{SAMPLE}:{RUNTIME}/src/grpc',
               ALPASIM_DRIVER_HOST='127.0.0.1', ALPASIM_DRIVER_PORT=str(PORT),
               ALPASIM_DRIVER_LOG_DIR=str(output / 'driver-logs'),
               GTRS_CHECKPOINT_PATH=str(ROOT / 'alternative_models/gtrs_dense/gtrs_dense_resnet_sim_reward_navhard.ckpt'),
               GTRS_VOCAB_PATH=str(ROOT / 'alternative_models/gtrs_dense/navsim_16384.npy'),
               GTRS_DEVICE='cuda', GTRS_BACKBONE='resnet', GTRS_SPEED_ENHANCEMENT='1',
               GTRS_SCORER_MODE='nc_dac_ep', GTRS_EP_EXPONENT='3', GTRS_SPEED_TOP_K='64', GTRS_SPEED_WEIGHT='3',
               ALPASIM_NUPLAN_ROOT='/home/skr/alpasim-challenge/nuplan-track')
    driver = simulation = None
    compose = None
    try:
        with (output / 'driver.log').open('w') as log:
            driver = subprocess.Popen([PYTHON, '-u', '-m', 'navsim_gtrs_dense_challenge.driver'],
                                      cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 120
        while True:
            if driver.poll() is not None:
                raise RuntimeError('Driver startup failed; see driver.log')
            try:
                with socket.create_connection(('127.0.0.1', PORT), timeout=1):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError('Driver startup timeout')
                time.sleep(1)
        with (output / 'probe.log').open('w') as log:
            subprocess.run([PYTHON, str(SAMPLE / 'scripts/probe_container.py'), '--address',
                            f'127.0.0.1:{PORT}', '--timeout', '180'], env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)
        report['probe'] = 'passed (host service, two sessions)'
        save()
        cameras = '[{logical_id:CAM_L0,frame_interval_us:500000,height:1080,width:1920},{logical_id:CAM_F0,frame_interval_us:500000,height:1080,width:1920},{logical_id:CAM_R0,frame_interval_us:500000,height:1080,width:1920}]'
        command = [str(RUNTIME / '.venv/bin/alpasim_wizard'), '+e2e_challenge_nuplan=dev',
                   f'scenes.scene_ids=[{SCENE}]', 'scenes.limit_to_first_n=1', 'scenes.test_suite_id=null',
                   'runtime.nr_workers=1', 'runtime.simulation_config.n_rollouts=1',
                   'runtime.simulation_config.n_sim_steps=20', f'runtime.simulation_config.cameras={cameras}',
                   'defines.nre_cache_size=2', 'eval.allow_aggregation_with_failed_rollouts=false',
                   'eval.video.render_video=false', f'wizard.log_dir={run_dir}', 'wizard.run_method=NONE']
        if full400:
            command = [str(RUNTIME / '.venv/bin/alpasim_wizard'), '+e2e_challenge_nuplan=dev_fast2_3cam',
                       'nuplan_scenes=navtest_local400', 'scenes.limit_to_first_n=0', 'scenes.test_suite_id=null',
                       'runtime.simulation_config.n_rollouts=1', 'runtime.simulation_config.n_sim_steps=200',
                       'eval.allow_aggregation_with_failed_rollouts=false', 'eval.video.render_video=false',
                       f'wizard.log_dir={run_dir}', 'wizard.run_method=NONE']
        with (output / 'config.log').open('w') as log:
            subprocess.run(command, cwd=RUNTIME, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
        config = yaml.safe_load((run_dir / 'wizard-config.yaml').read_text())
        assert config['scenes']['scene_ids'] == scene_ids
        assert config['runtime']['simulation_config']['n_rollouts'] == 1
        assert config['runtime']['simulation_config']['n_sim_steps'] == (200 if full400 else 20)
        compose = ['docker', 'compose', '-p', name, '-f', str(run_dir / 'docker-compose.yaml')]
        report['status'] = 'simulation_running'
        save()
        print(f'Probe passed; running {len(scene_ids)} scenes', flush=True)
        with (output / 'simulator.log').open('w') as log:
            simulation = subprocess.Popen(compose + ['up', '--pull', 'never', '--no-build', '--exit-code-from', 'runtime-0'],
                                          cwd=run_dir, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            report['simulation_exit_code'] = simulation.wait(timeout=86400 if full400 else 900)
        if report['simulation_exit_code'] != 0:
            raise RuntimeError('Simulation failed; see simulator.log')
        summary = json.loads((run_dir / 'aggregate/results-summary.json').read_text())
        assert len(summary['rollouts']) == len(scene_ids)
        assert {r['clipgt_id'] for r in summary['rollouts']} == set(scene_ids)
        report['rollout'] = summary['rollouts'][0] if not full400 else None
        if full400:
            import re
            lines = (output / 'driver.log').read_text().splitlines()
            counters = {}
            for line in lines:
                match = re.search(r'session=(\S+) gtrs_inference=(\d+) cached_plan=(\d+) straight_fallback=(\d+) dynamic_state_fallback=(\d+) inference_error=(\d+)', line)
                if match and not match[1].startswith('probe-'):
                    counters[match[1]] = list(map(int, match.groups()[1:]))
            assert len(counters) == 400, len(counters)
            assert all(v[0] > 0 and not any(v[1:]) for v in counters.values()), 'Driver errors/fallbacks; inspect logs'
            assert (output / 'simulator.log').read_text().count('Session COMPLETED') == 400
            report['successful_model_calls'] = sum(v[0] for v in counters.values())
            report['mean_scene_score'] = sum(r['score'] for r in summary['rollouts']) / 400
            with (output / 'board-report.log').open('w') as log:
                subprocess.run([str(RUNTIME / '.venv/bin/python'), str(ROOT / 'tools/eval-report.py'), str(run_dir)],
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
        report['status'] = 'completed_coverage_and_driver_counters_verified' if full400 else 'completed_requires_driver_log_review'
    except BaseException as exc:
        report.update(status='failed', error=repr(exc))
        raise
    finally:
        if simulation is not None and simulation.poll() is None:
            os.killpg(simulation.pid, signal.SIGTERM)
            try:
                simulation.wait(20)
            except subprocess.TimeoutExpired:
                os.killpg(simulation.pid, signal.SIGKILL)
                simulation.wait(5)
        if compose is not None:
            with (output / 'cleanup.log').open('w') as log:
                subprocess.run(compose + ['down', '--timeout', '10'], stdout=log, stderr=subprocess.STDOUT, timeout=60)
        if driver is not None and driver.poll() is None:
            driver.terminate()
            try:
                driver.wait(20)
            except subprocess.TimeoutExpired:
                driver.kill()
                driver.wait(5)
        save()
        print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--full400', action='store_true')
    main(parser.parse_args().full400)
