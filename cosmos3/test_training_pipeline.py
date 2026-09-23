"""CPU unit fixtures only: no real scene fitting, full checkpoint or evaluation."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace, MethodType
import unittest

import numpy as np
from PIL import Image
import torch

from cosmos3.training.contracts import (
    checked_path,
    expert_aligned,
    file_hash,
    input_identity,
    interpolate_poses,
    json_hash,
    load_pilot,
    planar_relative,
    require_rules,
    select_history,
    sparse_route,
    validate_arrays,
    write_json,
)
from cosmos3.training.dataset import DrivingDataset, CachedDrivingDataset, read_npz
from cosmos3.training.features import clean_latent_features, letterbox
from cosmos3.training.head import WaypointHead, waypoint_loss
from cosmos3.training.runner import fit_head, preflight, train_head

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "cosmos3/pilots/real-driving-v1/manifest.json"


def arrays():
    inputs = {
        "ego_state": np.array([4, 0, 0], np.float32),
        "ego_history": np.zeros((3, 4), np.float32),
        "history_mask": np.array([False, False, True]),
        "image_age_s": np.zeros(3, np.float32),
        "route": np.zeros((32, 2), np.float32),
        "route_mask": np.array([True] + [False] * 31),
    }
    inputs["ego_history"][2, 3] = 1
    inputs["route"][0] = [20, 0]
    targets = {
        "waypoints": np.zeros((40, 4), np.float32),
        "target_mask": np.ones(40, bool),
    }
    targets["waypoints"][:, 0] = np.arange(1, 41) * 0.4
    targets["waypoints"][:, 3] = 1
    return inputs, targets


def fixture_dataset(folder):
    """Tiny temporary fixture labelled for exercising the production schema only."""
    pilot = load_pilot(PILOT)
    row = pilot["samples"][0]
    image = folder / "camera.png"
    Image.new("RGB", (32, 16), "gray").save(image)
    inputs, targets = arrays()
    np.savez_compressed(folder / "inputs.npz", **inputs)
    np.savez_compressed(folder / "targets.npz", **targets)
    sample = {
        "sample_id": "unit-fixture",
        "scene_id": row["scene_id"],
        "source_log": row["source_log"],
        "time_us": 1_000_000,
        "query_time_us": 1_500_000,
        "target_time_basis": "time_now_us_plus_0.1_to_4.0_seconds",
        "images": [
            None,
            None,
            {
                "path": image.name,
                "sha256": file_hash(image),
                "start_us": 990_000,
                "end_us": 1_000_000,
                "size_wh": [32, 16],
            },
        ],
        "calibration": {"logical_id": "CAM_F0", "unit_fixture": True},
        "inputs": "inputs.npz",
        "targets": "targets.npz",
        "inputs_sha256": file_hash(folder / "inputs.npz"),
        "targets_sha256": file_hash(folder / "targets.npz"),
        "route_provenance": "runtime_route_request",
    }
    value = {
        "schema_version": 1,
        "contract": "cosmos-driving-v1",
        "data_kind": "real_asl_expert_aligned",
        "pilot_manifest_sha256": file_hash(PILOT),
        "samples": [sample],
    }
    write_json(folder / "dataset.json", value)
    spec = {"recipe": "cosmos3-generator-clean-image-v1", "feature_dim": 2048}
    features = np.zeros((3, 32, 2048), np.float32)
    features[2] = 0.1
    np.savez_compressed(folder / "features.npz", features=features)
    cache = {
        "schema_version": 1,
        "dataset_sha256": file_hash(folder / "dataset.json"),
        "pilot_manifest_sha256": file_hash(PILOT),
        "feature_spec": spec,
        "samples": [
            {
                "sample_id": sample["sample_id"],
                "path": "features.npz",
                "sha256": file_hash(folder / "features.npz"),
                "input_key": json_hash(
                    {
                        "inputs": input_identity(sample),
                        "feature_spec": spec,
                        "pilot_manifest_sha256": file_hash(PILOT),
                    }
                ),
            }
        ],
    }
    write_json(folder / "cache.json", cache)
    return value, cache


class ContractTests(unittest.TestCase):
    def test_documented_route_nan_tail_becomes_mask(self):
        route, mask = sparse_route(
            [[20, 1, 0], [float("nan")] * 3], np.eye(4), np.eye(4)
        )
        self.assertEqual(int(mask.sum()), 1)
        np.testing.assert_array_equal(route[0], [20, 1])
        self.assertTrue(np.isfinite(route).all())

    def test_malformed_route_nan_rows_are_not_silently_removed(self):
        for points in (
            [[float("nan")] * 3],
            [[20, float("nan"), 0]],
            [[20, 0, float("inf")]],
            [[float("nan")] * 3, [20, 0, 0]],
        ):
            with self.assertRaises(ValueError):
                sparse_route(points, np.eye(4), np.eye(4))

    def test_approved_split_preflight(self):
        report = preflight(PILOT)
        self.assertEqual(len(report["scenes"]), 8)
        self.assertEqual(report["excluded_same_log_scenes"], 207)
        self.assertTrue(
            all(
                s["basic_assets_present"] and s["config_unchanged"]
                for s in report["scenes"]
            )
        )
        self.assertFalse(report["training_ready"])

    def test_missing_rules_fails_before_data_or_model_access(self):
        with self.assertRaisesRegex(ValueError, "Rules unverified"):
            train_head(
                PILOT,
                "/nonexistent/data",
                "/nonexistent/cache",
                "/nonexistent/output",
                None,
            )

    def test_offline_rules_review_bound_to_pilot_and_evidence(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "terms.txt").write_text("UNIT FIXTURE ONLY, not actual terms")
            review = {
                "decision": "permitted",
                "scope": "training_on_approved_public_navtest_scenes",
                "pilot_manifest_sha256": file_hash(PILOT),
                "reviewed_by": "unit-test",
                "reviewed_at_utc": "2026-09-19T00:00:00Z",
                "source_description": "unit fixture",
                "evidence_file": "terms.txt",
                "evidence_sha256": file_hash(root / "terms.txt"),
            }
            write_json(root / "review.json", review)
            self.assertEqual(
                require_rules(PILOT, root / "review.json")["review"]["reviewed_by"],
                "unit-test",
            )
            (root / "terms.txt").write_text("changed")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                require_rules(PILOT, root / "review.json")

    def test_history_never_uses_future_and_masks_missing_past(self):
        current = {"start_us": 990_000, "end_us": 1_000_000}
        future = {"start_us": 1_000_000, "end_us": 1_010_000}
        self.assertEqual(
            select_history([current, future], 1_000_000), [None, None, current]
        )
        with self.assertRaises(ValueError):
            select_history([future], 1_000_000)

    def test_history_rejects_stale_observation(self):
        with self.assertRaises(ValueError):
            select_history([{"start_us": 0, "end_us": 1}], 1_000_000)

    def test_pose_interpolation_and_no_extrapolation(self):
        poses = np.repeat(np.eye(4)[None], 3, axis=0)
        poses[:, 0, 3] = [0, 1, 2]
        result = interpolate_poses([0, 100_000, 200_000], poses, [50_000])
        self.assertAlmostEqual(result[0, 0, 3], 0.5)
        with self.assertRaises(ValueError):
            interpolate_poses([0, 100_000, 200_000], poses, [300_000])

    def test_gaps_rejected_but_exact_boundary_allowed(self):
        poses = np.repeat(np.eye(4)[None], 2, axis=0)
        interpolate_poses([0, 2_000_000], poses, [0, 2_000_000])
        with self.assertRaisesRegex(ValueError, "gap"):
            interpolate_poses([0, 2_000_000], poses, [1_000_000])

    def test_yaw_wrap_interpolates_short_way(self):
        from scipy.spatial.transform import Rotation

        poses = np.repeat(np.eye(4)[None], 2, axis=0)
        poses[:, :3, :3] = Rotation.from_euler(
            "z", [[179], [-179]], degrees=True
        ).as_matrix()
        result = interpolate_poses([0, 100_000], poses, [50_000])
        self.assertAlmostEqual(abs(np.arctan2(result[0, 1, 0], result[0, 0, 0])), np.pi)

    def test_relative_coordinates_and_route_anchor(self):
        anchor = np.eye(4)
        anchor[0, 3] = 10
        future = anchor.copy()
        future[0, 3] += 5
        np.testing.assert_allclose(planar_relative(anchor, future), [5, 0, 0, 1])
        route, mask = sparse_route([[20, 0, 0]], np.eye(4), anchor)
        np.testing.assert_allclose(route[0], [10, 0])
        self.assertEqual(mask.sum(), 1)

    def test_off_expert_image_alignment_rejected(self):
        shifted = np.eye(4)
        shifted[1, 3] = 0.2
        self.assertFalse(expert_aligned(np.eye(4), shifted, np.eye(4)))

    def test_schema_rejects_future_labels_in_inputs(self):
        inputs, targets = arrays()
        validate_arrays(inputs, targets)
        inputs["future"] = targets["waypoints"]
        with self.assertRaises(ValueError):
            validate_arrays(inputs, targets)

    def test_bad_heading_and_float_masks_rejected(self):
        inputs, targets = arrays()
        targets["waypoints"][:, 3] = 2
        with self.assertRaises(ValueError):
            validate_arrays(inputs, targets)
        inputs, targets = arrays()
        inputs["history_mask"] = inputs["history_mask"].astype(np.float32)
        with self.assertRaises(ValueError):
            validate_arrays(inputs, targets)

    def test_cache_identity_does_not_use_targets(self):
        with tempfile.TemporaryDirectory() as name:
            data, _ = fixture_dataset(Path(name))
            sample = data["samples"][0]
            before = json_hash(input_identity(sample))
            sample["targets_sha256"] = "different-future"
            self.assertEqual(before, json_hash(input_identity(sample)))

    def test_path_escape_and_pickle_arrays_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with self.assertRaises(ValueError):
                checked_path(root, "../outside")
            np.savez_compressed(
                root / "object.npz", dangerous=np.array([{}], dtype=object)
            )
            with self.assertRaises(ValueError):
                read_npz(root / "object.npz")


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data, self.cache = fixture_dataset(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def rewrite_dataset(self):
        (self.root / "dataset.json").write_text(json.dumps(self.data))

    def test_reader_separates_inputs_from_targets(self):
        data = CachedDrivingDataset(
            self.root / "dataset.json", self.root / "cache.json", PILOT
        )
        inputs, targets = data.batch([0])
        self.assertEqual(inputs["features"].shape, (1, 3, 32, 2048))
        self.assertNotIn("waypoints", inputs)
        self.assertEqual(targets["waypoints"].shape, (1, 40, 4))
        with self.assertRaisesRegex(ValueError, "all 8 approved scenes"):
            data.dataset.require_all_scenes()

    def test_holdout_scene_rejected(self):
        self.data["samples"][0]["scene_id"] = load_pilot(PILOT)["protected_suites"][
            "py123d_holdout"
        ][0]
        self.rewrite_dataset()
        with self.assertRaisesRegex(ValueError, "approved pilot"):
            DrivingDataset(self.root / "dataset.json", PILOT)

    def test_future_image_rejected(self):
        self.data["samples"][0]["images"][2]["end_us"] += 1
        self.rewrite_dataset()
        with self.assertRaisesRegex(ValueError, "Future or stale"):
            DrivingDataset(self.root / "dataset.json", PILOT)

    def test_corrupted_image_rejected(self):
        (self.root / "camera.png").write_bytes(b"not an image")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            DrivingDataset(self.root / "dataset.json", PILOT)

    def test_stale_features_rejected(self):
        self.cache["samples"][0]["input_key"] = "old"
        (self.root / "cache.json").write_text(json.dumps(self.cache))
        with self.assertRaisesRegex(ValueError, "Stale"):
            CachedDrivingDataset(
                self.root / "dataset.json", self.root / "cache.json", PILOT
            )

    def test_changed_dataset_rejected_by_cache(self):
        self.data["description"] = "changed metadata"
        self.rewrite_dataset()
        with self.assertRaisesRegex(ValueError, "dataset hash"):
            CachedDrivingDataset(
                self.root / "dataset.json", self.root / "cache.json", PILOT
            )


class HeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def batch(self):
        inputs, targets = arrays()
        inputs = {k: torch.from_numpy(v)[None] for k, v in inputs.items()}
        inputs["features"] = torch.randn(1, 3, 32, 16)
        return inputs, {k: torch.from_numpy(v)[None] for k, v in targets.items()}

    def test_output_and_backward_are_finite(self):
        model = WaypointHead(feature_dim=16, width=32, layers=1)
        inputs, targets = self.batch()
        prediction = model(**inputs)
        self.assertEqual(prediction.shape, (1, 40, 4))
        torch.testing.assert_close(prediction[..., 2:].norm(dim=-1), torch.ones(1, 40))
        loss, _ = waypoint_loss(
            prediction,
            targets["waypoints"],
            targets["target_mask"],
            inputs["ego_state"],
        )
        loss.backward()
        self.assertTrue(
            all(
                p.grad is None or torch.isfinite(p.grad).all()
                for p in model.parameters()
            )
        )

    def test_masked_visual_and_route_values_do_not_change_prediction(self):
        model = WaypointHead(feature_dim=16, width=32, layers=1).eval()
        inputs, _ = self.batch()
        before = model(**inputs)
        inputs["features"][:, :2] = 100
        inputs["route"][:, 1:] = -100
        torch.testing.assert_close(before, model(**inputs), atol=1e-5, rtol=1e-5)

    def test_nonfinite_input_rejected(self):
        model = WaypointHead(feature_dim=16, width=32, layers=1)
        inputs, _ = self.batch()
        inputs["features"][0, 2, 0, 0] = float("nan")
        with self.assertRaises(ValueError):
            model(**inputs)

    def test_two_update_unit_fixture_loop_not_a_real_pilot(self):
        inputs, targets = self.batch()

        class Fixture:
            def __len__(self):
                return 1

            def batch(self, indices, device):
                return inputs, targets

        model = WaypointHead(feature_dim=16, width=32, layers=1)
        before = model.output.weight.detach().clone()
        result = fit_head(
            model,
            Fixture(),
            steps=2,
            batch_size=1,
            learning_rate=0.0003,
            device="cpu",
            seed=1,
            max_seconds=10,
        )
        self.assertEqual(result["optimizer_steps"], 2)
        self.assertFalse(torch.equal(before, model.output.weight))
        with self.assertRaises(ValueError):
            fit_head(
                model,
                Fixture(),
                steps=101,
                batch_size=1,
                learning_rate=0.0003,
                device="cpu",
                seed=1,
                max_seconds=10,
            )


class FeatureTests(unittest.TestCase):
    def test_letterbox_transform_and_range(self):
        pixels, info = letterbox(Image.new("RGB", (100, 50), "white"), 64, 64)
        self.assertEqual(pixels.shape, (1, 3, 1, 64, 64))
        self.assertEqual(
            info["pixel_transform"], [[0.64, 0, 0], [0, 0.64, 16], [0, 0, 1]]
        )
        self.assertEqual(float(pixels.min()), -1.0)
        self.assertEqual(float(pixels.max()), 1.0)

    def test_real_upstream_tiny_transformer_feature_tap_cpu(self):
        from diffusers import Cosmos3OmniTransformer, Cosmos3OmniPipeline

        model = (
            Cosmos3OmniTransformer(
                hidden_size=32,
                intermediate_size=64,
                head_dim=16,
                num_attention_heads=2,
                num_key_value_heads=1,
                num_hidden_layers=1,
                latent_channel=4,
                latent_patch_size=2,
                patch_latent_dim=16,
                vocab_size=64,
                rope_axes_dim=[4, 2, 2],
            )
            .requires_grad_(False)
            .eval()
        )
        pipe = SimpleNamespace(transformer=model, vae_scale_factor_temporal=4)
        pipe._prepare_text_segment = MethodType(
            Cosmos3OmniPipeline._prepare_text_segment, pipe
        )
        pipe._prepare_vision_segment = MethodType(
            Cosmos3OmniPipeline._prepare_vision_segment, pipe
        )
        latent = torch.randn(1, 4, 1, 4, 4)
        before = {k: v.clone() for k, v in model.state_dict().items()}
        features = clean_latent_features(pipe, latent, [1, 2, 3])
        self.assertEqual(features.shape, (32, 32))
        self.assertTrue(torch.isfinite(features).all())
        self.assertFalse(features.requires_grad)
        self.assertFalse(any(p.grad is not None for p in model.parameters()))
        for key, value in model.state_dict().items():
            torch.testing.assert_close(value, before[key], rtol=0, atol=0)
        self.assertEqual(len(model.norm_moe_gen._forward_hooks), 0)
        with self.assertRaises(ValueError):
            clean_latent_features(pipe, latent.expand(-1, -1, 2, -1, -1), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
