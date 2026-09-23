"""Freeze an outcome-independent, city/log-balanced development subset."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from eval_common import asset_missing, DEFAULT_DATA_ROOT


def build():
    folder = ROOT / 'evaluation/scene-lists'
    read = lambda name: (folder / (name + '.txt')).read_text().split()
    metadata = json.loads((ROOT / 'evaluation/public-suite.json').read_text())['scenes']
    protected = read('py123d_validation_pool') + read('py123d_holdout')
    protected_logs = {metadata[s]['source_log'] for s in protected}
    pool = read('py123d_development400')
    assert not {metadata[s]['source_log'] for s in pool} & protected_logs
    selected = []
    order = lambda s: hashlib.sha256(('optuna-dev64-v1:' + s).encode()).hexdigest()
    for city in sorted({metadata[s]['city'] for s in pool}):
        logs = defaultdict(list)
        for scene in pool:
            if metadata[scene]['city'] == city:
                logs[metadata[scene]['source_log']].append(scene)
        queues = [sorted(logs[log], key=order) for log in sorted(logs)]
        city_ids = []
        while len(city_ids) < 16:
            for queue in queues:
                if queue and len(city_ids) < 16:
                    city_ids.append(queue.pop(0))
        selected.extend(city_ids)
    assert len(selected) == len(set(selected)) == 64
    missing = {s: asset_missing(DEFAULT_DATA_ROOT, s) for s in selected}
    assert not any(missing.values()), missing
    return dict(scene_ids=selected, city_counts=dict(Counter(metadata[s]['city'] for s in selected)),
                source_log_counts=dict(Counter(metadata[s]['source_log'] for s in selected)),
                protected_log_overlap=[], data_root=str(DEFAULT_DATA_ROOT),
                selection='16 per city, round-robin source logs, deterministic hash order; no score selection',
                limitations=['Existing development logs, not new independent recordings',
                             'Turn/speed/traffic coverage not yet audited',
                             'No unseen Singapore source logs available in protected splits'],
                metadata_sha256=hashlib.sha256((ROOT / 'evaluation/public-suite.json').read_bytes()).hexdigest())


if __name__ == '__main__':
    result = build()
    target = Path(__file__).with_name('development64.json')
    if target.exists():
        assert json.loads(target.read_text()) == result, 'Frozen selection differs; do not overwrite'
    else:
        target.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'scene_ids'}, indent=2))
