"""Read-only nuPlan metadata/media audit; writes new reports, never runs models.

SQLite databases use mode=ro and query_only. Archive inspection reads only the
ZIP central directory. No pickle/torch objects are deserialized. Coverage is
metadata coverage, not usable video unless matching image files are verified.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import zipfile

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "tools"))
from eval_common import asset_missing, load_manifest, sha256

SEAGATE = Path("/media/skr/SeagateHub1")
LEGACY = SEAGATE / "autoresearch/autoresearch-paper/paper/dataset"
DB_ROOTS = {
    "train_boston": LEGACY / "nuplan-extracted/data/cache/train_boston",
    "train_pittsburgh": SEAGATE / "nuplan_cities/pittsburgh/data/cache/train_pittsburgh",
    "train_singapore": SEAGATE / "nuplan_cities/singapore/data/cache/train_singapore",
    "official_val": SEAGATE / "nuplan_cities/val/data/cache/val",
    "mini_quarantine": LEGACY / "nuplan-extracted/data/cache/mini",
}
MEDIA_ROOTS = [SEAGATE / "nuplan_cities", SEAGATE / "nuplan_zips",
               LEGACY / "nuplan-extracted", LEGACY / "nuplan-v1.1"]
WINDOW_RE = re.compile(r"^(?P<source>\d{4}(?:\.\d{2}){5}_veh-\d+)_(?P<start>\d+)_(?P<end>\d+)$")
CITIES = {
    "us-nv-las-vegas-strip": "vegas", "las_vegas": "vegas",
    "us-ma-boston": "boston", "boston": "boston",
    "us-pa-pittsburgh-hazelwood": "pittsburgh", "pittsburgh": "pittsburgh",
    "sg-one-north": "singapore", "singapore": "singapore",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def window_id(stem):
    match = WINDOW_RE.fullmatch(stem)
    if match is None:
        raise ValueError(f"Not a nuPlan recording window: {stem}")
    return match["source"], int(match["start"]), int(match["end"])


def union_duration(intervals):
    """Total interval length without double-counting overlapping recordings."""
    total = 0
    end = None
    for start, stop in sorted(intervals):
        if stop < start:
            raise ValueError("Reversed interval")
        total += max(0, stop - max(start, end if end is not None else start))
        end = max(stop, end if end is not None else stop)
    return total


def metadata_hours(rows, timestamp=False):
    groups = defaultdict(list)
    for row in rows:
        if timestamp:
            if row.get("front_first_us") is None:
                continue
            start, end = row["front_first_us"] / 1e6, row["front_last_us"] / 1e6
        else:
            start, end = row["window_start_s"], row["window_end_s"]
        groups[row["source_log"]].append((start, end))
    return sum(union_duration(v) for v in groups.values()) / 3600


def classify(row, protected_logs, protected_dates, val_logs, mini_logs):
    reasons = []
    if not row["collection"].startswith("train_"):
        reasons.append("official_val" if row["collection"] == "official_val" else "mini_quarantine")
    if row["source_log"] in protected_logs:
        reasons.append("public_navtest_source_log")
    if (row["city"], row["date"]) in protected_dates:
        reasons.append("public_navtest_city_date")
    if row["source_log"] in val_logs:
        reasons.append("official_val_source_log")
    if row["source_log"] in mini_logs:
        reasons.append("mini_source_log_quarantine")
    if row.get("error"):
        reasons.append("metadata_audit_error")
    return reasons


def media_inventory(roots):
    image_index = defaultdict(list)
    summary = []
    for root in roots:
        counts, examples, errors = Counter(), [], []
        def onerror(error):
            errors.append(str(error))
        for base, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__"}]
            for name in files:
                path = Path(base) / name
                suffix = path.suffix.lower()
                if suffix in IMAGE_SUFFIXES or suffix in {".mp4", ".mkv", ".zip", ".tar", ".gz"}:
                    counts[suffix] += 1
                    if len(examples) < 8:
                        examples.append(str(path))
                # nuPlan image filename is recording_window/CAM_*/token.jpg.
                if suffix in IMAGE_SUFFIXES and path.parent.name.startswith("CAM_"):
                    image_index["/".join(path.parts[-3:])].append(str(path))
        summary.append({"root": str(root), "exists": root.is_dir(), "counts": dict(counts),
                        "examples": examples, "errors": errors,
                        "symlink_policy": "Directory symlinks not followed; database roots are explicit."})
    return image_index, summary


def inspect_db(path, collection, image_index):
    source, start, end = window_id(path.stem)
    stat = path.stat()
    row = {"collection": collection, "path": str(path), "recording_window": path.stem,
           "source_log": source, "date": source[:10].replace(".", "-"),
           "window_start_s": start, "window_end_s": end,
           "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "error": ""}
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA cache_size=-2048")
        log = conn.execute("SELECT logfile,location,date FROM log").fetchall()
        if len(log) != 1 or log[0][0] != path.stem:
            raise ValueError(f"Log identity mismatch in {path}")
        row["city"] = CITIES.get(log[0][1], log[0][1])
        if log[0][2] != row["date"]:
            raise ValueError(f"Log date mismatch in {path}")
        cameras = conn.execute("SELECT channel,width,height,translation IS NOT NULL,rotation IS NOT NULL,intrinsic IS NOT NULL FROM camera").fetchall()
        row["camera_channels"] = ";".join(sorted(c[0] for c in cameras))
        front = [c for c in cameras if c[0] == "CAM_F0"]
        row["front_calibration_blobs_present"] = bool(front and all(front[0][3:]))
        row["front_resolution"] = f"{front[0][1]}x{front[0][2]}" if front else ""
        query = "FROM image WHERE camera_token=(SELECT token FROM camera WHERE channel='CAM_F0')"
        count, first, last = conn.execute("SELECT COUNT(*),MIN(timestamp),MAX(timestamp) " + query).fetchone()
        row.update(front_image_references=count, front_first_us=first, front_last_us=last)
        row["front_reference_span_hours"] = (last-first)/3.6e9 if first is not None else 0
        row["all_camera_image_references"] = conn.execute("SELECT COUNT(*) FROM image").fetchone()[0]
        sample = conn.execute("SELECT filename_jpg " + query + " LIMIT 1").fetchone()
        row["example_front_image"] = sample[0] if sample else ""
        scene_count, route_count = conn.execute("SELECT COUNT(*),SUM(roadblock_ids IS NOT NULL AND length(roadblock_ids)>0) FROM scene").fetchone()
        row.update(scene_records=scene_count, scenes_with_roadblock_ids=route_count or 0)
        row["ego_state_columns_present"] = all(
            key in {r[1] for r in conn.execute("PRAGMA table_info(ego_pose)")}
            for key in ("timestamp", "x", "y", "z", "qw", "qx", "qy", "qz", "vx", "vy", "angular_rate_z")
        )
        # If no indexed files exist for this recording, every DB image reference
        # is missing within the audited media roots. Do not issue millions of
        # redundant filesystem stats. Any future nonempty match needs a deeper
        # timestamp/decoding/label-integrity pass before certifying usable hours.
        matching_keys = [k for k in image_index if k.startswith(path.stem + "/CAM_F0/")]
        present = []
        if matching_keys:
            for filename, stamp in conn.execute("SELECT filename_jpg,timestamp " + query):
                if any(Path(p).is_file() and Path(p).stat().st_size > 0 for p in image_index.get(filename, [])):
                    present.append(stamp)
        row["front_image_files_matched"] = len(present)
        row["missing_front_image_files"] = count - len(present)
        row["verified_usable_footage_hours"] = 0.0
        row["footage_status"] = "missing_front_images" if not present else "matched_files_need_decode_and_alignment_validation"
    return row


def write_csv(path, rows):
    columns = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    manifest_path = WORKSPACE / "evaluation/public-suite.json"
    manifest_hash = sha256(manifest_path)
    manifest = load_manifest(manifest_path)
    public_logs = {m["source_log"] for m in manifest["scenes"].values()}
    public_dates = {(m["city"], m["date"].replace(".", "-")) for m in manifest["scenes"].values()}
    paths = {name: sorted(root.glob("*.db")) for name, root in DB_ROOTS.items()}
    val_logs = {window_id(p.stem)[0] for p in paths["official_val"]}
    mini_logs = {window_id(p.stem)[0] for p in paths["mini_quarantine"]}
    image_index, media = media_inventory(MEDIA_ROOTS)
    print(f"Media index: {len(image_index)} nuPlan image keys; {sum(map(len, paths.values()))} databases", flush=True)
    rows, start_clock = [], time.monotonic()
    progress_path = output / "progress.json"
    for collection, members in paths.items():
        for path in members:
            try:
                row = inspect_db(path, collection, image_index)
            except Exception as exc:
                source, start, end = window_id(path.stem)
                row = {"collection": collection, "path": str(path), "recording_window": path.stem,
                       "source_log": source, "date": source[:10].replace(".", "-"),
                       "window_start_s": start, "window_end_s": end, "city": "unknown", "error": repr(exc)}
            row["exclusion_reasons"] = ";".join(classify(row, public_logs, public_dates, val_logs, mini_logs))
            row["eligible_metadata_candidate"] = not row["exclusion_reasons"]
            rows.append(row)
            if len(rows) % 100 == 0:
                progress = {"completed": len(rows), "total": sum(map(len, paths.values())), "collection": collection,
                            "elapsed_s": round(time.monotonic()-start_clock, 2)}
                progress_path.write_text(json.dumps(progress, indent=2) + "\n")
                print(json.dumps(progress), flush=True)

    archive_path = SEAGATE / "nuplan_zips/nuplan-v1.1_train_vegas_5.zip"
    archive_rows = []
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        for member in infos:
            if Path(member.filename).suffix == ".db":
                stem = Path(member.filename).stem
                source, start, end = window_id(stem)
                row = {"collection": "train_vegas_5_archive_only", "archive": str(archive_path),
                       "member": member.filename, "recording_window": stem, "source_log": source,
                       "date": source[:10].replace(".", "-"), "city": "vegas",
                       "city_basis": "archive name, not queried database", "window_start_s": start, "window_end_s": end,
                       "uncompressed_bytes": member.file_size, "compressed_bytes": member.compress_size, "zip_crc": member.CRC}
                row["exclusion_reasons"] = ";".join(classify(row, public_logs, public_dates, val_logs, mini_logs))
                row["eligible_metadata_candidate"] = not row["exclusion_reasons"]
                archive_rows.append(row)
        archive_info = {"path": str(archive_path), "bytes": archive_path.stat().st_size,
                        "members": len(infos), "extension_counts": dict(Counter(Path(i.filename).suffix for i in infos)),
                        "uncompressed_bytes": sum(i.file_size for i in infos),
                        "integrity": "Central-directory read only, not full CRC/decompression verification"}

    all_rows = rows + archive_rows
    groups = defaultdict(list)
    for row in all_rows:
        groups[row["collection"]].append(row)
    summary = {}
    for name, group in groups.items():
        eligible = [r for r in group if r["eligible_metadata_candidate"]]
        summary[name] = {
            "database_windows": len(group), "source_logs": len({r["source_log"] for r in group}),
            "dates": len({r["date"] for r in group}), "cities": dict(Counter(r["city"] for r in group)),
            "nominal_recording_hours_union": metadata_hours(group),
            "front_reference_span_hours_union": metadata_hours(group, timestamp=True) if name in paths else None,
            "front_image_references": sum(r.get("front_image_references", 0) for r in group) if name in paths else None,
            "all_camera_image_references": sum(r.get("all_camera_image_references", 0) for r in group) if name in paths else None,
            "front_image_files_matched": sum(r.get("front_image_files_matched", 0) for r in group),
            "verified_usable_footage_hours": 0,
            "eligible_metadata_windows": len(eligible), "eligible_nominal_hours_union": metadata_hours(eligible),
            "eligible_source_logs": len({r["source_log"] for r in eligible}),
            "excluded_by_reason": dict(Counter(reason for r in group for reason in r["exclusion_reasons"].split(";") if reason)),
            "audit_errors": sum(bool(r.get("error")) for r in group),
        }

    # Proposed, never activated: 20% of eligible dates per city for model
    # selection, grouped before any fitting. Keep every recording of one
    # source log/date together. Archive-only rows cannot become train-ready.
    eligible_dates = defaultdict(set)
    for row in all_rows:
        if row["eligible_metadata_candidate"]:
            eligible_dates[row["city"]].add(row["date"])
    pilot_validation_dates = set()
    for city, dates in eligible_dates.items():
        ranked = sorted(dates, key=lambda d: hashlib.sha256(f"cosmos3-readiness-v1:20260918:{city}:{d}".encode()).hexdigest())
        n = max(1, round(.2*len(ranked))) if len(ranked) > 1 else 0
        pilot_validation_dates.update((city, d) for d in ranked[:n])
    for row in all_rows:
        row["proposed_role"] = ("excluded" if not row["eligible_metadata_candidate"] else
                                "pilot_validation" if (row["city"], row["date"]) in pilot_validation_dates else "pilot_training")
    split = {
        "status": "proposed_metadata_only_not_activated", "seed": 20260918,
        "method": "Hash-rank whole eligible city/date groups; round 20% per city for pilot validation, minimum one when >=2 dates; remainder pilot training.",
        "public_manifest": str(manifest_path), "public_manifest_sha256": manifest_hash,
        "protected_public_source_logs": sorted(public_logs),
        "protected_public_city_dates": [list(x) for x in sorted(public_dates)],
        "protected_official_val_source_logs": sorted(val_logs),
        "quarantined_mini_source_logs": sorted(mini_logs),
        "proposed_pilot_validation_city_dates": [list(x) for x in sorted(pilot_validation_dates)],
        "roles": {role: {"windows": sum(r["proposed_role"] == role for r in all_rows),
                          "source_logs": sorted({r["source_log"] for r in all_rows if r["proposed_role"] == role}),
                          "nominal_recording_hours_union": metadata_hours([r for r in all_rows if r["proposed_role"] == role])}
                  for role in ("pilot_training", "pilot_validation", "excluded")},
        "caution": "No image-ready training windows; proposals include archive-only metadata. Existing public suite unchanged. Prior model pretraining exposure and geographic overlap not certified.",
    }
    assert not set(split["roles"]["pilot_training"]["source_logs"]) & set(split["roles"]["pilot_validation"]["source_logs"])
    for role in ("pilot_training", "pilot_validation"):
        assert not set(split["roles"][role]["source_logs"]) & (public_logs | val_logs | mini_logs)

    eval_roots = {"old": Path(manifest["data_root"]), "seagate_expansion": SEAGATE / "alpasim-navtest-expansion-20260918/data"}
    available = {key: {s for s in manifest["scenes"] if not asset_missing(root, s)} for key, root in eval_roots.items()}
    union = set.union(*available.values())
    eval_status = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
                   "roots": {k: str(v) for k, v in eval_roots.items()},
                   "basic_assets_available_by_root": {k: len(v) for k, v in available.items()},
                   "union_basic_assets_available": len(union), "missing_scenes": sorted(set(manifest["scenes"])-union),
                   "not_certified": "Only config + video_scene_dict + road_height_map + background ckpt presence; no render, semantic integrity or assembled combined runtime root check.",
                   "suites": {name: {"scenes": len(ids), "source_logs": len({manifest['scenes'][s]['source_log'] for s in ids}),
                                     "union_basic_assets_available": len(set(ids)&union)} for name, ids in manifest["suites"].items()}}
    status_path = SEAGATE / "alpasim-navtest-expansion-20260918/status.json"
    if status_path.is_file():
        eval_status["downloader_status_snapshot"] = json.loads(status_path.read_text())

    assert sha256(manifest_path) == manifest_hash, "Public manifest changed during audit"
    write_csv(output / "database-inventory.csv", rows)
    write_csv(output / "archive-inventory.csv", archive_rows)
    write_csv(output / "missing-front-assets.csv", [
        {k: row.get(k) for k in ("collection", "recording_window", "source_log", "city", "date", "front_image_references", "front_image_files_matched", "missing_front_image_files", "example_front_image", "proposed_role")}
        for row in rows
    ])
    for name, value in (("protected-splits.json", split), ("evaluation-assets-snapshot.json", eval_status)):
        (output / name).write_text(json.dumps(value, indent=2) + "\n")
    report = {"started_at_utc": started, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
              "method": "Read-only SQLite metadata, explicit-root media inventory, ZIP central directory; no inference, training, evaluation, download, extraction or unsafe deserialization.",
              "script_sha256": sha256(Path(__file__)), "public_manifest_sha256_before_and_after": manifest_hash,
              "database_roots": {k: str(v) for k, v in DB_ROOTS.items()}, "media_search": media,
              "archive": archive_info, "collections": summary,
              "totals": {"extracted_databases": len(rows), "archive_only_databases": len(archive_rows),
                         "front_image_references": sum(r.get("front_image_references", 0) for r in rows),
                         "front_image_files_matched": sum(r.get("front_image_files_matched", 0) for r in rows),
                         "verified_usable_footage_hours": 0,
                         "audit_errors": sum(bool(r.get("error")) for r in rows)},
              "coverage_definition": "Metadata span uses per-source-log union of CAM_F0 timestamp ranges (max-min); internal gaps and history/future margins are not removed. Archive hours use filename window union only. Neither is usable video hours.",
              "limits": ["No global filesystem absence claim: only listed media roots were indexed.",
                         "No archive payload decompression/CRC verification; existing raw databases were not full-file checksummed.",
                         "Calibration blobs checked for presence, not deserialized; map/route semantics and state values not certified.",
                         "Known public/evaluation sources protected; organizer private selection and pretrained-model exposure are unknown."]}
    (output / "audit-summary.json").write_text(json.dumps(report, indent=2) + "\n")
    progress_path.write_text(json.dumps({"status": "complete", "databases": len(rows)}, indent=2) + "\n")
    print(json.dumps({"collections": summary, "totals": report["totals"], "output": str(output)}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory; existing paths are refused")
    run(parser.parse_args().output.resolve())
