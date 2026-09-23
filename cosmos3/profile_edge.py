"""Bounded full-generator hardware smoke test, not an AlpaSim evaluation.

Only the first clean camera observation from existing public ASL logs is used.
No future ground truth, simulator, training, or submission is accessed.
"""
import argparse
import concurrent.futures
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import traceback

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

GIB = 1024 ** 3
CHECKPOINT = Path("/media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918/checkpoint")
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
INPUT_MANIFEST = ARTIFACTS / "inputs" / "manifest.json"
PROMPT = (
    "You are an autonomous vehicle planning system. Follow the current driving lane "
    "and avoid obstacles while making smooth progress."
)


def save_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


class MemorySampler:
    """Sample this process's driver-reported memory, not just torch allocations."""
    def __init__(self):
        self.samples = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.stop.is_set():
            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=3, check=True,
                )
                for line in result.stdout.splitlines():
                    pid, memory = [v.strip() for v in line.split(",", 1)]
                    if int(pid) == os.getpid():
                        self.samples.append((time.monotonic(), float(memory) / 1024))
            except Exception:
                pass
            self.stop.wait(0.25)

    def peak(self, since=0):
        values = [memory for stamp, memory in self.samples if stamp >= since]
        return max(values) if values else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["load", "smoke", "driving", "canonical"], default="load")
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--resolution", choices=[256, 480], type=int, default=256)
    args = parser.parse_args()
    if not 1 <= args.steps <= 30:
        raise SystemExit("Bounded test accepts 1–30 denoising steps")
    ARTIFACTS.mkdir(exist_ok=True)
    run_name = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + args.profile
    output = ARTIFACTS / run_name
    output.mkdir()
    report = {
        "profile": args.profile, "checkpoint": str(CHECKPOINT),
        "revision": "344d602b128d1bbdacb43b08d0a3626f46343e29",
        "diffusers_revision": "344d6e7300716ff245d5941bc1fe3e95ad8cd1c3",
        "status": "starting", "requests": [], "pid": os.getpid(),
        "scope": "Full generative MoT + VAE pipeline, no CPU offload or quantization; not reasoner-only",
        "limitations": [
            "Hardware/API smoke test, not driving-quality evaluation.",
            "Single front image plus text only; no calibrated multiview, numerical route, or ego-state adapter.",
            "AV policy mode on the base checkpoint is exploratory, not a validated nuPlan driving policy.",
            "Predicted 9D actions are raw model output, not validated AlpaSim poses or metric trajectories.",
            "Default released model_index safety-checker configuration is preserved; no extra checker models loaded.",
            "Two incoming requests are serialized through one pipeline because upstream is single-sample and stateful.",
        ],
    }
    report_path = output / "results.json"
    save_json(report_path, report)
    print(f"RESULTS={report_path}", flush=True)
    sampler = MemorySampler()
    sampler.thread.start()
    try:
        import numpy as np
        import torch
        from PIL import Image
        from diffusers import Cosmos3OmniPipeline, CosmosActionCondition, UniPCMultistepScheduler

        torch.set_num_threads(4)
        report["versions"] = {name: importlib.metadata.version(name) for name in
                              ["torch", "torchvision", "diffusers", "transformers", "huggingface-hub", "safetensors", "av"]}
        report["cuda"] = torch.version.cuda
        report["gpu"] = torch.cuda.get_device_name(0)
        report["gpu_total_GiB"] = torch.cuda.get_device_properties(0).total_memory / GIB
        # Leave >2 GiB for the desktop and stop pathological allocation growth.
        # This is NOT a 16 GiB competition pass: actual process memory is measured separately.
        torch.cuda.set_per_process_memory_fraction(min(1.0, 21 * GIB / torch.cuda.get_device_properties(0).total_memory))
        report["torch_allocator_safety_cap_GiB"] = 21
        load_start = time.monotonic()
        print("Loading full generator in BF16, local files only, no CPU offload", flush=True)
        pipe = Cosmos3OmniPipeline.from_pretrained(
            CHECKPOINT, torch_dtype=torch.bfloat16, local_files_only=True,
        )
        pipe.to("cuda")
        pipe.scheduler = UniPCMultistepScheduler.from_config(
            pipe.scheduler.config, flow_shift=10.0, use_karras_sigmas=False,
        )
        pipe.set_progress_bar_config(disable=True)
        torch.cuda.synchronize()
        report["load_seconds"] = time.monotonic() - load_start
        report["components"] = {
            name: {"parameters": sum(p.numel() for p in component.parameters()),
                   "devices": sorted({str(p.device) for p in component.parameters()}),
                   "dtypes": sorted({str(p.dtype) for p in component.parameters()})}
            for name, component in pipe.components.items() if isinstance(component, torch.nn.Module)
        }
        report["checkpoint_safety_checker_enabled"] = bool(pipe.config.enable_safety_checker)
        report["loaded_torch_allocated_GiB"] = torch.cuda.memory_allocated() / GIB
        report["loaded_torch_reserved_GiB"] = torch.cuda.memory_reserved() / GIB
        report["status"] = "loaded"
        save_json(report_path, report)
        print(json.dumps({key: report[key] for key in ["load_seconds", "loaded_torch_allocated_GiB", "components"]}), flush=True)
        if args.profile == "load":
            return

        images = []
        report["inputs"] = json.loads(INPUT_MANIFEST.read_text())
        for entry in report["inputs"]:
            source = Path(entry["output"])
            if hashlib.sha256(source.read_bytes()).hexdigest() != entry["output_sha256"]:
                raise RuntimeError(f"Input hash mismatch: {source}")
            with Image.open(source) as image:
                images.append(image.convert("RGB"))
        if len(images) != 2:
            raise RuntimeError("Expected exactly two clean public camera inputs")
        lock = threading.Lock()

        def request(label, image_index, chunk_size, steps, seed, barrier=None):
            if barrier is not None:
                barrier.wait()
            arrival = time.monotonic()
            with lock:
                acquired = time.monotonic()
                gc.collect()
                torch.cuda.synchronize()
                torch.cuda.reset_peak_memory_stats()
                begin = time.monotonic()
                result = {"label": label, "mode": "policy", "domain": "av", "chunk_size": chunk_size,
                          "fps": 10, "resolution_tier": args.resolution, "denoising_steps": steps,
                          "guidance_scale": 1.0, "seed": seed, "input_index": image_index,
                          "queue_seconds": acquired - arrival, "prompt": PROMPT}
                print(f"REQUEST {label}: {chunk_size} actions, {steps} steps, {args.resolution} tier", flush=True)
                step_times = []

                def callback(_pipe, step, timestep, callback_kwargs):
                    torch.cuda.synchronize()
                    step_times.append(time.monotonic() - begin)
                    print(f"  step {step + 1}/{steps}: {step_times[-1]:.2f}s, peak {torch.cuda.max_memory_allocated() / GIB:.2f} GiB", flush=True)
                    return callback_kwargs

                try:
                    prediction = pipe(
                        prompt=PROMPT,
                        action=CosmosActionCondition(mode="policy", domain_name="av", chunk_size=chunk_size,
                                                    resolution_tier=args.resolution, image=images[image_index], view_point="ego_view"),
                        fps=10, num_inference_steps=steps, guidance_scale=1.0,
                        use_system_prompt=False, output_type="np",
                        generator=torch.Generator(device="cuda").manual_seed(seed),
                        callback_on_step_end=callback,
                    )
                    torch.cuda.synchronize()
                    result["compute_seconds"] = time.monotonic() - begin
                    result["response_seconds"] = time.monotonic() - arrival
                    if not prediction.action:
                        raise RuntimeError("Pipeline returned no future actions")
                    action = prediction.action[0].float().cpu().numpy()
                    video_array = np.asarray(prediction.video)
                    result.update({"status": "ok", "action_shape": list(action.shape),
                                   "actions_finite": bool(np.isfinite(action).all()),
                                   "video_shape": list(video_array.shape), "video_finite": bool(np.isfinite(video_array).all())})
                    np.save(output / f"{label}_actions_raw.npy", action)
                    if result["actions_finite"]:
                        save_json(output / f"{label}_actions_raw.json", action.tolist())
                    del prediction, action, video_array
                except Exception as exc:
                    result.update({"status": "failed", "error": repr(exc), "traceback": traceback.format_exc(),
                                   "compute_seconds": time.monotonic() - begin})
                    print(result["traceback"], flush=True)
                result["torch_peak_allocated_GiB"] = torch.cuda.max_memory_allocated() / GIB
                result["torch_peak_reserved_GiB"] = torch.cuda.max_memory_reserved() / GIB
                result["sampled_process_peak_GiB"] = sampler.peak(begin)
                result["step_elapsed_seconds"] = step_times
                report["requests"].append(result)
                save_json(report_path, report)
                print(json.dumps(result), flush=True)
                return result

        smoke = request("smoke_16", 0, 16, 2, 20260918)
        if smoke["status"] != "ok":
            raise RuntimeError("Smoke request failed; see requests in results.json")
        if args.profile == "smoke":
            report["status"] = "completed"
            return
        if args.profile == "canonical":
            result = request("canonical_60", 0, 60, args.steps, 20260918)
            if result["status"] != "ok":
                raise RuntimeError("Higher-resolution AV-shaped request failed")
            report["status"] = "completed"
            return
        first = request("single_40", 0, 40, args.steps, 20260918)
        if first["status"] != "ok":
            raise RuntimeError("Driving-shaped request failed; skipping queued wave")
        barrier = threading.Barrier(2)
        wave_start = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(request, f"queued_{i}", i, 40, args.steps, 20260919+i, barrier) for i in range(2)]
            results = [future.result() for future in futures]
        report["two_request_wave_seconds"] = time.monotonic() - wave_start
        report["two_request_execution"] = "serialized; one full model resident; not batch-2 or parallel GPU execution"
        report["status"] = "completed" if all(result["status"] == "ok" for result in results) else "request_failed"
    except Exception as exc:
        report.update({"status": "failed", "error": repr(exc), "traceback": traceback.format_exc()})
        print(report["traceback"], flush=True)
    finally:
        sampler.stop.set()
        sampler.thread.join(timeout=4)
        report["sampled_process_peak_GiB"] = sampler.peak()
        report["memory_samples"] = sampler.samples
        save_json(report_path, report)
        print(f"FINAL status={report['status']} results={report_path}", flush=True)
    if report["status"] in {"failed", "request_failed"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
