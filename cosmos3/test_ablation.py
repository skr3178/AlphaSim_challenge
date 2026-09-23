"""Causal state, fixed split and matched visual ablation CPU tests."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from cosmos3.ablation_scope import PILOT, proposal, validate
from cosmos3.run_ablation import FeatureArm, require_role, state_hash
from cosmos3.training.state_adapter import received_pose_state


class StateTests(unittest.TestCase):
    def test_rotated_forward_velocity(self):
        for yaw in (0, np.pi / 2, -2.0):
            old = np.eye(4)
            old[:3, :3] = Rotation.from_euler("z", yaw).as_matrix()
            now = old.copy()
            now[:3, 3] = old[:3, :3] @ np.array([0.068, 0, 0])
            state, meta = received_pose_state({0: old, 17000: now}, 17000)
            np.testing.assert_allclose(state, [4, 0, 0], atol=1e-6)
            self.assertEqual(meta["previous_received_timestamp_us"], 0)

    def test_yaw_wrap_and_current_frame(self):
        old = np.eye(4)
        old[:3, :3] = Rotation.from_euler("z", np.pi - 0.001).as_matrix()
        now = old.copy()
        now[:3, :3] = Rotation.from_euler("z", np.pi + 0.001).as_matrix()
        now[:3, 3] = now[:3, :3] @ np.array([0.08, 0.01, 0])
        state, _ = received_pose_state({0: old, 20000: now}, 20000)
        np.testing.assert_allclose(state, [4, 0.5, 0.1], atol=1e-6)

    def test_future_ignored_and_translation_invariant(self):
        old, now = np.eye(4), np.eye(4)
        now[0, 3] = 0.08
        wanted, _ = received_pose_state({0: old, 20000: now}, 20000)
        old[:3, 3] += 10000
        now[:3, 3] += 10000
        state, _ = received_pose_state(
            {0: old, 20000: now, 30000: np.full((4, 4), np.nan)}, 20000
        )
        np.testing.assert_allclose(state, wanted, atol=1e-5)

    def test_gaps_missing_past_or_current_rejected(self):
        for poses, t in (
            ({17000: np.eye(4)}, 17000),
            ({0: np.eye(4)}, 17000),
            ({0: np.eye(4), 5000: np.eye(4)}, 5000),
            ({0: np.eye(4), 700000: np.eye(4)}, 700000),
        ):
            with self.assertRaises(ValueError):
                received_pose_state(poses, t)

    def test_non_rigid_and_implausible_rejected(self):
        for matrix in (
            np.zeros((4, 4)),
            np.diag([2, 1, 1, 1]),
            np.full((4, 4), np.nan),
        ):
            with self.assertRaises(ValueError):
                received_pose_state({0: np.eye(4), 17000: matrix}, 17000)
        now = np.eye(4)
        now[0, 3] = 20
        with self.assertRaises(ValueError):
            received_pose_state({0: np.eye(4), 17000: now}, 17000)


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.auth = PILOT.parent / "AUTHORIZATION.md"
        self.value = proposal(self.auth)

    def test_split_fixed_and_log_disjoint(self):
        self.assertEqual(validate(PILOT, self.value), self.value)
        self.assertEqual(len(self.value["training_scene_ids"]), 10)
        self.assertEqual(len(self.value["evaluation_scene_ids"]), 9)
        self.assertFalse(
            set(self.value["training_source_logs"])
            & set(self.value["evaluation_source_logs"])
        )
        self.assertEqual(len(set(self.value["evaluation_source_logs"])), 9)
        protected = {s for ids in self.value["protected_suites"].values() for s in ids}
        self.assertFalse(protected & set(self.value["evaluation_scene_ids"]))

    def test_budget_split_or_state_tamper_rejected(self):
        for change in ("budget", "evaluation", "state", "submission"):
            value = json.loads(json.dumps(self.value))
            if change == "budget":
                value["ablation"]["optimizer_steps_per_arm"] = 101
            elif change == "evaluation":
                value["evaluation_scene_ids"][0] = value["training_scene_ids"][0]
            elif change == "state":
                value["ego_state_recipe"] = "logged"
            else:
                value["submission_allowed"] = True
            with self.assertRaises(ValueError):
                validate(PILOT, value)

    def test_role_rejects_test_samples_as_training(self):
        from types import SimpleNamespace

        data = SimpleNamespace(
            samples=[{"scene_id": s} for s in self.value["evaluation_scene_ids"]]
        )
        with self.assertRaises(ValueError):
            require_role(data, self.value, "training")

    def test_generic_fit_cannot_mix_ablation_train_and_evaluation(self):
        from cosmos3.training.contracts import write_json
        from cosmos3.training.runner import train_head
        import shutil

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(self.auth, root / self.auth.name)
            scope = root / "manifest.json"
            write_json(scope, self.value)
            with self.assertRaisesRegex(ValueError, "matched ablation runner"):
                train_head(
                    scope,
                    root / "unused",
                    root / "unused",
                    root / "unused",
                    None,
                    local_only=True,
                )

    def test_causal_realistic_export_uses_past_not_logged_state(self):
        from alpasim_grpc.v0.logging_pb2 import LogEntry
        from cosmos3.test_training_export import fixture_asl
        from cosmos3.training.contracts import write_json
        from cosmos3.training.dataset import DrivingDataset
        from cosmos3.training.export_asl import entries, export
        import struct
        import shutil

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(self.auth, root / self.auth.name)
            scope = root / "manifest.json"
            write_json(scope, self.value)
            source = root / "source.asl"
            fixture_asl(
                source, self.value["training_scene_ids"][0], nan_route_padding=True
            )
            corrected = root / "with-past.asl"
            with corrected.open("xb") as stream:
                for kind, value in entries(source):
                    if kind == "driver_ego_trajectory":
                        old = value.trajectory.poses.add(timestamp_us=0)
                        old.pose.quat.w = 1
                        value.dynamic_states.add().linear_velocity.x = -90
                        value.dynamic_states[0].linear_velocity.y = 20
                    message = LogEntry()
                    getattr(message, kind).CopyFrom(value)
                    payload = message.SerializeToString()
                    stream.write(struct.pack(">L", len(payload)))
                    stream.write(payload)
            result = export(
                scope, [corrected], root / "samples", None, 1, local_only=True
            )
            data = DrivingDataset(result["dataset"], scope)
            np.testing.assert_allclose(
                data.items[0][0]["ego_state"], [4, 0, 0], atol=1e-6
            )
            self.assertGreater(
                data.samples[0]["ego_state_provenance"]["velocity_difference_mps"], 19
            )


class ArmTests(unittest.TestCase):
    def test_zero_visual_preserves_every_other_input_and_targets(self):
        import torch

        class Data:
            def __len__(self):
                return 2

            def batch(self, indices, device):
                return {
                    "features": torch.ones(2, 3, 32, 2048),
                    "ego_state": torch.ones(2, 3),
                }, {"waypoints": torch.ones(2, 40, 4)}

        a, ta = FeatureArm(Data(), "cosmos").batch([0, 1])
        b, tb = FeatureArm(Data(), "state_route_only").batch([0, 1])
        self.assertTrue(a["features"].any())
        self.assertFalse(b["features"].any())
        self.assertTrue(torch.equal(a["ego_state"], b["ego_state"]))
        self.assertTrue(torch.equal(ta["waypoints"], tb["waypoints"]))

    def test_seeded_initial_weights_identical(self):
        import torch
        from cosmos3.training.head import WaypointHead

        torch.manual_seed(20260919)
        first = state_hash(WaypointHead())
        torch.manual_seed(20260919)
        self.assertEqual(first, state_hash(WaypointHead()))


if __name__ == "__main__":
    unittest.main()
