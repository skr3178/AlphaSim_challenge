"""Strict reader for the independent captured-camera pilot; never an ASL bypass.

Only small state/label arrays are resident. Images and cached visual features
remain on disk. All source-log roles come from the pre-existing protected split.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from .contracts import CONTRACT, checked_path, file_hash, validate_arrays
from .dataset import read_npz
from .state_adapter import STATE_RECIPE

RAW_KIND = "real_nuplan_camera_expert_aligned"
ROUTE_RECIPE = "alpasim-map-offset40-v1"
ROLE_KEYS = {"train": "pilot_training", "validation": "pilot_validation"}
EXCLUDED_KEYS = (
    "protected_public_source_logs",
    "protected_official_val_source_logs",
    "quarantined_mini_source_logs",
)


def shared_dates_approved(split):
    return bool(
        split
        and split.get("authorization", {}).get("scope")
        == "user_approved_raw_camera_whole_log_split_shared_dates"
        and split.get("allow_shared_city_dates") is True
    )


def source_json(record):
    path = Path(record["path"]).resolve()
    if not path.is_file() or file_hash(path) != record["sha256"]:
        raise ValueError("Missing or changed source manifest")
    return json.loads(path.read_text())


def activate_roles(
    protected,
    acquisition,
    pilot_split=None,
    *,
    protected_sha256=None,
    acquisition_sha256=None,
):
    """Resolve an explicit new pilot split without rewriting historical proposals."""
    windows = acquisition["windows"]
    available = {row["source_log"] for row in windows}
    allowed = {
        role: set(protected["roles"][key]["source_logs"])
        for role, key in ROLE_KEYS.items()
    }
    excluded = set().union(*(set(protected[key]) for key in EXCLUDED_KEYS))
    dates = {tuple(pair) for pair in protected["protected_public_city_dates"]}
    if allowed["train"] & allowed["validation"]:
        raise ValueError("Historical metadata proposal has overlapping roles")
    if pilot_split is None:
        result = {}
        for row in windows:
            role = next(
                (
                    name
                    for name, key in ROLE_KEYS.items()
                    if row["proposed_role"] == key
                ),
                None,
            )
            log = row["source_log"]
            if (
                role is None
                or log not in allowed[role]
                or (log in result and result[log] != role)
            ):
                raise ValueError("Acquisition differs from historical proposed roles")
            result[log] = role
    else:
        authorization = pilot_split.get("authorization", {})
        if (
            pilot_split.get("schema_version") != 1
            or pilot_split.get("purpose") != "independent_raw_camera_pilot"
            or authorization.get("scope")
            not in (
                "user_approved_raw_camera_whole_log_date_split",
                "user_approved_raw_camera_whole_log_split_shared_dates",
            )
            or not authorization.get("text")
            or not protected_sha256
            or not acquisition_sha256
            or pilot_split.get("protected_split_sha256") != protected_sha256
            or pilot_split.get("acquisition_manifest_sha256") != acquisition_sha256
            or set(pilot_split.get("roles", {})) != set(ROLE_KEYS)
        ):
            raise ValueError("Unapproved or stale pilot-role activation")
        if (
            authorization["scope"] == "user_approved_raw_camera_whole_log_split_shared_dates"
            and not shared_dates_approved(pilot_split)
        ):
            raise ValueError("Shared-date authorization requires explicit acknowledgment")
        result = {}
        for role, logs in pilot_split["roles"].items():
            if not logs or len(logs) != len(set(logs)):
                raise ValueError("Pilot roles must be nonempty and unique")
            for log in logs:
                if log in result or log not in allowed["train"] | allowed["validation"]:
                    raise ValueError(
                        "Pilot role duplicates or leaves eligible source logs"
                    )
                result[log] = role
        if set(result) != available:
            raise ValueError(
                "Pilot activation must account for every acquired source log"
            )
    date_roles = {}
    for row in windows:
        key = row["city"], row["date"]
        log, role = row["source_log"], result[row["source_log"]]
        if log in excluded or key in dates:
            raise ValueError("Pilot acquisition overlaps protected source logs/dates")
        if key in date_roles and date_roles[key] != role and not shared_dates_approved(pilot_split):
            raise ValueError("Pilot train/validation share a city/date group")
        date_roles[key] = role
    return result


def validate_causal_sample(sample, inputs, targets):
    validate_arrays(inputs, targets)
    if not inputs["history_mask"].all() or not targets["target_mask"].all():
        raise ValueError(
            "Raw temporal pilot requires all history and four-second labels"
        )
    images = sample["images"]
    if len(images) != 3 or any(image is None for image in images):
        raise ValueError("Three captured camera images required")
    times = np.array([image["timestamp_us"] for image in images], dtype=np.int64)
    now = int(sample["time_us"])
    if np.any(np.diff(times) < 400_000) or np.any(np.diff(times) > 600_000):
        raise ValueError(
            "Camera triplet must have distinct half-second-spaced exposures"
        )
    if not 0 <= now - times[-1] <= 100_000:
        raise ValueError("Future or stale current camera")
    ages = (now - times) / 1e6
    if not np.allclose(inputs["image_age_s"], ages, atol=1e-6):
        raise ValueError("Image ages disagree with exposure timestamps")
    if not np.allclose(
        np.linalg.norm(inputs["ego_history"][:, 2:], axis=1), 1, atol=1e-4
    ):
        raise ValueError("History headings must be unit sin/cos pairs")
    state = sample["ego_state_provenance"]
    before, current = (
        state["previous_received_timestamp_us"],
        state["current_received_timestamp_us"],
    )
    dt = (current - before) / 1e6
    if (
        state["recipe"] != STATE_RECIPE
        or state["past_and_current_received_poses_only"] is not True
        or current != now
        or not 0.01 <= dt <= 0.6
        or not np.isclose(dt, state["interval_seconds"], atol=1e-8)
        or not np.allclose(inputs["ego_state"], state["derived_state"], atol=1e-6)
    ):
        raise ValueError("Invalid past/current-only motion provenance")
    route = sample["route_provenance"]
    if (
        route["recipe"] != ROUTE_RECIPE
        or len(route.get("source_code_sha256", "")) != 64
    ):
        raise ValueError("Navigation must use the pinned sparse MAP-offset recipe")
    if not sample.get("calibration"):
        raise ValueError("Missing captured-camera calibration")


class RawDrivingDataset:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.root = self.path.parent
        self.manifest = json.loads(self.path.read_text())
        meta = self.manifest
        if (
            meta.get("schema_version") != 1
            or meta.get("contract") != CONTRACT
            or meta.get("data_kind") != RAW_KIND
            or meta.get("status") != "exported_for_local_training"
            or meta.get("route_recipe") != ROUTE_RECIPE
            or meta.get("submission_allowed") is not False
        ):
            raise ValueError(
                "Unsupported or unquarantined raw-camera training protocol"
            )
        self.image_root = Path(meta["image_root"]).resolve()
        if not self.image_root.is_dir():
            raise ValueError("Captured-image root unavailable")
        protected = source_json(meta["protected_split"])
        public = source_json(meta["public_manifest"])
        if protected["public_manifest_sha256"] != meta["public_manifest"]["sha256"]:
            raise ValueError("Protected split is bound to another public suite")
        acquired = source_json(meta["acquisition_manifest"])
        excluded = set().union(*(set(protected[k]) for k in EXCLUDED_KEYS))
        excluded.update(row["source_log"] for row in public["scenes"].values())
        protected_dates = {
            tuple(pair) for pair in protected["protected_public_city_dates"]
        }
        pilot_split = (
            source_json(meta["pilot_split"]) if meta.get("pilot_split") else None
        )
        activated = activate_roles(
            protected,
            acquired,
            pilot_split,
            protected_sha256=meta["protected_split"]["sha256"],
            acquisition_sha256=meta["acquisition_manifest"]["sha256"],
        )
        window_rows = acquired["windows"]
        windows = {row["window"]: row for row in window_rows}
        if len(windows) != len(window_rows):
            raise ValueError("Duplicate acquisition windows")
        image_rows = {}
        for window in window_rows:
            for image in window["images"]:
                identity = image["filename"]
                if identity in image_rows and image_rows[identity] != image:
                    raise ValueError("Conflicting acquisition image records")
                image_rows[identity] = image
        self.samples = meta["samples"]
        if not 2 <= len(self.samples) <= 6000:
            raise ValueError("Raw pilot requires 2–6000 total examples")
        self.items = []
        ids, identities, checked_images = set(), set(), {}
        role_logs = {role: set() for role in ROLE_KEYS}
        role_dates = {role: set() for role in ROLE_KEYS}
        for sample in self.samples:
            role, log = sample["role"], sample["source_log"]
            if role not in ROLE_KEYS or activated.get(log) != role or log in excluded:
                raise ValueError("Sample violates protected whole-log role")
            city_date = (sample["city"], sample["date"])
            if city_date in protected_dates:
                raise ValueError("Sample shares a protected public city/date")
            window = windows.get(sample["recording_window"])
            if (
                window is None
                or window["source_log"] != log
                or activated.get(window["source_log"]) != role
                or window["city"] != sample["city"]
                or window["date"] != sample["date"]
            ):
                raise ValueError("Sample identity differs from acquired recording")
            identity = (log, int(sample["time_us"]))
            if sample["sample_id"] in ids or identity in identities:
                raise ValueError("Duplicate sample/log-time identity")
            ids.add(sample["sample_id"])
            identities.add(identity)
            role_logs[role].add(log)
            role_dates[role].add(city_date)
            inputs = read_npz(
                checked_path(self.root, sample["inputs"], sample["inputs_sha256"])
            )
            targets = read_npz(
                checked_path(self.root, sample["targets"], sample["targets_sha256"])
            )
            validate_causal_sample(sample, inputs, targets)
            for image in sample["images"]:
                original = image_rows.get(image["path"])
                if (
                    original is None
                    or original["sha256"] != image["sha256"]
                    or original["timestamp_us"] != image["timestamp_us"]
                    or not image["path"].startswith(
                        sample["recording_window"] + "/CAM_F0/"
                    )
                ):
                    raise ValueError("Image is not the acquired same-recording camera")
                path = self.image_path(image)
                key = (str(path), image["sha256"])
                if key not in checked_images:
                    if file_hash(path) != image["sha256"]:
                        raise ValueError("Captured image hash mismatch")
                    with Image.open(path) as decoded:
                        if decoded.format != "JPEG":
                            raise ValueError("Expected JPEG camera payload")
                        size = list(decoded.size)
                        decoded.load()
                    checked_images[key] = size
                if checked_images[key] != image["size_wh"] or image["size_wh"] != [
                    1920,
                    1080,
                ]:
                    raise ValueError("Unexpected front-camera dimensions")
            self.items.append((inputs, targets))
        if (
            role_logs["train"] & role_logs["validation"]
            or (role_dates["train"] & role_dates["validation"] and not shared_dates_approved(pilot_split))
        ):
            raise ValueError(
                "Training/validation share source logs or city/date groups"
            )
        for role, maximum in (("train", 5000), ("validation", 1000)):
            if not 1 <= len(self.role_indices(role)) <= maximum:
                raise ValueError(f"Need 1–{maximum} {role} examples")
        self.validation_summary = {
            "samples": len(self.samples),
            "unique_images": len(checked_images),
            "role_samples": {role: len(self.role_indices(role)) for role in ROLE_KEYS},
            "role_logs": {role: sorted(logs) for role, logs in role_logs.items()},
            "whole_log_disjoint": True,
            "whole_log_and_city_date_disjoint": not bool(role_dates["train"] & role_dates["validation"]),
            "shared_city_dates": sorted(role_dates["train"] & role_dates["validation"]),
            "protected_source_logs_excluded": True,
        }

    def __len__(self):
        return len(self.samples)

    def role_indices(self, role):
        if role not in ROLE_KEYS:
            raise ValueError("Unknown dataset role")
        return [i for i, sample in enumerate(self.samples) if sample["role"] == role]

    def image_path(self, image):
        # Hash/decode is deduplicated at construction; path containment always checked.
        return checked_path(self.image_root, image["path"])
