# Cosmos3-Edge: measured full-generator feasibility

**Subsequent authorized check:** one closed-loop AlpaSim scene has now run.
Integration passed (10/10 model calls, no fallback), but the scene score was
0 due to lateral corridor exit. See [COMPATIBILITY.md](COMPATIBILITY.md).
The measurements below remain the earlier standalone hardware/API probe.

Initial probe completed 2026-09-18. **No AlpaSim evaluation, training, warmup
submission, or official submission was run during that probe.** Six standalone policy-generation calls were made
across two GPU processes, including two small warm-up calls. All returned finite
action arrays and video arrays. This establishes hardware/API feasibility, not
driving competence.

## Conclusion

- **Local use: yes.** Full generative Edge runs on the RTX PRO 4000 Blackwell
  (24467 MiB) without quantization or CPU offload.
- **Competition-ready at current settings: no.** Reduced-resolution inference
  fits within 16 GiB but takes approximately 2.64 seconds per request on this GPU.
  A larger AV-shaped request takes 21.87 seconds and uses about 16.54 GiB process
  VRAM with the default allocator behavior.
- Fine-tuning could change policy quality; it does not by itself remove this
  inference cost. Do not invest in full fine-tuning on the assumption that the
  current generation loop can be dropped into the contestant driver.
- Retain Edge for research, adaptation/distillation, or an offline teacher.
  For online use, investigate fewer/distilled denoising steps and an action-only
  path or a lightweight trajectory head, with fresh measurements and quality
  validation. No such changes have been tested here.

## Measurements

Model loading took 2.29 seconds with local/page-cached weights. Allocated model
memory after loading was **7.61 GiB**. Cold-disk/container startup time is not
established by this number.

| Request | Future horizon / denoising | Returned video size | Compute time | Sampled peak process VRAM |
| --- | --- | --- | ---: | ---: |
| Reduced-resolution single | 40 actions at 10 Hz / 30 steps | 41 × 176 × 320 RGB | 2.641 s | 10.70 GiB |
| Two clients, first served | Same / 30 steps | Same | 2.634 s | 10.78 GiB |
| Two clients, second served | Same / 30 steps | Same | 2.637 s | 10.86 GiB |
| Higher-resolution AV-shaped single | 60 actions at 10 Hz / 30 steps | 61 × 464 × 832 RGB | 21.872 s | 16.54 GiB |

The two clients arrived together but were **serialized through one shared
pipeline**, not batched or executed concurrently on the GPU. Their response
latencies were 2.76 and 5.38 seconds, and the whole wave took 5.51 seconds.
This verifies the queuing implementation, not an official two-rollout driver.

The released Diffusers API supports only one sample per call; list prompts are
collapsed to the first entry. Reusing the same mutable scheduler concurrently
would be unsafe. No batched implementation was added.

The `256` and `480` action-resolution tiers are preset selectors, not exact output
heights. Input resizing/padding and latent cropping produced the sizes above.
Reduced resolution is not a quality-equivalent stand-in for full driving images.

### Memory distinction

- Reduced-resolution peak torch allocated: **9.54 GiB**; reserved: **10.35 GiB**;
  sampled driver/process peak: **10.86 GiB**.
- Higher-resolution peak torch allocated: **12.04 GiB**; reserved: **16.20 GiB**;
  sampled driver/process peak: **16.54 GiB**.

Competition memory assessment must not substitute allocated tensor memory for
total process VRAM. The higher-resolution result exceeds 16 GiB **with these
defaults**; it is not proof that allocator tuning cannot bring it below the cap.
Sampling was every ~250 ms plus command overhead, so short peaks may be missed.
A 21 GiB torch allocator safety cap protected desktop headroom; it was not a
16 GiB compliance enforcement test.

### Latency distinction

The organizer specifies a 0.1-second model-work target and enforces total
evaluation throughput. Local 2.64-second latency is about 26 times that target;
21.87 seconds is about 219 times. **These are not official throughput results**:
the organizer hardware, shared-GPU replica layout, driver scheduling, and actual
number of model calls were not reproduced. They establish a serious speed risk,
not a mathematically proven official timeout.

The final denoising callback occurred at 1.91 seconds for low resolution and
14.61 seconds for high resolution; these include preprocessing. Omitting video
decoding alone therefore would not reduce these runs to 100 ms. That path has
not been separately benchmarked. Profiling callbacks synchronize the GPU, and
the environment uses eager PyTorch; compiled/optimized-server performance may
differ.

## What actually ran

- `nvidia/Cosmos3-Edge` revision `344d602b128d1bbdacb43b08d0a3626f46343e29`.
- All four downloaded safetensors files passed size and SHA-256 verification.
- Diffusers commit `344d6e7300716ff245d5941bc1fe3e95ad8cd1c3`, version 0.41.0.dev0.
- PyTorch 2.11.0+cu128, torchvision 0.26.0+cu128, Transformers 5.10.2.
- Full generative MoT: **3,369,657,024 parameters**, on CUDA.
- VAE: **704,688,668 parameters**, on CUDA.
- BF16 loading, with the model's FP32-preserved transformer parameters; no
  quantization, CPU offload, compilation, or auxiliary guardrail models.
- The checkpoint's default optional safety-checker configuration was retained.
- The separate reasoner vision encoder was downloaded and verified but is not
  used by the official generator pipeline. This was **not** reasoner-only
  inference, nor a simultaneous generator-plus-standalone-reasoner benchmark.
- Diffusers warned that checkpoint config fields `backbone_type`,
  `temporal_compression_factor`, and VAE `clip_output` were ignored. The pipeline
  loaded and returned outputs, but exact parity with NVIDIA's native framework
  was not tested. Do not infer quality parity from API success.

## Inputs and output contract

Only the first clean `CAM_F0` observation from two existing public-development
ASL logs was used. Both were 1920×1080 RGB at frame end timestamp 17,000 us.
The existing evaluation videos were inspected and rejected: they include score
panels and plotted trajectories. No cropped evaluation video, ground-truth
trajectory, or future frame was supplied to the model.

The actual request was **AV policy mode**, conditioning on the first image and a
generic driving instruction. The outputs were finite `[40, 9]` or `[60, 9]`
future action arrays and generated video. This is distinct from inverse dynamics
on an observed future clip, but it still does **not** establish a trained,
route-following nuPlan policy.

Missing from this probe: calibrated multiview/history, numerical ego-state and
route adapters, action denormalization, rig/local coordinate conversion,
timestamped AlpaSim poses, vehicle/controller execution, and closed-loop scoring.
Raw actions are saved without interpreting them as metric vehicle trajectories.
Returned video arrays were checked for shape/finiteness, then discarded; no video
quality assessment was performed.

## Saved artifacts

- [Low-resolution results](artifacts/20260918T111008Z_driving/results.json)
- [Higher-resolution results](artifacts/20260918T111124Z_canonical/results.json)
- [Clean input provenance](artifacts/inputs/manifest.json)
- Raw action `.npy` and `.json` arrays beside each result file.
- [Main run log](feasibility.log), [higher-resolution log](canonical.log).
- Verification record:
  `/media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918/verification.json`.
- Setup and reproduction: [README](README.md).

The isolated environment uses the existing `hilda` environment's packages
read-only and overlays new packages in its own venv; no packages in `hilda` or
the driving environments were modified. Download range fragments and the
original partial are retained on Seagate (approximately 5 GB in addition to the
verified checkpoint). GPU processes have exited. The separate public-scene
dataset download was left running.

## Official references

- [Challenge resource/throughput constraints](https://github.com/NVlabs/alpasim/blob/e2e_challenge/e2e_challenge/README.md#submission-image-requirements-and-constraints)
- [Pinned checkpoint](https://huggingface.co/nvidia/Cosmos3-Edge/tree/344d602b128d1bbdacb43b08d0a3626f46343e29)
- [Pinned generation/action API](https://github.com/huggingface/diffusers/blob/344d6e7300716ff245d5941bc1fe3e95ad8cd1c3/src/diffusers/pipelines/cosmos/pipeline_cosmos3_omni.py)
