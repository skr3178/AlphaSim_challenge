#!/usr/bin/env python3
"""Freeze metadata-only public validation splits. No downloads or evaluations.

Splits depend on scene IDs, authoritative city metadata and previous exposure,
never on scores or asset availability. Rebuilding a frozen suite is refused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from eval_common import (DEFAULT_DATA_ROOT, DEFAULT_RUNS_ROOT, WORKSPACE, CITY_NAMES,
                         asset_missing, load_yaml, recording_window, scene_ids, sha256, source_log)


def ordered(values, seed: int, salt: str):
    return sorted(values, key=lambda v: hashlib.sha256(f"{seed}:{salt}:{v}".encode()).hexdigest())


def build_manifest(public: Path, data_root: Path, summaries: list[Path], seed: int, validation_size: int) -> dict:
    ids = scene_ids(public)
    seen = set()
    history = []
    for path in sorted(summaries):
        data = json.loads(path.read_text())
        rows = data.get("rollouts", [])
        if not isinstance(rows, list):
            raise ValueError(f"{path}: invalid rollouts")
        seen.update(r["clipgt_id"] for r in rows if r.get("clipgt_id"))
        history.append({"path": str(path), "sha256": sha256(path), "rollouts": len(rows)})
    if not seen:
        raise ValueError("No historical exposure found; provide the previous run summaries")
    seen_logs = {source_log(s) for s in seen}
    scenes = {}
    logs_by_city = defaultdict(set)
    for scene in ids:
        path = data_root / "navtest/configs" / f"{scene}.yaml"
        cfg = load_yaml(path)
        window = recording_window(scene)
        if cfg.get("central_log") != window:
            raise ValueError(f"{path}: central_log does not match scene identity")
        if not cfg.get("city"):
            raise ValueError(f"{path}: missing authoritative city")
        log = source_log(scene)
        city = CITY_NAMES.get(cfg["city"], cfg["city"])
        scenes[scene] = {"source_log": log, "recording_window": window, "date": log[:10],
                         "city": city, "config_sha256": sha256(path),
                         "previously_evaluated": scene in seen, "source_log_exposed": log in seen_logs}
        if log not in seen_logs:
            logs_by_city[city].add(log)
    # Reserve whole source logs per city. No clip from a validation log enters
    # the final holdout, even if not selected for the compact validation suite.
    validation_logs, holdout_logs = set(), set()
    for city, logs in sorted(logs_by_city.items()):
        ranked = ordered(logs, seed, f"logs:{city}")
        n = max(1, min(len(ranked) - 1, round(len(ranked) * .6))) if len(ranked) > 1 else 1
        validation_logs.update(ranked[:n])
        holdout_logs.update(ranked[n:])
    per_log = {log: ordered([s for s in ids if scenes[s]["source_log"] == log], seed, "clips")
               for log in validation_logs}
    validation = []
    # Log-balanced round robin, explicitly not an official city-distribution proxy.
    while len(validation) < validation_size and any(per_log.values()):
        for log in ordered(per_log, seed, "round-robin"):
            if per_log[log] and len(validation) < validation_size:
                validation.append(per_log[log].pop())
    suites = {
        "py123d_development400": sorted(set(ids) & seen),
        "py123d_validation": sorted(validation),
        "py123d_validation_pool": sorted(s for s in ids if scenes[s]["source_log"] in validation_logs),
        "py123d_holdout": sorted(s for s in ids if scenes[s]["source_log"] in holdout_logs),
        "py123d_seen_log_extension": sorted(s for s in ids if s not in seen and scenes[s]["source_log"] in seen_logs),
        "py123d_public_full": sorted(ids),
    }
    all_cities = {m["city"] for m in scenes.values()}
    absent = sorted(all_cities - set(logs_by_city))
    return {"schema_version": 1, "seed": seed, "public_source": str(public),
            "public_sha256": sha256(public), "data_root": str(data_root), "exposure_sources": history,
            "selection": "60% of unused logs per city for validation; remainder sealed holdout; log-balanced validation clips",
            "limitations": ["Public suite only; no estimate of private PCS or rank.",
                            "Asset presence does not change split membership.",
                            f"No unseen source logs in: {', '.join(absent) or 'none'}.",
                            "Asset preflight checks required files, not renderer/cache semantic compatibility."],
            "scenes": scenes, "suites": suites}


def availability(manifest: dict, root: Path) -> dict:
    missing = {scene: asset_missing(root, scene) for scene in manifest["scenes"]}
    return {"data_root": str(root), "missing": {s: files for s, files in missing.items() if files},
            "suites": {name: {"scenes": len(ids), "available": sum(not missing[s] for s in ids),
                              "source_logs": len({manifest['scenes'][s]['source_log'] for s in ids}),
                              "cities": dict(Counter(manifest['scenes'][s]['city'] for s in ids))}
                       for name, ids in manifest["suites"].items()}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-scenes", type=Path, default=Path("/home/skr/alpasim-challenge/alpasim/src/wizard/configs/nuplan_scenes/navtest_full.yaml"))
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--seed", type=int, default=20260911)
    parser.add_argument("--validation-size", type=int, default=150)
    parser.add_argument("--output", type=Path, default=WORKSPACE / "evaluation")
    parser.add_argument("--write", action="store_true", help="write new immutable manifest/groups; never starts a run")
    args = parser.parse_args()
    if args.validation_size < 1:
        parser.error("--validation-size must be positive")
    try:
        manifest_path = args.output / "public-suite.json"
        if manifest_path.exists():
            if args.write:
                raise ValueError("Frozen manifest exists. Use another output directory for a deliberate new version.")
            manifest = json.loads(manifest_path.read_text())
        else:
            manifest = build_manifest(args.public_scenes, args.data_root,
                                      list(args.runs_root.glob("*/aggregate/results-summary.json")),
                                      args.seed, args.validation_size)
        assets = availability(manifest, args.data_root)
        if args.write:
            outputs = {manifest_path: json.dumps(manifest, indent=2) + "\n",
                       args.output / "asset-inventory.json": json.dumps(assets, indent=2) + "\n"}
            for name, ids in manifest["suites"].items():
                if ids:
                    outputs[args.output / "configs/nuplan_scenes" / f"{name}.yaml"] = (
                        "# @package _global_\n# Frozen public split; see evaluation/public-suite.json\n"
                        "scenes:\n  test_suite_id: null\n  limit_to_first_n: 0\n  scene_ids:\n" +
                        "".join(f"    - {s}\n" for s in ids))
            if any(p.exists() for p in outputs):
                raise ValueError("Refusing to overwrite existing suite files")
            for path, content in outputs.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("x") as stream:
                    stream.write(content)
        print(json.dumps({"suites": assets["suites"], "missing_assets_scenes": len(assets["missing"]),
                          "limitations": manifest["limitations"], "written": args.write}, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
