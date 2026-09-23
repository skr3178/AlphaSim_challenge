"""Copy the approved pilot to SSD and pin an explicit whole-log split. No training."""
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path

from cosmos3.training.contracts import file_hash, write_json
from cosmos3.training.raw_dataset import activate_roles

ROOT = Path('/media/skr/storage/cosmos3-allcity-pilot-20260921')
PROJECT = Path(__file__).resolve().parent.parent
SOURCE = Path('/media/skr/SeagateHub1/cosmos3-real-camera-pilot-20260919/extensions/all-city-20260921-v2/acquisition-manifest.json')
CHECKPOINT = Path('/media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918/checkpoint')
PROTECTED = PROJECT / 'cosmos3/artifacts/training-readiness-20260918/protected-splits.json'


def copy_verified(source, target, expected=None):
    source = Path(source)
    checksum = file_hash(source)
    if expected is not None and checksum != expected:
        raise ValueError(f'Source hash mismatch: {source}')
    if target.exists() or target.is_symlink():
        raise ValueError(f'Refusing overwrite: {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as src, target.open('xb') as dst:
        shutil.copyfileobj(src, dst, length=1024**2)
    if file_hash(target) != checksum:
        raise ValueError(f'Copy hash mismatch: {target}')
    return {'source': str(source), 'destination': str(target),
            'bytes': target.stat().st_size, 'sha256': checksum}


def main():
    if ROOT.exists():
        raise ValueError('Staging directory already exists; inspect before resuming')
    if shutil.disk_usage(ROOT.parent).free < 25 * 1024**3:
        raise ValueError('Need at least 25 GiB free before staging')
    source_hash = file_hash(SOURCE)
    manifest = json.loads(SOURCE.read_text())
    protected = json.loads(PROTECTED.read_text())
    if file_hash(Path(protected['public_manifest'])) != protected['public_manifest_sha256']:
        raise ValueError('Public evaluation manifest changed')
    ROOT.mkdir()
    records = []
    copy_verified(SOURCE, ROOT / 'original-acquisition.json', source_hash)
    manifest['sensor_root'] = str(ROOT / 'sensor_blobs')
    manifest['image_root'] = manifest['sensor_root']
    groups = defaultdict(list)
    for window in manifest['windows']:
        groups[window['city']].append(window['source_log'])
        db = ROOT / 'metadata' / (window['window'] + '.db')
        records.append(copy_verified(window['metadata_database'], db, window['metadata_sha256']))
        window['metadata_database'] = str(db)
        for image in window['images']:
            target = ROOT / 'sensor_blobs' / image['filename']
            if not target.resolve().is_relative_to(ROOT / 'sensor_blobs'):
                raise ValueError('Unsafe image path')
            records.append(copy_verified(image['image_path'], target, image['sha256']))
            image['image_path'] = str(target)
        print(f"Staged {window['city']} {window['source_log']}: {window['image_count']} images", flush=True)
    for source in sorted(CHECKPOINT.rglob('*')):
        if source.is_file():
            records.append(copy_verified(source, ROOT / 'checkpoint' / source.relative_to(CHECKPOINT)))
            print(f'Staged checkpoint: {source.relative_to(CHECKPOINT)}', flush=True)
    manifest['staging_provenance'] = {'source': str(SOURCE), 'source_sha256': source_hash,
                                     'files_receipt': str(ROOT / 'staging-receipt.json')}
    acquired = ROOT / 'acquisition-manifest.json'
    write_json(acquired, manifest)
    validation_counts = {'boston': 3, 'pittsburgh': 2, 'singapore': 1, 'vegas': 1}
    if set(groups) != set(validation_counts):
        raise ValueError('Missing required city')
    roles = {'train': [], 'validation': []}
    for city, logs in groups.items():
        if len(logs) != len(set(logs)):
            raise ValueError('Duplicate source log')
        logs.sort(key=lambda log: hashlib.sha256(('20260921:' + log).encode()).hexdigest())
        cut = validation_counts[city]
        roles['validation'].extend(logs[:cut])
        roles['train'].extend(logs[cut:])
    split = {'schema_version': 1, 'purpose': 'independent_raw_camera_pilot',
             'protected_split_sha256': file_hash(PROTECTED),
             'acquisition_manifest_sha256': file_hash(acquired), 'roles': roles,
             'allow_shared_city_dates': True,
             'selection': 'SHA256(20260921:source_log), fixed validation log quota per city, independent of scores',
             'authorization': {'scope': 'user_approved_raw_camera_whole_log_split_shared_dates',
                               'date': '2026-09-21',
                               'text': 'User replied "ok run these tests stepwise" to the explicit 19/7 whole-log-disjoint shared-date split confirmation.'}}
    activate_roles(protected, manifest, split, protected_sha256=file_hash(PROTECTED),
                   acquisition_sha256=file_hash(acquired))
    write_json(ROOT / 'pilot-split.json', split)
    write_json(ROOT / 'staging-receipt.json', {'status': 'complete', 'files': records,
               'bytes': sum(r['bytes'] for r in records), 'all_copies_sha256_verified': True,
               'source_acquisition_unchanged': file_hash(SOURCE) == source_hash,
               'roles': roles})
    print(json.dumps({'stage': 'staging_complete', 'bytes': sum(r['bytes'] for r in records),
                      'train_logs': len(roles['train']), 'validation_logs': len(roles['validation'])}), flush=True)


if __name__ == '__main__':
    main()
