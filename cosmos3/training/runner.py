"""Offline feature caching and a maximum-100-step head-only pilot runner."""

from __future__ import annotations

from pathlib import Path
import time

import numpy as np

from .contracts import (
    file_hash,
    input_identity,
    json_hash,
    load_pilot,
    require_run_authorization,
    write_json,
    checked_path,
)
from .dataset import DrivingDataset, CachedDrivingDataset


def preflight(pilot_path, run_root=None):
    from ..prepare_real_pilot import asset_missing

    pilot = load_pilot(pilot_path)
    scenes = []
    for sample in pilot["samples"]:
        root = Path(sample["asset_root"]).parents[2]
        missing = asset_missing(root, sample["scene_id"])
        config_ok = (
            Path(sample["config"]).is_file()
            and file_hash(sample["config"]) == sample["config_sha256"]
        )
        scenes.append(
            {
                "scene_id": sample["scene_id"],
                "basic_assets_present": not missing,
                "config_unchanged": config_ok,
                "missing": missing,
            }
        )
    report = {
        "mode": "metadata_only_no_model_or_training",
        "pilot": str(pilot_path),
        "pilot_manifest_sha256": file_hash(pilot_path),
        "scenes": scenes,
        "excluded_same_log_scenes": len(
            pilot["excluded_scene_ids_for_candidate_evaluation"]
        ),
        "protected_suite_sizes": {
            k: len(v) for k, v in pilot["protected_suites"].items()
        },
        "rules_status": "not_verified_by_preflight",
        "training_ready": False,
        "remaining_checks": [
            "reviewed training-data permission",
            "expert-aligned data export",
            "actual-checkpoint feature probe",
            "numerical/resource checks",
        ],
        "authentication_required_for_this_command": False,
    }
    if run_root is not None:
        from .export_asl import entries

        logs = []
        for sample in pilot["samples"]:
            paths = sorted(
                (Path(run_root) / "rollouts" / sample["scene_id"]).glob("*/rollout.asl")
            )
            row = {
                "scene_id": sample["scene_id"],
                "saved_rollouts": len(paths),
                "source": None,
            }
            if paths:
                row["source"] = str(paths[0].resolve())
                camera = None
                ego_stamps = set()
                route_stamp = None
                camera_calibration = False
                for kind, value in entries(paths[0]):
                    if kind == "rollout_metadata":
                        if value.session_metadata.scene_id != sample["scene_id"]:
                            raise ValueError(
                                "Saved ASL scene does not match its folder"
                            )
                        row["priming_end_us"] = int(
                            value.session_metadata.start_timestamp_us
                            + value.force_gt_duration
                        )
                    elif kind == "driver_session_request":
                        camera_calibration = any(
                            c.logical_id == "CAM_F0"
                            for c in value.rollout_spec.vehicle.available_cameras
                        )
                    elif (
                        kind == "driver_camera_image"
                        and value.camera_image.logical_id == "CAM_F0"
                    ):
                        c = value.camera_image
                        camera = {
                            "start_us": int(c.frame_start_us),
                            "end_us": int(c.frame_end_us),
                            "encoded_bytes": len(c.image_bytes),
                        }
                    elif kind == "driver_ego_trajectory":
                        ego_stamps.update(
                            int(p.timestamp_us) for p in value.trajectory.poses
                        )
                    elif kind == "route_request":
                        route_stamp = (
                            int(value.route.timestamp_us)
                            if value.route.waypoints
                            else None
                        )
                    elif kind == "driver_request":
                        t = int(value.time_now_us)
                        row.update(
                            first_time_now_us=t,
                            first_time_query_us=int(value.time_query_us),
                            front_camera=camera,
                            first_observation_contract_present=bool(
                                camera
                                and camera["encoded_bytes"]
                                and camera["end_us"] == t
                                and t in ego_stamps
                                and route_stamp in ego_stamps
                                and route_stamp <= t
                                and camera_calibration
                                and t < row.get("priming_end_us", -1)
                            ),
                        )
                        break
            logs.append(row)
        report["saved_log_inventory"] = logs
        report["saved_log_inventory_limit"] = (
            "First-request metadata/byte presence only; no frame export, image decode or expert-pose alignment certification. First sorted rollout per scene, no scores consulted."
        )
    return report


def cache_features(
    pilot_path,
    dataset_path,
    checkpoint,
    output,
    evidence_path,
    device="cuda",
    max_seconds=600,
    *,
    local_only=False,
):
    authorization = require_run_authorization(
        pilot_path, evidence_path, local_only=local_only
    )
    data = DrivingDataset(dataset_path, pilot_path)
    output = Path(output)
    if output.exists():
        raise ValueError("Refusing to overwrite feature cache")
    if device not in ("cpu", "cuda") or not 1 <= max_seconds <= 900:
        raise ValueError("Invalid device or bounded time limit")
    from PIL import Image
    import torch
    from .features import FrozenCosmosFeatures
    from ..profile_edge import MemorySampler

    torch.set_num_threads(4)
    if device == "cuda":
        if not torch.cuda.is_available():
            raise ValueError("CUDA unavailable; no silent device fallback")
        total = torch.cuda.get_device_properties(0).total_memory
        torch.cuda.set_per_process_memory_fraction(min(1.0, 21 * 1024**3 / total))
        torch.cuda.reset_peak_memory_stats()
    output.mkdir(parents=True)
    begin = time.monotonic()
    rows, image_times = [], []
    sampler = MemorySampler()
    sampler.thread.start()
    try:
        encoder = FrozenCosmosFeatures.from_checkpoint(checkpoint, device=device)
        if device == "cuda":
            torch.cuda.synchronize()
        load_seconds = time.monotonic() - begin
        versions = {
            (name, key): p._version
            for name in ("transformer", "vae")
            for key, p in getattr(encoder.pipe, name).named_parameters()
        }
        for index, (sample, (inputs, _)) in enumerate(zip(data.samples, data.items)):
            features = np.zeros((3, 32, 2048), np.float32)
            transforms = []
            for slot, image in enumerate(sample["images"]):
                if time.monotonic() - begin > max_seconds:
                    raise TimeoutError("Feature probe exceeded bounded time budget")
                if image is None:
                    transforms.append(None)
                    continue
                path = checked_path(data.root, image["path"], image["sha256"])
                start = time.monotonic()
                with Image.open(path) as rgb:
                    values, geometry = encoder.encode_image(rgb)
                if values.shape != (32, 2048) or values.requires_grad:
                    raise ValueError("Unexpected/unfrozen features")
                features[slot] = values.float().cpu().numpy()
                image_times.append(time.monotonic() - start)
                transforms.append(geometry)
            if not np.isfinite(features).all() or np.any(
                features[~inputs["history_mask"]] != 0
            ):
                raise ValueError("Invalid feature cache payload")
            name = f"{index:04d}.features.npz"
            with (output / name).open("xb") as stream:
                np.savez_compressed(stream, features=features)
            key = json_hash(
                {
                    "inputs": input_identity(sample),
                    "feature_spec": encoder.spec,
                    "pilot_manifest_sha256": file_hash(pilot_path),
                }
            )
            rows.append(
                {
                    "sample_id": sample["sample_id"],
                    "path": name,
                    "sha256": file_hash(output / name),
                    "input_key": key,
                    "image_transforms": transforms,
                }
            )
            print(f"Cached sample {index+1}/{len(data)}", flush=True)
        if any(
            p.requires_grad or p.grad is not None or p._version != versions[(name, key)]
            for name in ("transformer", "vae")
            for key, p in getattr(encoder.pipe, name).named_parameters()
        ):
            raise ValueError("Frozen backbone invariant failed")
        report = {
            "schema_version": 1,
            "status": "completed",
            "dataset_sha256": file_hash(dataset_path),
            "pilot_manifest_sha256": file_hash(pilot_path),
            "run_authorization": authorization,
            "submission_allowed": False if local_only else None,
            "feature_spec": encoder.spec,
            "samples": rows,
            "elapsed_seconds": time.monotonic() - begin,
            "load_seconds": load_seconds,
            "frozen_parameter_versions_unchanged": True,
            "process_peak_vram_gib": sampler.peak(),
            "vram_sample_count": len(sampler.samples),
            "encoder_seconds_per_image": image_times,
            "torch_peak_allocated_gib": (
                torch.cuda.max_memory_allocated() / 1024**3
                if device == "cuda"
                else None
            ),
            "limits": "Serial current/past feature extraction only; sampled process peak, not a hard bound or competition compliance. Timings include JPEG loading/preprocessing and synchronous feature copying, not model loading. Feature usefulness unvalidated.",
        }
        write_json(output / "cache.json", report)
    except BaseException as exc:
        write_json(
            output / "FAILED.json", {"error": repr(exc), "partial_samples": len(rows)}
        )
        raise
    finally:
        sampler.stop.set()
        sampler.thread.join(timeout=4)
    return {
        "cache": str(output / "cache.json"),
        "samples": len(rows),
        "elapsed_seconds": report["elapsed_seconds"],
    }


def fit_head(
    model, dataset, *, steps, batch_size, learning_rate, device, seed, max_seconds
):
    """Numerical core; production entry validates provenance before reaching here."""
    import torch
    from .head import waypoint_loss

    if (
        not 1 <= steps <= 100
        or not 1 <= batch_size <= 16
        or not 0 < learning_rate <= 0.01
    ):
        raise ValueError("Bounded pilot accepts 1–100 steps, batch 1–16 and LR (0,.01]")
    if not 1 <= max_seconds <= 900:
        raise ValueError("Bounded pilot accepts a 1–900 second training budget")
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=learning_rate, weight_decay=0.01
    )
    rng = np.random.default_rng(seed)
    start = time.monotonic()

    def measure():
        model.eval()
        total, count = 0.0, 0
        displacement, lateral, longitudinal, heading = 0.0, 0.0, 0.0, 0.0
        waypoint_count, final_count = 0, 0
        final_error, initial_velocity_error = 0.0, 0.0
        with torch.no_grad():
            for offset in range(0, len(dataset), batch_size):
                indices = list(range(offset, min(offset + batch_size, len(dataset))))
                inputs, targets = dataset.batch(indices, device)
                prediction = model(**inputs)
                value, _ = waypoint_loss(
                    prediction,
                    targets["waypoints"],
                    targets["target_mask"],
                    inputs["ego_state"],
                )
                total += float(value) * len(indices)
                count += len(indices)
                mask = targets["target_mask"]
                error = prediction[..., :2] - targets["waypoints"][..., :2]
                displacement += float(
                    torch.linalg.vector_norm(error, dim=-1)[mask].sum()
                )
                longitudinal += float(error[..., 0][mask].abs().sum())
                lateral += float(error[..., 1][mask].abs().sum())
                predicted_yaw = torch.atan2(prediction[..., 2], prediction[..., 3])
                target_yaw = torch.atan2(
                    targets["waypoints"][..., 2], targets["waypoints"][..., 3]
                )
                yaw_delta = predicted_yaw - target_yaw
                heading += float(
                    torch.atan2(yaw_delta.sin(), yaw_delta.cos())[mask].abs().sum()
                )
                waypoint_count += int(mask.sum())
                last = mask[:, -1]
                final_error += float(
                    torch.linalg.vector_norm(error[last, -1], dim=-1).sum()
                )
                final_count += int(last.sum())
                initial_velocity_error += float(
                    torch.linalg.vector_norm(
                        prediction[:, 0, :2] / 0.1 - inputs["ego_state"][:, :2], dim=-1
                    ).sum()
                )
        return {
            "loss": total / count,
            "ade_m": displacement / waypoint_count,
            "lateral_mae_m": lateral / waypoint_count,
            "longitudinal_mae_m": longitudinal / waypoint_count,
            "heading_mae_deg": heading / waypoint_count * 180 / np.pi,
            "fde_4s_m": final_error / final_count if final_count else None,
            "initial_velocity_error_mps": initial_velocity_error / count,
        }

    initial = measure()
    history = []
    for step in range(steps):
        if time.monotonic() - start > max_seconds:
            raise TimeoutError(f"Training time budget reached after {step} updates")
        model.train()
        indices = rng.choice(
            len(dataset), size=min(batch_size, len(dataset)), replace=False
        ).tolist()
        inputs, targets = dataset.batch(indices, device)
        optimizer.zero_grad(set_to_none=True)
        loss, components = waypoint_loss(
            model(**inputs),
            targets["waypoints"],
            targets["target_mask"],
            inputs["ego_state"],
        )
        if not torch.isfinite(loss):
            raise ValueError("Nonfinite loss")
        loss.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(), 1.0, error_if_nonfinite=True
        )
        optimizer.step()
        if not all(torch.isfinite(p).all() for p in model.parameters()):
            raise ValueError("Nonfinite head weights")
        history.append(
            {
                "step": step + 1,
                "loss": float(loss.detach()),
                "gradient_norm": float(grad_norm),
                **components,
            }
        )
        if step == 0 or (step + 1) % 25 == 0 or step + 1 == steps:
            print(
                f"Head update {step+1}/{steps}: loss={float(loss.detach()):.6f}",
                flush=True,
            )
    final = measure()
    return {
        "optimizer_steps": len(history),
        "initial_training_loss": initial["loss"],
        "final_training_loss": final["loss"],
        "initial_training_metrics": initial,
        "final_training_metrics": final,
        "updates": history,
        "elapsed_seconds": time.monotonic() - start,
        "interpretation": "Training-set losses only; not driving quality, held-out performance or leaderboard prediction.",
    }


def train_head(
    pilot_path,
    dataset_path,
    cache_path,
    output,
    evidence_path,
    steps=100,
    batch_size=8,
    learning_rate=0.0003,
    device="cpu",
    max_seconds=300,
    *,
    local_only=False,
):
    pilot = load_pilot(pilot_path)
    if pilot["pilot_id"] == "cosmos3-local-ablation-v1":
        raise ValueError(
            "Use the matched ablation runner; generic fitting must not mix train/evaluation roles"
        )
    authorization = require_run_authorization(
        pilot_path, evidence_path, local_only=local_only
    )
    if not 1 <= steps <= pilot["training_scope"]["max_optimizer_steps"]:
        raise ValueError("Optimizer steps exceed approved scope")
    if device not in ("cpu", "cuda"):
        raise ValueError("Explicit CPU or CUDA device required")
    data = CachedDrivingDataset(dataset_path, cache_path, pilot_path)
    data.dataset.require_all_scenes()
    output = Path(output)
    if output.exists():
        raise ValueError("Refusing to replace training output")
    import torch
    from safetensors.torch import save_file, load_file
    from .head import WaypointHead

    torch.set_num_threads(4)
    seed = 20260919
    torch.manual_seed(seed)
    if device == "cuda":
        if not torch.cuda.is_available():
            raise ValueError("CUDA unavailable; no silent fallback")
        total = torch.cuda.get_device_properties(0).total_memory
        torch.cuda.set_per_process_memory_fraction(min(1.0, 21 * 1024**3 / total))
        torch.cuda.reset_peak_memory_stats()
    model = WaypointHead().to(device)
    initial_parameters = {
        k: p.detach().cpu().clone() for k, p in model.named_parameters()
    }
    output.mkdir(parents=True)
    try:
        report = fit_head(
            model,
            data,
            steps=steps,
            batch_size=batch_size,
            learning_rate=learning_rate,
            device=device,
            seed=seed,
            max_seconds=max_seconds,
        )
        save_file(
            {k: v.detach().cpu().contiguous() for k, v in model.state_dict().items()},
            output / "head.safetensors",
        )
        report.update(
            status="completed",
            training_kind="frozen-feature head-only pilot",
            seed=seed,
            device=device,
            head_config=model.config,
            head_parameters=sum(p.numel() for p in model.parameters()),
            changed_head_parameter_tensors=sum(
                not torch.equal(initial_parameters[k], p.detach().cpu())
                for k, p in model.named_parameters()
            ),
            learning_rate=learning_rate,
            batch_size=batch_size,
            run_authorization=authorization,
            submission_allowed=False if local_only else None,
            dataset_sha256=file_hash(dataset_path),
            cache_sha256=file_hash(cache_path),
            pilot_manifest_sha256=file_hash(pilot_path),
            feature_spec=data.spec,
            head_sha256=file_hash(output / "head.safetensors"),
            runner_sha256=file_hash(__file__),
            head_source_sha256=file_hash(Path(__file__).with_name("head.py")),
            torch_version=torch.__version__,
            excluded_scene_ids_for_candidate_evaluation=pilot[
                "excluded_scene_ids_for_candidate_evaluation"
            ],
            torch_peak_allocated_gib=(
                torch.cuda.max_memory_allocated() / 1024**3
                if device == "cuda"
                else None
            ),
        )
        model.eval()
        with torch.no_grad():
            inputs, targets = data.batch(list(range(len(data))), device)
            predictions = model(**inputs).detach().cpu().numpy()
            restored = WaypointHead(**model.config).to(device).eval()
            restored.load_state_dict(
                load_file(output / "head.safetensors", device=device), strict=True
            )
            replay = restored(**inputs).detach().cpu().numpy()
            if not np.allclose(predictions, replay, rtol=1e-5, atol=1e-5):
                raise ValueError(
                    "Reloaded head checkpoint does not reproduce predictions"
                )
        report["checkpoint_reload_max_abs_difference"] = float(
            np.abs(predictions - replay).max()
        )
        with (output / "training_predictions.npz").open("xb") as stream:
            np.savez_compressed(
                stream,
                predictions=predictions,
                targets=targets["waypoints"].cpu().numpy(),
                target_mask=targets["target_mask"].cpu().numpy(),
            )
        report["training_prediction_sample_ids"] = [
            s["sample_id"] for s in data.dataset.samples
        ]
        report["training_predictions_sha256"] = file_hash(
            output / "training_predictions.npz"
        )
        write_json(output / "training.json", report)
    except BaseException as exc:
        write_json(
            output / "FAILED.json",
            {"status": "failed", "error": repr(exc), "complete_checkpoint": False},
        )
        raise
    return {
        k: report[k]
        for k in (
            "status",
            "optimizer_steps",
            "initial_training_loss",
            "final_training_loss",
            "elapsed_seconds",
        )
    }
