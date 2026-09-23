"""Export real nuPlan cameras into the frozen-Cosmos head's array contract.

CPU only. Navigation uses AlpaSim's actual MAP generator with its 40 m offset;
the recorded path used to infer authorized navigation is never a model tensor.
Existing rendered-ASL datasets and their authorization rules are untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import pickle
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation

from .contracts import (
    CONTRACT,
    FUTURE_US,
    file_hash,
    interpolate_poses,
    planar_relative,
    pose_matrix,
    sparse_route,
    validate_arrays,
    write_json,
)
from .state_adapter import STATE_RECIPE, received_pose_state

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAP_ROOT = Path("/home/skr/alpasim-challenge/nuplan-track/nuplan_test/maps")
PROTECTED = ROOT / "cosmos3/artifacts/training-readiness-20260918/protected-splits.json"
PUBLIC = ROOT / "evaluation/public-suite.json"
ROUTE_RECIPE = "alpasim-map-offset40-v1"
CITY_NAMES = {
    "boston": "boston",
    "us-ma-boston": "boston",
    "pittsburgh": "pittsburgh",
    "us-pa-pittsburgh-hazelwood": "pittsburgh",
    "singapore": "singapore",
    "sg-one-north": "singapore",
    "las_vegas": "las_vegas",
    "vegas": "las_vegas",
    "us-nv-las-vegas-strip": "las_vegas",
}


def reference_route_parity(map_root=DEFAULT_MAP_ROOT):
    scene = "2021.05.25.14.26.37_veh-27_04122_04279-303d452ddd2d58d1"
    run_root = Path("/media/skr/storage/alpasim-runs/confirm400-mup-g100/rollouts")
    candidates = list((run_root / scene).glob("*/rollout.asl"))
    if len(candidates) != 1:
        raise ValueError("Need the pinned saved route for CPU algorithm parity")
    cache = DEFAULT_MAP_ROOT.parent / scene / "agent_data_dt0.10.feather"
    return route_parity_check(candidates[0], cache, "las_vegas", map_root)


class CalibrationReader(pickle.Unpickler):
    """Accept array data constructors, never arbitrary pickle globals."""

    def find_class(self, module, name):
        from numpy._core import multiarray

        allowed = {
            ("numpy", "ndarray"): np.ndarray,
            ("numpy", "dtype"): np.dtype,
            ("numpy.core.multiarray", "_reconstruct"): multiarray._reconstruct,
            ("numpy._core.multiarray", "_reconstruct"): multiarray._reconstruct,
            ("numpy.core.multiarray", "scalar"): multiarray.scalar,
            ("numpy._core.multiarray", "scalar"): multiarray.scalar,
            # These nuPlan DB types are list subclasses; restore only their data.
            ("nuplan.database.common.data_types", "CameraIntrinsic"): list,
            ("nuplan.database.common.data_types", "Translation"): list,
            ("nuplan.database.common.data_types", "Rotation"): list,
        }
        if (module, name) not in allowed:
            raise ValueError(f"Unsafe calibration constructor {module}.{name}")
        return allowed[module, name]


def calibration_array(blob, shape=None):
    if not isinstance(blob, bytes) or not 0 < len(blob) <= 65536:
        raise ValueError("Missing/oversized calibration blob")
    value = np.asarray(CalibrationReader(io.BytesIO(blob)).load(), dtype=np.float64)
    if not np.isfinite(value).all() or (shape is not None and value.shape != shape):
        raise ValueError("Invalid calibration array")
    return value


def load_recording(path):
    """Read-only DB ingestion; DB ego pose is rear axle, not box centre.

    Match AlpaSim trajdata_data_source: preserve XYZ, use quaternion yaw only,
    subtract an origin in float64 before passing coordinates to Rust float32.
    """
    path = Path(path).resolve()
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        rows = db.execute(
            "SELECT timestamp,x,y,z,qw,qx,qy,qz FROM ego_pose ORDER BY timestamp"
        ).fetchall()
        camera_rows = db.execute(
            "SELECT model,translation,rotation,intrinsic,distortion,width,height "
            "FROM camera WHERE channel='CAM_F0'"
        ).fetchall()
        image_rows = db.execute(
            "SELECT i.filename_jpg,i.timestamp,e.timestamp FROM image i "
            "JOIN camera c ON i.camera_token=c.token "
            "JOIN ego_pose e ON i.ego_pose_token=e.token WHERE c.channel='CAM_F0'"
        ).fetchall()
    if len(rows) < 3 or len(camera_rows) != 1:
        raise ValueError("Need multiple ego poses and one front calibration")
    values = np.asarray(rows, dtype=np.float64)
    times = np.asarray([r[0] for r in rows], dtype=np.int64)
    if np.any(np.diff(times) <= 0) or not np.isfinite(values).all():
        raise ValueError("Invalid/duplicate ego timestamps or pose values")
    quat = values[:, [5, 6, 7, 4]]
    if not np.allclose(np.linalg.norm(quat, axis=1), 1, atol=1e-3):
        raise ValueError("Nonunit source quaternion")
    rotations = Rotation.from_quat(quat).as_matrix()
    yaw = np.arctan2(rotations[:, 1, 0], rotations[:, 0, 0])
    poses = np.repeat(np.eye(4)[None], len(rows), axis=0)
    poses[:, :3, :3] = Rotation.from_euler("z", yaw[:, None]).as_matrix()
    origin = values[0, 1:4].copy()
    poses[:, :3, 3] = values[:, 1:4] - origin
    model, trans, rot, intrinsic, distortion, width, height = camera_rows[0]
    k = calibration_array(intrinsic, (3, 3))
    rotation = calibration_array(rot, (4,))
    translation = calibration_array(trans, (3,))
    distortion = calibration_array(distortion).reshape(-1)
    if (
        not 0 < width <= 4096
        or not 0 < height <= 4096
        or k[0, 0] <= 0
        or k[1, 1] <= 0
        or not 0 <= k[0, 2] < width
        or not 0 <= k[1, 2] < height
        or not np.isclose(np.linalg.norm(rotation), 1, atol=1e-3)
    ):
        raise ValueError("Invalid front-camera calibration")
    calibration = {
        "logical_id": "CAM_F0",
        "model": model,
        "intrinsic": k.tolist(),
        "distortion": distortion.tolist(),
        "sensor_to_rear_axle_translation": translation.tolist(),
        "sensor_to_rear_axle_quaternion_wxyz": rotation.tolist(),
        "size_wh": [int(width), int(height)],
        "pose_convention": "nuplan_ego_pose_rear_axle_xyz_yaw_only",
        "timestamp_convention": "recorded_image_timestamp_no_invented_exposure_duration",
        "rolling_shutter_compensation": "not_applied; exposure duration is not in the DB",
    }
    images = {name: (int(ts), int(ego_ts)) for name, ts, ego_ts in image_rows}
    if len(images) != len(image_rows):
        raise ValueError("Duplicate DB image filename")
    return times, poses, origin, calibration, images


def select_triplet(images, current_index, tolerance_us=100_000):
    """Nearest half-second history, permitting timestamp jitter but never future."""
    timestamps = np.array([int(i["timestamp_us"]) for i in images], dtype=np.int64)
    if np.any(np.diff(timestamps) <= 0):
        raise ValueError("Images must have unique increasing timestamps")
    now = timestamps[current_index]
    selected = []
    for offset in (-1_000_000, -500_000, 0):
        target = now + offset
        candidates = np.flatnonzero(
            (timestamps <= now) & (abs(timestamps - target) <= tolerance_us)
        )
        if not len(candidates):
            raise ValueError("Missing half-second camera history")
        best = min(
            candidates,
            key=lambda i: (abs(int(timestamps[i]) - target), int(timestamps[i])),
        )
        selected.append(images[int(best)])
    stamps = [int(i["timestamp_us"]) for i in selected]
    if (
        not stamps[0] < stamps[1] < stamps[2]
        or stamps[-1] != now
        or np.any(np.diff(stamps) < 400_000)
        or np.any(np.diff(stamps) > 600_000)
    ):
        raise ValueError("Noncausal or repeated camera history")
    return selected


def spread_candidates(indices, preferred_count):
    """Visit evenly distributed primary anchors before score-blind replacements."""
    if len(indices) <= preferred_count:
        return list(indices)
    primary = set(
        np.linspace(0, len(indices) - 1, preferred_count).round().astype(int).tolist()
    )
    return [indices[i] for i in sorted(primary)] + [
        indices[i] for i in range(len(indices)) if i not in primary
    ]


def motion_category(inputs, targets):
    speed = float(np.linalg.norm(inputs["ego_state"][:2]))
    yaw = float(np.arctan2(targets["waypoints"][-1, 2], targets["waypoints"][-1, 3]))
    maneuver = (
        "stopped"
        if speed < 0.5
        else ("turn" if abs(yaw) >= np.deg2rad(10) else "straight")
    )
    speed_bin = (
        "below_0.5mps"
        if speed < 0.5
        else (
            "0.5_to_5mps"
            if speed < 5
            else ("5_to_15mps" if speed < 15 else "15mps_or_more")
        )
    )
    return {
        "initial_speed_mps": speed,
        "four_second_yaw_change_rad": yaw,
        "maneuver": maneuver,
        "speed_bin": speed_bin,
    }


def causal_example(times, poses, image_times):
    """Anchor to an actually available pose at/after the newest exposure."""
    image_times = np.asarray(image_times, dtype=np.int64)
    if image_times.shape != (3,) or np.any(np.diff(image_times) <= 0):
        raise ValueError("Need three distinct ordered image times")
    index = int(np.searchsorted(times, image_times[-1], side="left"))
    if index >= len(times) or not 0 <= times[index] - image_times[-1] <= 100_000:
        raise ValueError("No fresh recorded ego-pose anchor")
    t = int(times[index])
    # The adapter's documented >=10ms interval excludes sub-10ms DB jitter.
    previous_index = int(np.searchsorted(times, t - 10_000, side="right") - 1)
    if previous_index < 0:
        raise ValueError("No past pose for causal velocity")
    received = {int(times[previous_index]): poses[previous_index], t: poses[index]}
    state, provenance = received_pose_state(received, t)
    provenance["derived_state"] = state.tolist()
    provenance["source_pose_selection"] = (
        "latest_actual_pose_at_least_10ms_before_anchor"
    )
    history = interpolate_poses(
        times[: index + 1], poses[: index + 1], image_times, max_gap_us=100_000
    )
    future = interpolate_poses(times, poses, t + FUTURE_US, max_gap_us=100_000)
    inputs = {
        "ego_state": state,
        "ego_history": planar_relative(poses[index], history),
        "history_mask": np.ones(3, bool),
        "image_age_s": ((t - image_times) / 1e6).astype(np.float32),
    }
    targets = {
        "waypoints": planar_relative(poses[index], future),
        "target_mask": np.ones(40, bool),
    }
    return t, poses[index], inputs, targets, provenance


class RuntimeMapRouter:
    """The installed AlpaSim MAP implementation, not a target-as-route shortcut."""

    def __init__(self, map_path, origin_world):
        import alpasim_runtime.route_generator as runtime
        from trajdata.maps import VectorMap
        from trajdata.maps.map_kdtree import LaneCenterKDTree
        from trajdata.maps.vec_map_elements import MapElementType
        from trajdata.proto.vectorized_map_pb2 import VectorizedMap

        self.runtime = runtime
        self.map_path = Path(map_path).resolve()
        self.map_sha256 = file_hash(self.map_path)
        self.source_sha256 = file_hash(runtime.__file__)
        self.origin = np.asarray(origin_world, dtype=np.float64)
        self.vector_map = VectorMap.from_proto(
            VectorizedMap.FromString(self.map_path.read_bytes())
        )
        if not self.vector_map.lanes:
            raise ValueError("Empty city navigation map")
        for lane in self.vector_map.lanes:
            # Runtime subtracts global XY only; the road plane is at clip-start Z.
            for line in (lane.center, lane.left_edge, lane.right_edge):
                if line is not None:
                    line.points[:, :2] -= self.origin[:2]
        self.vector_map.search_kdtrees = {
            MapElementType.ROAD_LANE: LaneCenterKDTree(self.vector_map)
        }

    def generate(self, recorded_xyz, current_pose, time_us):
        from alpasim_utils.geometry import Pose

        points = np.asarray(recorded_xyz, dtype=np.float64).copy()
        current = np.asarray(current_pose, dtype=np.float64).copy()
        if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2:
            raise ValueError("Invalid recorded navigation geometry")
        # Each short navigation clip has its own flat map Z baseline, as runtime.
        baseline_z = float(points[0, 2])
        points[:, 2] -= baseline_z
        current[2, 3] -= baseline_z
        generator = self.runtime.RouteGeneratorMap(
            points, self.vector_map, route_start_offset_m=40.0
        )
        runtime_pose = Pose.from_se3(current.astype(np.float32))
        try:
            generated = generator.generate_route(
                int(time_us), runtime_pose
            )
        except IndexError as exc:
            # Runtime may lose the projected route after extending a dead end.
            # Reject only this verified empty-geometry case; propagate unrelated
            # programming errors rather than silently dropping arbitrary samples.
            cumulative, _ = generator.route_polyline_in_local.get_cumulative_distances_from_point(
                np.ascontiguousarray(runtime_pose.vec3)
            )
            if len(cumulative) == 0:
                raise ValueError("MAP route extension has no reachable waypoints") from exc
            raise
        generated = self.runtime.RouteGenerator.prepare_for_policy(generated)
        return np.asarray(generated.waypoints, dtype=np.float64)

    def example_route(self, times, poses, current_pose, time_us):
        # A bounded 5.5s recorded interval, not the entire potentially looping log.
        nav_times = time_us - 1_000_000 + np.arange(56, dtype=np.int64) * 100_000
        nav = interpolate_poses(times, poses, nav_times, max_gap_us=100_000)
        raw_route = self.generate(nav[:, :3, 3], current_pose, time_us)
        route, mask = sparse_route(raw_route, np.eye(4), np.eye(4))
        provenance = {
            "recipe": ROUTE_RECIPE,
            "source_code_sha256": self.source_sha256,
            "map_path": str(self.map_path),
            "map_sha256": self.map_sha256,
            "generator": "alpasim_runtime.route_generator.RouteGeneratorMap",
            "route_start_offset_m": 40.0,
            "route_lookahead_m": 80.0,
            "runtime_waypoint_count": 20,
            "recorded_navigation_start_us": int(nav_times[0]),
            "recorded_navigation_end_us": int(nav_times[-1]),
            "recorded_navigation_interval_us": 100_000,
            "recorded_geometry_sha256": hashlib.sha256(
                nav[:, :3, 3].astype("<f8").tobytes()
            ).hexdigest(),
            "dense_or_timed_future_targets_provided_to_head": False,
            "recorded_geometry_use": "authorized map-projected sparse navigation only; no speed/time channel",
            "coordinate_origin_world_xyz": self.origin.tolist(),
            "clip_policy": "anchor_minus_1s_to_plus_4.5s; runtime algorithm, not identical private-scene boundaries",
        }
        return route, mask, provenance


def route_parity_check(asl_path, trajectory_cache, city, map_root=DEFAULT_MAP_ROOT):
    """Reconstruct one saved first route, without evaluating/driving any scene."""
    import pyarrow.compute as pc
    from pyarrow import feather

    from .export_asl import entries, trajectory_arrays

    table = feather.read_table(trajectory_cache)
    rows = table.filter(pc.equal(table["agent_id"], "ego")).to_pylist()
    first = min(rows, key=lambda r: r["scene_ts"])
    origin = np.array([first[k] for k in ("x", "y", "z")])
    metadata, received, saved_route = None, {}, None
    for kind, value in entries(asl_path):
        if kind == "rollout_metadata":
            metadata = value
        elif kind == "driver_ego_trajectory":
            received.update(
                {
                    int(p.timestamp_us): pose_matrix(p.pose)
                    for p in value.trajectory.poses
                }
            )
        elif kind == "route_request":
            saved_route = value.route
        elif kind == "driver_request":
            break
    if (
        metadata is None
        or saved_route is None
        or int(saved_route.timestamp_us) not in received
    ):
        raise ValueError("Saved ASL lacks the first route and corresponding pose")
    _, gt = trajectory_arrays(metadata.ego_rig_recorded_ground_truth_trajectory)
    router = RuntimeMapRouter(Path(map_root) / f"{CITY_NAMES[city]}.pb", origin)
    predicted = router.generate(
        gt[:, :3, 3], received[int(saved_route.timestamp_us)], saved_route.timestamp_us
    )
    expected = np.array([[p.x, p.y, p.z] for p in saved_route.waypoints])
    finite = np.isfinite(expected).all(axis=1)
    same_mask = predicted.shape == expected.shape and np.array_equal(
        np.isfinite(predicted), np.isfinite(expected)
    )
    error = (
        float(np.max(np.abs(predicted[finite] - expected[finite])))
        if same_mask and finite.any()
        else None
    )
    return {
        "passed": bool(same_mask and error is not None and error <= 0.05),
        "finite_point_count": int(finite.sum()),
        "same_padding_mask": bool(same_mask),
        "maximum_coordinate_error_m": error,
        "tolerance_m": 0.05,
        "asl_path": str(Path(asl_path).resolve()),
        "asl_sha256": file_hash(asl_path),
        "trajectory_cache_sha256": file_hash(trajectory_cache),
        "map_sha256": router.map_sha256,
        "source_code_sha256": router.source_sha256,
        "limits": "One first-observation route, identical recorded geometry; not a full training/runtime or private-suite parity proof",
    }


def checked_image(root, image, calibration, verified):
    relative = image["filename"]
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Image missing or path escapes image root")
    identity = (relative, image["sha256"])
    if identity not in verified:
        if file_hash(path) != image["sha256"]:
            raise ValueError("Acquired image hash mismatch")
        with Image.open(path) as decoded:
            decoded.load()
            if decoded.format != "JPEG" or list(decoded.size) != calibration["size_wh"]:
                raise ValueError("Image decode/calibration dimensions mismatch")
        verified.add(identity)
    return {
        "path": relative,
        "sha256": image["sha256"],
        "timestamp_us": int(image["timestamp_us"]),
        "size_wh": calibration["size_wh"],
    }


def verify_scope(acquisition, protected):
    exclusions = set()
    for key in (
        "protected_public_source_logs",
        "protected_official_val_source_logs",
        "quarantined_mini_source_logs",
    ):
        exclusions.update(protected[key])
    seen, log_roles = set(), {}
    protected_dates = {tuple(pair) for pair in protected["protected_public_city_dates"]}
    role_dates = defaultdict(set)
    for window in acquisition["windows"]:
        name, log, role = (
            window["window"],
            window["source_log"],
            window["proposed_role"],
        )
        if (
            name in seen
            or log in exclusions
            or role not in ("pilot_training", "pilot_validation")
        ):
            raise ValueError("Duplicate, excluded, or unassigned acquisition window")
        if log not in protected["roles"][role]["source_logs"] or (
            log in log_roles and log_roles[log] != role
        ):
            raise ValueError("Whole-log split mismatch")
        date_group = (window["city"], window["date"])
        if date_group in protected_dates:
            raise ValueError("Acquisition shares a protected public city/date")
        role_dates[role].add(date_group)
        seen.add(name)
        log_roles[log] = role
    if not seen:
        raise ValueError("Acquisition manifest has no windows")
    if role_dates["pilot_training"] & role_dates["pilot_validation"]:
        raise ValueError("Original acquisition roles share a city/date")


def diagnose(acquisition_path, output, map_root=DEFAULT_MAP_ROOT):
    """Small CPU checks across available cities; never activates training roles."""
    acquisition_path, output = Path(acquisition_path).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Refusing to overwrite diagnostic output")
    acquired = json.loads(acquisition_path.read_text())
    protected = json.loads(PROTECTED.read_text())
    verify_scope(acquired, protected)
    image_root = Path(
        acquired.get("sensor_root", acquisition_path.parent / "sensor_blobs")
    ).resolve()
    output.mkdir(parents=True)
    write_json(output / "acquisition-snapshot.json", acquired)
    results, verified = [], set()
    cities = sorted({w["city"] for w in acquired["windows"]})
    for city in cities:
        # First part per city is fixed by archive identity, not quality scores.
        window = min(
            (w for w in acquired["windows"] if w["city"] == city),
            key=lambda w: w["part"],
        )
        times, poses, origin, calibration, _ = load_recording(
            window["metadata_database"]
        )
        router = RuntimeMapRouter(Path(map_root) / f"{CITY_NAMES[city]}.pb", origin)
        images = sorted(window["images"], key=lambda r: r["timestamp_us"])
        indices = np.linspace(4, len(images) - 12, 5).round().astype(int)
        for index in indices:
            row = {"window": window["window"], "city": city, "image_index": int(index)}
            try:
                triplet = select_triplet(images, int(index))
                t, current, inputs, targets, state = causal_example(
                    times, poses, [i["timestamp_us"] for i in triplet]
                )
                inputs["route"], inputs["route_mask"], route = router.example_route(
                    times, poses, current, t
                )
                validate_arrays(inputs, targets)
                selected = [
                    checked_image(image_root, i, calibration, verified) for i in triplet
                ]
                row.update(
                    passed=True,
                    time_us=t,
                    image_age_s=inputs["image_age_s"].tolist(),
                    ego_state=inputs["ego_state"].tolist(),
                    route_points=int(inputs["route_mask"].sum()),
                    target_shape=list(targets["waypoints"].shape),
                    images=selected,
                    motion=motion_category(inputs, targets),
                    route_provenance=route,
                    ego_state_provenance=state,
                )
            except ValueError as exc:
                row.update(passed=False, error=str(exc))
            results.append(row)
    parity = reference_route_parity(map_root)
    report = {
        "mode": "CPU_only_no_training_no_new_role_assignment",
        "route_parity": parity,
        "anchors": results,
        "passed": sum(r["passed"] for r in results),
        "checked": len(results),
        "exporter_sha256": file_hash(__file__),
        "original_roles": dict(
            Counter(w["proposed_role"] for w in acquired["windows"])
        ),
    }
    write_json(output / "diagnostic.json", report)
    return {
        "report": str(output / "diagnostic.json"),
        "passed": report["passed"],
        "checked": report["checked"],
        "route_parity_passed": parity["passed"],
    }


def export(
    acquisition_path,
    output,
    max_train=5000,
    max_validation=1000,
    map_root=DEFAULT_MAP_ROOT,
    pilot_split=None,
):
    acquisition_path, output = Path(acquisition_path).resolve(), Path(output).resolve()
    if output.exists() or not 1 <= max_train <= 5000 or not 1 <= max_validation <= 1000:
        raise ValueError("Output exists or export exceeds 5000/1000 bounds")
    acquisition_bytes = acquisition_path.read_bytes()
    acquisition_sha256 = hashlib.sha256(acquisition_bytes).hexdigest()
    acquisition = json.loads(acquisition_bytes)
    protected_sha256 = file_hash(PROTECTED)
    protected = json.loads(PROTECTED.read_text())
    if file_hash(PUBLIC) != protected["public_manifest_sha256"]:
        raise ValueError("Protected public manifest changed")
    verify_scope(acquisition, protected)
    from .raw_dataset import activate_roles

    split_path = Path(pilot_split).resolve() if pilot_split is not None else None
    split_json = json.loads(split_path.read_text()) if split_path is not None else None
    split_sha256 = file_hash(split_path) if split_path is not None else None
    role_by_log = activate_roles(
        protected,
        acquisition,
        split_json,
        protected_sha256=protected_sha256,
        acquisition_sha256=acquisition_sha256,
    )
    image_root = Path(
        acquisition.get(
            "image_root",
            acquisition.get("sensor_root", acquisition_path.parent / "sensor_blobs"),
        )
    ).resolve()
    by_role = defaultdict(list)
    for window in acquisition["windows"]:
        effective_role = (
            "pilot_training"
            if role_by_log[window["source_log"]] == "train"
            else "pilot_validation"
        )
        by_role[effective_role].append(window)
    if not by_role["pilot_training"] or not by_role["pilot_validation"]:
        raise ValueError(
            "Need distinct authorized train and validation logs before corpus export"
        )
    caps = {"pilot_training": max_train, "pilot_validation": max_validation}
    parity = reference_route_parity(map_root)
    if not parity["passed"]:
        raise ValueError("Saved-ASL route algorithm parity check failed")
    output.mkdir(parents=True)
    # Acquisition updates in the background; bind exports to these exact receipts.
    acquisition_snapshot = output / "acquisition-snapshot.json"
    with acquisition_snapshot.open("xb") as stream:
        stream.write(acquisition_bytes)
    samples, sources, rejected, verified = [], [], Counter(), set()
    per_log_counts = Counter()
    accepted_times = defaultdict(list)
    try:
        for proposed_role in ("pilot_training", "pilot_validation"):
            windows = sorted(
                by_role[proposed_role], key=lambda w: (w["source_log"], w["window"])
            )
            logs = sorted({w["source_log"] for w in windows})
            log_caps = (
                {
                    log: caps[proposed_role] // len(logs)
                    + (i < caps[proposed_role] % len(logs))
                    for i, log in enumerate(logs)
                }
                if logs
                else {}
            )
            for window in windows:
                log = window["source_log"]
                remaining = log_caps[log] - per_log_counts[log]
                if remaining <= 0:
                    continue
                db_path = Path(window["metadata_database"]).resolve()
                db_sha = file_hash(db_path)
                if window.get("metadata_sha256") not in (None, db_sha):
                    raise ValueError("DB differs from acquisition receipt")
                times, poses, origin, calibration, db_images = load_recording(db_path)
                images = sorted(window["images"], key=lambda r: r["timestamp_us"])
                for image in images:
                    identity = db_images.get(image["filename"])
                    if identity != (
                        int(image["timestamp_us"]),
                        int(image["ego_pose_timestamp_us"]),
                    ):
                        raise ValueError(
                            "Acquisition image identity does not match source DB"
                        )
                router = RuntimeMapRouter(
                    Path(map_root) / f"{CITY_NAMES[window['city']]}.pb", origin
                )
                # Evenly spread bounded candidates through each window; all tests are score-blind.
                candidates = []
                last_time = None
                for index, image in enumerate(images):
                    stamp = int(image["timestamp_us"])
                    if (
                        stamp < times[0] + 1_100_000
                        or stamp > times[-1] - 4_600_000
                        or (last_time is not None and stamp - last_time < 999_000)
                    ):
                        continue
                    candidates.append(index)
                    last_time = stamp
                candidates = spread_candidates(candidates, remaining)
                accepted = 0
                for index in candidates:
                    if accepted >= remaining:
                        break
                    try:
                        triplet = select_triplet(images, index)
                        t, current, inputs, targets, state_provenance = causal_example(
                            times, poses, [i["timestamp_us"] for i in triplet]
                        )
                        exposure = int(triplet[-1]["timestamp_us"])
                        if any(
                            abs(exposure - old) < 999_000 for old in accepted_times[log]
                        ):
                            raise ValueError(
                                "Anchor too close to an accepted same-log example"
                            )
                        inputs["route"], inputs["route_mask"], route_provenance = (
                            router.example_route(times, poses, current, t)
                        )
                        validate_arrays(inputs, targets)
                        selected_images = [
                            checked_image(image_root, i, calibration, verified)
                            for i in triplet
                        ]
                    except ValueError as exc:
                        rejected[str(exc)] += 1
                        continue
                    sample_id = hashlib.sha256(
                        f"{window['window']}:{t}".encode()
                    ).hexdigest()[:24]
                    input_name, target_name = (
                        f"{sample_id}.inputs.npz",
                        f"{sample_id}.targets.npz",
                    )
                    with (output / input_name).open("xb") as stream:
                        np.savez_compressed(stream, **inputs)
                    with (output / target_name).open("xb") as stream:
                        np.savez_compressed(stream, **targets)
                    samples.append(
                        {
                            "sample_id": sample_id,
                            "source_log": log,
                            "city": window["city"],
                            "date": window["date"],
                            "recording_window": window["window"],
                            "time_us": t,
                            "role": (
                                "train"
                                if proposed_role == "pilot_training"
                                else "validation"
                            ),
                            "inputs": input_name,
                            "targets": target_name,
                            "inputs_sha256": file_hash(output / input_name),
                            "targets_sha256": file_hash(output / target_name),
                            "images": selected_images,
                            "calibration": calibration,
                            "route_provenance": route_provenance,
                            "ego_state_provenance": state_provenance,
                            "metadata_database": str(db_path),
                            "metadata_database_sha256": db_sha,
                            "target_time_basis": "time_now_us_plus_0.1_to_4.0_seconds",
                            "target_pose_reference": "same_current_rear_axle_yaw_frame_as_inputs",
                            "motion": motion_category(inputs, targets),
                        }
                    )
                    accepted += 1
                    per_log_counts[log] += 1
                    accepted_times[log].append(exposure)
                if file_hash(db_path) != db_sha:
                    raise ValueError("Source DB changed during export")
                sources.append(
                    {
                        "recording_window": window["window"],
                        "source_log": log,
                        "metadata_database": str(db_path),
                        "sha256": db_sha,
                        "accepted": accepted,
                        "candidate_count": len(candidates),
                    }
                )
                print(
                    f"Exported {window['window']}: {accepted} {proposed_role} examples",
                    flush=True,
                )
        if (
            not samples
            or not any(s["role"] == "train" for s in samples)
            or not any(s["role"] == "validation" for s in samples)
        ):
            raise ValueError(
                "No valid train/validation corpus; never substitute protected scenes"
            )
        if (
            file_hash(PROTECTED) != protected_sha256
            or file_hash(PUBLIC) != protected["public_manifest_sha256"]
        ):
            raise ValueError("Protected sources changed during export")
        if split_path is not None and file_hash(split_path) != split_sha256:
            raise ValueError("Activated pilot split changed during export")
        manifest = {
            "schema_version": 1,
            "contract": CONTRACT,
            "data_kind": "real_nuplan_camera_expert_aligned",
            "status": "exported_for_local_training",
            "submission_allowed": False,
            "image_root": str(image_root),
            "ego_state_recipe": STATE_RECIPE,
            "protected_split": {"path": str(PROTECTED), "sha256": file_hash(PROTECTED)},
            "public_manifest": {"path": str(PUBLIC), "sha256": file_hash(PUBLIC)},
            "acquisition_manifest": {
                "path": str(acquisition_snapshot),
                "sha256": file_hash(acquisition_snapshot),
            },
            "route_recipe": ROUTE_RECIPE,
            "samples": samples,
            "sources": sources,
            "route_algorithm_parity": parity,
            "rejected_candidates": dict(rejected),
            "source_log_sample_counts": dict(per_log_counts),
            "exporter_sha256": file_hash(__file__),
            "motion_bins_by_role": {
                role: {
                    name: dict(
                        Counter(s["motion"][name] for s in samples if s["role"] == role)
                    )
                    for name in ("maneuver", "speed_bin")
                }
                for role in ("train", "validation")
            },
            "limits": "Local-only real-camera head training; private-scene route context and real-to-rendered transfer are not certified",
        }
        if split_path is not None:
            manifest["pilot_split"] = {"path": str(split_path), "sha256": split_sha256}
        write_json(output / "dataset.json", manifest)
    except BaseException as exc:
        write_json(
            output / "FAILED.json",
            {"error": repr(exc), "partial_samples": len(samples)},
        )
        raise
    return {
        "dataset": str(output / "dataset.json"),
        "samples": len(samples),
        "roles": dict(Counter(s["role"] for s in samples)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-train", default=5000, type=int)
    parser.add_argument("--max-validation", default=1000, type=int)
    parser.add_argument("--map-root", default=DEFAULT_MAP_ROOT, type=Path)
    parser.add_argument(
        "--pilot-split",
        type=Path,
        help="Separately user-approved whole-log/date assignment; never edits old splits",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            export(
                args.acquisition_manifest,
                args.output,
                args.max_train,
                args.max_validation,
                args.map_root,
                args.pilot_split,
            )
        )
    )


if __name__ == "__main__":
    main()
