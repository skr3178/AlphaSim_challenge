"""Freeze the user-approved real-data pilot; metadata only, never starts training.

The eight scenes were proposed before approval on 2026-09-19. Do not silently
replace unavailable scenes. This creates a separate, conditional pilot manifest;
the public evaluation manifest and the existing training-readiness audit remain
unchanged. Challenge training-data permission is deliberately unresolved here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "tools"))
from eval_common import asset_missing, load_manifest, sha256

PUBLIC_SHA256 = "a2a150d4eb139db0cbfa7d1cfa37a8eff701db34fff8264034c0433ab2f36b64"
APPROVED_SCENES = (
    "2021.09.09.14.18.22_veh-48_00322_00895-8659bfccd4195fb6",
    "2021.09.09.14.18.22_veh-48_00322_00895-4b721ff0b7025f21",
    "2021.09.16.15.47.30_veh-45_01199_01391-09cd7b3746d65a79",
    "2021.09.16.15.47.30_veh-45_01199_01391-bf896d504b4356c7",
    "2021.10.06.07.26.10_veh-52_00422_00728-fb1d534ccf82583f",
    "2021.10.06.07.26.10_veh-52_01245_02064-b031e4b0aea8528b",
    "2021.05.25.15.59.03_veh-30_00625_00855-5c34deba76605c7b",
    "2021.05.25.15.59.03_veh-30_00625_00855-247ba5f9646c5528",
)
PROTECTED_SUITES = (
    "py123d_validation", "py123d_validation_pool", "py123d_holdout",
)


def membership(manifest, selected):
    """Build whole-source-log exclusions, refusing any protected log overlap."""
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("Pilot must contain distinct scenes")
    if not set(selected) <= set(manifest["suites"]["py123d_development400"]):
        raise ValueError("Pilot scenes must belong to development400")
    logs = {manifest["scenes"][s]["source_log"] for s in selected}
    excluded = sorted(s for s, meta in manifest["scenes"].items()
                      if meta["source_log"] in logs)
    for name in PROTECTED_SUITES:
        protected = {manifest["scenes"][s]["source_log"]
                     for s in manifest["suites"][name]}
        if logs & protected:
            raise ValueError(f"Training log overlaps protected suite: {name}")
    return {
        "training_source_logs": sorted(logs),
        "excluded_scene_ids_for_candidate_evaluation": excluded,
        "protected_suites": {name: list(manifest["suites"][name])
                             for name in PROTECTED_SUITES},
    }


def prepare(output):
    if output.exists():
        raise ValueError(f"Refusing to replace pilot manifest: {output}")
    public_path = WORKSPACE / "evaluation/public-suite.json"
    if sha256(public_path) != PUBLIC_SHA256:
        raise ValueError("Public manifest differs from the approved proposal")
    manifest = load_manifest(public_path)
    groups = membership(manifest, APPROVED_SCENES)
    if len(groups["training_source_logs"]) != 4 or len(groups["excluded_scene_ids_for_candidate_evaluation"]) != 207:
        raise ValueError("Approved four-log / 207-scene scope changed")
    cities = Counter(manifest["scenes"][s]["city"] for s in APPROVED_SCENES)
    if cities != {"boston": 2, "pittsburgh": 2, "singapore": 2, "vegas": 2}:
        raise ValueError("Approved city balance changed")
    root = Path(manifest["data_root"])
    samples = []
    for scene in APPROVED_SCENES:
        missing = asset_missing(root, scene)
        if missing:
            raise ValueError(f"Approved scene has missing basic assets: {scene}: {missing}")
        meta = manifest["scenes"][scene]
        config = root / "navtest/configs" / f"{scene}.yaml"
        if sha256(config) != meta["config_sha256"]:
            raise ValueError(f"Scene config changed: {scene}")
        samples.append({"scene_id": scene, **meta,
                        "asset_root": str(root / "navtest/assets" / scene),
                        "config": str(config), "basic_assets_present": True})
    if sha256(public_path) != PUBLIC_SHA256:
        raise ValueError("Public manifest changed during preparation")
    result = {
        "schema_version": 1,
        "pilot_id": "cosmos3-real-driving-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "approved_split_pending_rules_and_implementation",
        "user_approval": {
            "date_local": "2026-09-19", "timezone": "Asia/Kolkata",
            "scope": "Eight real development400 scenes, frozen Cosmos backbone, at most 100 head optimizer steps; conditional on training-data rules and feature/label checks.",
            "synthetic_training_substitution_authorized": False,
        },
        "rules_gate": {
            "status": "unverified",
            "evidence": None,
            "requirement": "Confirm current challenge terms permit training on these public navtest scenes before data export, fitting or rendering for training.",
        },
        "public_manifest": str(public_path),
        "public_manifest_sha256": PUBLIC_SHA256,
        "selection": "Before approval: SHA256 rank with prefix cosmos-real-pilot-v1:20260919:, one development source log per city, two scenes per log; no outcome scores used.",
        "samples": samples,
        **groups,
        "training_scope": {
            "backbone_frozen": True, "trainable_component": "new waypoint head only",
            "max_optimizer_steps": 100, "full_evaluation": False, "submission": False,
            "full_backbone_finetuning": False,
        },
        "readiness": {
            "basic_scene_assets": "present; render compatibility not retested",
            "paired_training_samples": "not_exported",
            "causal_generator_feature_tap": "not_implemented_or_validated",
            "waypoint_head_and_training_loop": "not_implemented",
            "trained_checkpoint": None, "optimizer_steps_completed": 0,
        },
        "evaluation_policy": {
            "status": "recorded_overlay_not_integrated_into_existing_evaluator",
            "effective_for_any_candidate_fitted_on_this_pilot": True,
            "rule": "Exclude every scene from the four training source logs, not just the eight fitted clips. Historical scores remain unchanged; development400/full1485 averages are not independent validation for a fitted candidate.",
            "limits": "Source-log separation only, not date/geography/pretraining separation. Existing validation and holdout have no Singapore scenes.",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"path": str(output), "status": result["status"],
                      "training_scenes": len(samples), "training_logs": 4,
                      "candidate_evaluation_exclusions": 207,
                      "rules_verified": False, "training_started": False}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="New pilot JSON path; refuses replacement")
    args = parser.parse_args()
    prepare(args.output.resolve())
