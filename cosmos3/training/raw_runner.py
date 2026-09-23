"""Bounded real-camera pilot: frozen image cache, then matched head-only fits.

No simulator, submission, hub fallback, backbone optimizer or implicit download.
The raw dataset reader certifies causal observations and protected whole-log
splits before model loading. Cache and training are deliberately separate CLI
processes. All artifacts live in a new, exclusively created output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np

from .contracts import checked_path, file_hash, json_hash, write_json

SEED = 20260919
RECIPE = "cosmos3-generator-clean-image-v1"
ARMS = ("cosmos", "state_route_only")
GIB = 1024**3


def _load_dataset(path):
    from .raw_dataset import RawDrivingDataset

    return RawDrivingDataset(path)


def check_roles(data):
    roles = {role: list(data.role_indices(role)) for role in ("train", "validation")}
    if any(not indices for indices in roles.values()):
        raise ValueError("Nonempty train and whole-log validation roles are required")
    all_indices = roles["train"] + roles["validation"]
    if sorted(all_indices) != list(range(len(data))):
        raise ValueError("Train and validation must partition samples exactly once")
    ids = [s["sample_id"] for s in data.samples]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate sample IDs")
    logs = {
        role: {data.samples[i]["source_log"] for i in indices}
        for role, indices in roles.items()
    }
    if logs["train"] & logs["validation"]:
        raise ValueError("Whole-log train/validation overlap")
    if data.manifest.get("data_kind") != "real_nuplan_camera_expert_aligned":
        raise ValueError(
            "Only the independently validated real-camera contract is allowed"
        )
    return roles


def unique_images(data):
    """Stable first-observation order; identical JPEG bytes are encoded once."""
    images = {}
    for sample in data.samples:
        if len(sample["images"]) != 3 or any(x is None for x in sample["images"]):
            raise ValueError("Three genuine observed camera frames are required")
        for row in sample["images"]:
            images.setdefault(row["sha256"], row)
    return images


def _device(device):
    import torch

    if device not in ("cpu", "cuda"):
        raise ValueError("Explicit cpu or cuda device required")
    torch.set_num_threads(4)
    if device == "cuda":
        if not torch.cuda.is_available():
            raise ValueError("CUDA unavailable; no silent device fallback")
        total = torch.cuda.get_device_properties(0).total_memory
        torch.cuda.set_per_process_memory_fraction(min(1, 21 * GIB / total))
        torch.cuda.reset_peak_memory_stats()


def _deadline(start, seconds):
    if time.monotonic() - start >= seconds:
        raise TimeoutError("Bounded stage time budget exhausted")


def _frozen_versions(encoder):
    versions = {}
    for component in ("transformer", "vae"):
        model = getattr(encoder.pipe, component)
        if any(module.training for module in model.modules()):
            raise ValueError("All frozen backbone modules must remain in eval mode")
        for name, parameter in model.named_parameters():
            if parameter.requires_grad or parameter.grad is not None:
                raise ValueError(
                    "Backbone/VAE must be frozen with no parameter gradients"
                )
            versions[(component, name)] = parameter._version
    return versions


def _checkpoint_inventory(checkpoint):
    root = Path(checkpoint).resolve()
    if not root.is_dir():
        raise ValueError("A local full checkpoint directory is required")
    rows = []
    for component in ("transformer", "vae"):
        files = sorted((root / component).glob("*.safetensors"))
        if not files:
            raise ValueError(f"No local {component} safetensors found")
        for path in files:
            stat = path.stat()
            rows.append(
                {
                    "path": str(path.relative_to(root)),
                    "sha256": file_hash(path),
                    "bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
    return rows


def cache_features(dataset, checkpoint, output, *, device="cpu", max_seconds=7200):
    if not 1 <= max_seconds <= 7200:
        raise ValueError("Feature cache accepts a maximum two-hour budget")
    data = _load_dataset(dataset)
    check_roles(data)
    images = unique_images(data)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    rows = {}
    report = {
        "schema_version": 1,
        "status": "partial",
        "data_kind": data.manifest["data_kind"],
        "dataset_sha256": file_hash(data.path),
        "dataset_path": str(data.path),
        "expected_unique_images": len(images),
        "dataset_validation": data.validation_summary,
        "images": rows,
        "submission_allowed": False,
        "device": device,
        "max_seconds": max_seconds,
        "runner_sha256": file_hash(__file__),
    }
    sampler = None
    try:
        # Must precede importing/loading the model stack. No token is requested.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        import torch
        from PIL import Image

        from ..profile_edge import MemorySampler
        from .features import FrozenCosmosFeatures

        _device(device)
        if device == "cuda":
            sampler = MemorySampler()
            sampler.thread.start()
        inventory = _checkpoint_inventory(checkpoint)
        _deadline(started, max_seconds)
        encoder = FrozenCosmosFeatures.from_checkpoint(checkpoint, device=device)
        encoder.spec["checkpoint_weight_sha256_inventory"] = inventory
        report["feature_spec"] = encoder.spec
        report["feature_spec_sha256"] = json_hash(encoder.spec)
        if (
            encoder.spec.get("recipe") != RECIPE
            or encoder.spec.get("feature_dim") != 2048
        ):
            raise ValueError("Unexpected frozen Cosmos feature recipe")
        original_versions = _frozen_versions(encoder)
        report["load_seconds"] = time.monotonic() - started
        (output / "images").mkdir()
        with (output / "progress.jsonl").open("x") as progress:
            for image_hash, image_row in images.items():
                _deadline(started, max_seconds)
                path = data.image_path(image_row)
                if file_hash(path) != image_hash:
                    raise ValueError("Observed image changed since dataset validation")
                before = time.monotonic()
                with Image.open(path) as image:
                    if list(image.size) != image_row["size_wh"]:
                        raise ValueError("Camera dimensions changed")
                    with torch.inference_mode():
                        values, geometry = encoder.encode_image(image)
                if values.shape != (32, 2048) or values.requires_grad:
                    raise ValueError("Unexpected differentiable/shape feature output")
                array = values.detach().to(device="cpu", dtype=torch.float16).numpy()
                if not np.isfinite(array).all():
                    raise ValueError("Nonfinite or FP16-overflowed feature output")
                if _frozen_versions(encoder) != original_versions:
                    raise ValueError("Frozen backbone parameter versions changed")
                if sampler is not None and (sampler.peak() or 0) > 21:
                    raise MemoryError("Sampled process memory exceeded 21 GiB budget")
                key = json_hash(
                    {"image_sha256": image_hash, "feature_spec": encoder.spec}
                )
                relative = f"images/{key}.npy"
                with (output / relative).open("xb") as stream:
                    np.save(stream, array, allow_pickle=False)
                row = {
                    "path": relative,
                    "sha256": file_hash(output / relative),
                    "image_sha256": image_hash,
                    "feature_key": key,
                    "seconds": time.monotonic() - before,
                    "geometry": geometry,
                }
                rows[image_hash] = row
                progress.write(json.dumps(row, allow_nan=False) + "\n")
                progress.flush()
                if len(rows) == 1 or len(rows) % 50 == 0 or len(rows) == len(images):
                    print(f"Frozen images cached {len(rows)}/{len(images)}", flush=True)
        _deadline(started, max_seconds)
        if _frozen_versions(encoder) != original_versions:
            raise ValueError("Frozen backbone final invariant failed")
        if file_hash(data.path) != report["dataset_sha256"]:
            raise ValueError("Dataset manifest changed during extraction")
        for row in inventory:
            stat = (Path(checkpoint) / row["path"]).stat()
            if (stat.st_size, stat.st_mtime_ns) != (row["bytes"], row["mtime_ns"]):
                raise ValueError("Checkpoint file changed during extraction")
        report.update(
            status="completed",
            frozen_parameter_versions_unchanged=True,
            elapsed_seconds=time.monotonic() - started,
            process_peak_vram_gib=sampler.peak() if sampler else None,
            torch_peak_allocated_gib=(
                torch.cuda.max_memory_allocated() / GIB if device == "cuda" else None
            ),
            resource_limit_caveat="21 GiB torch allocator cap plus sampled process check; time checked between operations, not an OS hard kill",
        )
        write_json(output / "cache.json", report)
    except BaseException as exc:
        report.update(
            status="failed",
            error=repr(exc),
            elapsed_seconds=time.monotonic() - started,
            completed_unique_images=len(rows),
            usable_for_training=False,
        )
        write_json(output / "PARTIAL.json", report)
        raise
    finally:
        if sampler is not None:
            sampler.stop.set()
            sampler.thread.join(timeout=4)
    return {
        "cache": str(output / "cache.json"),
        "unique_images": len(rows),
        "samples": len(data),
        "elapsed_seconds": report["elapsed_seconds"],
    }


class CachedRawDataset:
    """JPEG-deduplicated, checksum-checked mmap cache with bounded open-file LRU."""

    def __init__(self, dataset, cache, *, lru_size=128):
        if not 1 <= lru_size <= 256:
            raise ValueError("Feature LRU must contain 1–256 image arrays")
        self.dataset = _load_dataset(dataset)
        self.roles = check_roles(self.dataset)
        self.path = Path(cache).resolve()
        self.manifest = json.loads(self.path.read_text())
        manifest = self.manifest
        if (
            manifest.get("status") != "completed"
            or manifest.get("schema_version") != 1
            or manifest.get("dataset_sha256") != file_hash(self.dataset.path)
            or manifest.get("frozen_parameter_versions_unchanged") is not True
        ):
            raise ValueError(
                "Cache incomplete, unfrozen or bound to a different dataset"
            )
        self.spec = manifest["feature_spec"]
        if (
            self.spec.get("recipe") != RECIPE
            or self.spec.get("feature_dim") != 2048
            or json_hash(self.spec) != manifest.get("feature_spec_sha256")
            or not self.spec.get("checkpoint_weight_sha256_inventory")
        ):
            raise ValueError("Missing or mismatched frozen-feature provenance")
        self.rows = manifest["images"]
        if set(self.rows) != set(unique_images(self.dataset)):
            raise ValueError("Cache unique-image coverage mismatch")
        for image_hash, row in self.rows.items():
            if row.get("image_sha256") != image_hash or row.get(
                "feature_key"
            ) != json_hash({"image_sha256": image_hash, "feature_spec": self.spec}):
                raise ValueError("Cached image/feature recipe identity mismatch")
            path = checked_path(self.path.parent, row["path"], row["sha256"])
            if path.stat().st_size > 256 * 1024:
                raise ValueError("Feature file exceeds bounded float16 tensor size")
        self.lru_size, self._lru = lru_size, OrderedDict()

    def __len__(self):
        return len(self.dataset)

    def _image(self, image_hash):
        if image_hash not in self._lru:
            row = self.rows[image_hash]
            path = checked_path(self.path.parent, row["path"], row["sha256"])
            array = np.load(path, allow_pickle=False, mmap_mode="r")
            if (
                array.shape != (32, 2048)
                or array.dtype != np.float16
                or not np.isfinite(array).all()
            ):
                raise ValueError("Invalid finite float16 image features")
            self._lru[image_hash] = array
            while len(self._lru) > self.lru_size:
                self._lru.popitem(last=False)
        self._lru.move_to_end(image_hash)
        return self._lru[image_hash]

    def batch(self, indices, device="cpu", *, arm="cosmos"):
        import torch

        if arm not in ARMS or not indices or len(indices) > 64:
            raise ValueError("Known arm and bounded nonempty minibatch required")
        if any(i < 0 or i >= len(self) for i in indices):
            raise ValueError("Sample index out of bounds")
        items = [self.dataset.items[i] for i in indices]
        inputs = {
            key: torch.from_numpy(np.stack([item[0][key] for item in items])).to(device)
            for key in items[0][0]
        }
        features = np.zeros((len(indices), 3, 32, 2048), dtype=np.float32)
        if arm == "cosmos":
            for batch, index in enumerate(indices):
                for slot, image in enumerate(self.dataset.samples[index]["images"]):
                    features[batch, slot] = self._image(image["sha256"])
        inputs["features"] = torch.from_numpy(features).to(device)
        targets = {
            key: torch.from_numpy(np.stack([item[1][key] for item in items])).to(device)
            for key in items[0][1]
        }
        return inputs, targets


def state_hash(model):
    digest = hashlib.sha256()
    for name, value in model.state_dict().items():
        digest.update(name.encode())
        digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def constant_velocity(inputs):
    import torch

    state = inputs["ego_state"]
    times = torch.arange(1, 41, device=state.device, dtype=state.dtype) * 0.1
    xy = state[:, None, :2] * times[None, :, None]
    # Constant translational velocity, constant heading: no use of future targets.
    heading = torch.zeros_like(xy)
    heading[..., 1] = 1
    return torch.cat([xy, heading], dim=-1)


def sample_metrics(prediction, targets, ego_state):
    """Per-example open-loop metrics in the anchor ego coordinate frame."""
    import torch

    truth, mask = targets["waypoints"], targets["target_mask"]
    if not mask.all() or not torch.isfinite(prediction).all():
        raise ValueError(
            "Raw pilot requires finite predictions and complete 4s targets"
        )
    error = prediction[..., :2] - truth[..., :2]
    distance = torch.linalg.vector_norm(error, dim=-1)
    yaw = torch.atan2(prediction[..., 2], prediction[..., 3])
    gt_yaw = torch.atan2(truth[..., 2], truth[..., 3])
    delta = yaw - gt_yaw
    return {
        "ade_m": distance.mean(dim=1),
        "fde_4s_m": distance[:, -1],
        "lateral_mae_m": error[..., 1].abs().mean(dim=1),
        "longitudinal_mae_m": error[..., 0].abs().mean(dim=1),
        "heading_mae_deg": torch.atan2(delta.sin(), delta.cos()).abs().mean(dim=1)
        * (180 / np.pi),
        "initial_velocity_error_mps": torch.linalg.vector_norm(
            prediction[:, 0, :2] / 0.1 - ego_state[:, :2], dim=-1
        ),
        "initial_velocity_target_error_mps": torch.linalg.vector_norm(
            error[:, 0] / 0.1, dim=-1
        ),
    }


def measure(model, data, indices, *, arm, device, batch_size, deadline=None):
    import torch

    from .head import waypoint_loss

    if model is not None:
        model.eval()
    rows, weighted_loss = [], 0.0
    with torch.inference_mode():
        for start in range(0, len(indices), batch_size):
            if deadline is not None:
                _deadline(*deadline)
            selected = indices[start : start + batch_size]
            inputs, targets = data.batch(selected, device, arm=arm)
            prediction = (
                model(**inputs) if model is not None else constant_velocity(inputs)
            )
            loss, _ = waypoint_loss(
                prediction,
                targets["waypoints"],
                targets["target_mask"],
                inputs["ego_state"],
            )
            metrics = {
                k: v.cpu().numpy()
                for k, v in sample_metrics(
                    prediction, targets, inputs["ego_state"]
                ).items()
            }
            weighted_loss += float(loss) * len(selected)
            for slot, index in enumerate(selected):
                sample = data.dataset.samples[index]
                rows.append(
                    {
                        "sample_id": sample["sample_id"],
                        "source_log": sample["source_log"],
                        **{k: float(v[slot]) for k, v in metrics.items()},
                    }
                )
    keys = [k for k in rows[0] if k not in ("sample_id", "source_log")]

    def aggregate(selected):
        return {
            "samples": len(selected),
            **{k: float(np.mean([r[k] for r in selected])) for k in keys},
        }

    result = aggregate(rows)
    result["loss"] = weighted_loss / len(rows)
    result["by_log"] = {
        log: aggregate([r for r in rows if r["source_log"] == log])
        for log in sorted({r["source_log"] for r in rows})
    }
    return result


def epoch_batches(indices, epochs, batch_size, max_steps, seed=SEED):
    rng = np.random.default_rng(seed)
    steps = 0
    for epoch in range(1, epochs + 1):
        order = rng.permutation(indices).tolist()
        for start in range(0, len(order), batch_size):
            if steps >= max_steps:
                return
            steps += 1
            batch = order[start : start + batch_size]
            yield (
                epoch,
                steps,
                batch,
                start + batch_size >= len(order) or steps == max_steps,
            )


def _save_head(model, path):
    from safetensors.torch import save_file

    temporary = path.with_suffix(".pending.safetensors")
    save_file(
        {k: v.detach().cpu().contiguous() for k, v in model.state_dict().items()},
        temporary,
    )
    os.replace(temporary, path)


def _reload(model, path, data, *, arm, device, batch_size, deadline):
    import torch
    from safetensors.torch import load_file

    from .head import WaypointHead

    model.eval()
    replay = WaypointHead(**model.config).to(device).eval()
    replay.load_state_dict(load_file(str(path), device=device), strict=True)
    if state_hash(model) != state_hash(replay):
        raise ValueError("Checkpoint reload changed exact tensor state")
    delta = 0.0
    with torch.inference_mode():
        for start in range(0, len(data), batch_size):
            _deadline(*deadline)
            inputs, _ = data.batch(
                list(range(start, min(start + batch_size, len(data)))), device, arm=arm
            )
            delta = max(delta, float((model(**inputs) - replay(**inputs)).abs().max()))
    if delta != 0:
        raise ValueError(f"Same-device checkpoint replay was not exact: {delta}")
    return delta


def fit(
    dataset,
    cache,
    output,
    *,
    device="cpu",
    epochs=10,
    batch_size=32,
    steps=2000,
    max_seconds=3600,
    learning_rate=0.0003,
    seed=SEED,
):
    if (
        not 1 <= epochs <= 10
        or not 1 <= batch_size <= 64
        or not 1 <= steps <= 2000
        or not 1 <= max_seconds <= 3600
        or not 0 < learning_rate <= 0.001
    ):
        raise ValueError(
            "Pilot bounds: epochs≤10, batch≤64, updates≤2000/arm, seconds≤3600/arm, lr≤.001"
        )
    data = CachedRawDataset(dataset, cache)
    import torch
    from safetensors.torch import load_file

    from .head import WaypointHead, waypoint_loss

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    _device(device)
    torch.use_deterministic_algorithms(True)
    if device == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = False
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    reports = {}
    started = time.monotonic()
    protocol = {
        "epochs": epochs,
        "batch_size": batch_size,
        "max_optimizer_steps_per_arm": steps,
        "max_seconds_per_arm": max_seconds,
        "learning_rate": learning_rate,
        "seed": seed,
        "optimizer": "AdamW, weight_decay=.01, clip_grad_norm=1",
        "device": device,
    }
    provenance = {
        "dataset_sha256": file_hash(data.dataset.path),
        "dataset_validation": data.dataset.validation_summary,
        "cache_sha256": file_hash(data.path),
        "runner_sha256": file_hash(__file__),
        "head_source_sha256": file_hash(Path(__file__).with_name("head.py")),
        "feature_spec": data.spec,
        "roles": {
            r: {
                "samples": len(ii),
                "sample_ids_sha256": json_hash(
                    [data.dataset.samples[i]["sample_id"] for i in ii]
                ),
                "source_logs": sorted(
                    {data.dataset.samples[i]["source_log"] for i in ii}
                ),
            }
            for r, ii in data.roles.items()
        },
        "torch_version": torch.__version__,
        "submission_allowed": False,
        "competition_training_permission": "not_certified_by_this_runner",
    }
    write_json(output / "protocol.json", {**protocol, **provenance})
    initial_hash = None
    current_model, directory = None, None
    try:
        baseline = {
            role: measure(
                None,
                data,
                indices,
                arm="state_route_only",
                device=device,
                batch_size=batch_size,
                deadline=(started, max_seconds),
            )
            for role, indices in data.roles.items()
        }
        write_json(output / "constant-velocity.json", baseline)
        for arm in ARMS:
            arm_start = time.monotonic()
            deadline = (arm_start, max_seconds)
            directory = output / arm
            directory.mkdir()
            torch.manual_seed(seed)
            current_model = model = WaypointHead().to(device)
            if sum(p.numel() for p in model.parameters()) != 815235:
                raise ValueError("Unexpected head architecture/parameter count")
            if initial_hash is not None and state_hash(model) != initial_hash:
                raise ValueError("Matched arms do not share exact initial weights")
            initial_hash = state_hash(model)
            optimizer = torch.optim.AdamW(
                model.parameters(), lr=learning_rate, weight_decay=0.01
            )
            initial = {
                r: measure(
                    model,
                    data,
                    ii,
                    arm=arm,
                    device=device,
                    batch_size=batch_size,
                    deadline=deadline,
                )
                for r, ii in data.roles.items()
            }
            best_value, best_epoch, best_step = initial["validation"]["ade_m"], 0, 0
            _save_head(model, directory / "best.safetensors")
            order_hash, updates, validations = hashlib.sha256(), [], []
            with (directory / "updates.jsonl").open("x") as journal:
                for epoch, step, selected, epoch_end in epoch_batches(
                    data.roles["train"], epochs, batch_size, steps, seed
                ):
                    _deadline(*deadline)
                    order_hash.update(
                        json.dumps(selected, separators=(",", ":")).encode() + b"\n"
                    )
                    model.train()
                    inputs, targets = data.batch(selected, device, arm=arm)
                    optimizer.zero_grad(set_to_none=True)
                    loss, components = waypoint_loss(
                        model(**inputs),
                        targets["waypoints"],
                        targets["target_mask"],
                        inputs["ego_state"],
                    )
                    if not torch.isfinite(loss):
                        raise ValueError("Nonfinite training loss")
                    loss.backward()
                    norm = torch.nn.utils.clip_grad_norm_(
                        model.parameters(), 1.0, error_if_nonfinite=True
                    )
                    optimizer.step()
                    if any(not torch.isfinite(p).all() for p in model.parameters()):
                        raise ValueError("Nonfinite head weights")
                    row = {
                        "epoch": epoch,
                        "step": step,
                        "loss": float(loss.detach()),
                        "gradient_norm": float(norm),
                        **components,
                    }
                    updates.append(row)
                    journal.write(json.dumps(row, allow_nan=False) + "\n")
                    journal.flush()
                    if step == 1 or step % 25 == 0:
                        print(
                            f"{arm} epoch {epoch}, update {step}: loss={row['loss']:.5f}",
                            flush=True,
                        )
                    if epoch_end:
                        validation = measure(
                            model,
                            data,
                            data.roles["validation"],
                            arm=arm,
                            device=device,
                            batch_size=batch_size,
                            deadline=deadline,
                        )
                        validations.append(
                            {"epoch": epoch, "step": step, "metrics": validation}
                        )
                        if validation["ade_m"] < best_value:
                            best_value, best_epoch, best_step = (
                                validation["ade_m"],
                                epoch,
                                step,
                            )
                            _save_head(model, directory / "best.safetensors")
                        _save_head(model, directory / "latest.safetensors")
            _save_head(model, directory / "final.safetensors")
            final = {
                r: measure(
                    model,
                    data,
                    ii,
                    arm=arm,
                    device=device,
                    batch_size=batch_size,
                    deadline=deadline,
                )
                for r, ii in data.roles.items()
            }
            final_hash = state_hash(model)
            final_delta = _reload(
                model,
                directory / "final.safetensors",
                data,
                arm=arm,
                device=device,
                batch_size=batch_size,
                deadline=deadline,
            )
            model.load_state_dict(
                load_file(str(directory / "best.safetensors"), device=device),
                strict=True,
            )
            best = {
                r: measure(
                    model,
                    data,
                    ii,
                    arm=arm,
                    device=device,
                    batch_size=batch_size,
                    deadline=deadline,
                )
                for r, ii in data.roles.items()
            }
            best_delta = _reload(
                model,
                directory / "best.safetensors",
                data,
                arm=arm,
                device=device,
                batch_size=batch_size,
                deadline=deadline,
            )
            report = {
                "status": "completed",
                "arm": arm,
                "protocol": protocol,
                "provenance": provenance,
                "head_parameters": 815235,
                "head_config": model.config,
                "backbone_loaded_during_training": False,
                "trainable_component": "waypoint head only",
                "initial_weights_sha256": initial_hash,
                "final_weights_sha256": final_hash,
                "initial": initial,
                "final": final,
                "best": best,
                "selection": {
                    "metric": "validation ADE",
                    "best_epoch": best_epoch,
                    "best_step": best_step,
                    "validation_used_for_selection": True,
                    "validation_used_for_optimizer": False,
                },
                "optimizer_steps": len(updates),
                "training_batch_order_sha256": order_hash.hexdigest(),
                "validation_history": validations,
                "elapsed_seconds": time.monotonic() - arm_start,
                "checkpoints": {
                    name: {
                        "sha256": file_hash(directory / f"{name}.safetensors"),
                        "reload_max_abs_difference": delta,
                    }
                    for name, delta in (("best", best_delta), ("final", final_delta))
                },
            }
            if initial_hash == final_hash:
                raise ValueError("Head weights did not change")
            write_json(directory / "metrics.json", report)
            reports[arm] = report
        if (
            reports[ARMS[0]]["training_batch_order_sha256"]
            != reports[ARMS[1]]["training_batch_order_sha256"]
        ):
            raise ValueError("Arms used different optimizer sample orders")
        if (
            file_hash(data.dataset.path) != provenance["dataset_sha256"]
            or file_hash(data.path) != provenance["cache_sha256"]
        ):
            raise ValueError("Pinned dataset/cache changed while fitting")
        summary = {
            "status": "completed",
            "protocol": protocol,
            "provenance": provenance,
            "constant_velocity": baseline,
            "arms": {
                a: {
                    "best_validation": r["best"]["validation"],
                    "best_step": r["selection"]["best_step"],
                    "optimizer_steps": r["optimizer_steps"],
                }
                for a, r in reports.items()
            },
            "elapsed_seconds": time.monotonic() - started,
            "interpretation": "Open-loop, validation-selected local pilot only; not an unbiased test, closed-loop score or leaderboard prediction.",
        }
        write_json(output / "COMPLETED.json", summary)
        return summary
    except BaseException as exc:
        checkpoint_error = None
        if current_model is not None and directory is not None:
            try:
                _save_head(current_model, directory / "partial.safetensors")
            except Exception as save_error:  # noqa: BLE001 - preserve the original stage failure
                checkpoint_error = repr(save_error)
        write_json(
            output / "FAILED.json",
            {
                "status": "failed",
                "error": repr(exc),
                "completed_arms": list(reports),
                "elapsed_seconds": time.monotonic() - started,
                "partial_artifacts_retained": True,
                "partial_checkpoint_error": checkpoint_error,
                "matched_comparison_complete": False,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    for name in ("cache", "fit"):
        sub = stages.add_parser(name)
        sub.add_argument("--dataset", required=True)
        sub.add_argument("--output", required=True)
        sub.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
        sub.add_argument(
            "--max-seconds", type=int, default=7200 if name == "cache" else 3600
        )
        if name == "cache":
            sub.add_argument("--checkpoint", required=True)
        else:
            sub.add_argument("--cache", required=True)
            sub.add_argument("--epochs", type=int, default=10)
            sub.add_argument("--batch-size", type=int, default=32)
            sub.add_argument("--steps", type=int, default=2000)
            sub.add_argument("--learning-rate", type=float, default=0.0003)
            sub.add_argument("--seed", type=int, default=SEED)
    args = vars(parser.parse_args())
    stage = args.pop("stage")
    print(
        json.dumps(
            (cache_features if stage == "cache" else fit)(**args),
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
