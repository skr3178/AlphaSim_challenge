"""Read-only audit of later saved observations; never exports training examples.

Inputs are accumulated in ASL event order. Reference/true poses are used only
for diagnostics and candidate filtering, never to synthesize causal inputs.
The existing exporter, training roles and authorization gates are unchanged.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation

from .training.contracts import (
    FUTURE_US,
    file_hash,
    interpolate_poses,
    pose_matrix,
    select_history,
    sparse_route,
    write_json,
)
from .training.export_asl import entries, trajectory_arrays
from .training.state_adapter import received_pose_state

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SHA = "a2a150d4eb139db0cbfa7d1cfa37a8eff701db34fff8264034c0433ab2f36b64"
POSITION_M = 0.10
ROTATION_RAD = 0.01
VELOCITY_MPS = 0.50
YAW_RATE_RADPS = 0.05
GATES = (
    "post_priming",
    "full_history",
    "future_4s",
    "causal_inputs",
    "history_pose_aligned",
    "exposure_boundaries_aligned",
    "motion_consistent",
)


def pose_error(first, second):
    relative = np.linalg.inv(first) @ second
    return (
        float(np.linalg.norm(relative[:3, 3])),
        float(Rotation.from_matrix(relative[:3, :3]).magnitude()),
    )


def within(errors):
    return all(
        position <= POSITION_M and angle <= ROTATION_RAD for position, angle in errors
    )


def audit_anchor(
    *,
    time_us,
    query_us,
    priming_end,
    frames,
    ego,
    route,
    calibration_ok,
    reference_times,
    reference_poses,
    true_times,
    true_poses,
):
    row = {"time_us": int(time_us), "post_priming": bool(time_us >= priming_end)}
    row.update({gate: False for gate in GATES if gate != "post_priming"})
    row["current_pose_aligned"] = False
    row["errors"] = {}
    selected = []
    try:
        selected = select_history(frames, time_us)
        row["history_timestamps_us"] = [f["end_us"] if f else None for f in selected]
        row["full_history"] = all(f is not None and f["decode_ok"] for f in selected)
        if row["full_history"]:
            row["image_triplet_sha256"] = hashlib.sha256(
                ":".join(f["sha256"] for f in selected).encode()
            ).hexdigest()
    except ValueError as exc:
        row["errors"]["history"] = str(exc)
    row["reference_remaining_s"] = (int(reference_times[-1]) - time_us) / 1e6
    try:
        target = interpolate_poses(
            reference_times, reference_poses, time_us + FUTURE_US
        )
        row["future_4s"] = bool(np.isfinite(target).all())
    except ValueError as exc:
        row["errors"]["future_4s"] = str(exc)

    state = None
    try:
        state, provenance = received_pose_state(ego, time_us)
        row["state_previous_timestamp_us"] = provenance[
            "previous_received_timestamp_us"
        ]
        row["speed_mps"] = float(np.linalg.norm(state[:2]))
        if not calibration_ok:
            raise ValueError("Missing or malformed calibration")
        if not time_us <= query_us <= time_us + int(FUTURE_US[-1]):
            raise ValueError("Control query outside prediction horizon")
        if route is None or route["time_us"] > time_us or route["time_us"] not in ego:
            raise ValueError("Missing causal route anchor")
        _, mask = sparse_route(route["points"], ego[route["time_us"]], ego[time_us])
        row["valid_route_points"] = int(mask.sum())
        row["causal_inputs"] = True
    except (ValueError, KeyError) as exc:
        row["errors"]["causal_inputs"] = str(exc)

    try:
        stamps = sorted({time_us} | {f["end_us"] for f in selected if f})
        actual = interpolate_poses(true_times, true_poses, stamps)
        reference = interpolate_poses(reference_times, reference_poses, stamps)
        all_errors = []
        for stamp, true, expert in zip(stamps, actual, reference):
            errors = [
                pose_error(ego[stamp], true),
                pose_error(ego[stamp], expert),
                pose_error(true, expert),
            ]
            all_errors.extend(errors)
            if stamp == time_us:
                row["current_pose_aligned"] = within(errors)
                (
                    row["current_true_expert_position_error_m"],
                    row["current_true_expert_rotation_error_rad"],
                ) = errors[-1]
        row["history_max_position_error_m"] = max(e[0] for e in all_errors)
        row["history_max_rotation_error_rad"] = max(e[1] for e in all_errors)
        row["history_pose_aligned"] = row["full_history"] and within(all_errors)
    except (ValueError, KeyError) as exc:
        row["errors"]["pose_alignment"] = str(exc)

    try:
        boundaries = sorted(
            {stamp for f in selected if f for stamp in (f["start_us"], f["end_us"])}
        )
        if not boundaries:
            raise ValueError("No exposure boundaries")
        actual = interpolate_poses(true_times, true_poses, boundaries)
        reference = interpolate_poses(reference_times, reference_poses, boundaries)
        errors = [pose_error(a, r) for a, r in zip(actual, reference)]
        row["exposure_max_position_error_m"] = max(e[0] for e in errors)
        row["exposure_max_rotation_error_rad"] = max(e[1] for e in errors)
        row["exposure_boundaries_aligned"] = row["full_history"] and within(errors)
    except ValueError as exc:
        row["errors"]["exposure_alignment"] = str(exc)

    # Reference motion is a diagnostic only, over the SAME backward interval.
    try:
        if state is None:
            raise ValueError("No causal observed state")
        before = row["state_previous_timestamp_us"]
        reference = interpolate_poses(
            reference_times, reference_poses, [before, time_us]
        )
        reference_state, _ = received_pose_state(
            {before: reference[0], time_us: reference[1]}, time_us
        )
        velocity_difference = float(np.linalg.norm(state[:2] - reference_state[:2]))
        yaw_rate_difference = float(abs(state[2] - reference_state[2]))
        row["diagnostic_velocity_difference_mps"] = velocity_difference
        row["diagnostic_yaw_rate_difference_radps"] = yaw_rate_difference
        row["motion_consistent"] = (
            velocity_difference <= VELOCITY_MPS
            and yaw_rate_difference <= YAW_RATE_RADPS
        )
    except (ValueError, KeyError) as exc:
        row["errors"]["motion_consistency"] = str(exc)
    row["candidate"] = all(row[gate] for gate in GATES)
    return row


def audit_scene(path, info):
    stat_before = path.stat()
    source_hash = file_hash(path)
    records = list(entries(path))
    metadata = [value for kind, value in records if kind == "rollout_metadata"]
    if len(metadata) != 1:
        raise ValueError("Expected exactly one rollout metadata message")
    meta = metadata[0]
    scene = path.parent.parent.name
    if (
        meta.session_metadata.scene_id != scene
        or meta.session_metadata.session_uuid != path.parent.name
    ):
        raise ValueError("ASL metadata does not match its scene/session directory")
    reference_times, reference_poses = trajectory_arrays(
        meta.ego_rig_recorded_ground_truth_trajectory
    )
    actual = {}
    aabb_to_rig = np.linalg.inv(pose_matrix(meta.transform_ego_coords_rig_to_aabb))
    for kind, value in records:
        if kind == "actor_poses":
            for actor in value.actor_poses:
                if actor.actor_id == "EGO":
                    actual[int(value.timestamp_us)] = (
                        pose_matrix(actor.actor_pose) @ aabb_to_rig
                    )
    true_times = np.array(sorted(actual), dtype=np.int64)
    true_poses = np.array([actual[t] for t in true_times])
    frames, ego, route, rows = [], {}, None, []
    calibration_ok = False
    for kind, value in records:
        if (
            getattr(value, "session_uuid", meta.session_metadata.session_uuid)
            != meta.session_metadata.session_uuid
        ):
            raise ValueError("Mixed-session messages")
        if kind == "driver_session_request":
            cameras = [
                c
                for c in value.rollout_spec.vehicle.available_cameras
                if c.logical_id == "CAM_F0"
            ]
            if len(cameras) == 1:
                c = cameras[0]
                pose_matrix(c.rig_to_camera)
                calibration_ok = (
                    c.intrinsics.resolution_w > 0 and c.intrinsics.resolution_h > 0
                )
        elif (
            kind == "driver_camera_image" and value.camera_image.logical_id == "CAM_F0"
        ):
            c = value.camera_image
            decoded = False
            try:
                with Image.open(io.BytesIO(c.image_bytes)) as image:
                    image.load()
                    decoded = image.format in ("JPEG", "PNG")
            except (OSError, ValueError):
                pass
            frames.append(
                {
                    "start_us": int(c.frame_start_us),
                    "end_us": int(c.frame_end_us),
                    "decode_ok": decoded,
                    "sha256": hashlib.sha256(c.image_bytes).hexdigest(),
                }
            )
        elif kind == "driver_ego_trajectory":
            for pose in value.trajectory.poses:
                # Never retain a state received only after its Drive request.
                ego[int(pose.timestamp_us)] = pose_matrix(pose.pose)
        elif kind == "route_request":
            route = {
                "time_us": int(value.route.timestamp_us),
                "points": [[w.x, w.y, w.z] for w in value.route.waypoints],
            }
        elif kind == "driver_request":
            result = audit_anchor(
                time_us=int(value.time_now_us),
                query_us=int(value.time_query_us),
                priming_end=int(
                    meta.session_metadata.start_timestamp_us + meta.force_gt_duration
                ),
                frames=frames,
                ego=ego,
                route=route,
                calibration_ok=calibration_ok,
                reference_times=reference_times,
                reference_poses=reference_poses,
                true_times=true_times,
                true_poses=true_poses,
            )
            result.update(
                scene_id=scene,
                session_uuid=path.parent.name,
                source_log=info["source_log"],
                city=info["city"],
            )
            rows.append(result)
    stat_after = path.stat()
    if (stat_before.st_size, stat_before.st_mtime_ns) != (
        stat_after.st_size,
        stat_after.st_mtime_ns,
    ):
        raise ValueError("Source ASL changed during audit")
    return rows, {
        "path": str(path),
        "sha256": source_hash,
        "scene_id": scene,
        "front_images": len(frames),
        "decoded_front_images": sum(f["decode_ok"] for f in frames),
        "reference_last_us": int(reference_times[-1]),
        "priming_us": int(meta.force_gt_duration),
    }


def summarize(rows, training_logs):
    later = [r for r in rows if r["post_priming"]]
    candidates = [r for r in rows if r["candidate"]]
    funnel, remaining = {}, rows
    for gate in GATES:
        remaining = [r for r in remaining if r[gate]]
        funnel[gate] = {
            "windows": len(remaining),
            "scenes": len({r["scene_id"] for r in remaining}),
        }
    by_log = {}
    for log in sorted({r["source_log"] for r in rows}):
        subset = [r for r in candidates if r["source_log"] == log]
        by_log[log] = {
            "city": next(r["city"] for r in rows if r["source_log"] == log),
            "existing_cosmos_training_log": log in training_logs,
            "candidate_windows": len(subset),
            "candidate_scenes": len({r["scene_id"] for r in subset}),
        }

    def speed_bin(speed):
        return (
            "stopped_<0.5"
            if speed < 0.5
            else (
                "slow_0.5_to_2"
                if speed < 2
                else "moving_2_to_8" if speed < 8 else "fast_ge8"
            )
        )

    return {
        "drive_requests": len(rows),
        "later_requests": len(later),
        "cumulative_funnel": funnel,
        "independent_later_failures": {
            gate: sum(not r[gate] for r in later) for gate in GATES[1:]
        },
        "later_current_pose_aligned": sum(r["current_pose_aligned"] for r in later),
        "candidate_windows": len(candidates),
        "candidate_scenes": len({r["scene_id"] for r in candidates}),
        "candidate_source_logs": len({r["source_log"] for r in candidates}),
        "candidate_unique_image_triplets": len(
            {r["image_triplet_sha256"] for r in candidates}
        ),
        "candidate_cities": dict(Counter(r["city"] for r in candidates)),
        "candidate_speeds": dict(
            Counter(speed_bin(r["speed_mps"]) for r in candidates)
        ),
        "candidate_anchor_times_us": dict(
            Counter(str(r["time_us"]) for r in candidates)
        ),
        "candidates_from_existing_training_logs": sum(
            r["source_log"] in training_logs for r in candidates
        ),
        "by_source_log": by_log,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("/media/skr/storage/alpasim-runs/confirm400-mup-g100"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    public_path = ROOT / "evaluation/public-suite.json"
    if file_hash(public_path) != PUBLIC_SHA:
        raise ValueError("Public split changed")
    public = json.loads(public_path.read_text())
    allowed = set(public["suites"]["py123d_development400"])
    paths = sorted((args.run_root / "rollouts").glob("*/*/rollout.asl"))
    if len(paths) != 400 or {p.parent.parent.name for p in paths} != allowed:
        raise ValueError(
            "Audit requires exactly one saved rollout for each development400 scene"
        )
    if args.output.exists():
        raise ValueError("Refusing to overwrite an existing audit")
    training_logs = set(
        json.loads((ROOT / "cosmos3/pilots/local-head10-v1/manifest.json").read_text())[
            "training_source_logs"
        ]
    )
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(
        args.output / "protocol.json",
        {
            "mode": "saved_data_alignment_audit_only",
            "scope": "development400",
            "source_run": str(args.run_root),
            "public_manifest_sha256": PUBLIC_SHA,
            "audit_source_sha256": file_hash(Path(__file__)),
            "history_offsets_us": [-1_000_000, -500_000, 0],
            "future_horizon_us": int(FUTURE_US[-1]),
            "pose_position_limit_m": POSITION_M,
            "pose_rotation_limit_rad": ROTATION_RAD,
            "diagnostic_velocity_limit_mps": VELOCITY_MPS,
            "diagnostic_yaw_rate_limit_radps": YAW_RATE_RADPS,
            "thresholds_fixed_before_full_audit": True,
            "gates_in_order": list(GATES),
            "training_authorized": False,
            "submission_allowed": False,
            "exporter_unchanged": True,
        },
    )
    rows, sources = [], []
    try:
        for index, path in enumerate(paths, 1):
            part, source = audit_scene(path, public["scenes"][path.parent.parent.name])
            rows.extend(part)
            sources.append(source)
            if index % 25 == 0:
                print(
                    f"Audited {index}/400 saved scenes; no model or simulator calls",
                    flush=True,
                )
        if file_hash(public_path) != PUBLIC_SHA:
            raise ValueError("Public manifest changed during audit")
        result = summarize(rows, training_logs)
        result.update(
            front_images=sum(s["front_images"] for s in sources),
            decoded_front_images=sum(s["decoded_front_images"] for s in sources),
            reference_end_times_us=dict(
                Counter(str(s["reference_last_us"]) for s in sources)
            ),
        )
        write_json(args.output / "sources.json", sources)
        write_json(args.output / "windows.json", rows)
        write_json(args.output / "summary.json", result)
        print(json.dumps(result, indent=2), flush=True)
    except Exception as exc:
        write_json(
            args.output / "FAILED.json",
            {"error": str(exc), "completed_scenes": len(sources)},
        )
        raise


if __name__ == "__main__":
    main()
