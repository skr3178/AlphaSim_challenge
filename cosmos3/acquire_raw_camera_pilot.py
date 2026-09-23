"""Acquire a bounded, independent raw-camera pilot; never train or run inference.

Only the first CAM_F0 directory of pinned public OpenScene trainval archives is
read. Exact SQLite image membership, immutable split assignments, decoded pixels
and persistent compressed-transfer accounting are mandatory. Metadata-only
candidate eligibility is not organizer certification of training eligibility.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tarfile
import threading
import time
import urllib.request
import uuid

from PIL import Image

REVISION = "a76f840b65e972bc45e56c2adced897498e9a026"
TOTAL_CAP = 20 * 1024**3
PROBE_CAP = 64 * 1024
DIRECTORY_CAP = 256 * 1024**2
ARCHIVE_PREFIX = "openscene-v1.1/sensor_blobs/trainval/"
WINDOW_PATTERN = re.compile(r"^2021\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{2}_veh-\d+_\d{5}_\d{5}$")
ROLES = ("pilot_training", "pilot_validation")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def archive_url(part):
    return (f"https://huggingface.co/datasets/OpenDriveLab/OpenScene/resolve/{REVISION}/"
            f"openscene-v1.1/openscene_sensor_trainval_camera/"
            f"openscene_sensor_trainval_camera_{part}.tgz?download=true")


class Ledger:
    """Reserve before network I/O; interrupted reservations remain fully charged."""

    def __init__(self, path, cap=TOTAL_CAP):
        self.path, self.cap, self.lock = path, cap, threading.Lock()
        self.reservations = {}
        if path.exists():
            for line in path.read_text().splitlines():
                event = json.loads(line)
                self.reservations[event["id"]] = event["charged_bytes"]

    @property
    def charged(self):
        return sum(self.reservations.values())

    def append(self, event):
        with self.path.open("a") as stream:
            stream.write(json.dumps(event) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.reservations[event["id"]] = event["charged_bytes"]

    def begin(self, cap, purpose):
        with self.lock:
            if self.charged + cap > self.cap:
                raise RuntimeError("Persistent 20 GiB transfer budget exhausted")
            identity = uuid.uuid4().hex
            self.append({"id": identity, "event": "reserved", "purpose": purpose,
                         "charged_bytes": cap, "time_unix": time.time()})
            return identity

    def finish(self, identity, count):
        with self.lock:
            if count > self.reservations[identity]:
                raise ValueError("Network accounting exceeded reservation")
            self.append({"id": identity, "event": "finished", "charged_bytes": count,
                         "time_unix": time.time()})


class BoundedReader:
    def __init__(self, response, cap, deadline_seconds=600):
        self.response, self.cap, self.count = response, cap, 0
        self.deadline = time.monotonic() + deadline_seconds

    def read(self, size=-1):
        if time.monotonic() > self.deadline:
            raise TimeoutError("Per-request transfer deadline exceeded")
        remaining = self.cap - self.count
        if remaining <= 0:
            raise ValueError("Compressed transfer prefix cap reached")
        chunk = self.response.read(min(remaining, size if size >= 0 else remaining))
        self.count += len(chunk)
        return chunk


class Transfer:
    def __init__(self, ledger, part, cap, kind):
        self.ledger, self.part, self.cap, self.kind = ledger, part, cap, kind
        self.reader = self.response = None

    def __enter__(self):
        self.identity = self.ledger.begin(self.cap, f"{self.kind}:{self.part}")
        try:
            request = urllib.request.Request(archive_url(self.part), headers={"Range": f"bytes=0-{self.cap - 1}"})
            self.response = urllib.request.urlopen(request, timeout=45)
            if self.response.status != 206 or not self.response.headers.get("Content-Range", "").startswith("bytes 0-"):
                raise ValueError("Server did not honor bounded byte range")
            self.reader = BoundedReader(self.response, self.cap)
            return self.reader
        except Exception:
            if self.response:
                self.response.close()
            # Unknown pre-reader transfer is conservatively charged at reservation.
            raise

    def __exit__(self, *exc):
        self.response.close()
        self.ledger.finish(self.identity, self.reader.count)


def eligible_rows(inventory, protected):
    split = json.loads(protected.read_text())
    excluded = set().union(*(set(split[key]) for key in (
        "protected_public_source_logs", "protected_official_val_source_logs", "quarantined_mini_source_logs")))
    dates = {tuple(pair) for pair in split["protected_public_city_dates"]}
    result = {}
    with inventory.open() as stream:
        for row in csv.DictReader(stream):
            if (row["proposed_role"] not in ROLES or row["eligible_metadata_candidate"] != "True"
                    or row["exclusion_reasons"] or row["source_log"] in excluded
                    or (row["city"], row["date"]) in dates or not Path(row["path"]).is_file()):
                continue
            window = row["recording_window"]
            if not WINDOW_PATTERN.fullmatch(window) or window in result:
                raise ValueError("Ambiguous or unsafe metadata window")
            result[window] = row
    return result


def probe(ledger, part):
    try:
        with Transfer(ledger, part, PROBE_CAP, "probe") as reader:
            with tarfile.open(fileobj=reader, mode="r|gz") as archive:
                member = next(iter(archive))
                pieces = PurePosixPath(member.name).parts
                if (len(pieces) not in (5, 6) or pieces[:3] != ("openscene-v1.1", "sensor_blobs", "trainval")
                        or not WINDOW_PATTERN.fullmatch(pieces[3]) or pieces[4] != "CAM_F0"):
                    raise ValueError("Archive does not start at a safe front-camera directory")
                return {"part": part, "window": pieces[3], "status": "probed", "compressed_bytes_read": reader.count}
    except Exception as exc:
        return {"part": part, "status": "probe_failed", "error_type": type(exc).__name__}


def expected_images(row):
    with sqlite3.connect(Path(row["path"]).as_uri() + "?mode=ro", uri=True) as connection:
        records = connection.execute(
            "SELECT i.filename_jpg, i.timestamp, e.timestamp FROM image i "
            "JOIN camera c ON i.camera_token=c.token JOIN ego_pose e ON i.ego_pose_token=e.token "
            "WHERE c.channel='CAM_F0' ORDER BY i.timestamp").fetchall()
    result = {name: {"timestamp_us": int(timestamp), "ego_pose_timestamp_us": int(ego_timestamp)}
              for name, timestamp, ego_timestamp in records}
    if not records or len(result) != len(records):
        raise ValueError("Missing or duplicate database image references")
    return result


def validate_member(member, window, expected):
    prefix = f"{ARCHIVE_PREFIX}{window}/CAM_F0/"
    if not member.name.startswith(prefix):
        raise ValueError("Image outside selected camera directory")
    name = member.name[len(prefix):]
    key = f"{window}/CAM_F0/{name}"
    if (not re.fullmatch(r"[a-fA-F0-9]{16}\.jpg", name) or key not in expected
            or not member.isfile() or not 0 < member.size <= 8 * 1024**2):
        raise ValueError("Unsafe/unlisted/nonregular camera image")
    return name, key


def download(ledger, output, part, row, *, receipt_dir=None):
    window = row["recording_window"]
    expected = expected_images(row)
    destination = output / "sensor_blobs" / window / "CAM_F0"
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or any(p.is_symlink() for p in destination.parents):
        raise ValueError("Symlinks prohibited in acquisition destination")
    prefix = f"{ARCHIVE_PREFIX}{window}/CAM_F0"
    images, finished = [], False
    with Transfer(ledger, part, DIRECTORY_CAP, "camera") as reader:
        with tarfile.open(fileobj=reader, mode="r|gz") as archive:
            for member in archive:
                if member.name.rstrip("/") == prefix and member.isdir():
                    continue
                if not member.name.startswith(prefix + "/"):
                    if not images:
                        raise ValueError("Archive differs from probed first camera")
                    finished = True
                    break
                name, key = validate_member(member, window, expected)
                source = archive.extractfile(member)
                payload = source.read(member.size + 1)
                if len(payload) != member.size:
                    raise ValueError("Truncated camera JPEG")
                with Image.open(io.BytesIO(payload)) as image:
                    if image.format != "JPEG" or image.size != (1920, 1080):
                        raise ValueError("Unexpected camera image dimensions/format")
                    image.load()
                image_path, checksum = destination / name, digest(payload)
                if image_path.exists():
                    if image_path.is_symlink() or digest(image_path.read_bytes()) != checksum:
                        raise ValueError("Existing image differs; no overwrites permitted")
                else:
                    with image_path.open("xb") as stream:
                        stream.write(payload)
                images.append({"filename": key, "image_path": str(image_path), **expected[key],
                               "bytes": len(payload), "sha256": checksum})
        compressed = reader.count
    images.sort(key=lambda item: item["timestamp_us"])
    times = [item["timestamp_us"] for item in images]
    if not finished or len(images) < 12 or len(set(times)) != len(times):
        raise ValueError("Incomplete camera directory or insufficient/nonunique image timestamps")
    gaps = [right - left for left, right in zip(times, times[1:])]
    receipt = {"status": "camera_directory_verified_training_export_pending", "part": part, "window": window,
               "source_log": row["source_log"], "city": row["city"], "date": row["date"],
               "proposed_role": row["proposed_role"], "metadata_database": row["path"],
               "source_url": archive_url(part), "source_revision": REVISION,
               "metadata_sha256": digest(Path(row["path"]).read_bytes()),
               "image_count": len(images), "span_s": (times[-1] - times[0]) / 1e6,
               "compressed_bytes_read": compressed, "image_bytes": sum(item["bytes"] for item in images),
               "max_gap_us": max(gaps), "min_gap_us": min(gaps),
               "gaps_over_600ms": sum(gap > 600000 for gap in gaps),
               "full_archive_checksum_verified": False, "complete_first_camera_directory": True,
               "images": images}
    save_json((receipt_dir if receipt_dir is not None else output / "receipts") / f"part-{part:04d}.json", receipt)
    return receipt


def stats(receipts):
    result = {}
    for role in ROLES:
        selected = [receipt for receipt in receipts if receipt["proposed_role"] == role]
        result[role] = {"windows": len(selected), "logs": len({r["source_log"] for r in selected}),
                        "cities": sorted({r["city"] for r in selected}),
                        "raw_images": sum(r["image_count"] for r in selected),
                        "nominal_1hz_anchor_upper_bound": sum(max(0, int(r["span_s"] - 5)) for r in selected)}
    return result


def satisfied(receipts):
    current = stats(receipts)
    train, validation = (current[role] for role in ROLES)
    return (train["logs"] >= 12 and validation["logs"] >= 4 and len(train["cities"]) >= 3
            and train["nominal_1hz_anchor_upper_bound"] >= 3500
            and validation["nominal_1hz_anchor_upper_bound"] >= 700)


def still_needed(row, receipts):
    current = stats(receipts)[row["proposed_role"]]
    if row["proposed_role"] == "pilot_training":
        return (current["logs"] < 12 or len(current["cities"]) < 3
                or current["nominal_1hz_anchor_upper_bound"] < 3500)
    return current["logs"] < 4 or current["nominal_1hz_anchor_upper_bound"] < 700


def verify_saved_receipts(receipts, rows):
    seen_logs = set()
    for receipt in receipts:
        row = rows.get(receipt["window"])
        if (row is None or row["source_log"] != receipt["source_log"]
                or row["proposed_role"] != receipt["proposed_role"]
                or row["source_log"] in seen_logs):
            raise ValueError("Saved receipt no longer matches independent immutable split")
        seen_logs.add(row["source_log"])
        for image in receipt["images"]:
            path = Path(image["image_path"])
            if path.is_symlink() or digest(path.read_bytes()) != image["sha256"]:
                raise ValueError("Saved camera image failed resume integrity check")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--max-probes", type=int, default=128)
    args = parser.parse_args()
    if not 1 <= args.max_probes <= 512:
        raise ValueError("Total probe index bound must be 1..512")
    base = Path(__file__).resolve().parent / "artifacts/training-readiness-20260918"
    inventory, protected = base / "database-inventory.csv", base / "protected-splits.json"
    rows = eligible_rows(inventory, protected)
    print(json.dumps({"eligible_metadata_windows": len(rows), "download": args.run,
                      "maximum_transfer_bytes": TOTAL_CAP}), flush=True)
    if not args.run:
        return
    args.output.mkdir(parents=False, exist_ok=True)
    if args.output.is_symlink():
        raise ValueError("Output cannot be a symlink")
    with (args.output / "acquisition.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = {"revision": REVISION, "inventory_sha256": digest(inventory.read_bytes()),
                "protected_split_sha256": digest(protected.read_bytes()), "transfer_cap_bytes": TOTAL_CAP,
                "scope": "independent_raw_front_camera_only_no_training_no_evaluation",
                "split_role_policy": "preserve_existing_metadata_inventory_proposed_role"}
        plan_path = args.output / "acquisition-plan.json"
        if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
            raise ValueError("Existing output has different immutable acquisition plan")
        save_json(plan_path, plan)
        (args.output / "receipts").mkdir(exist_ok=True)
        ledger = Ledger(args.output / "transfer-ledger.jsonl")
        probe_path = args.output / "probes.json"
        probes = json.loads(probe_path.read_text()) if probe_path.exists() else []
        known_parts = {item["part"] for item in probes}
        receipts = [json.loads(path.read_text()) for path in sorted((args.output / "receipts").glob("part-*.json"))]
        verify_saved_receipts(receipts, rows)
        selected_logs = {item["source_log"] for item in receipts}
        failures = []

        def publish(status):
            summary = {"schema_version": 1, "status": status, "sensor_root": str(args.output / "sensor_blobs"),
                       "charged_compressed_transfer_bytes": ledger.charged, "transfer_cap_bytes": TOTAL_CAP,
                       "statistics": stats(receipts), "windows": receipts, "failures": failures,
                       "usable_training_examples": "unknown_until_causal_export_validation",
                       "protected_splits_modified": False, **plan}
            save_json(args.output / "acquisition-manifest.json", summary)
            print(json.dumps({"status": status, "charged_GiB": round(ledger.charged / 1024**3, 3),
                              "statistics": summary["statistics"]}), flush=True)

        publish("acquiring")
        for start in range(0, args.max_probes, 16):
            parts = [part for part in range(start, min(start + 16, args.max_probes)) if part not in known_parts]
            with ThreadPoolExecutor(max_workers=4) as pool:
                probes.extend(pool.map(lambda part: probe(ledger, part), parts))
            save_json(probe_path, probes)
            candidates = [item for item in probes if start <= item["part"] < start + 16
                          and item.get("window") in rows and rows[item["window"]]["source_log"] not in selected_logs]
            candidates.sort(key=lambda item: (rows[item["window"]]["proposed_role"] != "pilot_validation", item["part"]))
            for candidate in candidates:
                row = rows[candidate["window"]]
                if row["source_log"] in selected_logs or not still_needed(row, receipts):
                    continue
                try:
                    receipt = download(ledger, args.output, candidate["part"], row)
                    receipts.append(receipt)
                    selected_logs.add(row["source_log"])
                    print(f"Verified part {candidate['part']}: {row['city']} {row['proposed_role']} {receipt['image_count']} images", flush=True)
                except Exception as exc:
                    failures.append({"part": candidate["part"], "window": candidate["window"], "error_type": type(exc).__name__})
                    print(f"Skipped part {candidate['part']}: {type(exc).__name__}", flush=True)
                publish("acquiring")
                if satisfied(receipts):
                    break
            if satisfied(receipts) or ledger.charged + DIRECTORY_CAP > TOTAL_CAP:
                break
        publish("acquisition_target_met_export_pending" if satisfied(receipts) else "bounded_acquisition_finished_below_target")


if __name__ == "__main__":
    main()
