"""Validate exported corpus, then run a 16-example frozen-feature/head smoke gate.

Each step fails closed. This does not launch the full fit or any simulator.
"""
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from cosmos3.training.contracts import file_hash, write_json
from cosmos3.training.raw_dataset import RawDrivingDataset

ROOT = Path('/media/skr/storage/cosmos3-allcity-pilot-20260921')


def main():
    dataset_path = ROOT / 'export-v3/dataset.json'
    dataset = RawDrivingDataset(dataset_path)
    groups = defaultdict(list)
    for sample in dataset.samples:
        groups[(sample['role'], sample['city'])].append(sample)
    cities = {'boston', 'pittsburgh', 'singapore', 'vegas'}
    if set(groups) != {(role, city) for role in ('train', 'validation') for city in cities}:
        raise ValueError('Export lost all-city role coverage')
    coverage = {f'{role}/{city}': len(samples) for (role, city), samples in groups.items()}
    write_json(ROOT / 'data-validation.json', {
        **dataset.validation_summary, 'status': 'passed', 'coverage': coverage,
        'dataset_sha256': file_hash(dataset_path),
        'accepted_examples_are_overlapping_windows_not_independent_hours': True,
    })
    print(json.dumps({'stage': 'corpus_validation_passed', 'coverage': coverage}), flush=True)
    mini = ROOT / 'smoke-dataset'
    mini.mkdir(exist_ok=False)
    selected = []
    for key, samples in sorted(groups.items()):
        samples = sorted(samples, key=lambda s: (s['source_log'], s['time_us']))
        if len(samples) < 2:
            raise ValueError('Need two genuine examples per city/role for smoke')
        selected.extend([samples[0], samples[len(samples)//2]])
    manifest = dict(dataset.manifest)
    manifest['samples'] = selected
    manifest['subset_provenance'] = {'parent_dataset': str(dataset_path),
                                    'parent_sha256': file_hash(dataset_path),
                                    'purpose': 'engineering smoke only, not generalization benchmark'}
    manifest['source_log_sample_counts'] = dict(Counter(s['source_log'] for s in selected))
    for sample in selected:
        for field in ('inputs', 'targets'):
            source = dataset.root / sample[field]
            target = mini / sample[field]
            with source.open('rb') as src, target.open('xb') as dst:
                shutil.copyfileobj(src, dst)
            if file_hash(target) != sample[field + '_sha256']:
                raise ValueError('Smoke sample copy hash mismatch')
    write_json(mini / 'dataset.json', manifest)
    RawDrivingDataset(mini / 'dataset.json')
    command = [sys.executable, '-u', '-m', 'cosmos3.training.raw_runner']
    subprocess.run(command + ['cache', '--dataset', str(mini / 'dataset.json'),
                   '--checkpoint', str(ROOT / 'checkpoint'), '--output', str(ROOT / 'smoke-cache'),
                   '--device', 'cuda', '--max-seconds', '600'], check=True, timeout=900)
    subprocess.run(command + ['fit', '--dataset', str(mini / 'dataset.json'),
                   '--cache', str(ROOT / 'smoke-cache/cache.json'), '--output', str(ROOT / 'smoke-fit'),
                   '--device', 'cuda', '--epochs', '10', '--steps', '100', '--batch-size', '4',
                   '--max-seconds', '600'], check=True, timeout=1500)
    report = json.loads((ROOT / 'smoke-fit/COMPLETED.json').read_text())
    if report['status'] != 'completed':
        raise ValueError('Smoke training did not complete')
    write_json(ROOT / 'SMOKE-PASSED.json', {'status': 'passed', 'examples': len(selected),
               'full_dataset_validation': str(ROOT / 'data-validation.json'),
               'smoke_report': str(ROOT / 'smoke-fit/COMPLETED.json'),
               'interpretation': 'Engineering only; no closed-loop or generalization claim'})
    print('ALL-CITY ENGINEERING SMOKE PASSED; no full fit or simulator launched', flush=True)


if __name__ == '__main__':
    main()
