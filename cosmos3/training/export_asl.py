"""Export only causally observed, expert-aligned samples from approved saved ASLs.

This does not run a renderer or evaluator. Logs with insufficient priming/history
are rejected rather than paired with off-policy expert futures. Use the existing
AlpaSim Python environment for protobuf bindings; output is ordinary JSON/NPZ/JPEG.
"""

from __future__ import annotations

from collections import Counter
import io
from pathlib import Path
import struct

import numpy as np
from PIL import Image

from .contracts import (
    CONTRACT,
    FUTURE_US,
    expert_aligned,
    file_hash,
    interpolate_poses,
    load_pilot,
    planar_relative,
    pose_matrix,
    require_run_authorization,
    require_scene,
    select_history,
    sparse_route,
    validate_arrays,
    write_json,
)
from .state_adapter import STATE_RECIPE, received_pose_state


def entries(path):
    from alpasim_grpc.v0.logging_pb2 import LogEntry

    with Path(path).open("rb") as stream:
        while prefix := stream.read(4):
            if len(prefix) != 4:
                raise ValueError("Truncated ASL prefix")
            size = struct.unpack(">L", prefix)[0]
            if not 0 < size <= 100_000_000:
                raise ValueError("Invalid ASL message size")
            payload = stream.read(size)
            if len(payload) != size:
                raise ValueError("Truncated ASL payload")
            entry = LogEntry.FromString(payload)
            kind = entry.WhichOneof("log_entry")
            if kind:
                yield kind, getattr(entry, kind)


def trajectory_arrays(trajectory):
    return (
        np.array([p.timestamp_us for p in trajectory.poses], dtype=np.int64),
        np.array([pose_matrix(p.pose) for p in trajectory.poses]),
    )


def summarize_source(path, pilot):
    metadata, actors = [], {}
    for kind, value in entries(path):
        if kind == "rollout_metadata":
            require_scene(pilot, value.session_metadata.scene_id)
            metadata.append(value)
        elif kind == "actor_poses":
            for actor in value.actor_poses:
                if actor.actor_id == "EGO":
                    actors[value.timestamp_us] = pose_matrix(actor.actor_pose)
    if len(metadata) != 1 or len(actors) < 2:
        raise ValueError("Need one rollout metadata entry and multiple true ego poses")
    meta = metadata[0]
    row = require_scene(pilot, meta.session_metadata.scene_id)
    gt_times, gt_poses = trajectory_arrays(
        meta.ego_rig_recorded_ground_truth_trajectory
    )
    times = np.array(sorted(actors), dtype=np.int64)
    aabb_to_rig = np.linalg.inv(pose_matrix(meta.transform_ego_coords_rig_to_aabb))
    poses = np.array([actors[t] @ aabb_to_rig for t in times])
    return meta, row, gt_times, gt_poses, times, poses


def export(
    pilot_path, asl_paths, output, evidence_path, max_samples=64, *, local_only=False
):
    pilot = load_pilot(pilot_path)
    authorization = require_run_authorization(
        pilot_path, evidence_path, local_only=local_only
    )
    from google.protobuf.json_format import MessageToDict

    max_allowed = 10 if local_only else 256
    if not 1 <= max_samples <= max_allowed or not 1 <= len(asl_paths) <= len(
        pilot["samples"]
    ):
        raise ValueError("Export exceeds the approved scene/sample bounds")
    output = Path(output)
    if output.exists():
        raise ValueError("Refusing to overwrite dataset output")
    paths = [Path(p).resolve() for p in asl_paths]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate ASL paths")
    if max_samples < len(paths):
        raise ValueError("Sample budget must allow at least one sample per source")
    per_source_limit = max_samples // len(paths)
    initial_hashes = [file_hash(p) for p in paths]
    sources = [summarize_source(p, pilot) for p in paths]
    scenes = [s[0].session_metadata.scene_id for s in sources]
    if len(scenes) != len(set(scenes)):
        raise ValueError("Choose one saved rollout per approved scene")
    output.mkdir(parents=True)
    (output / "images").mkdir()
    samples, rejected, source_records = [], Counter(), []
    try:
        for path, source, source_hash in zip(paths, sources, initial_hashes):
            meta, row, gt_t, gt_pose, true_t, true_pose = source
            if file_hash(path) != source_hash:
                raise ValueError("ASL changed during metadata scan")
            source_sample_count = 0
            source_records.append(
                {
                    "path": str(path),
                    "sha256": source_hash,
                    "scene_id": row["scene_id"],
                    "session_uuid": meta.session_metadata.session_uuid,
                }
            )
            frames, ego, route, calibration = [], {}, None, None
            priming_start = int(meta.session_metadata.start_timestamp_us)
            priming_end = priming_start + int(meta.force_gt_duration)
            for kind, value in entries(path):
                if (
                    getattr(value, "session_uuid", meta.session_metadata.session_uuid)
                    != meta.session_metadata.session_uuid
                ):
                    raise ValueError("Mixed-session ASL data")
                if kind == "driver_session_request":
                    cameras = [
                        c
                        for c in value.rollout_spec.vehicle.available_cameras
                        if c.logical_id == "CAM_F0"
                    ]
                    if len(cameras) != 1:
                        raise ValueError("Missing/ambiguous front-camera calibration")
                    calibration = MessageToDict(
                        cameras[0], preserving_proto_field_name=True
                    )
                    pose_matrix(cameras[0].rig_to_camera)
                    if (
                        cameras[0].intrinsics.resolution_w <= 0
                        or cameras[0].intrinsics.resolution_h <= 0
                    ):
                        raise ValueError("Missing native camera dimensions")
                elif (
                    kind == "driver_camera_image"
                    and value.camera_image.logical_id == "CAM_F0"
                ):
                    c = value.camera_image
                    if c.image_bytes:
                        frames.append(
                            {
                                "start_us": int(c.frame_start_us),
                                "end_us": int(c.frame_end_us),
                                "bytes": c.image_bytes,
                            }
                        )
                        newest = max(f["end_us"] for f in frames)
                        frames = [
                            f for f in frames if newest - f["end_us"] <= 1_200_000
                        ]
                elif kind == "driver_ego_trajectory":
                    if len(value.trajectory.poses) != len(value.dynamic_states):
                        raise ValueError("Pose/dynamic-state pairing mismatch")
                    for p, state in zip(value.trajectory.poses, value.dynamic_states):
                        ego[int(p.timestamp_us)] = (
                            pose_matrix(p.pose),
                            np.array(
                                [
                                    state.linear_velocity.x,
                                    state.linear_velocity.y,
                                    state.angular_velocity.z,
                                ],
                                np.float32,
                            ),
                        )
                elif kind == "route_request":
                    route = value.route
                elif kind == "driver_request":
                    t = int(value.time_now_us)
                    if source_sample_count >= per_source_limit:
                        break
                    try:
                        # AlpaSim's query is the next control endpoint, not a
                        # second observation timestamp. Predict from time_now;
                        # require the four-second output to cover that endpoint.
                        if not t <= value.time_query_us <= t + int(FUTURE_US[-1]):
                            raise ValueError(
                                "Control query is outside the current-pose prediction horizon"
                            )
                        if not priming_start <= t < priming_end:
                            raise ValueError("Outside expert priming window")
                        if t not in ego or calibration is None:
                            raise ValueError(
                                "No same-time observed ego state or calibration"
                            )
                        if (
                            route is None
                            or route.timestamp_us > t
                            or route.timestamp_us not in ego
                        ):
                            raise ValueError("No causal runtime route/anchor pose")
                        selected = select_history(frames, t)
                        if any(
                            f
                            and not priming_start
                            <= f["start_us"]
                            <= f["end_us"]
                            < priming_end
                            for f in selected
                        ):
                            raise ValueError(
                                "Image exposure extends outside expert priming"
                            )
                        current, state = ego[t]
                        state_provenance = {
                            "recipe": "logged-dynamic-state-unverified-rig-frame-v1"
                        }
                        if pilot.get("ego_state_recipe") == STATE_RECIPE:
                            logged_state = state.copy()
                            state, state_provenance = received_pose_state(
                                {stamp: value[0] for stamp, value in ego.items()}, t
                            )
                            state_provenance.update(
                                logged_dynamic_state=logged_state.tolist(),
                                derived_state=state.tolist(),
                                velocity_difference_mps=float(
                                    np.linalg.norm(state[:2] - logged_state[:2])
                                ),
                                yaw_rate_difference_radps=float(
                                    abs(state[2] - logged_state[2])
                                ),
                            )
                        timestamps = sorted({t} | {f["end_us"] for f in selected if f})
                        true_at = interpolate_poses(true_t, true_pose, timestamps)
                        gt_at = interpolate_poses(gt_t, gt_pose, timestamps)
                        for stamp, actual, reference in zip(timestamps, true_at, gt_at):
                            if stamp not in ego or not expert_aligned(
                                ego[stamp][0], actual, reference
                            ):
                                raise ValueError(
                                    "Observed/true/expert poses do not align"
                                )
                        future = interpolate_poses(gt_t, gt_pose, t + FUTURE_US)
                        route_array, route_mask = sparse_route(
                            [[v.x, v.y, v.z] for v in route.waypoints],
                            ego[int(route.timestamp_us)][0],
                            current,
                        )
                        history_mask = np.array(
                            [f is not None for f in selected], dtype=bool
                        )
                        history = np.zeros((3, 4), np.float32)
                        ages = np.zeros(3, np.float32)
                        for i, frame in enumerate(selected):
                            if frame:
                                history[i] = planar_relative(
                                    current, ego[frame["end_us"]][0]
                                )
                                ages[i] = (t - frame["end_us"]) / 1e6
                        inputs = dict(
                            ego_state=state,
                            ego_history=history,
                            history_mask=history_mask,
                            image_age_s=ages,
                            route=route_array,
                            route_mask=route_mask,
                        )
                        targets = dict(
                            waypoints=planar_relative(current, future),
                            target_mask=np.ones(40, bool),
                        )
                        validate_arrays(inputs, targets)
                        decoded = []
                        for frame in selected:
                            if frame:
                                with Image.open(io.BytesIO(frame["bytes"])) as image:
                                    image.load()
                                    if image.format not in ("JPEG", "PNG"):
                                        raise ValueError(
                                            "Unexpected camera image format"
                                        )
                                    decoded.append((image.size, image.format))
                            else:
                                decoded.append(None)
                    except ValueError as exc:
                        rejected[str(exc)] += 1
                        continue
                    sample_id = f"{row['scene_id']}__{t}"
                    images = []
                    for frame, decoded_info in zip(selected, decoded):
                        if frame is None:
                            images.append(None)
                            continue
                        import hashlib

                        digest = hashlib.sha256(frame["bytes"]).hexdigest()
                        suffix = ".jpg" if decoded_info[1] == "JPEG" else ".png"
                        relative = f"images/{digest}{suffix}"
                        destination = output / relative
                        if not destination.exists():
                            with destination.open("xb") as stream:
                                stream.write(frame["bytes"])
                        images.append(
                            {
                                "path": relative,
                                "sha256": digest,
                                "start_us": frame["start_us"],
                                "end_us": frame["end_us"],
                                "size_wh": list(decoded_info[0]),
                            }
                        )
                    inputs_path, targets_path = (
                        f"{sample_id}.inputs.npz",
                        f"{sample_id}.targets.npz",
                    )
                    with (output / inputs_path).open("xb") as stream:
                        np.savez_compressed(stream, **inputs)
                    with (output / targets_path).open("xb") as stream:
                        np.savez_compressed(stream, **targets)
                    samples.append(
                        {
                            "sample_id": sample_id,
                            "scene_id": row["scene_id"],
                            "source_log": row["source_log"],
                            "time_us": t,
                            "images": images,
                            "query_time_us": int(value.time_query_us),
                            "target_time_basis": "time_now_us_plus_0.1_to_4.0_seconds",
                            "calibration": calibration,
                            "inputs": inputs_path,
                            "targets": targets_path,
                            "inputs_sha256": file_hash(output / inputs_path),
                            "targets_sha256": file_hash(output / targets_path),
                            "source_asl_sha256": source_hash,
                            "route_provenance": "runtime_route_request",
                            "ego_state_provenance": state_provenance,
                            "route_valid_points": int(route_mask.sum()),
                            "route_nan_padding_rows": int(
                                sum(
                                    np.isnan([v.x, v.y, v.z]).all()
                                    for v in route.waypoints
                                )
                            ),
                            "alignment": "all observed frames/current pose within 0.10m and 0.01rad of true and recorded expert pose",
                        }
                    )
                    source_sample_count += 1
            if file_hash(path) != source_hash:
                raise ValueError("ASL changed during export")
        if not samples:
            raise ValueError(
                "No eligible expert-aligned samples; do not substitute off-policy frames"
            )
        write_json(
            output / "dataset.json",
            {
                "schema_version": 1,
                "contract": CONTRACT,
                "data_kind": "real_asl_expert_aligned",
                "ego_state_recipe": pilot.get(
                    "ego_state_recipe", "logged-dynamic-state-unverified-rig-frame-v1"
                ),
                "pilot_manifest_sha256": file_hash(pilot_path),
                "run_authorization": authorization,
                "submission_allowed": False if local_only else None,
                "sources": source_records,
                "samples": samples,
                "rejected_requests": dict(rejected),
                "exporter_sha256": file_hash(__file__),
            },
        )
    except Exception as exc:
        write_json(
            output / "FAILED.json",
            {
                "error": repr(exc),
                "partial_samples": len(samples),
                "rejected_requests": dict(rejected),
            },
        )
        raise
    return {
        "dataset": str(output / "dataset.json"),
        "samples": len(samples),
        "rejected": dict(rejected),
    }
