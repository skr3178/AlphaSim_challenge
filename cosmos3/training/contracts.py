"""Versioned, causal sample contract and local provenance checks. No model imports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

CONTRACT = "cosmos-driving-v1"
HISTORY_US = (-1_000_000, -500_000, 0)
FUTURE_US = np.arange(1, 41, dtype=np.int64) * 100_000
MAX_ROUTE = 32
LOCAL_PILOT_ID = "cosmos3-local-head10-v1"
LOCAL_EXTRA_SCENES = (
    "2021.09.16.15.47.30_veh-45_01199_01391-0481cf2b75f1532f",
    "2021.10.06.07.26.10_veh-52_01245_02064-115d3d7bdadf52f8",
)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_hash(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def checked_path(root, relative, expected_hash=None):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Missing file or path escapes dataset: {relative}")
    if expected_hash is not None and file_hash(path) != expected_hash:
        raise ValueError(f"File hash mismatch: {relative}")
    return path


def load_pilot(path):
    from ..prepare_real_pilot import APPROVED_SCENES, PROTECTED_SUITES, PUBLIC_SHA256

    path = Path(path).resolve()
    value = json.loads(path.read_text())
    if value.get("pilot_id") == "cosmos3-local-ablation-v1":
        from ..ablation_scope import validate

        return validate(path, value)
    if value.get("schema_version") != 1 or value.get("pilot_id") not in (
        "cosmos3-real-driving-v1",
        LOCAL_PILOT_ID,
    ):
        raise ValueError("Unsupported pilot manifest")
    public = Path(value["public_manifest"])
    if (
        file_hash(public) != value["public_manifest_sha256"]
        or value["public_manifest_sha256"] != PUBLIC_SHA256
    ):
        raise ValueError("Public manifest changed")
    universe = json.loads(public.read_text())
    scenes = [row["scene_id"] for row in value["samples"]]
    local_only = value["pilot_id"] == LOCAL_PILOT_ID
    expected = set(APPROVED_SCENES) | (set(LOCAL_EXTRA_SCENES) if local_only else set())
    if len(scenes) != len(expected) or set(scenes) != expected:
        raise ValueError(f"Expected {len(expected)} distinct approved pilot scenes")
    if not set(scenes) <= set(universe["suites"]["py123d_development400"]):
        raise ValueError("Pilot escaped development400")
    logs = {universe["scenes"][s]["source_log"] for s in scenes}
    excluded = {
        s for s, meta in universe["scenes"].items() if meta["source_log"] in logs
    }
    if logs != set(value["training_source_logs"]) or len(logs) != 4:
        raise ValueError("Pilot source logs changed")
    if (
        excluded != set(value["excluded_scene_ids_for_candidate_evaluation"])
        or len(excluded) != 207
    ):
        raise ValueError("Whole-log exclusions changed")
    if set(value["protected_suites"]) != set(PROTECTED_SUITES):
        raise ValueError("Protected suite list changed")
    for name, ids in value["protected_suites"].items():
        if ids != universe["suites"][name] or excluded & set(ids):
            raise ValueError(f"Protected suite changed or overlaps training: {name}")
    for row in value["samples"]:
        original = universe["scenes"][row["scene_id"]]
        if (
            row["source_log"] != original["source_log"]
            or row["config_sha256"] != original["config_sha256"]
        ):
            raise ValueError("Pilot scene identity/config hash changed")
    scope = value["training_scope"]
    if scope["backbone_frozen"] is not True or scope["max_optimizer_steps"] != 100:
        raise ValueError("Approved frozen-backbone/100-step scope changed")
    if local_only:
        if (
            scope.get("max_samples") != 10
            or scope.get("trainable_component") != "new waypoint head only"
            or scope.get("full_backbone_finetuning") is not False
            or scope.get("submission") is not False
            or scope.get("full_evaluation") is not False
            or value.get("competition_training_permission") != "unverified"
            or value.get("submission_allowed") is not False
        ):
            raise ValueError("Local-only quarantine/scope changed")
        approval = value["local_authorization"]
        if approval.get("scope") != "local_only_frozen_cosmos_head_test":
            raise ValueError("Missing local head-only authorization")
        checked_path(path.parent, approval["file"], approval["sha256"])
    return value


def require_rules(pilot_path, evidence_path):
    """An offline review record, not authentication or proof of legal permission."""
    if evidence_path is None:
        raise ValueError(
            "Rules unverified: supply a locally reviewed --rules-evidence JSON; no token is required"
        )
    path = Path(evidence_path).resolve()
    evidence = json.loads(path.read_text())
    if (
        evidence.get("decision") != "permitted"
        or evidence.get("scope") != "training_on_approved_public_navtest_scenes"
    ):
        raise ValueError("Rules review does not permit the approved data use")
    if evidence.get("pilot_manifest_sha256") != file_hash(pilot_path):
        raise ValueError("Rules review is bound to a different pilot")
    for key in ("reviewed_by", "reviewed_at_utc", "source_description"):
        if not isinstance(evidence.get(key), str) or not evidence[key].strip():
            raise ValueError(f"Rules review needs {key}")
    checked_path(path.parent, evidence["evidence_file"], evidence["evidence_sha256"])
    return {"record": str(path), "sha256": file_hash(path), "review": evidence}


def require_run_authorization(pilot_path, evidence_path, *, local_only=False):
    """Keep user-authorized local testing separate from competition permission."""
    pilot = load_pilot(pilot_path)
    if local_only:
        if (
            pilot["pilot_id"] not in (LOCAL_PILOT_ID, "cosmos3-local-ablation-v1")
            or evidence_path is not None
        ):
            raise ValueError(
                "Local-only mode needs its separate ten-sample manifest and no rules claim"
            )
        return {
            "status": "user_authorized_local_only",
            "submission_allowed": False,
            "competition_training_permission": "unverified",
            "pilot_manifest_sha256": file_hash(pilot_path),
            "authorization": pilot["local_authorization"],
        }
    if pilot["pilot_id"] in (LOCAL_PILOT_ID, "cosmos3-local-ablation-v1"):
        raise ValueError(
            "This quarantined pilot requires explicit --local-only acknowledgement"
        )
    return require_rules(pilot_path, evidence_path)


def require_scene(pilot, scene_id):
    rows = [row for row in pilot["samples"] if row["scene_id"] == scene_id]
    if len(rows) != 1:
        raise ValueError(f"Scene is not in the approved pilot: {scene_id}")
    return rows[0]


def pose_matrix(pose):
    q = np.array([pose.quat.x, pose.quat.y, pose.quat.z, pose.quat.w], dtype=np.float64)
    if not np.isfinite(q).all() or abs(np.linalg.norm(q) - 1) > 1e-3:
        raise ValueError("Invalid pose quaternion")
    result = np.eye(4)
    result[:3, :3] = Rotation.from_quat(q).as_matrix()
    result[:3, 3] = [pose.vec.x, pose.vec.y, pose.vec.z]
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite pose")
    return result


def interpolate_poses(times, poses, queries, max_gap_us=600_000):
    times = np.asarray(times, dtype=np.int64)
    queries = np.asarray(queries, dtype=np.int64)
    poses = np.asarray(poses, dtype=np.float64)
    if (
        len(times) < 2
        or poses.shape != (len(times), 4, 4)
        or np.any(np.diff(times) <= 0)
    ):
        raise ValueError(
            "Pose times must be strictly increasing with at least two poses"
        )
    if (
        not np.isfinite(poses).all()
        or queries.min() < times[0]
        or queries.max() > times[-1]
    ):
        raise ValueError("Invalid poses or requested extrapolation")
    hi = np.searchsorted(times, queries, side="left").clip(1, len(times) - 1)
    lo = hi - 1
    exact = (times[hi] == queries) | (times[lo] == queries)
    if np.any((times[hi] - times[lo] > max_gap_us) & ~exact):
        raise ValueError("Cannot interpolate across a recording gap")
    fraction = (queries - times[lo]) / (times[hi] - times[lo])
    out = np.repeat(np.eye(4)[None], len(queries), axis=0)
    out[:, :3, 3] = (
        poses[lo, :3, 3] * (1 - fraction[:, None])
        + poses[hi, :3, 3] * fraction[:, None]
    )
    # Subtract the epoch before floating-point interpolation.
    stamps = (times - times[0]) / 1e6
    out[:, :3, :3] = Slerp(stamps, Rotation.from_matrix(poses[:, :3, :3]))(
        (queries - times[0]) / 1e6
    ).as_matrix()
    return out


def planar_relative(anchor, poses):
    relative = np.linalg.inv(anchor) @ np.asarray(poses)
    yaw = np.arctan2(relative[..., 1, 0], relative[..., 0, 0])
    return np.stack(
        [relative[..., 0, 3], relative[..., 1, 3], np.sin(yaw), np.cos(yaw)], axis=-1
    ).astype(np.float32)


def expert_aligned(estimated, true_pose, reference, position_m=0.10, angle_rad=0.01):
    for other in (true_pose, reference):
        relative = np.linalg.inv(estimated) @ other
        if (
            np.linalg.norm(relative[:3, 3]) > position_m
            or Rotation.from_matrix(relative[:3, :3]).magnitude() > angle_rad
        ):
            return False
    return True


def select_history(frames, time_us, max_age_us=100_000):
    """Return causal frames or None; never repeat a newer frame into missing past."""
    selected = []
    for offset in HISTORY_US:
        cutoff = time_us + offset
        eligible = [f for f in frames if f["start_us"] <= f["end_us"] <= cutoff]
        frame = max(eligible, key=lambda f: f["end_us"]) if eligible else None
        selected.append(
            frame if frame and cutoff - frame["end_us"] <= max_age_us else None
        )
    if selected[-1] is None:
        raise ValueError("No fresh causal current camera observation")
    return selected


def sparse_route(points, route_pose, current_pose):
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if not len(points):
        raise ValueError("Missing or invalid runtime route")
    # AlpaSim RouteGenerator.prepare_for_policy pads short routes with trailing
    # all-NaN Vec3 rows. Only that documented padding is masked; partial NaNs,
    # infinities, interior gaps and entirely empty routes are errors.
    finite = np.isfinite(points).all(axis=1)
    padding = np.isnan(points).all(axis=1)
    valid_count = int(finite.sum())
    if (
        not valid_count
        or not np.all(finite | padding)
        or not finite[:valid_count].all()
        or not padding[valid_count:].all()
    ):
        raise ValueError("Missing or invalid runtime route/padding")
    points = points[:valid_count]
    transformed = (
        np.linalg.inv(current_pose)
        @ route_pose
        @ np.column_stack([points, np.ones(len(points))]).T
    ).T[:, :2]
    if len(transformed) > MAX_ROUTE:
        transformed = transformed[
            np.linspace(0, len(transformed) - 1, MAX_ROUTE).round().astype(int)
        ]
    route, mask = np.zeros((MAX_ROUTE, 2), np.float32), np.zeros(MAX_ROUTE, bool)
    route[: len(transformed)], mask[: len(transformed)] = transformed, True
    return route, mask


def validate_arrays(inputs, targets):
    shapes = {
        "ego_state": (3,),
        "ego_history": (3, 4),
        "history_mask": (3,),
        "image_age_s": (3,),
        "route": (32, 2),
        "route_mask": (32,),
    }
    if set(inputs) != set(shapes) or set(targets) != {"waypoints", "target_mask"}:
        raise ValueError("Unexpected input/target fields; labels must remain separate")
    for name, shape in shapes.items():
        if inputs[name].shape != shape or not np.isfinite(inputs[name]).all():
            raise ValueError(f"Invalid input {name}")
        if not name.endswith("mask") and inputs[name].dtype != np.float32:
            raise ValueError(f"Input {name} must have float32 dtype")
    if targets["waypoints"].shape != (40, 4) or targets["target_mask"].shape != (40,):
        raise ValueError("Invalid four-second waypoint target")
    for value in (inputs["history_mask"], inputs["route_mask"], targets["target_mask"]):
        if value.dtype != np.bool_:
            raise ValueError("Masks must have boolean dtype")
    if (
        not inputs["history_mask"][-1]
        or not inputs["route_mask"].any()
        or not targets["target_mask"].any()
    ):
        raise ValueError("Missing current observation, navigation or targets")
    if not np.isfinite(targets["waypoints"]).all():
        raise ValueError("Nonfinite targets")
    if targets["waypoints"].dtype != np.float32:
        raise ValueError("Waypoint targets must have float32 dtype")
    valid = targets["waypoints"][targets["target_mask"], 2:]
    if not np.allclose(np.linalg.norm(valid, axis=-1), 1, atol=1e-4):
        raise ValueError("Target headings must be unit sin/cos pairs")
    ages = inputs["image_age_s"][inputs["history_mask"]]
    if (ages < 0).any():
        raise ValueError("Future observation")


def input_identity(sample):
    # No target arrays or future trajectories enter feature computation/cache keys.
    return {
        key: sample[key]
        for key in ("scene_id", "time_us", "images", "calibration", "inputs_sha256")
    }
