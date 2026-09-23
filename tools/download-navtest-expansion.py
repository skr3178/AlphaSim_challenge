#!/usr/bin/env python3
"""Pinned, resumable asset staging only. Never starts AlpaSim or modifies old data.

prepare writes a new immutable plan from the locally cached HF catalog (whose
revision and LFS metadata were checked against the public API before this job).
run keeps archives, verifies their SHA-256, safely extracts only missing public
scenes, and records receipts. Invoke run via the detached launcher alongside it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import time

from eval_common import DEFAULT_DATA_ROOT, WORKSPACE, asset_missing, load_manifest, source_log

REPO = "OpenDriveLab/AlpasimChallenge2026_nuplan_track"
REVISION = "6b3569897bd9c4f999d8aa856bb4f9e4aaa96c3c"
MOUNT = Path("/media/skr/SeagateHub1")
DESTINATION = MOUNT / "alpasim-navtest-expansion-20260918"
CATALOG = MOUNT / f"alpasim-nuplan-track-hf/.cache/huggingface/trees/{REVISION}.json"
PARTS = (2, 3, 4, 5, 6, 8, 10, 11, 12, 13, 15)
RESERVE = 30 * 2**30


def now():
    return datetime.now(timezone.utc).isoformat()


def log(message):
    print(f"[{now()}] {message}", flush=True)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 2**20), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    tmp.replace(path)


def require_space(root, additional):
    free = shutil.disk_usage(root).free
    if free < additional + RESERVE:
        raise RuntimeError(f"Insufficient space: {free:,} free; need {additional:,} plus {RESERVE:,} reserve")


def prepare(path):
    if path.exists():
        raise ValueError(f"Refusing to overwrite plan: {path}")
    manifest_path = WORKSPACE / "evaluation/public-suite.json"
    manifest = load_manifest(manifest_path)
    missing = sorted(s for s in manifest["scenes"] if asset_missing(DEFAULT_DATA_ROOT, s))
    if len(missing) != 1085:
        raise ValueError(f"Inventory changed: expected 1085 missing scenes, found {len(missing)}; review scope")
    for scene, meta in manifest["scenes"].items():
        config = DEFAULT_DATA_ROOT / "navtest/configs" / f"{scene}.yaml"
        if digest(config) != meta["config_sha256"]:
            raise ValueError(f"Scene config changed: {scene}")
    catalog = json.loads(CATALOG.read_text())["files"]
    shards = []
    for part in PARTS:
        relative = f"MTGS_asset/navtest/assets/part{part:03d}.tar.gz"
        entry = catalog[relative]
        assert entry["size"] == entry["lfs_size"]
        shards.append({"name": Path(relative).name, "size": entry["size"],
                       "sha256": entry["lfs_sha256"],
                       "url": f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{relative}"})
    plan = {"schema_version": 1, "created_at_utc": now(), "repo": REPO, "revision": REVISION,
            "destination": str(DESTINATION), "required_mount": str(MOUNT),
            "old_data_root": str(DEFAULT_DATA_ROOT), "manifest": str(manifest_path),
            "manifest_sha256": digest(manifest_path), "catalog_sha256": digest(CATALOG),
            "downloader_sha256": digest(Path(__file__)),
            "shards": shards, "archive_bytes": sum(s["size"] for s in shards),
            "expanded_budget_bytes_estimate": 450_000_000_000,
            "keep_verified_archives": True, "missing_scene_ids": missing,
            "already_available_scenes": len(manifest["scenes"]) - len(missing),
            "skipped_historical_shards": ["part001", "part007", "part009", "part014"],
            "note": "Skipped shards follow previous staging records. Final coverage is verified by exact scene IDs, not assumed from shard counts."}
    if not MOUNT.is_mount():
        raise ValueError(f"External disk is not mounted: {MOUNT}")
    require_space(MOUNT, plan["archive_bytes"] + plan["expanded_budget_bytes_estimate"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(plan, stream, indent=2)
        stream.write("\n")
    log(f"Plan saved: {len(missing)} scenes; {len(shards)} shards; {plan['archive_bytes']:,} compressed bytes")


class Stager:
    def __init__(self, plan_path):
        self.plan_path = plan_path.resolve()
        self.plan = json.loads(plan_path.read_text())
        self.root = Path(self.plan["destination"])
        self.data = self.root / "data"
        self.state = {"pid": os.getpid(), "started_at_utc": now(), "status": "starting",
                      "plan_sha256": digest(plan_path), "completed_shards": []}

    def status(self, phase, **values):
        self.state.update(status=phase, updated_at_utc=now(), **values)
        save_json(self.root / "status.json", self.state)

    def initialize(self):
        if self.root != DESTINATION or Path(self.plan["required_mount"]) != MOUNT:
            raise ValueError("Unexpected destination/mount; review before using another disk")
        if not MOUNT.is_mount() or MOUNT.is_symlink():
            raise ValueError("Seagate is not mounted at the expected real mountpoint")
        if self.root.is_symlink():
            raise ValueError("Destination must not be a symlink")
        self.root.mkdir(exist_ok=True)
        marker = self.root / "plan.json"
        if marker.exists():
            if digest(marker) != digest(self.plan_path):
                raise ValueError("Destination belongs to another plan")
        else:
            if any(self.root.iterdir()):
                raise ValueError("Refusing to use an unmarked nonempty destination")
            with marker.open("xb") as stream:
                stream.write(self.plan_path.read_bytes())
        self.lock = (self.root / "job.lock").open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for name in ("archives", "receipts", "staging", "data/navtest/assets", "data/navtest/configs"):
            directory = self.root / name
            directory.mkdir(parents=True, exist_ok=True)
            if directory.resolve() != directory:
                raise ValueError(f"Unexpected symlink in destination: {directory}")
        manifest_path = Path(self.plan["manifest"])
        if digest(manifest_path) != self.plan["manifest_sha256"]:
            raise ValueError("Frozen scene manifest changed")
        self.manifest = load_manifest(manifest_path)
        for scene, meta in self.manifest["scenes"].items():
            src = Path(self.plan["old_data_root"]) / "navtest/configs" / f"{scene}.yaml"
            dst = self.data / "navtest/configs" / src.name
            if digest(src) != meta["config_sha256"]:
                raise ValueError(f"Source config changed: {scene}")
            if dst.exists():
                if digest(dst) != meta["config_sha256"]:
                    raise ValueError(f"Conflicting destination config: {scene}")
            else:
                with dst.open("xb") as stream:
                    stream.write(src.read_bytes())
        self.status("ready")

    def download(self, shard):
        target = self.root / "archives" / shard["name"]
        partial = target.with_suffix(target.suffix + ".part")
        if target.is_symlink() or partial.is_symlink():
            raise ValueError("Refusing symlink archive target")
        if not target.exists():
            for attempt in range(1, 21):
                current = partial.stat().st_size if partial.exists() else 0
                if current > shard["size"]:
                    raise ValueError(f"Oversized partial archive; preserved for inspection: {partial}")
                if current == shard["size"]:
                    break
                require_space(self.root, shard["size"] - current)
                log(f"DOWNLOAD {shard['name']}: attempt {attempt}; resume at {current:,}/{shard['size']:,} bytes")
                self.status("downloading", shard=shard["name"], shard_bytes=current,
                            shard_total_bytes=shard["size"], attempt=attempt)
                # A fresh resolver query avoids reusing an expired signed CDN URL.
                url = shard["url"] + f"?download=true&request_time={time.time_ns()}"
                command = ["curl", "--fail", "--location", "--silent", "--show-error",
                           "--connect-timeout", "30", "--max-time", "7200",
                           "--speed-limit", "1024", "--speed-time", "120",
                           "--continue-at", "-", "--output", str(partial), url]
                started = time.monotonic()
                proc = subprocess.Popen(command)
                try:
                    while proc.poll() is None:
                        try:
                            proc.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            size = partial.stat().st_size if partial.exists() else 0
                            speed = (size - current) / max(1, time.monotonic() - started)
                            self.status("downloading", shard_bytes=size, bytes_per_second=speed)
                            log(f"PROGRESS {shard['name']}: {size / 1e9:.3f}/{shard['size'] / 1e9:.3f} GB; {speed / 1e6:.2f} MB/s")
                            require_space(self.root, shard["size"] - size)
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                if proc.returncode == 0 and partial.stat().st_size == shard["size"]:
                    break
                if proc.returncode == 33:
                    raise RuntimeError("Server refused byte-range resume; partial archive preserved")
                if attempt == 20:
                    raise RuntimeError(f"Download retry budget exhausted: {shard['name']}; rerun to resume")
                log(f"RETRY {shard['name']}: curl exit {proc.returncode}; keeping partial bytes")
                time.sleep(min(300, 15 * attempt))
            candidate = partial
        else:
            candidate = target
        self.status("verifying_archive", shard=shard["name"])
        log(f"SHA256 {candidate.name}")
        if candidate.stat().st_size != shard["size"] or digest(candidate) != shard["sha256"]:
            raise ValueError(f"Archive verification failed; file preserved: {candidate}")
        if candidate != target:
            candidate.rename(target)
        return target

    def extract(self, archive, shard):
        self.status("extracting", shard=shard["name"])
        stage = self.root / "staging" / shard["name"].removesuffix(".tar.gz")
        stage.mkdir(exist_ok=True)
        selected = set(self.plan["missing_scene_ids"])
        files, all_scenes = {}, set()
        total = 0
        log(f"EXTRACT {archive.name}: selected public scenes only")
        with tarfile.open(archive, "r|gz") as tar:
            for member in tar:
                relative = safe_member(member)
                if relative is None:
                    continue
                scene, *components = relative.parts
                all_scenes.add(scene)
                if scene not in selected or member.isdir():
                    continue
                key = relative.as_posix()
                if key in files:
                    raise ValueError(f"Duplicate archive member: {key}")
                files[key] = member.size
                # A previous interrupted promotion may have already placed a
                # complete scene here. Its full member inventory is checked below.
                if (self.data / "navtest/assets" / scene).exists():
                    continue
                destination = stage / scene / Path(*components)
                if destination.resolve().is_relative_to(stage.resolve()) is False:
                    raise ValueError("Unsafe extraction destination")
                require_space(self.root, member.size)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temp = destination.with_name(destination.name + ".download-tmp")
                if temp.is_symlink() or destination.is_symlink():
                    raise ValueError("Unexpected symlink in staging")
                with tar.extractfile(member) as src, temp.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=2**20)
                if temp.stat().st_size != member.size:
                    raise ValueError(f"Incomplete member: {key}")
                temp.replace(destination)
                total += member.size
                if len(files) % 100 == 0:
                    log(f"EXTRACT {archive.name}: {len(files)} files inspected; {total / 1e9:.2f} GB written")
        grouped = {}
        for name, size in files.items():
            scene, relative = name.split("/", 1)
            grouped.setdefault(scene, {})[relative] = size
        for scene, members in sorted(grouped.items()):
            destination = self.data / "navtest/assets" / scene
            source = destination if destination.exists() else stage / scene
            verify_members(source, members)
            if source != destination:
                source.rename(destination)
            if asset_missing(self.data, scene):
                raise ValueError(f"Basic scene files missing after extraction: {scene}")
        receipt = {"completed_at_utc": now(), "archive": shard,
                   "scene_ids": sorted(grouped), "archive_scene_ids": sorted(all_scenes),
                   "selected_file_bytes": sum(files.values()), "files": files,
                   "archive_mtime_ns": archive.stat().st_mtime_ns,
                   "note": "Archive SHA-256 verified; selected member paths/types/sizes checked. No simulation or cache compatibility test."}
        save_json(self.root / "receipts" / (shard["name"] + ".json"), receipt)
        log(f"COMPLETE {shard['name']}: {len(grouped)} public scenes staged; {sum(files.values()) / 1e9:.2f} GB")

    def completed(self, shard):
        path = self.root / "receipts" / (shard["name"] + ".json")
        archive = self.root / "archives" / shard["name"]
        if not path.is_file():
            return False
        receipt = json.loads(path.read_text())
        if (receipt["archive"] != shard or not archive.is_file()
                or archive.stat().st_size != shard["size"]
                or archive.stat().st_mtime_ns != receipt["archive_mtime_ns"]):
            raise ValueError(f"Completed archive changed: {shard['name']}")
        for relative, size in receipt["files"].items():
            p = self.data / "navtest/assets" / relative
            if not p.is_file() or p.is_symlink() or p.stat().st_size != size:
                raise ValueError(f"Previously staged file missing/changed: {p}")
        return True

    def run(self):
        self.initialize()
        try:
            for shard in self.plan["shards"]:
                if self.completed(shard):
                    log(f"SKIP verified completed shard: {shard['name']}")
                else:
                    self.extract(self.download(shard), shard)
                self.state["completed_shards"].append(shard["name"])
                self.status("between_shards")
            missing = [s for s in self.plan["missing_scene_ids"] if asset_missing(self.data, s)]
            old_root = Path(self.plan["old_data_root"])
            union_missing = [s for s in self.manifest["scenes"]
                             if asset_missing(self.data, s) and asset_missing(old_root, s)]
            report = {"checked_at_utc": now(), "new_scene_count": len(self.plan["missing_scene_ids"]) - len(missing),
                      "new_missing_scene_ids": missing, "union_missing_scene_ids": union_missing,
                      "union_available": len(self.manifest["scenes"]) - len(union_missing),
                      "new_root": str(self.data), "old_root": str(old_root),
                      "note": "Coverage across TWO roots only; runtime root/mounts and cache compatibility remain separate work."}
            save_json(self.root / "coverage.json", report)
            if missing or union_missing:
                raise RuntimeError(f"Incomplete public coverage: {len(missing)} new scenes still missing; inspect coverage.json")
            self.status("complete", new_scenes=report["new_scene_count"], union_available=report["union_available"])
            log("ALL DONE: 1085 additional scenes staged; 1485 public scenes covered across old and new roots. No evaluation launched.")
        except BaseException as exc:
            self.status("failed", error=str(exc))
            raise


def safe_member(member):
    """Accept only regular files/directories in navtest/assets/<scene>/... ."""
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts or "\\" in member.name:
        raise ValueError(f"Unsafe archive path: {member.name}")
    if not (member.isdir() or member.isfile()):
        raise ValueError(f"Unsafe archive type: {member.name}")
    if path.parts in ((), ("navtest",), ("navtest", "assets")) and member.isdir():
        return None
    if len(path.parts) < 3 or path.parts[:2] != ("navtest", "assets"):
        raise ValueError(f"Unexpected archive path: {member.name}")
    source_log(path.parts[2])
    if len(path.parts) == 3 and not member.isdir():
        raise ValueError("Scene root must be a directory")
    return PurePosixPath(*path.parts[2:])


def verify_members(root, members):
    if root.is_symlink():
        raise ValueError("Scene directory must not be a symlink")
    for relative, size in members.items():
        path = root / relative
        if not path.is_file() or path.is_symlink() or path.stat().st_size != size:
            raise ValueError(f"Scene member incomplete: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.plan)
    else:
        Stager(args.plan).run()


if __name__ == "__main__":
    main()
