"""Run the frozen combo_2 candidate on the 141 completed baseline scenes."""
import datetime
import fcntl
import json
import shutil
import subprocess

import run_screen as screen


def main():
    previous = screen.HERE / 'artifacts/split-validation-20260922T100233Z'
    completed = previous / 'available144_baseline/simulation/rollouts'
    ids = sorted(p.parent.parent.name for p in completed.glob('*/*/_complete')
                 if (p.parent / 'metrics.parquet').is_file())
    assert len(ids) == len(set(ids)) == 141
    config = json.loads((previous / 'fixed-candidates.json').read_text())['combo_2']
    out = screen.HERE / 'artifacts' / ('tuned141-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir()
    print('ARTIFACTS=' + str(out), flush=True)
    state = dict(status='starting', scenes=141, candidate='combo_2', baseline=str(previous),
                 scope='Partial matched subset; excludes three route failures and six untested scenes.')
    screen.save(out / 'scene_ids.json', ids)
    screen.save(out / 'candidate.json', config)
    screen.save(out / 'status.json', state)
    try:
        with open('/home/skr/alpasim-challenge/logs/.run-eval.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert not subprocess.check_output(['docker', 'ps', '-q'], text=True).strip(), 'Other containers running'
            assert shutil.disk_usage(screen.ROOT).free > 8 * 1024**3
            source = out / 'source'
            shutil.copytree(previous / 'source', source)
            mounts = tuple(screen.Path(p) for p in (
                '/home/skr/alpasim-challenge/nuplan-track',
                '/media/skr/SeagateHub1/alpasim-navtest-expansion-20260918/data'))
            assert all(p.exists() for p in mounts)
            state['status'] = 'evaluating'
            screen.save(out / 'status.json', state)
            result = screen.run_arm(out, source, 'combo_2', config['stabilization_weight'], ids,
                                    config['gains'], predicted_yaw=config['predicted_yaw'],
                                    data_root=previous / 'runtime-data', extra_mounts=mounts)
            state.update(status='completed', result=result)
            print(json.dumps(result), flush=True)
    except BaseException as exc:
        state.update(status='failed', error=repr(exc))
        raise
    finally:
        screen.save(out / 'status.json', state)


if __name__ == '__main__':
    main()
