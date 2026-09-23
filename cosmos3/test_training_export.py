"""Temporary protobuf fixtures for ASL export. No real data or policy is fitted."""

import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

# Use the installed local AlpaSim protobuf source; no packages are installed.
GRPC_SOURCE = Path("/home/skr/alpasim-challenge/alpasim/src/grpc")
sys.path.insert(0, str(GRPC_SOURCE))
from alpasim_grpc.v0.logging_pb2 import LogEntry

from cosmos3.training.contracts import file_hash, load_pilot, write_json
from cosmos3.training.dataset import DrivingDataset
from cosmos3.training.export_asl import entries, export

PILOT = Path(__file__).resolve().parent / "pilots/real-driving-v1/manifest.json"


def fixture_asl(
    path,
    scene,
    offset=0,
    future_camera=False,
    post_priming=False,
    nan_route_padding=False,
):
    session = "unit-fixture-session"
    t = 517_000 if post_priming else 17_000
    messages = []
    message = LogEntry()
    meta = message.rollout_metadata
    meta.session_metadata.scene_id = scene
    meta.session_metadata.session_uuid = session
    meta.session_metadata.start_timestamp_us = 0
    meta.force_gt_duration = 500_000
    meta.transform_ego_coords_rig_to_aabb.quat.w = 1
    meta.transform_ego_coords_rig_to_aabb.vec.x = 1.461
    for stamp in range(0, 5_100_000, 100_000):
        p = meta.ego_rig_recorded_ground_truth_trajectory.poses.add(timestamp_us=stamp)
        p.pose.quat.w = 1
        p.pose.vec.x = stamp / 1e6 * 4
    messages.append(message)
    for stamp in [0, 17_000, 500_000, 517_000, 1_017_000]:
        message = LogEntry()
        message.actor_poses.timestamp_us = stamp
        actor = message.actor_poses.actor_poses.add(actor_id="EGO")
        actor.actor_pose.quat.w = 1
        actor.actor_pose.vec.x = stamp / 1e6 * 4 + 1.461
        actor.actor_pose.vec.y = offset
        messages.append(message)
    message = LogEntry()
    session_request = message.driver_session_request
    session_request.session_uuid = session
    c = session_request.rollout_spec.vehicle.available_cameras.add(logical_id="CAM_F0")
    c.rig_to_camera.quat.w = 1
    c.intrinsics.resolution_w, c.intrinsics.resolution_h = 32, 16
    c.intrinsics.opencv_pinhole_param.focal_length_x = 20
    c.intrinsics.opencv_pinhole_param.focal_length_y = 20
    messages.append(message)
    buffer = io.BytesIO()
    Image.new("RGB", (32, 16), "gray").save(buffer, format="JPEG")
    message = LogEntry()
    message.driver_camera_image.session_uuid = session
    camera = message.driver_camera_image.camera_image
    camera.logical_id = "CAM_F0"
    camera.frame_start_us = t - 17_000
    camera.frame_end_us = t + (1 if future_camera else 0)
    camera.image_bytes = buffer.getvalue()
    messages.append(message)
    message = LogEntry()
    value = message.driver_ego_trajectory
    value.session_uuid = session
    p = value.trajectory.poses.add(timestamp_us=t)
    p.pose.quat.w = 1
    p.pose.vec.x = t / 1e6 * 4
    p.pose.vec.y = offset
    value.dynamic_states.add().linear_velocity.x = 4
    messages.append(message)
    message = LogEntry()
    message.route_request.session_uuid = session
    message.route_request.route.timestamp_us = t
    message.route_request.route.waypoints.add(x=20)
    if nan_route_padding:
        message.route_request.route.waypoints.add(
            x=float("nan"), y=float("nan"), z=float("nan")
        )
    messages.append(message)
    message = LogEntry()
    message.driver_request.session_uuid = session
    message.driver_request.time_now_us = t
    message.driver_request.time_query_us = t + 500_000
    messages.append(message)
    with path.open("xb") as stream:
        for message in messages:
            payload = message.SerializeToString()
            stream.write(struct.pack(">L", len(payload)))
            stream.write(payload)


class ExportTests(unittest.TestCase):
    def test_realistic_nan_route_padding_export(self):
        result = self.run_export(nan_route_padding=True)
        data = DrivingDataset(result["dataset"], PILOT)
        self.assertEqual(data.samples[0]["route_nan_padding_rows"], 1)
        self.assertEqual(int(data.items[0][0]["route_mask"].sum()), 1)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pilot = load_pilot(PILOT)
        (self.root / "fixture-terms.txt").write_text(
            "UNIT FIXTURE ONLY, not actual terms"
        )
        write_json(
            self.root / "rules.json",
            {
                "decision": "permitted",
                "scope": "training_on_approved_public_navtest_scenes",
                "pilot_manifest_sha256": file_hash(PILOT),
                "reviewed_by": "unit-test",
                "reviewed_at_utc": "2026-09-19T00:00:00Z",
                "source_description": "temporary test fixture",
                "evidence_file": "fixture-terms.txt",
                "evidence_sha256": file_hash(self.root / "fixture-terms.txt"),
            },
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_export(self, **kwargs):
        fixture_asl(
            self.root / "log.asl", self.pilot["samples"][0]["scene_id"], **kwargs
        )
        return export(
            PILOT,
            [self.root / "log.asl"],
            self.root / "export",
            self.root / "rules.json",
        )

    def test_expert_sample_export_with_next_step_query(self):
        result = self.run_export()
        self.assertEqual(result["samples"], 1)
        dataset = DrivingDataset(self.root / "export/dataset.json", PILOT)
        inputs, targets = dataset.items[0]
        np.testing.assert_allclose(
            targets["waypoints"][:, 0], np.arange(1, 41) * 0.4, atol=1e-6
        )
        self.assertEqual(inputs["history_mask"].tolist(), [False, False, True])
        sample = dataset.samples[0]
        self.assertEqual(sample["query_time_us"] - sample["time_us"], 500_000)
        self.assertNotIn("waypoints", inputs)

    def test_off_reference_sample_rejected(self):
        with self.assertRaisesRegex(ValueError, "No eligible"):
            self.run_export(offset=1.0)
        self.assertFalse((self.root / "export/dataset.json").exists())
        self.assertTrue((self.root / "export/FAILED.json").exists())

    def test_future_camera_rejected(self):
        with self.assertRaisesRegex(ValueError, "No eligible"):
            self.run_export(future_camera=True)

    def test_post_priming_rejected(self):
        with self.assertRaisesRegex(ValueError, "No eligible"):
            self.run_export(post_priming=True)

    def test_export_refuses_existing_output(self):
        self.run_export()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            export(
                PILOT,
                [self.root / "log.asl"],
                self.root / "export",
                self.root / "rules.json",
            )

    def test_truncated_binary_log_rejected(self):
        (self.root / "broken.asl").write_bytes(b"\x00\x00")
        with self.assertRaisesRegex(ValueError, "Truncated"):
            list(entries(self.root / "broken.asl"))


if __name__ == "__main__":
    unittest.main()
