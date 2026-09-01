# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA Corporation

"""Thin VAVAM inference wrapper used by the challenge driver."""

from __future__ import annotations

import logging
import os
import platform
from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import dataclass

import numpy as np
import omegaconf.dictconfig
import omegaconf.listconfig
import torch
import torch.serialization
from PIL import Image

LOGGER = logging.getLogger(__name__)

torch.serialization.add_safe_globals(
    [
        omegaconf.listconfig.ListConfig,
        omegaconf.dictconfig.DictConfig,
    ]
)


@dataclass(frozen=True)
class VavamPrediction:
    trajectory_xy: np.ndarray
    headings: np.ndarray
    candidates_xy: np.ndarray | None = None
    """(k,T,2) all sampled candidates, gain-scaled. None when k == 1.

    Row 0 is byte-identical to what `predict()` would have returned with the same
    seed - the k-sample path must reproduce candidate #2 exactly when selection is
    off. S0 relies on this.
    """


class VavamPolicy:
    """Loads VAVAM and predicts a 2 Hz ego-relative trajectory."""

    expected_height = 900
    expected_width = 1600
    output_frequency_hz = 2.0
    dtype = torch.float32 if platform.machine() == "aarch64" else torch.float16

    def __init__(
        self,
        *,
        checkpoint_path: str,
        tokenizer_path: str,
        device: str = "cuda",
    ) -> None:
        from vam.action_expert import VideoActionModelInference
        from vam.datalib.transforms import NeuroNCAPTransform

        resolved_device = torch.device(device if torch.cuda.is_available() else "cpu")
        if resolved_device.type != "cuda":
            LOGGER.warning("CUDA is unavailable; loading VAVAM on CPU")

        ckpt = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        config = ckpt["hyper_parameters"]["vam_conf"].copy()
        config.pop("_target_", None)
        config.pop("_recursive_", None)
        config["gpt_checkpoint_path"] = None
        config["action_checkpoint_path"] = None
        config["gpt_mup_base_shapes"] = None
        config["action_mup_base_shapes"] = None

        LOGGER.info("Loading VAVAM checkpoint from %s", checkpoint_path)
        vam = VideoActionModelInference(**config)
        state_dict = OrderedDict()
        for key, value in ckpt["state_dict"].items():
            state_dict[key.replace("vam.", "")] = value
        vam.load_state_dict(state_dict, strict=True)
        # LOCAL PATCH: apply the muP base shapes the checkpoint was trained with (MuReadout divides
        # by width_mult = 4 for B, 8 for L). Upstream sample leaves them None. Opt-in via env var.
        mup_dir = os.environ.get("VAVAM_MUP_SHAPES_DIR")
        if mup_dir:
            import mup
            mup.set_base_shapes(vam.gpt, os.path.join(mup_dir, "gpt2_24layers_basewidth256.bsh"), rescale_params=False)
            mup.set_base_shapes(vam.action_expert, os.path.join(mup_dir, "actionexpert_24layers_baseattentiondim256_baseembeddingdim64.bsh"), rescale_params=False)
            LOGGER.info("Applied muP base shapes from %s", mup_dir)
        self._vam = vam.eval().to(resolved_device)

        LOGGER.info("Loading VQ tokenizer from %s", tokenizer_path)
        self._tokenizer = torch.jit.load(tokenizer_path, map_location=resolved_device)
        self._tokenizer.to(resolved_device).eval()

        self._device = resolved_device
        self._preproc_pipeline = NeuroNCAPTransform()
        # LOCAL PATCH (opt-in, inert by default): output gain on the predicted waypoints and deterministic
        # per-call seeding of the flow-matching sampler (torch.randn start noise). VAVAM_SEED=-1 -> unseeded.
        self._output_gain = float(os.environ.get("VAVAM_OUTPUT_GAIN", "1.0"))
        self._seed = int(os.environ.get("VAVAM_SEED", "-1"))
        self._num_samples = max(1, int(os.environ.get("VAVAM_NUM_SAMPLES", "1")))
        self._euler_steps = int(os.environ.get("VAVAM_EULER_STEPS", "0")) or None
        # Per-session call counters. The old code used one global counter, so with two
        # concurrent rollouts sharing this policy the *order* in which they reached the
        # inference lock decided which noise each got - serialised is not ordered, and
        # A/B pairs silently stopped being paired. Keying on session_uuid makes each
        # rollout's noise sequence independent of scheduling.
        self._session_calls: dict[str, int] = {}
        if self._output_gain != 1.0 or self._seed >= 0 or self._num_samples > 1:
            LOGGER.info(
                "Policy options: output_gain=%.3f seed=%d k=%d euler_steps=%s",
                self._output_gain, self._seed, self._num_samples, self._euler_steps,
            )
        self._use_autocast = (
            resolved_device.type == "cuda" and platform.machine() != "aarch64"
        )

    def _seed_for(self, session_uuid: str | None) -> None:
        """Seed the sampler deterministically per session, not per global call."""
        if self._seed < 0:
            return
        key = session_uuid or ""
        n = self._session_calls.get(key, 0)
        self._session_calls[key] = n + 1
        # stable 32-bit offset per session; independent of arrival order
        offset = 0 if not key else (hash(key) & 0xFFFF) * 100_003
        torch.manual_seed((self._seed + offset + n) % (2**31 - 1))

    def predict(
        self, image_hwc: np.ndarray, command: int, session_uuid: str | None = None
    ) -> VavamPrediction:
        """Predict a single trajectory. Equivalent to `predict_k(..., k=1)`."""
        return self.predict_k(image_hwc, command, k=1, session_uuid=session_uuid)

    def predict_k(
        self,
        image_hwc: np.ndarray,
        command: int,
        k: int | None = None,
        session_uuid: str | None = None,
    ) -> VavamPrediction:
        """Draw k trajectories from one forward pass and return them all.

        `forward_inference` reads batch size from the visual tokens and draws
        `randn((bsz,1,6,2))`, so k i.i.d. samples cost **one** call: the GPT trunk runs
        once and is KV-cached, and only the small action-expert Euler steps scale with k.

        Row 0 of a seeded `randn((k,...))` equals the seeded `randn((1,...))` draw, so
        with the same seed `predict_k(k=5).trajectory_xy == predict(k=1).trajectory_xy`.
        That identity is what makes S0 behaviour-identical to candidate #2.

        Args:
            image_hwc: uint8 RGB image in HWC layout.
            command: VAVAM command id, where 0=right, 1=left, 2=straight.
            k: number of samples. Defaults to `VAVAM_NUM_SAMPLES` (1).
            session_uuid: rollout id; scopes the RNG so concurrent rollouts do not
                steal each other's noise.
        """
        k = self._num_samples if k is None else max(1, int(k))

        image = self._resize_and_center_crop(
            image_hwc,
            self.expected_height,
            self.expected_width,
        )
        tensor = self._preproc_pipeline(image).unsqueeze(0).to(self._device)
        autocast_ctx = (
            torch.amp.autocast(self._device.type, dtype=self.dtype)
            if self._use_autocast
            else nullcontext()
        )

        self._seed_for(session_uuid)
        with torch.no_grad():
            with autocast_ctx:
                tokens = self._tokenizer(tensor)
                batched_tokens = tokens.unsqueeze(1)
                if k > 1:  # (1,1,N) -> (k,1,N); trunk runs once, KV-cached
                    batched_tokens = batched_tokens.expand(k, -1, -1)
                batched_command = torch.full(
                    (k, 1), command, device=self._device, dtype=torch.long
                )
                if self._euler_steps:
                    trajectory = self._vam(
                        batched_tokens, batched_command, self.dtype,
                        num_inference_steps=self._euler_steps,
                    )
                else:
                    trajectory = self._vam(batched_tokens, batched_command, self.dtype)

        candidates = _format_trajectories(trajectory, k)
        if self._output_gain != 1.0:
            candidates = candidates * self._output_gain
        trajectory_xy = candidates[0]
        return VavamPrediction(
            trajectory_xy=trajectory_xy,
            headings=_compute_headings(trajectory_xy),
            candidates_xy=candidates if k > 1 else None,
        )

    @staticmethod
    def _resize_and_center_crop(
        image: np.ndarray,
        target_height: int,
        target_width: int,
    ) -> np.ndarray:
        h, w = image.shape[:2]
        if h == target_height and w == target_width:
            return image

        pil_img = Image.fromarray(image)
        scale = target_height / h
        new_w = int(w * scale)
        pil_img = pil_img.resize((new_w, target_height), Image.Resampling.BILINEAR)

        if new_w > target_width:
            left = (new_w - target_width) // 2
            pil_img = pil_img.crop((left, 0, left + target_width, target_height))
        elif new_w < target_width:
            raise ValueError(
                f"Image width {new_w} too small after resize, need {target_width}"
            )

        return np.array(pil_img)


def _format_trajectories(trajectory: torch.Tensor, k: int) -> np.ndarray:
    """(k,T,2) from whatever shape the model returns. k == 1 matches `_format_trajectory`."""
    array = trajectory.detach().float().cpu().numpy()
    # squeeze any singleton axes that are not the k axis or the (T,2) tail
    while array.ndim > 3 and array.shape[0] == 1:
        array = array.squeeze(0)
    if array.ndim == 2:
        array = array[None, ...]
    if array.ndim == 4 and array.shape[1] == 1:
        array = array.squeeze(1)
    if array.ndim != 3 or array.shape[0] != k or array.shape[2] != 2:
        raise ValueError(
            f"Unexpected VAVAM trajectory shape {tuple(array.shape)} for k={k}"
        )
    return array


def _format_trajectory(trajectory: torch.Tensor) -> np.ndarray:
    array = trajectory.detach().float().cpu().numpy()
    while array.ndim > 2 and array.shape[0] == 1:
        array = array.squeeze(0)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError(f"Unexpected VAVAM trajectory shape {array.shape}")
    return array


def _compute_headings(trajectory_xy: np.ndarray) -> np.ndarray:
    prev = np.zeros_like(trajectory_xy)
    prev[1:, :] = trajectory_xy[:-1, :]
    deltas = trajectory_xy - prev
    return np.arctan2(deltas[:, 1], deltas[:, 0])
