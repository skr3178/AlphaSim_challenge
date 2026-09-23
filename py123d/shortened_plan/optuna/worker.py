"""One locked real evaluation, executed by the existing runtime Python."""
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_screen as screen


def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    out = Path(request['output'])
    out.mkdir(exist_ok=True)
    with open('/home/skr/alpasim-challenge/logs/.run-eval.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not subprocess.check_output(['docker', 'ps', '-q'], text=True).strip(), 'GPU evaluator busy'
        assert shutil.disk_usage(screen.ROOT).free > 8 * 1024**3
        result = screen.run_arm(out, Path(request['source']), 'candidate', request['blend'],
                                request['scene_ids'], request['gains'], data_root=request['data_root'])
        screen.save(out / 'result.json', result)


if __name__ == '__main__':
    main()
