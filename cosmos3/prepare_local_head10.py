"""Prepare only the explicitly approved local-only ten-example head-test scope."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from cosmos3.prepare_real_pilot import APPROVED_SCENES, membership
from cosmos3.probe_features10 import candidate_scenes
from cosmos3.training.contracts import (
    LOCAL_EXTRA_SCENES,
    LOCAL_PILOT_ID,
    file_hash,
    load_pilot,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "cosmos3/pilots/real-driving-v1/manifest.json"
OUTPUT = ROOT / "cosmos3/pilots/local-head10-v1/manifest.json"


def proposal(approval_file):
    parent = load_pilot(PARENT)
    selected, public = candidate_scenes()
    if set(selected) != set(APPROVED_SCENES) | set(LOCAL_EXTRA_SCENES):
        raise ValueError("Ten-image probe selection changed")
    result = deepcopy(parent)
    result.update(
        pilot_id=LOCAL_PILOT_ID,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        status="local_only_authorized_not_trained",
        parent_manifest=str(PARENT),
        parent_manifest_sha256=file_hash(PARENT),
        competition_training_permission="unverified",
        submission_allowed=False,
        user_approval={
            "date_local": "2026-09-19",
            "scope": "Local-only frozen-Cosmos head test; ten samples; at most 100 updates; no submissions",
            "synthetic_training_substitution_authorized": False,
        },
        local_authorization={
            "scope": "local_only_frozen_cosmos_head_test",
            "file": approval_file.name,
            "sha256": file_hash(approval_file),
        },
        selection="Original eight plus two deterministic same-source-log examples, fixed by the ten-image feature probe before fitting; no outcome scores used",
        **membership(public, selected),
    )
    result.pop("rules_gate", None)
    result["training_scope"]["max_samples"] = 10
    root = Path(public["data_root"])
    result["samples"] = []
    for scene in selected:
        config = root / "navtest/configs" / f"{scene}.yaml"
        if file_hash(config) != public["scenes"][scene]["config_sha256"]:
            raise ValueError("Scene config changed")
        result["samples"].append(
            {
                "scene_id": scene,
                **public["scenes"][scene],
                "config": str(config),
                "asset_root": str(root / "navtest/assets" / scene),
            }
        )
    result["readiness"] = {
        "paired_training_samples": "not_exported",
        "frozen_generator_feature_probe": "ten observed images passed; not a learnability result",
        "trained_checkpoint": None,
        "optimizer_steps_completed": 0,
    }
    result["evaluation_policy"][
        "rule"
    ] = "Local-only fitted head excluded from submissions. Exclude all 207 source-log scenes from any future independent assessment of a derived model."
    return result


def main():
    if OUTPUT.exists():
        raise ValueError("Refusing to overwrite the local pilot manifest")
    value = proposal(OUTPUT.parent / "AUTHORIZATION.md")
    write_json(OUTPUT, value)
    load_pilot(OUTPUT)
    print(f"Prepared {OUTPUT}: ten samples, head only, local only, at most 100 updates")


if __name__ == "__main__":
    main()
