"""Hash-checked JSON/NPZ sample and frozen-feature readers. No pickle loading."""

from __future__ import annotations

import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image

from .contracts import (
    CONTRACT,
    HISTORY_US,
    LOCAL_PILOT_ID,
    checked_path,
    file_hash,
    input_identity,
    json_hash,
    load_pilot,
    require_scene,
    validate_arrays,
)

RECIPE = "cosmos3-generator-clean-image-v1"


def read_npz(path, max_bytes=16 * 1024**2):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 16 or sum(i.file_size for i in infos) > max_bytes:
            raise ValueError("Array archive exceeds bounded sample size")
    with np.load(path, allow_pickle=False) as arrays:
        return {name: arrays[name] for name in arrays.files}


class DrivingDataset:
    """Inputs and targets stay separate; full validation occurs before GPU load."""

    def __init__(self, path, pilot_path):
        self.path = Path(path).resolve()
        self.root = self.path.parent
        self.pilot = load_pilot(pilot_path)
        self.manifest = json.loads(self.path.read_text())
        meta = self.manifest
        if (
            self.pilot.get("ego_state_recipe") is not None
            and meta.get("ego_state_recipe") != self.pilot["ego_state_recipe"]
        ):
            raise ValueError("Dataset ego-state recipe differs from experiment")
        if meta.get("schema_version") != 1 or meta.get("contract") != CONTRACT:
            raise ValueError("Unsupported dataset contract")
        if meta.get("data_kind") != "real_asl_expert_aligned":
            raise ValueError("Only real, expert-aligned ASL datasets are supported")
        if meta.get("pilot_manifest_sha256") != file_hash(pilot_path):
            raise ValueError("Dataset belongs to another pilot")
        self.samples = meta["samples"]
        maximum = 10 if self.pilot["pilot_id"] == LOCAL_PILOT_ID else 256
        if not 1 <= len(self.samples) <= maximum:
            raise ValueError(f"Pilot dataset must contain 1–{maximum} samples")
        ids = [s["sample_id"] for s in self.samples]
        identities = [(s["scene_id"], s["time_us"]) for s in self.samples]
        if len(ids) != len(set(ids)) or len(identities) != len(set(identities)):
            raise ValueError("Duplicate sample identity")
        self.items = []
        for sample in self.samples:
            row = require_scene(self.pilot, sample["scene_id"])
            if (
                sample["source_log"] != row["source_log"]
                or sample.get("route_provenance") != "runtime_route_request"
            ):
                raise ValueError("Source log or route provenance mismatch")
            if (
                sample.get("target_time_basis") != "time_now_us_plus_0.1_to_4.0_seconds"
                or not sample["time_us"]
                <= sample["query_time_us"]
                <= sample["time_us"] + 4_000_000
            ):
                raise ValueError("Invalid target time basis/control query coverage")
            inputs = read_npz(
                checked_path(self.root, sample["inputs"], sample["inputs_sha256"])
            )
            targets = read_npz(
                checked_path(self.root, sample["targets"], sample["targets_sha256"])
            )
            validate_arrays(inputs, targets)
            if self.pilot.get("ego_state_recipe"):
                provenance = sample.get("ego_state_provenance", {})
                if (
                    provenance.get("recipe") != self.pilot["ego_state_recipe"]
                    or provenance.get("past_and_current_received_poses_only")
                    is not True
                    or provenance.get("current_received_timestamp_us")
                    != sample["time_us"]
                    or not provenance.get(
                        "previous_received_timestamp_us", sample["time_us"]
                    )
                    < sample["time_us"]
                    or not 0.01 <= provenance.get("interval_seconds", 0) <= 0.6
                    or not np.allclose(
                        inputs["ego_state"],
                        provenance.get("derived_state", []),
                        atol=1e-6,
                    )
                ):
                    raise ValueError("Invalid causal ego-state provenance")
            if len(sample["images"]) != 3 or not sample.get("calibration"):
                raise ValueError("Missing image slots/calibration")
            for i, image in enumerate(sample["images"]):
                if (image is not None) != bool(inputs["history_mask"][i]):
                    raise ValueError("Image and history mask disagree")
                if image is None:
                    continue
                cutoff = sample["time_us"] + HISTORY_US[i]
                if (
                    not image["start_us"] <= image["end_us"] <= cutoff
                    or cutoff - image["end_us"] > 100_000
                ):
                    raise ValueError("Future or stale image in history")
                if not np.isclose(
                    inputs["image_age_s"][i],
                    (sample["time_us"] - image["end_us"]) / 1e6,
                    atol=1e-6,
                ):
                    raise ValueError("Image age does not match exposure timestamp")
                path = checked_path(self.root, image["path"], image["sha256"])
                with Image.open(path) as decoded:
                    if list(decoded.size) != image["size_wh"] or decoded.format not in (
                        "JPEG",
                        "PNG",
                    ):
                        raise ValueError("Image dimensions/format mismatch")
                    decoded.verify()
            self.items.append((inputs, targets))

    def __len__(self):
        return len(self.samples)

    def require_all_scenes(self):
        expected = {s["scene_id"] for s in self.pilot["samples"]}
        actual = {s["scene_id"] for s in self.samples}
        if actual != expected:
            raise ValueError(
                f"Training requires all {len(expected)} approved scenes; missing {len(expected-actual)}"
            )


class CachedDrivingDataset:
    def __init__(self, dataset_path, cache_path, pilot_path):
        self.dataset = DrivingDataset(dataset_path, pilot_path)
        self.path = Path(cache_path).resolve()
        self.manifest = json.loads(self.path.read_text())
        cache = self.manifest
        if cache.get("schema_version") != 1 or cache.get("dataset_sha256") != file_hash(
            dataset_path
        ):
            raise ValueError("Feature cache dataset hash/version mismatch")
        if cache.get("pilot_manifest_sha256") != file_hash(pilot_path):
            raise ValueError("Feature cache pilot mismatch")
        self.spec = cache["feature_spec"]
        if self.spec.get("recipe") != RECIPE or self.spec.get("feature_dim") != 2048:
            raise ValueError(
                "Cache is not the specified Cosmos world-generator feature recipe"
            )
        rows = cache["samples"]
        if len(rows) != len(self.dataset) or len({r["sample_id"] for r in rows}) != len(
            rows
        ):
            raise ValueError("Feature cache coverage mismatch")
        by_id = {r["sample_id"]: r for r in rows}
        self.features = []
        for sample, (inputs, _) in zip(self.dataset.samples, self.dataset.items):
            if sample["sample_id"] not in by_id:
                raise ValueError("Missing cached sample")
            row = by_id[sample["sample_id"]]
            expected = json_hash(
                {
                    "inputs": input_identity(sample),
                    "feature_spec": self.spec,
                    "pilot_manifest_sha256": file_hash(pilot_path),
                }
            )
            if row["input_key"] != expected:
                raise ValueError("Stale cached input/features")
            arrays = read_npz(
                checked_path(self.path.parent, row["path"], row["sha256"])
            )
            if set(arrays) != {"features"}:
                raise ValueError("Unexpected fields in feature cache")
            features = arrays["features"]
            if features.shape != (3, 32, 2048) or not np.isfinite(features).all():
                raise ValueError("Invalid cached feature shape/values")
            if np.any(features[~inputs["history_mask"]] != 0):
                raise ValueError("Missing history must have zero feature payloads")
            self.features.append(features.astype(np.float32))

    def __len__(self):
        return len(self.dataset)

    def batch(self, indices, device="cpu"):
        import torch

        inputs = {
            name: torch.from_numpy(
                np.stack([self.dataset.items[i][0][name] for i in indices])
            ).to(device)
            for name in self.dataset.items[0][0]
        }
        inputs["features"] = torch.from_numpy(
            np.stack([self.features[i] for i in indices])
        ).to(device)
        targets = {
            name: torch.from_numpy(
                np.stack([self.dataset.items[i][1][name] for i in indices])
            ).to(device)
            for name in self.dataset.items[0][1]
        }
        # Prediction takes this input dict only; labels are a distinct return value.
        return inputs, targets
