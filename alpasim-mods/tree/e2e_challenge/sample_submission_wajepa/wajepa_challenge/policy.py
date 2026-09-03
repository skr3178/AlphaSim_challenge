# SPDX-License-Identifier: Apache-2.0
"""WA-JEPA policy wrapper: batched predict_trajectory behind the BatchWorker."""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from .preprocessing import CAMERA_IDS, MODEL_HEIGHT, MODEL_WIDTH

LOGGER = logging.getLogger(__name__)

NUM_HISTORY_FRAMES = 4
TRAJECTORY_SHAPE = (8, 3)
EGO_STATUS_DIM = 8


@dataclass(frozen=True)
class InferenceInput:
    """Preprocessed model inputs for one session at one 2 Hz tick.

    history_images: float32 [T=4, V=4, 3, 256, 512] in [-1, 1], oldest first,
        camera order = preprocessing.CAMERA_IDS (model slot order).
    ego_status: float32 [8] = [command_one_hot(4), vx, vy, ax, ay] (rig frame).
    history_trajectory: float32 [T=4, 3] relative SE(2) poses of the ego at the
        history frame times, expressed in the newest frame (last row ~ 0).
    """

    history_images: np.ndarray
    ego_status: np.ndarray
    history_trajectory: np.ndarray

    def __post_init__(self) -> None:
        expected = (NUM_HISTORY_FRAMES, len(CAMERA_IDS), 3, MODEL_HEIGHT, MODEL_WIDTH)
        if self.history_images.shape != expected:
            raise ValueError(
                f"history_images must have shape {expected}; "
                f"got {self.history_images.shape}"
            )
        if self.ego_status.shape != (EGO_STATUS_DIM,):
            raise ValueError(f"ego_status must have shape ({EGO_STATUS_DIM},)")
        if self.history_trajectory.shape != (NUM_HISTORY_FRAMES, 3):
            raise ValueError(
                f"history_trajectory must have shape ({NUM_HISTORY_FRAMES}, 3)"
            )


@dataclass(frozen=True)
class Prediction:
    """trajectory: float64 [8, 3] = (x fwd, y left, heading) in the rig frame
    at the inference timestamp, one pose every 0.5 s from +0.5 s to +4.0 s."""

    trajectory: np.ndarray


class WAJEPAPolicy:
    def __init__(
        self,
        config_path: str,
        checkpoint_path: str,
        *,
        device: str = "cuda",
        num_inference_steps: int | None = None,
        source_root: str = "/app/wajepa_src",
    ) -> None:
        source_root = str(Path(source_root).resolve())
        if source_root not in sys.path:
            sys.path.insert(0, source_root)
        from omegaconf import OmegaConf

        cfg = OmegaConf.load(config_path)
        OmegaConf.set_struct(cfg, False)
        # Inference restores the full trained state dict; neither the V-JEPA
        # pretrained weights nor init_from_checkpoint are needed (or present).
        cfg.model.require_pretrained = False
        cfg.model.vjepa2_ckpt = None
        cfg.model.init_from_checkpoint = None
        cfg.model.require_init_from_checkpoint = False
        if num_inference_steps is not None:
            if not 1 <= num_inference_steps <= 64:
                raise ValueError("WAJEPA_STEPS must be in [1, 64]")
            cfg.model.num_inference_steps = num_inference_steps
        cfg_dict = OmegaConf.to_container(cfg, resolve=True)

        model_cams = [str(c).lower() for c in cfg_dict["model"]["camera_names"]]
        expected_cams = [c.lower() for c in CAMERA_IDS]
        if model_cams != expected_cams:
            raise RuntimeError(
                f"model.camera_names {model_cams} does not match the driver's "
                f"camera slot order {expected_cams}"
            )

        from models.factory import build_world_model
        from training.checkpoint import load_checkpoint

        self._device = torch.device(device)
        start = time.monotonic()
        model = build_world_model(cfg_dict).to(self._device)
        # strict by default: a partially restored trajectory head would still
        # produce plausible-looking waypoints.
        load_checkpoint(
            checkpoint_path, model, map_location=device, log_fn=LOGGER.info
        )
        self.model = model.eval()
        self.steps = int(cfg_dict["model"]["num_inference_steps"])
        LOGGER.info(
            "WA-JEPA ready in %.1f s: steps=%d device=%s cuda_mem=%.2f GB",
            time.monotonic() - start,
            self.steps,
            device,
            torch.cuda.memory_allocated() / 1e9 if self._device.type == "cuda" else 0.0,
        )

    def predict_batch(self, requests: list[InferenceInput]) -> list[Prediction]:
        if not requests:
            return []
        history = torch.from_numpy(
            np.stack([r.history_images for r in requests], axis=0)
        )
        ego_status = torch.from_numpy(
            np.stack([r.ego_status for r in requests], axis=0).astype(np.float32)
        )
        history_trajectory = torch.from_numpy(
            np.stack([r.history_trajectory for r in requests], axis=0).astype(
                np.float32
            )
        )
        features = {
            "history_images": history.to(self._device, non_blocking=True),
            "ego_status": ego_status.to(self._device, non_blocking=True),
            "history_trajectory": history_trajectory.to(
                self._device, non_blocking=True
            ),
        }
        autocast = (
            torch.autocast("cuda", dtype=torch.bfloat16)
            if self._device.type == "cuda"
            else torch.autocast("cpu", dtype=torch.bfloat16)
        )
        with torch.no_grad(), autocast:
            predicted = self.model.predict_trajectory(features)
        trajectories = predicted.float().cpu().numpy().astype(np.float64)
        if trajectories.shape != (len(requests), *TRAJECTORY_SHAPE):
            raise RuntimeError(
                f"unexpected prediction shape {trajectories.shape} for "
                f"batch of {len(requests)}"
            )
        if not np.isfinite(trajectories).all():
            raise RuntimeError("prediction contains non-finite values")
        return [Prediction(trajectory=t) for t in trajectories]
