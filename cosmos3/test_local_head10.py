"""CPU checks for local-only scope; no real fitting or pretrained model load."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from cosmos3.prepare_local_head10 import proposal
from cosmos3.training.contracts import load_pilot, require_run_authorization, write_json
from cosmos3.training.dataset import DrivingDataset
from cosmos3.training.export_asl import export
from cosmos3.report_local_head10 import pose_velocity

ROOT = Path(__file__).resolve().parent
OLD_PILOT = ROOT / "pilots/real-driving-v1/manifest.json"


class LocalScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.approval = self.root / "AUTHORIZATION.md"
        shutil.copyfile(ROOT / "pilots/local-head10-v1/AUTHORIZATION.md", self.approval)
        self.value = proposal(self.approval)
        self.path = self.root / "manifest.json"
        write_json(self.path, self.value)

    def tearDown(self):
        self.temp.cleanup()

    def test_ten_scenes_same_four_logs_protected_suites_unchanged(self):
        pilot = load_pilot(self.path)
        old = load_pilot(OLD_PILOT)
        self.assertEqual(len(pilot["samples"]), 10)
        self.assertEqual(pilot["training_source_logs"], old["training_source_logs"])
        self.assertEqual(pilot["protected_suites"], old["protected_suites"])
        self.assertEqual(
            pilot["excluded_scene_ids_for_candidate_evaluation"],
            old["excluded_scene_ids_for_candidate_evaluation"],
        )

    def test_local_requires_explicit_acknowledgement(self):
        with self.assertRaisesRegex(ValueError, "explicit --local-only"):
            require_run_authorization(self.path, None)

    def test_local_does_not_assert_competition_permission(self):
        result = require_run_authorization(self.path, None, local_only=True)
        self.assertEqual(result["competition_training_permission"], "unverified")
        self.assertIs(result["submission_allowed"], False)
        self.assertNotIn("decision", result)

    def test_original_competition_scope_cannot_be_relabelled_local(self):
        with self.assertRaisesRegex(ValueError, "separate ten-sample"):
            require_run_authorization(OLD_PILOT, None, local_only=True)

    def test_local_cannot_mix_with_rules_claim(self):
        with self.assertRaises(ValueError):
            require_run_authorization(self.path, self.approval, local_only=True)

    def test_tampered_authorization_rejected(self):
        self.approval.write_text("changed temporary test fixture")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            load_pilot(self.path)

    def test_backbone_or_submission_scope_change_rejected(self):
        for field in ("backbone_frozen", "submission"):
            changed = json.loads(json.dumps(self.value))
            changed["training_scope"][field] = not changed["training_scope"][field]
            path = self.root / (field + ".json")
            write_json(path, changed)
            with self.assertRaises(ValueError):
                load_pilot(path)

    def test_ten_fixture_exports_keep_local_authority_and_schema(self):
        from test_training_export import fixture_asl

        paths = []
        for index, row in enumerate(self.value["samples"]):
            path = self.root / f"fixture-{index}.asl"
            fixture_asl(path, row["scene_id"])
            paths.append(path)
        result = export(
            self.path, paths, self.root / "export", None, 10, local_only=True
        )
        self.assertEqual(result["samples"], 10)
        data = DrivingDataset(result["dataset"], self.path)
        data.require_all_scenes()
        self.assertIs(data.manifest["submission_allowed"], False)
        self.assertEqual(
            data.manifest["run_authorization"]["competition_training_permission"],
            "unverified",
        )

    def test_local_export_limit_is_ten(self):
        with self.assertRaisesRegex(ValueError, "bounds"):
            export(
                self.path,
                [self.root / "nonexistent.asl"],
                self.root / "export",
                None,
                11,
                local_only=True,
            )

    def test_causal_pose_velocity_rotates_world_motion_and_ignores_future(self):
        before = np.eye(4)
        before[:2, :2] = [[0, -1], [1, 0]]
        current = before.copy()
        current[1, 3] = 0.068
        future = current.copy()
        future[0, 3] = 1000
        velocity, dt = pose_velocity(
            {0: before, 17_000: current, 117_000: future}, 17_000
        )
        np.testing.assert_allclose(velocity, [4, 0])
        self.assertAlmostEqual(dt, 0.017)

    def test_causal_velocity_needs_past_pose_and_rejects_gaps(self):
        for poses in ({17_000: np.eye(4)}, {0: np.eye(4), 700_000: np.eye(4)}):
            with self.assertRaises(ValueError):
                pose_velocity(poses, max(poses))


if __name__ == "__main__":
    unittest.main()
