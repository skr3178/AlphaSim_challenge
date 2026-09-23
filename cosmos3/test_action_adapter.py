"""CPU-only conversion checks; no model or simulator calls."""
import unittest
import numpy as np
from scipy.spatial.transform import Rotation
from action_adapter import decode_rig_poses, build_trajectory, validate_timestamps


class AdapterTests(unittest.TestCase):
    def setUp(self):
        # OpenCV camera right/down/forward -> vehicle forward/left/up.
        self.camera = np.eye(4)
        self.camera[:3, :3] = [[0, 0, 1], [-1, 0, 0], [0, -1, 0]]
        self.camera[:3, 3] = [1.5, 0.0, 1.4]

    def test_forward_scale_and_column_layout(self):
        actions = np.tile([0, 0, 1.35, 1, 0, 0, 0, 1, 0], (4, 1))
        poses = decode_rig_poses(actions, self.camera, np.eye(4))
        np.testing.assert_allclose(poses[:, 0, 3], np.arange(5), atol=1e-6)
        np.testing.assert_allclose(poses[:, 1:3, 3], 0, atol=1e-6)

    def test_turn_extrinsic_lever_arm_and_global_frame(self):
        expected = np.repeat(np.eye(4)[None], 5, axis=0)
        expected[:, :3, :3] = Rotation.from_euler("z", (np.arange(5) * 0.1)[:, None]).as_matrix()
        expected[:, 0, 3] = np.arange(5)
        cameras = expected @ self.camera
        delta = np.linalg.inv(cameras[:-1]) @ cameras[1:]
        actions = np.concatenate([delta[:, :3, 3] * 1.35, delta[:, :3, 0], delta[:, :3, 1]], axis=1)
        origin = np.eye(4)
        origin[:3, :3] = Rotation.from_euler("z", 0.7).as_matrix()
        origin[:3, 3] = [10, -4, 2]
        actual = decode_rig_poses(actions, self.camera, origin)
        np.testing.assert_allclose(actual, origin @ expected, atol=2e-6)

    def test_invalid_actions_fail(self):
        for actions in [np.zeros((4, 9)), np.full((4, 9), np.nan), np.zeros((4, 8))]:
            with self.assertRaises(ValueError):
                decode_rig_poses(actions, self.camera, np.eye(4))

    def test_protobuf_time_and_planar_contract(self):
        from alpasim_grpc.v0 import common_pb2
        actions = np.tile([1.35, 0, 0, 1, 0, 0, 0, 1, 0], (40, 1))
        identity = common_pb2.Pose(quat=common_pb2.Quat(w=1))
        latest = common_pb2.PoseAtTime(timestamp_us=500_000, pose=identity)
        traj, _ = build_trajectory(actions, identity, latest, 500_000)
        self.assertEqual(len(traj.poses), 41)
        self.assertEqual(traj.poses[-1].timestamp_us, 4_500_000)
        self.assertAlmostEqual(traj.poses[-1].pose.vec.x, 40, places=5)
        self.assertTrue(all(p.pose.quat.w == 1 for p in traj.poses))

    def test_real_exposure_end_and_control_query_timestamps(self):
        validate_timestamps(17_000, 0, 17_000, 17_000, 517_000)
        validate_timestamps(517_000, 500_000, 517_000, 517_000, 1_017_000)
        with self.assertRaises(ValueError):
            validate_timestamps(517_000, 0, 17_000, 517_000, 1_017_000)
        with self.assertRaises(ValueError):
            validate_timestamps(17_000, 0, 17_000, 17_000, 5_017_000)


if __name__ == "__main__":
    unittest.main()
