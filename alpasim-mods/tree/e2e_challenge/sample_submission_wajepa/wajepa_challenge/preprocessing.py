# SPDX-License-Identifier: Apache-2.0
"""Camera preprocessing for the WA-JEPA driver.

CAMERA_IDS is the MODEL slot order (wa_jepa_infer.yaml `model.camera_names`
lower-cased): the model indexes a learned camera embedding by list position,
so this tuple must stay aligned with the config entry by entry.
"""

from __future__ import annotations

import cv2
import numpy as np

CAMERA_IDS = ("CAM_L0", "CAM_F0", "CAM_R0", "CAM_B0")
EXPECTED_HEIGHT = 1080
EXPECTED_WIDTH = 1920
MODEL_HEIGHT = 256
MODEL_WIDTH = 512


def image_to_model_tensor(camera_id: str, image: np.ndarray) -> np.ndarray:
    """1920x1080 RGB uint8 -> float32 [3, 256, 512] in [-1, 1].

    Mirrors WA-JEPA's HUGSIM adapter `_image_tensor` (resize INTER_AREA,
    /255 * 2 - 1, clamp); further normalization happens inside the model.
    """
    if image.shape != (EXPECTED_HEIGHT, EXPECTED_WIDTH, 3):
        raise ValueError(
            f"{camera_id} image must be {EXPECTED_WIDTH}x{EXPECTED_HEIGHT} RGB; "
            f"got {image.shape}"
        )
    resized = cv2.resize(
        image, (MODEL_WIDTH, MODEL_HEIGHT), interpolation=cv2.INTER_AREA
    )
    tensor = resized.astype(np.float32).transpose(2, 0, 1) / 255.0
    return np.clip(tensor * 2.0 - 1.0, -1.0, 1.0)
