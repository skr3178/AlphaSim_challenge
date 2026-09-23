"""Experimental clean-observation feature tap of the *world generator*.

No future/noisy/action tokens, denoising loop or video decoder. This is a new
feature recipe, not a validated encoder or a claimed Odyssey reproduction.
"""

from __future__ import annotations

import inspect
from pathlib import Path
import threading

import numpy as np
from PIL import Image
import torch
from torch.nn import functional as F

from .contracts import file_hash

RECIPE = "cosmos3-generator-clean-image-v1"
PROMPT = "A front-facing camera observation from a driving vehicle."


def letterbox(image, height=256, width=448):
    image = image.convert("RGB")
    original_w, original_h = image.size
    scale = min(width / original_w, height / original_h)
    resized = (max(1, round(original_w * scale)), max(1, round(original_h * scale)))
    left, top = (width - resized[0]) // 2, (height - resized[1]) // 2
    canvas = Image.new("RGB", (width, height))
    canvas.paste(image.resize(resized, Image.Resampling.BILINEAR), (left, top))
    transform = [
        [resized[0] / original_w, 0, left],
        [0, resized[1] / original_h, top],
        [0, 0, 1],
    ]
    tensor = (
        torch.from_numpy(np.asarray(canvas).copy()).permute(2, 0, 1).float() / 127.5 - 1
    )
    return tensor[None, :, None], {
        "original_size_wh": [original_w, original_h],
        "network_size_wh": [width, height],
        "pixel_transform": transform,
    }


@torch.no_grad()
def clean_latent_features(pipe, latent, text_ids):
    if (
        latent.ndim != 5
        or latent.shape[0] != 1
        or latent.shape[2] != 1
        or not torch.isfinite(latent).all()
    ):
        raise ValueError(
            "Expected one finite observed-image latent; future/video latents are not accepted"
        )
    model = pipe.transformer
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise ValueError("Feature backbone must be eval-mode and frozen")
    device = latent.device
    text = pipe._prepare_text_segment(text_ids, device)
    vision = pipe._prepare_vision_segment(
        latent,
        True,
        text["vision_start_temporal_offset"],
        10.0,
        text["und_len"],
        device,
        condition_frame_indexes=[0],
    )
    if vision["num_noisy_vision_tokens"] or vision["vision_mse_loss_indexes"].numel():
        raise ValueError("Feature recipe unexpectedly includes prediction tokens")
    captured = []
    hook = model.norm_moe_gen.register_forward_hook(
        lambda module, args, output: captured.append(output.detach())
    )
    try:
        model(
            input_ids=text["input_ids"],
            text_indexes=text["text_indexes"],
            position_ids=torch.cat(
                [text["text_mrope_ids"], vision["vision_mrope_ids"]], dim=1
            ),
            und_len=text["und_len"],
            sequence_length=text["und_len"] + vision["num_vision_tokens"],
            vision_tokens=[latent],
            vision_token_shapes=vision["vision_token_shapes"],
            vision_sequence_indexes=vision["vision_sequence_indexes"],
            vision_mse_loss_indexes=vision["vision_mse_loss_indexes"],
            vision_timesteps=torch.empty(0, device=device, dtype=latent.dtype),
            vision_noisy_frame_indexes=vision["vision_noisy_frame_indexes"],
            return_dict=False,
        )
    finally:
        hook.remove()
    if len(captured) != 1 or captured[0].shape != (
        vision["num_vision_tokens"],
        model.config.hidden_size,
    ):
        raise ValueError("Unexpected normalized generator feature shape")
    _, height, width = vision["vision_token_shapes"][0]
    grid = captured[0].float().reshape(height, width, -1).permute(2, 0, 1)[None]
    features = F.adaptive_avg_pool2d(grid, (4, 8))[0].permute(1, 2, 0).reshape(32, -1)
    if not torch.isfinite(features).all():
        raise ValueError("Nonfinite Cosmos features")
    return features.detach()


class FrozenCosmosFeatures:
    def __init__(self, pipe, provenance, height=256, width=448):
        if (
            height % 32
            or width % 32
            or not (64 <= height <= 256 and 64 <= width <= 448)
        ):
            raise ValueError(
                "Bounded extractor requires 32-aligned dimensions, up to 256x448"
            )
        self.pipe, self.height, self.width = pipe, height, width
        self.lock = threading.Lock()
        for name in ("transformer", "vae"):
            getattr(pipe, name).requires_grad_(False).eval()
        self.spec = {
            "recipe": RECIPE,
            "prompt": PROMPT,
            "height": height,
            "width": width,
            "preprocessing": "RGB PIL bilinear letterbox, black padding, [-1,1], one frame",
            "tap": "MoT norm_moe_gen output; clean observed VAE tokens only",
            "pool_grid_hw": [4, 8],
            "feature_dim": pipe.transformer.config.hidden_size,
            "history_encoding": "independent per-frame encoding; temporal fusion in head",
            "validated_driving_encoder": False,
            **provenance,
        }

    @classmethod
    def from_checkpoint(cls, checkpoint, device="cuda", height=256, width=448):
        # All paths local; no authentication, hub fallback, or auto-download.
        from diffusers import (
            AutoencoderKLWan,
            Cosmos3OmniPipeline,
            Cosmos3OmniTransformer,
        )

        checkpoint = Path(checkpoint).resolve()
        if not checkpoint.is_dir():
            raise ValueError("A local checkpoint directory is required")
        dtype = torch.bfloat16 if str(device).startswith("cuda") else torch.float32
        components, loading = {}, {}
        for name, model_class in (
            ("transformer", Cosmos3OmniTransformer),
            ("vae", AutoencoderKLWan),
        ):
            component, info = model_class.from_pretrained(
                checkpoint / name,
                torch_dtype=dtype,
                local_files_only=True,
                output_loading_info=True,
            )
            if any(
                info.get(key)
                for key in (
                    "missing_keys",
                    "unexpected_keys",
                    "mismatched_keys",
                    "error_msgs",
                )
            ):
                raise ValueError(f"Strict checkpoint loading failed for {name}: {info}")
            components[name], loading[name] = component, info
        pipe = Cosmos3OmniPipeline.from_pretrained(
            checkpoint, local_files_only=True, torch_dtype=dtype, **components
        )
        pipe.to(device)
        pipe.set_progress_bar_config(disable=True)
        provenance = {
            "checkpoint": str(checkpoint),
            "strict_loading": loading,
            "model_index_sha256": file_hash(checkpoint / "model_index.json"),
            "transformer_config_sha256": file_hash(
                checkpoint / "transformer/config.json"
            ),
            "transformer_source_sha256": file_hash(
                inspect.getfile(type(pipe.transformer))
            ),
            "pipeline_source_sha256": file_hash(inspect.getfile(type(pipe))),
            "feature_code_sha256": file_hash(__file__),
            "weights_inventory": [
                {
                    "path": str(p.relative_to(checkpoint)),
                    "bytes": p.stat().st_size,
                    "mtime_ns": p.stat().st_mtime_ns,
                }
                for folder in ("transformer", "vae")
                for p in sorted((checkpoint / folder).glob("*.safetensors"))
            ],
        }
        return cls(pipe, provenance, height, width)

    @torch.no_grad()
    def encode_image(self, image):
        # VAE caches and temporary hooks are not shared concurrently.
        with self.lock:
            tensor, geometry = letterbox(image, self.height, self.width)
            param = next(self.pipe.transformer.parameters())
            latent = self.pipe._encode_video(
                tensor.to(device=param.device, dtype=param.dtype)
            )
            ids, _ = self.pipe.tokenize_prompt(
                PROMPT,
                num_frames=1,
                height=self.height,
                width=self.width,
                use_system_prompt=False,
                add_duration_template=False,
            )
            return clean_latent_features(self.pipe, latent, ids), geometry
