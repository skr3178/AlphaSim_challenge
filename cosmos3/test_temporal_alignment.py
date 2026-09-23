"""Synthetic geometry tests for the read-only temporal audit, no fitted models."""

from __future__ import annotations

from copy import deepcopy
import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from cosmos3.audit_temporal_alignment import audit_anchor, pose_error


def inputs():
    times = np.arange(0, 5_600_000, 100_000, dtype=np.int64)
    poses = np.repeat(np.eye(4)[None], len(times), axis=0)
    poses[:, 0, 3] = times / 1e6 * 4.0
    ego = {}
    for stamp in [0, 17_000, 517_000, 1_017_000]:
        ego[stamp] = np.eye(4)
        ego[stamp][0, 3] = stamp / 1e6 * 4.0
    return dict(
        time_us=1_017_000,
        query_us=1_517_000,
        priming_end=500_000,
        frames=[
            {"start_us": t - 17_000, "end_us": t, "decode_ok": True, "sha256": str(t)}
            for t in [17_000, 517_000, 1_017_000]
        ],
        ego=ego,
        route={"time_us": 1_017_000, "points": [[20, 0, 0]]},
        calibration_ok=True,
        reference_times=times,
        reference_poses=poses,
        true_times=times.copy(),
        true_poses=poses.copy(),
    )


class TemporalAuditTests(unittest.TestCase):
    def test_aligned_later_triplet_passes_without_relaxing_priming_exporter(self):
        result = audit_anchor(**inputs())
        self.assertTrue(result["candidate"])
        self.assertEqual(result["history_timestamps_us"], [17_000, 517_000, 1_017_000])

    def test_single_current_image_cannot_supply_history(self):
        data = inputs()
        data["frames"] = data["frames"][-1:]
        result = audit_anchor(**data)
        self.assertTrue(result["current_pose_aligned"])
        self.assertFalse(result["full_history"])
        self.assertFalse(result["candidate"])

    def test_future_frame_cannot_fill_a_missing_history_slot(self):
        data = inputs()
        data["frames"][0]["end_us"] += 1
        result = audit_anchor(**data)
        self.assertFalse(result["full_history"])

    def test_bad_decode_rejected(self):
        data = inputs()
        data["frames"][0]["decode_ok"] = False
        self.assertFalse(audit_anchor(**data)["candidate"])

    def test_alignment_requires_past_frames_not_only_current(self):
        data = inputs()
        data["ego"][517_000][1, 3] = 0.11
        result = audit_anchor(**data)
        self.assertTrue(result["current_pose_aligned"])
        self.assertFalse(result["history_pose_aligned"])

    def test_heading_error_is_checked(self):
        data = inputs()
        data["ego"][1_017_000][:3, :3] = Rotation.from_euler("z", 0.02).as_matrix()
        result = audit_anchor(**data)
        self.assertFalse(result["current_pose_aligned"])

    def test_actual_view_must_align_even_when_observed_pose_matches_expert(self):
        data = inputs()
        data["true_poses"][:, 1, 3] = 0.2
        result = audit_anchor(**data)
        self.assertFalse(result["current_pose_aligned"])
        self.assertFalse(result["exposure_boundaries_aligned"])

    def test_future_targets_not_extrapolated(self):
        data = inputs()
        data["reference_times"] = data["reference_times"][:51]
        data["reference_poses"] = data["reference_poses"][:51]
        result = audit_anchor(**data)
        # 1.017 + 4 = 5.017 s, NOT covered by a reference ending at 5.0 s.
        self.assertFalse(result["future_4s"])
        self.assertFalse(result["candidate"])

    def test_future_ego_pose_cannot_change_causal_state(self):
        data = inputs()
        expected = audit_anchor(**data)
        future = np.eye(4)
        future[0, 3] = 999
        data["ego"][2_000_000] = future
        actual = audit_anchor(**data)
        self.assertEqual(actual["speed_mps"], expected["speed_mps"])
        self.assertEqual(actual["candidate"], expected["candidate"])

    def test_future_route_rejected(self):
        data = inputs()
        data["route"]["time_us"] += 1
        self.assertFalse(audit_anchor(**data)["causal_inputs"])

    def test_invalid_route_rejected(self):
        data = inputs()
        data["route"]["points"] = [[np.nan] * 3]
        self.assertFalse(audit_anchor(**data)["causal_inputs"])

    def test_motion_consistency_is_separate_from_position_alignment(self):
        data = inputs()
        data["ego"][1_000_000] = data["ego"][1_017_000].copy()
        # Identical positions over the last 17 ms imply zero speed, unlike the expert.
        result = audit_anchor(**data)
        self.assertTrue(result["history_pose_aligned"])
        self.assertFalse(result["motion_consistent"])

    def test_yaw_wrap_uses_small_relative_angle(self):
        first, second = np.eye(4), np.eye(4)
        first[:3, :3] = Rotation.from_euler("z", np.pi - 0.001).as_matrix()
        second[:3, :3] = Rotation.from_euler("z", -np.pi + 0.001).as_matrix()
        self.assertAlmostEqual(pose_error(first, second)[1], 0.002)

    def test_inputs_not_modified(self):
        data = inputs()
        original = deepcopy(data)
        audit_anchor(**data)
        for t in original["ego"]:
            np.testing.assert_array_equal(data["ego"][t], original["ego"][t])
        self.assertEqual(data["frames"], original["frames"])


if __name__ == "__main__":
    unittest.main()
