"""Pinned ten-train/nine-unseen-log local feature-ablation scope; no model calls."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from cosmos3.training.contracts import checked_path, file_hash, load_pilot, write_json
from cosmos3.training.state_adapter import STATE_RECIPE

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "cosmos3/pilots/local-head10-v1/manifest.json"
PILOT = ROOT / "cosmos3/pilots/local-ablation-v1/manifest.json"
RUN = ROOT / "cosmos3/artifacts/local-ablation-v1"
ASL_ROOT = Path("/home/skr/alpasim-challenge/alpasim/runs/confirm400-mup-g100/rollouts")
ABLATION_ID = "cosmos3-local-ablation-v1"
PARENT_SHA = "1ae99e1644dc5bc0e7317333bfe51c989e49a2d968cb450c1d7b58d9599c3f4d"


def heldout_selection(public, training_logs):
    groups = {}
    for scene in public["suites"]["py123d_development400"]:
        log = public["scenes"][scene]["source_log"]
        if log not in training_logs:
            groups.setdefault(log, []).append(scene)
    if len(groups) != 9:
        raise ValueError("Expected nine development source logs unseen by this head")
    return [
        min(
            groups[log],
            key=lambda s: hashlib.sha256((ABLATION_ID + ":" + s).encode()).hexdigest(),
        )
        for log in sorted(groups)
    ]


def proposal(authorization):
    if file_hash(PARENT) != PARENT_SHA:
        raise ValueError("Original local pilot changed")
    parent = load_pilot(PARENT)
    public = json.loads(Path(parent["public_manifest"]).read_text())
    evaluation = heldout_selection(public, set(parent["training_source_logs"]))
    result = deepcopy(parent)
    result.update(
        pilot_id=ABLATION_ID,
        parent_manifest=str(PARENT),
        parent_manifest_sha256=PARENT_SHA,
        status="authorized_local_matched_ablation_not_run",
        selection="Original ten training scenes; one SHA256-ranked scene per remaining development source log; no outcomes used",
        training_scene_ids=[r["scene_id"] for r in parent["samples"]],
        evaluation_scene_ids=evaluation,
        evaluation_source_logs=sorted(
            {public["scenes"][s]["source_log"] for s in evaluation}
        ),
        ego_state_recipe=STATE_RECIPE,
        ablation={
            "arms": ["cosmos", "state_route_only"],
            "seed": 20260919,
            "optimizer_steps_per_arm": 100,
            "total_optimizer_steps": 200,
            "batch_size": 10,
            "learning_rate": 0.0003,
            "same_initial_weights": True,
            "visual_control": "all-zero features with identical head architecture and history/state/route",
            "evaluation": "one fixed post-training open-loop check; never optimizer or checkpoint selection input",
        },
        local_authorization={
            "scope": "local_only_corrected_state_matched_ablation",
            "file": authorization.name,
            "sha256": file_hash(authorization),
        },
        user_approval={
            "request": "ok lets do that",
            "scope": "Correct state inputs, matched with/without Cosmos comparison, unseen source logs; local only",
        },
    )
    result["training_scope"]["max_evaluation_samples"] = 9
    result["training_scope"]["max_optimizer_steps_total"] = 200
    for scene in evaluation:
        meta = public["scenes"][scene]
        result["samples"].append(
            {
                "scene_id": scene,
                **meta,
                "config": str(
                    Path(public["data_root"]) / "navtest/configs" / f"{scene}.yaml"
                ),
                "asset_root": str(Path(public["data_root"]) / "navtest/assets" / scene),
            }
        )
    result["evaluation_policy"][
        "rule"
    ] = "Original four training logs/207 scenes excluded. Nine additional development logs are evaluation-only, not sealed holdout. No training on evaluation samples, no selection using their losses. No submission."
    return result


def validate(path, value):
    path = Path(path).resolve()
    approval = value.get("local_authorization", {})
    evidence = checked_path(path.parent, approval["file"], approval["sha256"])
    expected = proposal(evidence)
    # The entire fixed protocol, splits and authorization must match, not just counts.
    if value != expected:
        raise ValueError("Ablation scope, split, state recipe or budget changed")
    train = set(value["training_source_logs"])
    test = set(value["evaluation_source_logs"])
    if (
        train & test
        or len(value["training_scene_ids"]) != 10
        or len(value["evaluation_scene_ids"]) != 9
    ):
        raise ValueError("Training/evaluation source logs overlap or counts changed")
    return value


def main():
    if PILOT.exists():
        raise ValueError("Refusing to overwrite fixed ablation scope")
    value = proposal(PILOT.parent / "AUTHORIZATION.md")
    validate(PILOT, value)
    for row in value["samples"]:
        if file_hash(row["config"]) != row["config_sha256"]:
            raise ValueError("Selected scene config changed")
        if not list((ASL_ROOT / row["scene_id"]).glob("*/rollout.asl")):
            raise ValueError(
                f"Missing pinned ASL; do not substitute: {row['scene_id']}"
            )
    write_json(PILOT, value)
    print(
        json.dumps(
            {
                "manifest": str(PILOT),
                "train": 10,
                "evaluation": 9,
                "source_log_overlap": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
