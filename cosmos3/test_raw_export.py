"""CPU regression tests for raw-camera timing, frames, navigation and scope."""

import io
import pickle
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from cosmos3.training.export_raw import (
    CITY_NAMES,
    CalibrationReader,
    RuntimeMapRouter,
    calibration_array,
    causal_example,
    load_recording,
    select_triplet,
    spread_candidates,
    verify_scope,
)


def test_vegas_inventory_and_database_aliases_use_same_map():
    assert CITY_NAMES["vegas"] == CITY_NAMES["las_vegas"]
    assert CITY_NAMES["vegas"] == CITY_NAMES["us-nv-las-vegas-strip"]


@pytest.mark.parametrize("cumulative,error", [(np.array([]), ValueError), (np.array([1.0]), IndexError)])
def test_empty_runtime_extension_rejected_but_other_index_errors_propagate(cumulative, error):
    router = object.__new__(RuntimeMapRouter)
    router.vector_map = object()

    def broken(*args):
        raise IndexError("index -1 is out of bounds for axis 0 with size 0")

    def distances(position):
        assert position.flags.c_contiguous
        assert position.dtype == np.float32
        return cumulative, 0

    generator = SimpleNamespace(
        generate_route=broken,
        route_polyline_in_local=SimpleNamespace(
            get_cumulative_distances_from_point=distances
        ),
    )
    router.runtime = SimpleNamespace(RouteGeneratorMap=lambda *a, **k: generator)
    with pytest.raises(error):
        router.generate(np.array([[0, 0, 0], [1, 0, 0]]), np.eye(4), 0)


def recording(yaw=0.0):
    times = np.arange(0, 8_000_001, 10_000, dtype=np.int64)
    poses = np.repeat(np.eye(4)[None], len(times), axis=0)
    poses[:, :3, :3] = Rotation.from_euler("z", [yaw]).as_matrix()
    poses[:, 0, 3] = np.cos(yaw) * times / 1e6 * 5
    poses[:, 1, 3] = np.sin(yaw) * times / 1e6 * 5
    return times, poses


def test_history_allows_nominal_half_second_jitter_without_future():
    images = [{"timestamp_us": t} for t in (100, 500_120, 1_000_100, 1_500_200)]
    selected = select_triplet(images, 2)
    assert [i["timestamp_us"] for i in selected] == [100, 500_120, 1_000_100]


def test_history_rejects_missing_past_and_duplicate_images():
    with pytest.raises(ValueError, match="Missing"):
        select_triplet([{"timestamp_us": 0}, {"timestamp_us": 1_000_000}], 1)
    with pytest.raises(ValueError, match="unique"):
        select_triplet([{"timestamp_us": 0}, {"timestamp_us": 0}], 1)


def test_history_rejects_individually_valid_but_adjacent_bad_spacing():
    images = [{"timestamp_us": t} for t in (100_000, 450_000, 1_000_000)]
    with pytest.raises(ValueError, match="Noncausal"):
        select_triplet(images, 2)


def test_causal_anchor_is_actual_pose_after_exposure_and_labels_current_frame():
    times, poses = recording()
    now, _current, inputs, targets, provenance = causal_example(
        times, poses, [1_005_000, 1_505_000, 2_005_000]
    )
    assert now == 2_010_000
    np.testing.assert_allclose(inputs["image_age_s"], [1.005, 0.505, 0.005])
    np.testing.assert_allclose(inputs["ego_state"], [5, 0, 0], atol=1e-6)
    np.testing.assert_allclose(
        targets["waypoints"][:, 0], np.arange(1, 41) * 0.5, atol=1e-5
    )
    assert provenance["previous_received_timestamp_us"] < now


def test_inputs_do_not_change_when_unobserved_future_poses_change():
    times, poses = recording()
    stamps = [1_000_000, 1_500_000, 2_000_000]
    original = causal_example(times, poses, stamps)
    altered = poses.copy()
    altered[times > 2_000_000, 0, 3] += 20
    changed = causal_example(times, altered, stamps)
    for key in original[2]:
        np.testing.assert_array_equal(original[2][key], changed[2][key])
    assert not np.array_equal(original[3]["waypoints"], changed[3]["waypoints"])


def test_world_y_direction_becomes_forward_not_lateral():
    times, poses = recording(np.pi / 2)
    _, _, inputs, targets, _ = causal_example(
        times, poses, [1_000_000, 1_500_000, 2_000_000]
    )
    np.testing.assert_allclose(inputs["ego_state"], [5, 0, 0], atol=1e-6)
    np.testing.assert_allclose(targets["waypoints"][-1, :2], [20, 0], atol=1e-6)


def test_future_gap_and_target_extrapolation_rejected():
    times, poses = recording()
    keep = ~((times > 3_000_000) & (times < 3_500_000))
    with pytest.raises(ValueError, match="gap"):
        causal_example(times[keep], poses[keep], [1_000_000, 1_500_000, 2_000_000])
    with pytest.raises(ValueError, match="extrapolation"):
        causal_example(times, poses, [5_000_000, 5_500_000, 6_000_000])


def test_stale_pose_after_image_rejected():
    times, poses = recording()
    keep = ~((times >= 2_000_000) & (times <= 2_100_000))
    with pytest.raises(ValueError, match="fresh"):
        causal_example(times[keep], poses[keep], [1_000_000, 1_500_000, 2_000_000])


def test_safe_calibration_reader_rejects_code_globals():
    with pytest.raises(ValueError, match="Unsafe"):
        CalibrationReader(io.BytesIO(pickle.dumps(eval))).load()
    np.testing.assert_array_equal(
        calibration_array(pickle.dumps([[1, 0], [0, 1]]), (2, 2)), np.eye(2)
    )
    with pytest.raises(ValueError, match="Invalid"):
        calibration_array(pickle.dumps([float("nan")]))


def create_db(path, bad_quaternion=False):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE ego_pose(token BLOB,timestamp INTEGER,x REAL,y REAL,z REAL,qw REAL,qx REAL,qy REAL,qz REAL);
            CREATE TABLE camera(token BLOB,channel TEXT,model TEXT,translation BLOB,rotation BLOB,intrinsic BLOB,distortion BLOB,width INT,height INT);
            CREATE TABLE image(filename_jpg TEXT,timestamp INTEGER,ego_pose_token BLOB,camera_token BLOB);
        """)
        q = Rotation.from_euler("xyz", [0.1, 0.2, 0.3]).as_quat()
        if bad_quaternion:
            q *= 2
        for i in range(4):
            db.execute(
                "INSERT INTO ego_pose VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    bytes([i]),
                    1_000_000 + i * 10_000,
                    600_000 + i * 0.05,
                    4_000_000,
                    250,
                    q[3],
                    *q[:3],
                ),
            )
        db.execute(
            "INSERT INTO camera VALUES(?,?,?,?,?,?,?,?,?)",
            (
                b"c",
                "CAM_F0",
                "test",
                pickle.dumps([1.6, 0, 1.5]),
                pickle.dumps([1, 0, 0, 0]),
                pickle.dumps([[1545, 0, 960], [0, 1545, 560], [0, 0, 1]]),
                pickle.dumps([0] * 5),
                1920,
                1080,
            ),
        )
        db.execute(
            "INSERT INTO image VALUES(?,?,?,?)",
            ("log/CAM_F0/a.jpg", 1_010_000, bytes([1]), b"c"),
        )


def test_recording_reader_does_not_shift_rear_axle_and_removes_roll_pitch(tmp_path):
    path = tmp_path / "source.db"
    create_db(path)
    _times, poses, origin, calibration, images = load_recording(path)
    np.testing.assert_allclose(origin, [600_000, 4_000_000, 250])
    np.testing.assert_allclose(poses[0, :3, 3], [0, 0, 0])
    np.testing.assert_allclose(poses[1, :3, 3], [0.05, 0, 0])
    np.testing.assert_allclose(
        poses[0, :3, :3], Rotation.from_euler("z", [0.3]).as_matrix(), atol=1e-7
    )
    assert images["log/CAM_F0/a.jpg"] == (1_010_000, 1_010_000)
    assert calibration["pose_convention"] == "nuplan_ego_pose_rear_axle_xyz_yaw_only"


def test_recording_rejects_bad_quaternion(tmp_path):
    path = tmp_path / "source.db"
    create_db(path, bad_quaternion=True)
    with pytest.raises(ValueError, match="Nonunit"):
        load_recording(path)


def test_even_spread_primaries_cover_window_before_replacements():
    ordered = spread_candidates(list(range(100)), 5)
    assert ordered[:5] == [0, 25, 50, 74, 99]
    assert set(ordered) == set(range(100)) and len(ordered) == 100


def test_runtime_map_route_has_40m_offset_not_near_term_target(tmp_path):
    pytest.importorskip("alpasim_runtime.route_generator")
    from trajdata.maps import VectorMap
    from trajdata.maps.vec_map_elements import Polyline, RoadLane

    vector = VectorMap("nuplan_test:boston", extent=np.array([0, 0, 0, 200, 10, 0]))
    center = np.column_stack([np.linspace(0, 200, 201), np.zeros((201, 3))])
    vector.add_map_element(RoadLane("lane", center=Polyline(center)))
    path = tmp_path / "boston.pb"
    path.write_bytes(vector.to_proto().SerializeToString())
    router = RuntimeMapRouter(path, np.zeros(3))
    trajectory = np.column_stack([np.linspace(0, 25, 56), np.zeros((56, 2))])
    points = router.generate(trajectory, np.eye(4), 1_000_000)
    finite = np.isfinite(points).all(axis=1)
    assert finite.sum() == 10
    assert points[finite, 0].min() >= 40
    np.testing.assert_allclose(np.diff(points[finite, 0]), 80 / 19, atol=1e-4)


def test_scope_blocks_protected_and_cross_date_roles():
    protected = {
        "protected_public_source_logs": ["p"],
        "protected_official_val_source_logs": [],
        "quarantined_mini_source_logs": [],
        "protected_public_city_dates": [],
        "roles": {
            "pilot_training": {"source_logs": ["a"]},
            "pilot_validation": {"source_logs": ["b"]},
        },
    }
    acq = {
        "windows": [
            {
                "window": "a1",
                "source_log": "a",
                "proposed_role": "pilot_training",
                "city": "boston",
                "date": "d1",
            },
            {
                "window": "b1",
                "source_log": "b",
                "proposed_role": "pilot_validation",
                "city": "boston",
                "date": "d2",
            },
        ]
    }
    verify_scope(acq, protected)
    acq["windows"][1]["date"] = "d1"
    with pytest.raises(ValueError, match="city/date"):
        verify_scope(acq, protected)
    acq["windows"][1]["source_log"] = "p"
    with pytest.raises(ValueError, match="excluded"):
        verify_scope(acq, protected)
