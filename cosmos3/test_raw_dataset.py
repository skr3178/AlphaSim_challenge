"""CPU fixtures for the raw-camera protocol; not a driving experiment."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from cosmos3.training.contracts import file_hash
from cosmos3.training.raw_dataset import (
    RAW_KIND,
    ROUTE_RECIPE,
    RawDrivingDataset,
    activate_roles,
)
from cosmos3.training.state_adapter import STATE_RECIPE


def write(path, value):
    path.write_text(json.dumps(value))


def reference(path):
    return {"path": str(path), "sha256": file_hash(path)}


def fixture(root):
    image_root = root / "sensor_blobs"
    image_root.mkdir()
    public_path, protected_path, acquired_path = [
        root / (name + ".json") for name in ("public", "protected", "acquired")
    ]
    public = {"scenes": {"sealed": {"source_log": "protected-log"}}}
    write(public_path, public)
    split = {
        "public_manifest_sha256": file_hash(public_path),
        "protected_public_source_logs": ["protected-log"],
        "protected_official_val_source_logs": ["official-log"],
        "quarantined_mini_source_logs": ["mini-log"],
        "protected_public_city_dates": [["boston", "2021-08-30"]],
        "roles": {
            "pilot_training": {"source_logs": ["training-log"]},
            "pilot_validation": {"source_logs": ["validation-log"]},
        },
    }
    write(protected_path, split)
    acquired = {"windows": []}
    samples = []
    for index, role in enumerate(("train", "validation")):
        log = "training-log" if index == 0 else "validation-log"
        date = f"2021-08-{17 + index:02d}"
        window = log + "_00000_00010"
        destination = image_root / window / "CAM_F0"
        destination.mkdir(parents=True)
        now = 2_010_000
        timestamps = [1_000_000, 1_500_000, 2_000_000]
        images, receipt_images = [], []
        for slot, timestamp in enumerate(timestamps):
            path = destination / f"{slot:016x}.jpg"
            Image.new("RGB", (1920, 1080), (slot * 30, 0, 0)).save(path)
            relative = str(path.relative_to(image_root))
            images.append(
                {
                    "path": relative,
                    "sha256": file_hash(path),
                    "timestamp_us": timestamp,
                    "size_wh": [1920, 1080],
                }
            )
            receipt_images.append(
                {
                    "filename": relative,
                    "sha256": file_hash(path),
                    "timestamp_us": timestamp,
                }
            )
        inputs = {
            "ego_state": np.array([4, 0, 0], dtype=np.float32),
            "ego_history": np.array(
                [[-4.04, 0, 0, 1], [-2.04, 0, 0, 1], [-0.04, 0, 0, 1]], dtype=np.float32
            ),
            "history_mask": np.ones(3, dtype=bool),
            "image_age_s": np.array([1.01, 0.51, 0.01], dtype=np.float32),
            "route": np.zeros((32, 2), dtype=np.float32),
            "route_mask": np.array([True] * 10 + [False] * 22),
        }
        inputs["route"][:10, 0] = np.linspace(40, 80, 10)
        targets = {
            "waypoints": np.zeros((40, 4), dtype=np.float32),
            "target_mask": np.ones(40, dtype=bool),
        }
        targets["waypoints"][:, 0] = np.arange(1, 41) * 0.4
        targets["waypoints"][:, 3] = 1
        inputs_path, targets_path = (
            root / f"{index}-inputs.npz",
            root / f"{index}-targets.npz",
        )
        np.savez_compressed(inputs_path, **inputs)
        np.savez_compressed(targets_path, **targets)
        sample = {
            "sample_id": role,
            "source_log": log,
            "city": "boston",
            "date": date,
            "recording_window": window,
            "time_us": now,
            "role": role,
            "images": images,
            "inputs": inputs_path.name,
            "inputs_sha256": file_hash(inputs_path),
            "targets": targets_path.name,
            "targets_sha256": file_hash(targets_path),
            "calibration": {"channel": "CAM_F0", "unit_fixture": True},
            "route_provenance": {
                "recipe": ROUTE_RECIPE,
                "source_code_sha256": "0" * 64,
            },
            "ego_state_provenance": {
                "recipe": STATE_RECIPE,
                "previous_received_timestamp_us": now - 100_000,
                "current_received_timestamp_us": now,
                "interval_seconds": 0.1,
                "past_and_current_received_poses_only": True,
                "derived_state": [4, 0, 0],
            },
        }
        samples.append(sample)
        acquired["windows"].append(
            {
                "window": window,
                "source_log": log,
                "city": "boston",
                "date": date,
                "proposed_role": "pilot_training" if index == 0 else "pilot_validation",
                "images": receipt_images,
            }
        )
    write(acquired_path, acquired)
    meta = {
        "schema_version": 1,
        "contract": "cosmos-driving-v1",
        "data_kind": RAW_KIND,
        "status": "exported_for_local_training",
        "submission_allowed": False,
        "route_recipe": ROUTE_RECIPE,
        "image_root": str(image_root),
        "protected_split": reference(protected_path),
        "public_manifest": reference(public_path),
        "acquisition_manifest": reference(acquired_path),
        "samples": samples,
    }
    path = root / "dataset.json"
    write(path, meta)
    return path, meta


class RawDatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path, self.meta = fixture(Path(self.tmp.name))

    def check_rejected(self, change):
        data = copy.deepcopy(self.meta)
        change(data)
        write(self.path, data)
        with self.assertRaises((ValueError, KeyError)):
            RawDrivingDataset(self.path)

    def test_loads_distinct_roles(self):
        data = RawDrivingDataset(self.path)
        self.assertEqual(data.role_indices("train"), [0])
        self.assertEqual(data.role_indices("validation"), [1])
        self.assertEqual(data.validation_summary["unique_images"], 6)

    def test_cannot_accept_asl(self):
        self.check_rejected(
            lambda data: data.update(data_kind="real_asl_expert_aligned")
        )

    def test_protected_log_rejected(self):
        self.check_rejected(
            lambda data: data["samples"][0].update(source_log="protected-log")
        )

    def test_protected_date_rejected(self):
        self.check_rejected(lambda data: data["samples"][0].update(date="2021-08-30"))

    def test_role_swap_rejected(self):
        self.check_rejected(lambda data: data["samples"][1].update(role="train"))

    def test_future_camera_rejected(self):
        self.check_rejected(
            lambda data: data["samples"][0]["images"][-1].update(timestamp_us=2_020_000)
        )

    def test_repeated_history_rejected(self):
        self.check_rejected(
            lambda data: data["samples"][0]["images"][0].update(timestamp_us=1_500_000)
        )

    def test_state_from_future_rejected(self):
        self.check_rejected(
            lambda data: data["samples"][0]["ego_state_provenance"].update(
                previous_received_timestamp_us=2_020_000
            )
        )

    def test_dense_target_route_provenance_rejected(self):
        self.check_rejected(
            lambda data: data["samples"][0]["route_provenance"].update(
                recipe="copied-targets"
            )
        )

    def test_changed_image_rejected(self):
        image = self.meta["samples"][0]["images"][0]
        path = Path(self.meta["image_root"]) / image["path"]
        path.write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            RawDrivingDataset(self.path)

    def test_changed_source_manifest_rejected(self):
        Path(self.meta["protected_split"]["path"]).write_text("{}")
        with self.assertRaises(ValueError):
            RawDrivingDataset(self.path)

    def test_duplicate_identity_rejected(self):
        self.check_rejected(
            lambda data: data["samples"].append(copy.deepcopy(data["samples"][0]))
        )

    def test_no_submission_eligibility_claim(self):
        self.check_rejected(lambda data: data.update(submission_allowed=True))

    def test_explicit_new_pilot_keeps_original_receipts(self):
        original = Path(self.meta["acquisition_manifest"]["path"])
        original_hash = file_hash(original)
        pilot = {
            "schema_version": 1,
            "purpose": "independent_raw_camera_pilot",
            "protected_split_sha256": self.meta["protected_split"]["sha256"],
            "acquisition_manifest_sha256": original_hash,
            "roles": {"train": ["validation-log"], "validation": ["training-log"]},
            "authorization": {
                "scope": "user_approved_raw_camera_whole_log_date_split",
                "text": "unit fixture only",
            },
        }
        pilot_path = self.path.parent / "pilot.json"
        write(pilot_path, pilot)
        self.meta["pilot_split"] = reference(pilot_path)
        self.meta["samples"][0]["role"] = "validation"
        self.meta["samples"][1]["role"] = "train"
        write(self.path, self.meta)
        data = RawDrivingDataset(self.path)
        self.assertEqual(data.role_indices("train"), [1])
        self.assertEqual(file_hash(original), original_hash)

    def test_unapproved_pilot_rejected(self):
        protected = json.loads(Path(self.meta["protected_split"]["path"]).read_text())
        acquired = json.loads(
            Path(self.meta["acquisition_manifest"]["path"]).read_text()
        )
        with self.assertRaisesRegex(ValueError, "Unapproved"):
            activate_roles(
                protected,
                acquired,
                {
                    "roles": {
                        "train": ["training-log"],
                        "validation": ["validation-log"],
                    }
                },
            )

    def test_cross_role_city_date_rejected_before_export(self):
        protected = json.loads(Path(self.meta["protected_split"]["path"]).read_text())
        acquired = json.loads(
            Path(self.meta["acquisition_manifest"]["path"]).read_text()
        )
        acquired["windows"][1]["date"] = acquired["windows"][0]["date"]
        with self.assertRaisesRegex(ValueError, "city/date"):
            activate_roles(protected, acquired)

    def test_explicit_shared_dates_still_require_disjoint_unprotected_logs(self):
        protected_path = Path(self.meta["protected_split"]["path"])
        acquired_path = Path(self.meta["acquisition_manifest"]["path"])
        protected = json.loads(protected_path.read_text())
        acquired = json.loads(acquired_path.read_text())
        acquired["windows"][1]["date"] = acquired["windows"][0]["date"]
        write(acquired_path, acquired)
        self.meta["acquisition_manifest"] = reference(acquired_path)
        self.meta["samples"][1]["date"] = self.meta["samples"][0]["date"]
        pilot = {
            "schema_version": 1, "purpose": "independent_raw_camera_pilot",
            "protected_split_sha256": file_hash(protected_path),
            "acquisition_manifest_sha256": file_hash(acquired_path),
            "roles": {"train": ["training-log"], "validation": ["validation-log"]},
            "allow_shared_city_dates": True,
            "authorization": {
                "scope": "user_approved_raw_camera_whole_log_split_shared_dates",
                "text": "unit fixture only",
            },
        }
        pilot_path = self.path.parent / "pilot-shared.json"
        write(pilot_path, pilot)
        self.meta["pilot_split"] = reference(pilot_path)
        write(self.path, self.meta)
        data = RawDrivingDataset(self.path)
        self.assertTrue(data.validation_summary["whole_log_disjoint"])
        self.assertFalse(data.validation_summary["whole_log_and_city_date_disjoint"])
        for mutate in (
            lambda p: p.update(allow_shared_city_dates=False),
            lambda p: p["roles"]["validation"].append("training-log"),
            lambda p: p["authorization"].update(scope="unapproved"),
        ):
            bad = copy.deepcopy(pilot)
            mutate(bad)
            with self.assertRaises(ValueError):
                activate_roles(protected, acquired, bad,
                               protected_sha256=file_hash(protected_path),
                               acquisition_sha256=file_hash(acquired_path))
        protected["protected_public_city_dates"].append(
            [acquired["windows"][0]["city"], acquired["windows"][0]["date"]]
        )
        with self.assertRaisesRegex(ValueError, "protected"):
            activate_roles(protected, acquired, pilot,
                           protected_sha256=file_hash(protected_path),
                           acquisition_sha256=file_hash(acquired_path))


if __name__ == "__main__":
    unittest.main()
