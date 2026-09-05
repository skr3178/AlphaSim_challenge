# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA Corporation

from __future__ import annotations

import os
from enum import IntEnum

import numpy as np
from alpasim_grpc.v0 import egodriver_pb2


class DriveCommand(IntEnum):
    LEFT = 0
    STRAIGHT = 1
    RIGHT = 2
    UNKNOWN = 3


def command_one_hot(command: DriveCommand) -> np.ndarray:
    one_hot = np.zeros(4, dtype=np.float32)
    one_hot[int(command)] = 1.0
    return one_hot


# LOCAL PATCH: these three values were copied from the GTRS sample (5.0 / 2.0 / Euclidean).
# VaVAM, which is the driver validated on this nuPlan route contract, uses 20.0 / 3.0 and measures
# LONGITUDINAL distance only (driver.py:735-737). A 5 m Euclidean gate fires on a waypoint that is
# merely 5 m to the SIDE, so the command flips to LEFT/RIGHT while the ego is still travelling
# straight - the suspected cause of the 15 corridor exits (worth 0.0375 of the margin). Defaults now
# match VaVAM; all three are env-overridable so arms can be screened without a rebuild.
_LATERAL_THRESHOLD_M = float(os.environ.get("WAJEPA_ROUTE_LATERAL_THRESHOLD_M", "3.0"))
_MIN_LOOKAHEAD_M = float(os.environ.get("WAJEPA_ROUTE_MIN_LOOKAHEAD_M", "20.0"))
_USE_EUCLIDEAN = os.environ.get("WAJEPA_ROUTE_EUCLIDEAN", "0") == "1"


def command_from_route(
    route: egodriver_pb2.Route,
    *,
    lateral_threshold_m: float | None = None,
    min_lookahead_m: float | None = None,
) -> np.ndarray:
    lateral_threshold_m = (
        _LATERAL_THRESHOLD_M if lateral_threshold_m is None else lateral_threshold_m
    )
    min_lookahead_m = _MIN_LOOKAHEAD_M if min_lookahead_m is None else min_lookahead_m
    if not route.waypoints:
        return command_one_hot(DriveCommand.UNKNOWN)

    def _reach(waypoint: egodriver_pb2.Waypoint) -> float:
        return float(
            np.hypot(waypoint.x, waypoint.y) if _USE_EUCLIDEAN else waypoint.x
        )

    target = next(
        (
            waypoint
            for waypoint in route.waypoints
            if _reach(waypoint) >= min_lookahead_m
        ),
        None,
    )
    if target is None:
        return command_one_hot(DriveCommand.STRAIGHT)

    if abs(target.y) <= lateral_threshold_m:
        command = DriveCommand.STRAIGHT
    elif target.y > 0:
        command = DriveCommand.LEFT
    else:
        command = DriveCommand.RIGHT
    return command_one_hot(command)
