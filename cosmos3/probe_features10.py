"""Ten observed-image feature calls: no fitting, label export or evaluation.

Uses the earlier eight development scenes plus two deterministic examples from
the same source logs. Outputs measurements only, never a feature training cache.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import time

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from PIL import Image

from cosmos3.profile_edge import CHECKPOINT, MemorySampler
from cosmos3.training.contracts import file_hash, load_pilot, write_json
from cosmos3.training.export_asl import entries

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "cosmos3/pilots/real-driving-v1/manifest.json"
RUNS = Path("/home/skr/alpasim-challenge/alpasim/runs/confirm400-mup-g100/rollouts")


def candidate_scenes():
    pilot = load_pilot(PILOT)
    public = json.loads(Path(pilot["public_manifest"]).read_text())
    selected = [row["scene_id"] for row in pilot["samples"]]
    extras = [
        scene
        for scene in public["suites"]["py123d_development400"]
        if scene not in selected
        and public["scenes"][scene]["source_log"] in pilot["training_source_logs"]
    ]
    extras.sort(
        key=lambda scene: hashlib.sha256(
            ("cosmos-local-compat10-v1:" + scene).encode()
        ).hexdigest()
    )
    extra_logs = set()
    for scene in extras:
        source_log = public["scenes"][scene]["source_log"]
        if source_log in extra_logs:
            continue
        selected.append(scene)
        extra_logs.add(source_log)
        if len(selected) == 10:
            break
    if len(selected) != 10 or len(set(selected)) != 10:
        raise ValueError("Need ten distinct observations; no duplication fallback")
    return selected, public


def observations():
    selected, public = candidate_scenes()
    result = []
    for scene in selected:
        paths = sorted((RUNS / scene).glob("*/rollout.asl"))
        if not paths:
            raise ValueError(f"Missing saved observation: {scene}")
        source = paths[0].resolve()
        frame = None
        checked_scene = None
        for kind, value in entries(source):
            if kind == "rollout_metadata":
                checked_scene = value.session_metadata.scene_id
            elif (
                kind == "driver_camera_image"
                and value.camera_image.logical_id == "CAM_F0"
            ):
                frame = value.camera_image
            elif kind == "driver_request":
                now = int(value.time_now_us)
                if checked_scene != scene or frame is None or not frame.image_bytes:
                    raise ValueError("ASL scene mismatch or missing observation")
                if not frame.frame_start_us <= frame.frame_end_us <= now:
                    raise ValueError("Future camera observation")
                if now - frame.frame_end_us > 100_000:
                    raise ValueError("Stale camera observation")
                with Image.open(io.BytesIO(frame.image_bytes)) as original:
                    original.load()
                    image = original.convert("RGB")
                result.append(
                    (
                        image,
                        {
                            "scene_id": scene,
                            "source_log": public["scenes"][scene]["source_log"],
                            "city": public["scenes"][scene]["city"],
                            "source_asl": str(source),
                            "image_sha256": hashlib.sha256(
                                frame.image_bytes
                            ).hexdigest(),
                            "image_size_wh": list(image.size),
                            "time_now_us": now,
                            "exposure_end_us": int(frame.frame_end_us),
                        },
                    )
                )
                break
        else:
            raise ValueError("No initial driver request")
    return result


def main():
    images = observations()
    output = (
        ROOT
        / "cosmos3/artifacts"
        / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_features10_no_training")
    )
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "status": "starting",
        "mode": "frozen_feature_probe_no_training",
        "competition_training_permission": "unverified_not_changed_by_this_probe",
        "checkpoint": str(CHECKPOINT),
        "pid": os.getpid(),
        "source_code_sha256": file_hash(__file__),
        "samples": [],
        "optimizer_steps": 0,
        "feature_cache_written": False,
    }
    sampler = MemorySampler()
    started = time.monotonic()
    sampler.thread.start()
    try:
        import numpy as np
        import torch
        from cosmos3.training.features import FrozenCosmosFeatures

        torch.set_num_threads(4)
        if not torch.cuda.is_available():
            raise ValueError("CUDA unavailable")
        total = torch.cuda.get_device_properties(0).total_memory
        torch.cuda.set_per_process_memory_fraction(min(1.0, 21 * 1024**3 / total))
        torch.cuda.reset_peak_memory_stats()
        print(f"Loading local frozen generator; report directory {output}", flush=True)
        load_start = time.monotonic()
        encoder = FrozenCosmosFeatures.from_checkpoint(CHECKPOINT, device="cuda")
        torch.cuda.synchronize()
        report["load_seconds"] = time.monotonic() - load_start
        report["feature_spec"] = encoder.spec
        report["components"] = {
            name: {
                "parameters": sum(
                    p.numel() for p in getattr(encoder.pipe, name).parameters()
                ),
                "trainable_parameters": sum(
                    p.numel()
                    for p in getattr(encoder.pipe, name).parameters()
                    if p.requires_grad
                ),
            }
            for name in ("transformer", "vae")
        }
        versions = {
            (name, key): p._version
            for name in ("transformer", "vae")
            for key, p in getattr(encoder.pipe, name).named_parameters()
        }
        for image, identity in images:
            if time.monotonic() - started > 600:
                raise TimeoutError("Bounded feature probe exceeded 600 seconds")
            torch.cuda.synchronize()
            before = time.monotonic()
            values, geometry = encoder.encode_image(image)
            torch.cuda.synchronize()
            elapsed = time.monotonic() - before
            if (
                values.shape != (32, 2048)
                or values.requires_grad
                or not torch.isfinite(values).all()
            ):
                raise ValueError("Invalid frozen feature output")
            row = {
                **identity,
                "seconds": elapsed,
                "shape": list(values.shape),
                "finite": True,
                "mean": float(values.mean()),
                "std": float(values.std()),
                "image_geometry": geometry,
            }
            report["samples"].append(row)
            print(
                f"Feature call {len(report['samples'])}/10: {elapsed:.3f}s, finite",
                flush=True,
            )
            del values
        unchanged = all(
            p._version == versions[(name, key)]
            and not p.requires_grad
            and p.grad is None
            for name in ("transformer", "vae")
            for key, p in getattr(encoder.pipe, name).named_parameters()
        )
        if not unchanged:
            raise ValueError("Frozen parameter invariant failed")
        times = [row["seconds"] for row in report["samples"]]
        report.update(
            status="completed",
            frozen_parameters_unchanged_by_version_check=True,
            first_call_seconds=times[0],
            mean_seconds=float(np.mean(times)),
            warmed_mean_seconds=float(np.mean(times[1:])),
            p95_seconds=float(np.percentile(times, 95)),
        )
    except BaseException as exc:
        report.update(status="failed", error=repr(exc))
        raise
    finally:
        sampler.stop.set()
        sampler.thread.join(timeout=4)
        report["process_peak_vram_gib"] = sampler.peak()
        report["vram_sample_count"] = len(sampler.samples)
        report["elapsed_seconds"] = time.monotonic() - started
        report["limits"] = (
            "One serial observed-image call per sample; no trained head, no history, no simulator, no competition-throughput claim. Process peak is sampled, not a hard upper bound."
        )
        write_json(output / "results.json", report)
        print(f"Saved {output / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
