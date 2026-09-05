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


# LOCAL PATCH: env-overridable so route-command arms can be screened without a rebuild.
# DEFAULTS ARE THE ORIGINAL VALUES and must stay that way - they are what the n=400 confirm measured.
#
# TESTED AND REJECTED (09-05): matching VaVAM's 20.0 / 3.0 / longitudinal-x scored 0.9399 vs 0.9499
# pre-fix on the paired 100 (97 unchanged, 1 better, 2 worse, 0 corridor exits repaired, 1 new one).
# The premise was wrong: `route_start_offset_m: 40.0` (e2e_challenge_nuplan_common/base.yaml:121, and
# in every run config) means the submitted route STARTS ~40 m ahead of the ego, so no waypoint is ever
# within 5 m and BOTH gates select the same first waypoint. The lookahead and the distance metric are
# therefore inert on real routes; only the lateral threshold (2.0 vs 3.0) has any effect, and 3.0 was
# slightly worse. The "phantom turn on a sideways waypoint" mechanism cannot occur - the synthetic
# route [(1,6),(30,0.5)] used to demonstrate it is not a shape the simulator produces.
_LATERAL_THRESHOLD_M = float(os.environ.get("WAJEPA_ROUTE_LATERAL_THRESHOLD_M", "2.0"))
_MIN_LOOKAHEAD_M = float(os.environ.get("WAJEPA_ROUTE_MIN_LOOKAHEAD_M", "5.0"))
_USE_EUCLIDEAN = os.environ.get("WAJEPA_ROUTE_EUCLIDEAN", "1") == "1"

# LOCAL PATCH 2 (2026-09-05): WAJEPA_ROUTE_MODE selects the route -> command rule.
#   waypoint    (default) the rule above: first waypoint at >= min_lookahead, lateral test only.
#   arc_length  WA-JEPA's own label-inference rule, ported from WA-JEPA/datasets/nav_command_infer.py
#               (infer_nav_command_arc_length + decide_command, module defaults NAV_COMMAND_*): prepend
#               the ego origin, walk FORWARD_M along the polyline, read lateral y and heading there, and
#               emit LEFT/RIGHT only when BOTH exceed their thresholds (combine=and). Route waypoints
#               carry no heading, so vertex headings are the outgoing segment directions. The challenge
#               route starts ~40 m ahead (route_start_offset_m: 40), so the first 40 m of the walk is the
#               straight join ego -> first waypoint, exactly as WA-JEPA's function handles a trajectory
#               shorter than FORWARD_M.
_ROUTE_MODE = os.environ.get("WAJEPA_ROUTE_MODE", "waypoint").strip().lower()
_ARC_FORWARD_M = float(os.environ.get("WAJEPA_ROUTE_FORWARD_M", "20.0"))
_ARC_LATERAL_M = float(os.environ.get("WAJEPA_ROUTE_LATERAL_M", "2.5"))
_ARC_HEADING_RAD = float(os.environ.get("WAJEPA_ROUTE_HEADING_RAD", "0.15"))
_ARC_COMBINE = os.environ.get("WAJEPA_ROUTE_COMBINE", "and").strip().lower()
if _ROUTE_MODE not in ("waypoint", "arc_length"):
    raise ValueError(f"WAJEPA_ROUTE_MODE must be 'waypoint' or 'arc_length', got {_ROUTE_MODE!r}")
if _ARC_COMBINE not in ("or", "and", "lat_only", "heading_only"):
    raise ValueError(f"WAJEPA_ROUTE_COMBINE must be or/and/lat_only/heading_only, got {_ARC_COMBINE!r}")


def describe_route_rule() -> str:
    """One line for the startup log so the RESOLVED rule is on record, not just the env."""
    if _ROUTE_MODE == "arc_length":
        return (
            f"route_rule=arc_length forward_m={_ARC_FORWARD_M} lateral_m={_ARC_LATERAL_M} "
            f"heading_rad={_ARC_HEADING_RAD} combine={_ARC_COMBINE}"
        )
    return (
        f"route_rule=waypoint min_lookahead_m={_MIN_LOOKAHEAD_M} "
        f"lateral_threshold_m={_LATERAL_THRESHOLD_M} euclidean={_USE_EUCLIDEAN}"
    )


def _decide(y: float, h: float, lateral_m: float, head_rad: float, combine: str) -> DriveCommand:
    """Port of WA-JEPA decide_command; its 0/1/2 coincide with DriveCommand LEFT/STRAIGHT/RIGHT."""
    if combine == "or":
        if h > head_rad or y > lateral_m:
            return DriveCommand.LEFT
        if h < -head_rad or y < -lateral_m:
            return DriveCommand.RIGHT
        return DriveCommand.STRAIGHT
    if combine == "and":
        if h > head_rad and y > lateral_m:
            return DriveCommand.LEFT
        if h < -head_rad and y < -lateral_m:
            return DriveCommand.RIGHT
        return DriveCommand.STRAIGHT
    if combine == "lat_only":
        if y > lateral_m:
            return DriveCommand.LEFT
        if y < -lateral_m:
            return DriveCommand.RIGHT
        return DriveCommand.STRAIGHT
    if h > head_rad:
        return DriveCommand.LEFT
    if h < -head_rad:
        return DriveCommand.RIGHT
    return DriveCommand.STRAIGHT


def _finite_xy(route: egodriver_pb2.Route) -> np.ndarray:
    pts = np.array([(wp.x, wp.y) for wp in route.waypoints], dtype=np.float64).reshape(-1, 2)
    if len(pts) == 0:
        return pts
    return pts[np.isfinite(pts).all(axis=1)]


def arc_length_decision(
    pts: np.ndarray,
    forward_m: float,
    lateral_m: float,
    heading_rad: float,
    combine: str,
) -> tuple[DriveCommand, float, float]:
    """WA-JEPA infer_nav_command_arc_length on finite ego-frame waypoints; returns (cmd, y, heading)."""
    if len(pts) == 0:
        return DriveCommand.STRAIGHT, 0.0, 0.0
    xy = np.vstack([np.zeros((1, 2)), pts])  # ego origin first, as WA-JEPA does (xy[0] = 0)
    diffs = np.diff(xy, axis=0)
    seg_len = np.linalg.norm(diffs, axis=1)
    total = float(seg_len.sum())
    if total < 1e-9:
        return DriveCommand.STRAIGHT, 0.0, 0.0
    seg_h = np.arctan2(diffs[:, 1], diffs[:, 0])
    h_vert = np.empty(len(xy), dtype=np.float64)
    h_vert[0] = 0.0  # ego heading at the origin (WA-JEPA: h_vert[0] = 0)
    h_vert[1:-1] = seg_h[1:]  # outgoing segment direction at each interior waypoint
    h_vert[-1] = seg_h[-1]  # incoming direction at the last waypoint

    if total < forward_m:
        if float(seg_len[-1]) > 1e-9:
            direc = diffs[-1] / seg_len[-1]
        else:
            direc = np.array([np.cos(h_vert[-1]), np.sin(h_vert[-1])])
        pos = xy[-1] + direc * (forward_m - total)
        y_lat, h_at = float(pos[1]), float(h_vert[-1])
    else:
        y_lat, h_at = float(xy[-1, 1]), float(h_vert[-1])
        cum = 0.0
        for i in range(len(seg_len)):
            length = float(seg_len[i])
            if length < 1e-12:
                continue
            if cum + length >= forward_m - 1e-9:
                t = (forward_m - cum) / length
                pos = xy[i] + t * diffs[i]
                dh = float(h_vert[i + 1] - h_vert[i])
                dh = (dh + np.pi) % (2 * np.pi) - np.pi
                y_lat, h_at = float(pos[1]), float(h_vert[i] + t * dh)
                break
            cum += length
    return _decide(y_lat, h_at, lateral_m, heading_rad, combine), y_lat, h_at


def command_from_route_arc_length(
    route: egodriver_pb2.Route,
    *,
    forward_m: float | None = None,
    lateral_m: float | None = None,
    heading_rad: float | None = None,
    combine: str | None = None,
) -> np.ndarray:
    if not route.waypoints:
        return command_one_hot(DriveCommand.UNKNOWN)
    cmd, _, _ = arc_length_decision(
        _finite_xy(route),
        _ARC_FORWARD_M if forward_m is None else forward_m,
        _ARC_LATERAL_M if lateral_m is None else lateral_m,
        _ARC_HEADING_RAD if heading_rad is None else heading_rad,
        _ARC_COMBINE if combine is None else combine,
    )
    return command_one_hot(cmd)


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
    if _ROUTE_MODE == "arc_length":
        return command_from_route_arc_length(route)
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
