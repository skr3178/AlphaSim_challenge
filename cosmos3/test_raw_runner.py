"""Small CPU protocol fixtures only; no checkpoint, network or real-data fitting."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import torch

from cosmos3.test_raw_dataset import fixture
from cosmos3.training.contracts import file_hash, json_hash, write_json
from cosmos3.training.raw_dataset import RawDrivingDataset
from cosmos3.training.raw_runner import (
    RECIPE,
    CachedRawDataset,
    _frozen_versions,
    cache_features,
    check_roles,
    epoch_batches,
    fit,
    measure,
    unique_images,
)


def cached_fixture(path, root):
    data = RawDrivingDataset(path)
    root.mkdir()
    spec = {
        "recipe": RECIPE,
        "feature_dim": 2048,
        "checkpoint_weight_sha256_inventory": [
            {"path": "UNIT_FIXTURE", "sha256": "0" * 64}
        ],
    }
    rows = {}
    for index, image_hash in enumerate(unique_images(data)):
        key = json_hash({"image_sha256": image_hash, "feature_spec": spec})
        array = np.full((32, 2048), 0.01 * (index + 1), np.float16)
        target = root / f"{key}.npy"
        with target.open("xb") as stream:
            np.save(stream, array, allow_pickle=False)
        rows[image_hash] = {
            "path": target.name,
            "sha256": file_hash(target),
            "image_sha256": image_hash,
            "feature_key": key,
        }
    manifest = {
        "schema_version": 1,
        "status": "completed",
        "dataset_sha256": file_hash(path),
        "frozen_parameter_versions_unchanged": True,
        "feature_spec": spec,
        "feature_spec_sha256": json_hash(spec),
        "images": rows,
    }
    write_json(root / "cache.json", manifest)
    return root / "cache.json", manifest


class FakeEncoder:
    def __init__(self):
        self.pipe = SimpleNamespace(
            transformer=torch.nn.Linear(1, 1).requires_grad_(False).eval(),
            vae=torch.nn.Linear(1, 1).requires_grad_(False).eval(),
        )
        self.spec = {"recipe": RECIPE, "feature_dim": 2048}
        self.calls = 0

    def encode_image(self, image):
        self.calls += 1
        return torch.full((32, 2048), 0.2), {"unit_fixture": True}


class RawRunnerTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path, self.meta = fixture(self.root)
        self.cache, self.manifest = cached_fixture(self.path, self.root / "cache")

    def change_cache(self, change):
        change(self.manifest)
        self.cache.write_text(json.dumps(self.manifest))

    def test_unique_image_deduplication_and_lru(self):
        data = CachedRawDataset(self.path, self.cache, lru_size=1)
        self.assertEqual(
            len(data.rows), 3
        )  # Six fixture paths, three byte-identical pairs.
        inputs, targets = data.batch([0, 1])
        self.assertEqual(tuple(inputs["features"].shape), (2, 3, 32, 2048))
        self.assertEqual(len(data._lru), 1)
        self.assertTrue(torch.equal(inputs["features"][0], inputs["features"][1]))
        self.assertNotIn("waypoints", inputs)
        self.assertIn("waypoints", targets)

    def test_zero_vision_changes_only_feature_values(self):
        data = CachedRawDataset(self.path, self.cache)
        actual, target = data.batch([0], arm="cosmos")
        zero, zero_target = data.batch([0], arm="state_route_only")
        self.assertEqual(int(zero["features"].count_nonzero()), 0)
        self.assertGreater(int(actual["features"].count_nonzero()), 0)
        for key in actual:
            if key != "features":
                self.assertTrue(torch.equal(actual[key], zero[key]))
        for key in target:
            self.assertTrue(torch.equal(target[key], zero_target[key]))

    def test_partial_cache_rejected(self):
        self.change_cache(lambda m: m.update(status="partial"))
        with self.assertRaisesRegex(ValueError, "Cache incomplete"):
            CachedRawDataset(self.path, self.cache)

    def test_dataset_hash_mismatch_rejected(self):
        self.change_cache(lambda m: m.update(dataset_sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "different dataset"):
            CachedRawDataset(self.path, self.cache)

    def test_feature_recipe_identity_rejected(self):
        self.change_cache(
            lambda m: next(iter(m["images"].values())).update(feature_key="bad")
        )
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            CachedRawDataset(self.path, self.cache)

    def test_corrupt_feature_rejected(self):
        row = next(iter(self.manifest["images"].values()))
        (self.cache.parent / row["path"]).write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            CachedRawDataset(self.path, self.cache)

    def test_nonfinite_feature_rejected_even_when_checksum_updated(self):
        row = next(iter(self.manifest["images"].values()))
        path = self.cache.parent / row["path"]
        with path.open("wb") as stream:
            np.save(stream, np.full((32, 2048), np.nan, np.float16), allow_pickle=False)
        row["sha256"] = file_hash(path)
        self.change_cache(lambda m: None)
        data = CachedRawDataset(self.path, self.cache)
        with self.assertRaisesRegex(ValueError, "finite float16"):
            data.batch([0])

    def test_role_overlap_rejected(self):
        data = RawDrivingDataset(self.path)
        data.samples[1]["source_log"] = data.samples[0]["source_log"]
        with self.assertRaisesRegex(ValueError, "Whole-log"):
            check_roles(data)

    def test_frozen_invariants(self):
        encoder = FakeEncoder()
        versions = _frozen_versions(encoder)
        with torch.no_grad():
            encoder.pipe.transformer.weight.add_(1)
        self.assertNotEqual(versions, _frozen_versions(encoder))
        encoder.pipe.vae.train()
        with self.assertRaisesRegex(ValueError, "eval mode"):
            _frozen_versions(encoder)

    def test_schedule_reproducible_train_only_and_step_bounded(self):
        a = list(epoch_batches([1, 4, 7, 9], 10, 3, 5))
        b = list(epoch_batches([1, 4, 7, 9], 10, 3, 5))
        self.assertEqual(a, b)
        self.assertEqual(len(a), 5)
        self.assertTrue(a[-1][-1])
        self.assertTrue(all(set(row[2]) <= {1, 4, 7, 9} for row in a))

    def test_constant_velocity_fixture_is_exact(self):
        data = CachedRawDataset(self.path, self.cache)
        result = measure(
            None, data, [0, 1], arm="state_route_only", device="cpu", batch_size=1
        )
        self.assertLess(result["ade_m"], 1e-6)
        self.assertLess(result["fde_4s_m"], 1e-6)
        self.assertEqual(len(result["by_log"]), 2)

    def checkpoint(self):
        root = self.root / "checkpoint"
        for component in ("transformer", "vae"):
            folder = root / component
            folder.mkdir(parents=True)
            (folder / "model.safetensors").write_bytes(b"UNIT_FIXTURE")
        return root

    def test_cache_extracts_each_distinct_observed_jpeg_once(self):
        encoder = FakeEncoder()
        with patch(
            "cosmos3.training.features.FrozenCosmosFeatures.from_checkpoint",
            return_value=encoder,
        ):
            result = cache_features(
                self.path, self.checkpoint(), self.root / "fresh-cache", max_seconds=60
            )
        self.assertEqual(encoder.calls, 3)
        self.assertEqual(result["unique_images"], 3)
        data = CachedRawDataset(self.path, result["cache"])
        self.assertEqual(len(data), 2)

    def test_feature_failure_retains_partial_progress_not_completed(self):
        encoder = FakeEncoder()
        encoder.encode_image = lambda image: (_ for _ in ()).throw(
            ValueError("unit failure")
        )
        output = self.root / "failed-cache"
        with (
            patch(
                "cosmos3.training.features.FrozenCosmosFeatures.from_checkpoint",
                return_value=encoder,
            ),
            self.assertRaisesRegex(ValueError, "unit failure"),
        ):
            cache_features(self.path, self.checkpoint(), output, max_seconds=60)
        self.assertTrue((output / "PARTIAL.json").is_file())
        self.assertFalse((output / "cache.json").exists())

    def test_matched_cpu_training_smoke_and_exact_checkpoint_replay(self):
        result = fit(
            self.path,
            self.cache,
            self.root / "fit",
            epochs=1,
            steps=1,
            batch_size=1,
            max_seconds=60,
        )
        self.assertEqual(result["status"], "completed")
        reports = [
            json.loads((self.root / "fit" / arm / "metrics.json").read_text())
            for arm in ("cosmos", "state_route_only")
        ]
        self.assertEqual(
            reports[0]["initial_weights_sha256"], reports[1]["initial_weights_sha256"]
        )
        self.assertEqual(
            reports[0]["training_batch_order_sha256"],
            reports[1]["training_batch_order_sha256"],
        )
        for report in reports:
            self.assertFalse(report["backbone_loaded_during_training"])
            self.assertEqual(report["optimizer_steps"], 1)
            self.assertEqual(
                report["checkpoints"]["final"]["reload_max_abs_difference"], 0
            )
        with self.assertRaises(FileExistsError):
            fit(
                self.path,
                self.cache,
                self.root / "fit",
                epochs=1,
                steps=1,
                max_seconds=60,
            )

    def test_invalid_budget_before_output_creation(self):
        with self.assertRaisesRegex(ValueError, "Pilot bounds"):
            fit(self.path, self.cache, self.root / "bad-fit", steps=2001)
        self.assertFalse((self.root / "bad-fit").exists())


if __name__ == "__main__":
    unittest.main()
