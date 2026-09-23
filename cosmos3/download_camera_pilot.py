"""Bounded, front-only camera acquisition; no training, rendering or evaluation.

Read only the first CAM_F0 directory in three pinned public OpenScene archives.
Every image must match an independent training window in our local nuPlan DBs.
Never extract archive paths directly, deserialize metadata pickles, or overwrite.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tarfile
import time
import urllib.request

from PIL import Image

REVISION = "a76f840b65e972bc45e56c2adced897498e9a026"
CANDIDATES = (
    (0, "2021.08.17.15.02.08_veh-45_02003_02086"),
    (3, "2021.10.06.14.31.13_veh-28_00589_00665"),
    (10, "2021.09.15.14.27.22_veh-39_00038_00414"),
)
COMPRESSED_CAP = 256 * 1024**2  # Per archive; stop earlier when the first camera ends.


class BoundedReader:
    def __init__(self, response):
        self.response = response
        self.count = 0
        self.started = time.monotonic()

    def read(self, size=-1):
        if time.monotonic() - self.started > 600:
            raise TimeoutError("Camera transfer exceeded ten-minute per-archive bound")
        remaining = COMPRESSED_CAP - self.count
        if remaining <= 0:
            raise ValueError("First camera directory exceeds compressed-byte bound")
        data = self.response.read(min(remaining, size if size >= 0 else remaining))
        self.count += len(data)
        return data


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def preflight(inventory, protected):
    with inventory.open() as stream:
        rows = list(csv.DictReader(stream))
    with protected.open() as stream:
        split = json.load(stream)
    excluded = set()
    for key in ("protected_public_source_logs", "protected_official_val_source_logs", "quarantined_mini_source_logs"):
        excluded.update(split[key])
    selected = []
    for part, window in CANDIDATES:
        matches = [r for r in rows if r["recording_window"] == window]
        if len(matches) != 1:
            raise ValueError(f"Ambiguous/missing local metadata for {window}")
        row = matches[0]
        if (row["proposed_role"] != "pilot_training" or row["eligible_metadata_candidate"] != "True"
                or row["exclusion_reasons"] or row["source_log"] in excluded):
            raise ValueError(f"Window is not an eligible training-side candidate: {window}")
        with sqlite3.connect(Path(row["path"]).as_uri() + "?mode=ro", uri=True) as db:
            records = db.execute(
                "SELECT i.filename_jpg, i.timestamp, e.timestamp FROM image i "
                "JOIN camera c ON i.camera_token=c.token "
                "JOIN ego_pose e ON i.ego_pose_token=e.token "
                "WHERE c.channel='CAM_F0'"
            ).fetchall()
        expected = {name: {"timestamp_us": int(ts), "ego_pose_timestamp_us": int(ego_ts)}
                    for name, ts, ego_ts in records}
        if not expected or len(expected) != len(records):
            raise ValueError(f"Missing/duplicate image and pose references: {window}")
        selected.append((part, window, row, expected))
    return selected


def download_one(output, part, window, row, expected):
    relative_archive = f"openscene-v1.1/openscene_sensor_trainval_camera/openscene_sensor_trainval_camera_{part}.tgz"
    url = f"https://huggingface.co/datasets/OpenDriveLab/OpenScene/resolve/{REVISION}/{relative_archive}?download=true"
    prefix = f"openscene-v1.1/sensor_blobs/trainval/{window}/CAM_F0"
    destination = output / "sensor_blobs" / window / "CAM_F0"
    destination.mkdir(parents=True, exist_ok=False)
    images = []
    finished = False
    dimensions = set()
    request = urllib.request.Request(url, headers={"Range": f"bytes=0-{COMPRESSED_CAP - 1}"})
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 206 or not response.headers.get("Content-Range", "").startswith("bytes 0-"):
            raise ValueError("Server did not honor the bounded prefix request")
        bounded = BoundedReader(response)
        with tarfile.open(fileobj=bounded, mode="r|gz") as archive:
            for member in archive:
                if member.name == prefix and member.isdir():
                    continue
                if not member.name.startswith(prefix + "/"):
                    if not images:
                        raise ValueError("Pinned archive no longer starts at the expected front camera")
                    finished = True
                    break
                name = member.name[len(prefix) + 1:]
                # Exact DB membership plus flat basename prevents paths escaping the destination.
                key = f"{window}/CAM_F0/{name}"
                if (Path(name).name != name or not name.endswith(".jpg") or key not in expected
                        or not member.isfile() or not 0 < member.size <= 8 * 1024**2):
                    raise ValueError(f"Unexpected camera member: {member.name}")
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("Missing image stream")
                payload = source.read(member.size + 1)
                if len(payload) != member.size:
                    raise ValueError("Truncated image")
                with Image.open(io.BytesIO(payload)) as image:
                    if image.width > 4096 or image.height > 4096:
                        raise ValueError("Unexpected camera dimensions")
                    image.load()
                    dimensions.add(image.size)
                with (destination / name).open("xb") as stream:
                    stream.write(payload)
                images.append({"filename": key, **expected[key], "bytes": len(payload),
                               "sha256": hashlib.sha256(payload).hexdigest()})
                if len(images) % 100 == 0:
                    print(f"part {part}: verified {len(images)} front images", flush=True)
        bytes_read = bounded.count
    if not finished or len(images) < 12:
        raise ValueError("Did not reach the end of a sufficiently long first-camera directory")
    images.sort(key=lambda image: image["timestamp_us"])
    times = [image["timestamp_us"] for image in images]
    if len(times) != len(set(times)):
        raise ValueError("Duplicate exposure timestamps")
    gaps = [b - a for a, b in zip(times, times[1:])]
    result = {"status": "downloaded_camera_directory_not_training_ready", "window": window,
              "city": row["city"], "source_log": row["source_log"], "date": row["date"],
              "proposed_role": row["proposed_role"], "metadata_database": row["path"],
              "source_url": url, "source_revision": REVISION, "compressed_bytes_read": bytes_read,
              "image_count": len(images), "image_bytes": sum(image["bytes"] for image in images),
              "dimensions": sorted(dimensions), "span_s": (times[-1] - times[0]) / 1e6,
              "min_gap_us": min(gaps), "max_gap_us": max(gaps),
              "gaps_over_600ms": sum(gap > 600_000 for gap in gaps),
              "complete_first_camera_directory": True, "full_archive_checksum_verified": False,
              "images": images}
    write_json(output / f"part-{part}-receipt.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("images", "source_url")}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true", help="Otherwise only check local metadata/splits")
    args = parser.parse_args()
    base = Path(__file__).resolve().parent / "artifacts/training-readiness-20260918"
    inventory, protected = base / "database-inventory.csv", base / "protected-splits.json"
    selected = preflight(inventory, protected)
    print(json.dumps({"windows": [item[1] for item in selected], "download": args.download,
                      "maximum_compressed_transfer_bytes": len(selected) * COMPRESSED_CAP}), flush=True)
    if not args.download:
        return
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "acquisition-plan.json", {
        "status": "acquisition_only_no_training", "revision": REVISION,
        "candidates": CANDIDATES, "inventory_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
        "protected_split_sha256": hashlib.sha256(protected.read_bytes()).hexdigest(),
        "training_eligibility": "candidate_under_local_exclusion_rules_not_organizer_certification",
        "maximum_compressed_transfer_bytes": len(selected) * COMPRESSED_CAP,
    })
    try:
        results = [download_one(args.output, *item) for item in selected]
        write_json(args.output / "summary.json", {
            "status": "camera_acquisition_passed_training_export_pending",
            "images": sum(r["image_count"] for r in results),
            "compressed_bytes_read": sum(r["compressed_bytes_read"] for r in results),
            "image_bytes": sum(r["image_bytes"] for r in results),
            "summed_window_span_s": sum(r["span_s"] for r in results),
            "windows": [{k: v for k, v in r.items() if k != "images"} for r in results],
        })
    except Exception as exc:
        write_json(args.output / "FAILED.json", {"error": str(exc), "partial_files_retained": True})
        raise


if __name__ == "__main__":
    main()
