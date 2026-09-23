"""Targeted Vegas acquisition; retain original manifests and the shared 20 GiB cap.

No training, model inference, or split activation. Reuses pinned archive probes,
extracts only two explicitly selected local ZIP database members, and downloads
their front camera directories under a 384 MiB compressed request cap each.
"""
import argparse
import csv
import fcntl
import json
from pathlib import Path
import sqlite3
import zipfile

from cosmos3 import acquire_raw_camera_pilot as acquisition

BASE = Path(__file__).resolve().parent
ROOT = Path('/media/skr/SeagateHub1/cosmos3-real-camera-pilot-20260919')
EXTENSION = ROOT / 'extensions/all-city-20260921-v2'
INVENTORY = BASE / 'artifacts/training-readiness-20260918'
PARTS = (109, 37)


def eligible(row, protected):
    excluded = set().union(*(set(protected[k]) for k in (
        'protected_public_source_logs', 'protected_official_val_source_logs',
        'quarantined_mini_source_logs')))
    if (row['eligible_metadata_candidate'] != 'True' or row['exclusion_reasons']
            or row['proposed_role'] not in acquisition.ROLES
            or row['source_log'] in excluded
            or [row['city'], row['date']] in protected['protected_public_city_dates']):
        raise ValueError('Protected or ineligible recording')


def extract_metadata(row, destination):
    """ZIP CRC is checked by streaming to EOF; never extract archive paths."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(row['archive']) as archive:
        info = archive.getinfo(row['member'])
        if (info.file_size != int(row['uncompressed_bytes'])
                or info.CRC != int(row['zip_crc']) or info.file_size > 512 * 1024**2):
            raise ValueError('Unexpected local archive member or size')
        temporary = destination.with_suffix('.db.partial')
        if destination.exists() or temporary.exists():
            raise ValueError('Metadata target exists; inspect before resuming')
        count = 0
        with archive.open(info) as source, temporary.open('xb') as target:
            while chunk := source.read(1024**2):
                count += len(chunk)
                if count > info.file_size:
                    raise ValueError('Local ZIP member exceeded expected bytes')
                target.write(chunk)
        if count != info.file_size:
            raise ValueError('Incomplete local ZIP member')
        with sqlite3.connect(temporary.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
            logs = db.execute('SELECT logfile,location,date FROM log').fetchall()
            if (len(logs) != 1 or logs[0][0] != row['recording_window']
                    or logs[0][1] not in ('us-nv-las-vegas-strip', 'las_vegas')
                    or logs[0][2] != row['date']):
                raise ValueError(f'Metadata identity/city mismatch: {logs}')
            if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError('Database integrity check failed')
        temporary.rename(destination)
    return dict(row, path=str(destination))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    original_path = ROOT / 'acquisition-manifest.json'
    original = json.loads(original_path.read_text())
    protected_path = INVENTORY / 'protected-splits.json'
    protected = json.loads(protected_path.read_text())
    public = Path(protected['public_manifest'])
    if acquisition.digest(public.read_bytes()) != protected['public_manifest_sha256']:
        raise ValueError('Protected public manifest changed')
    rows = {r['recording_window']: r for r in csv.DictReader((INVENTORY / 'archive-inventory.csv').open())}
    probes = {p['part']: p for p in json.loads((ROOT / 'probes.json').read_text())}
    selected = []
    for part in PARTS:
        row = rows[probes[part]['window']]
        eligible(row, protected)
        selected.append((part, row))
    if len({r['source_log'] for _, r in selected}) != len(PARTS):
        raise ValueError('Target recordings are not independent')
    ledger = acquisition.Ledger(ROOT / 'transfer-ledger.jsonl')
    plan = {
        'scope': 'all_city_data_extension_no_split_activation_no_training',
        'original_acquisition_sha256': acquisition.digest(original_path.read_bytes()),
        'protected_split_sha256': acquisition.digest(protected_path.read_bytes()),
        'remaining_transfer_bytes_before': ledger.cap - ledger.charged,
        'maximum_additional_compressed_bytes': len(PARTS) * 384 * 1024**2,
        'targets': [{'part': p, **r} for p, r in selected],
    }
    print(json.dumps(plan), flush=True)
    if not args.run:
        return
    with (ROOT / 'acquisition.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        EXTENSION.mkdir(parents=True, exist_ok=False)
        (EXTENSION / 'receipts').mkdir()
        acquisition.save_json(EXTENSION / 'plan.json', plan)
        ledger = acquisition.Ledger(ROOT / 'transfer-ledger.jsonl')
        acquisition.DIRECTORY_CAP = 384 * 1024**2
        receipts, failures = [], []

        def publish(status):
            manifest = dict(original, status=status,
                            charged_compressed_transfer_bytes=ledger.charged,
                            windows=original['windows'] + receipts,
                            extension_plan=str(EXTENSION / 'plan.json'),
                            extension_failures=failures)
            manifest['statistics'] = acquisition.stats(manifest['windows'])
            acquisition.save_json(EXTENSION / 'acquisition-manifest.json', manifest)
            print(json.dumps({'status': status, 'new_logs': len(receipts),
                              'charged_GiB': ledger.charged / 1024**3,
                              'failures': failures}), flush=True)

        publish('all_city_extension_acquiring')
        for part, row in selected:
            try:
                actual = extract_metadata(row, EXTENSION / 'metadata' / (row['recording_window'] + '.db'))
                print(f'Verified Vegas metadata for part {part}', flush=True)
                receipt = acquisition.download(ledger, ROOT, part, actual,
                                               receipt_dir=EXTENSION / 'receipts')
                receipts.append(receipt)
            except Exception as exc:
                failures.append({'part': part, 'type': type(exc).__name__, 'message': str(exc)})
            publish('all_city_extension_acquiring')
        if acquisition.digest(original_path.read_bytes()) != plan['original_acquisition_sha256']:
            raise ValueError('Original acquisition manifest changed')
        publish('all_city_extension_downloaded_split_pending' if len(receipts) == 2
                else 'all_city_extension_incomplete')


if __name__ == '__main__':
    main()
