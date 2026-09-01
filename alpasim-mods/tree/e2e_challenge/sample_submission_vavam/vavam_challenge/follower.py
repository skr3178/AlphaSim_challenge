# SPDX-License-Identifier: Apache-2.0
"""Route follower: lateral path from the accumulated route, speed from bounded rules.

Design: ROUTE-FOLLOWER-CONCEPT.md §2 (PDM-Closed structure: one centre-line reference, a
few speed options, pick conservatively). Pure numpy; the driver turns the returned
CachedPlan into the Drive response with the existing `build_trajectory_from_plan`, so speed
is encoded the way the simulator MPC expects (pose spacing in time).

Sources of the target speed along the reference (all bounded by a_max / d_max / v_max):
  keep  - hold the current speed (the sim starts the ego at the recorded state, so v0 is the
          human's speed), floored at v_min so a slow start still makes progress;
  curv  - lateral-acceleration cap sqrt(a_lat_max / kappa) from the reference curvature;
  vavam - the speed profile implied by the camera model's own waypoints (its view of lead
          vehicles, lights, stop lines), decoupled from its lateral wander.
speed_src selects which are combined by a point-wise minimum: min|curv|keep|vavam.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .route_map import RouteMap, hermite_join
from .trajectory import CachedPlan

__all__ = ["FollowConfig", "FollowResult", "build_follow_plan", "speed_profile_from_trajectory"]


@dataclass(frozen=True)
class FollowConfig:
    speed_src: str = "min"
    a_lat_max: float = 3.0
    a_max: float = 2.0
    d_max: float = 3.0
    v_min: float = 3.0
    v_max: float = 20.0
    horizon_s: float = 5.0
    dt_s: float = 0.1
    ds_m: float = 0.5
    join_time_s: float = 2.0
    join_min_m: float = 8.0
    join_max_m: float = 25.0
    curv_window_m: float = 6.0
    max_offset_m: float = 15.0
    """Beyond this cross-track distance the path is not trusted (fallback to the model)."""


@dataclass(frozen=True)
class FollowResult:
    plan: CachedPlan
    s_ego: float
    e_y: float
    e_psi: float
    dist: float
    join_m: float
    v0: float
    v_end: float
    kappa_max: float
    limiting: str
    """Which source set the minimum target most often over the horizon."""
    ref_xy: np.ndarray


def speed_profile_from_trajectory(traj_xy: np.ndarray, step_s: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """(s, v) implied by a rig-frame waypoint trajectory sampled every step_s (first point = one step ahead)."""
    p = np.vstack([[0.0, 0.0], np.asarray(traj_xy, dtype=float).reshape(-1, 2)])
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    v = np.maximum(seg / step_s, 0.0)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    v = np.concatenate([v[:1], v])  # speed at s=0 is the first segment's
    return s, v


def _curvature(ref: np.ndarray, ds: float, window_m: float) -> np.ndarray:
    d = np.diff(ref, axis=0)
    ang = np.unwrap(np.arctan2(d[:, 1], d[:, 0]))
    kappa = np.zeros(len(ref))
    if len(ang) >= 2:
        k = np.diff(ang) / ds
        kappa[1:-1] = k
        kappa[0], kappa[-1] = k[0], k[-1]
    kappa = np.abs(kappa)
    w = max(1, int(round(window_m / ds)))
    if w > 1:
        # dilate (running max) rather than blur: the cap must be reached BEFORE the turn, and a
        # moving average halves the apparent curvature at the entry, which let 3.9 m/s2 through.
        padded = np.pad(kappa, (w // 2, w - 1 - w // 2), mode="edge")
        kappa = np.max(np.lib.stride_tricks.sliding_window_view(padded, w), axis=1)
    return kappa


def _resample(poly: np.ndarray, ds: float) -> tuple[np.ndarray, np.ndarray]:
    keep = np.concatenate([[True], np.linalg.norm(np.diff(poly, axis=0), axis=1) > 1e-6])
    poly = poly[keep]
    cl = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(poly, axis=0), axis=1))])
    n = max(2, int(np.floor(cl[-1] / ds)) + 1)
    s = np.linspace(0.0, cl[-1], n)
    return np.column_stack([np.interp(s, cl, poly[:, 0]), np.interp(s, cl, poly[:, 1])]), s


def build_follow_plan(
    route_map: RouteMap,
    pose_xy_yaw: tuple[float, float, float],
    speed_mps: float,
    time_now_us: int,
    cfg: FollowConfig = FollowConfig(),
    vavam_traj_rig: np.ndarray | None = None,
) -> FollowResult | None:
    """Reference path + speed profile -> CachedPlan anchored at the current pose. None if not usable."""
    q = route_map.query(pose_xy_yaw)
    if q is None or not np.isfinite(q.dist):
        return None
    if q.on_path or q.s_ego > float(route_map.s[0]) + 0.5:
        if q.dist > cfg.max_offset_m:
            return None  # interior projection but far from the path: not our lane
    else:
        # ego is before the path start (cold start: the first windows begin 40 m ahead). Accept only
        # if the start lies ahead of the ego and within a lane-ish lateral band.
        c, s_ = np.cos(pose_xy_yaw[2]), np.sin(pose_xy_yaw[2])
        rel = route_map.path[0] - np.array([pose_xy_yaw[0], pose_xy_yaw[1]])
        fwd, lat = c * rel[0] + s_ * rel[1], -s_ * rel[0] + c * rel[1]
        if fwd < -5.0 or abs(lat) > cfg.max_offset_m or fwd > 90.0:
            return None
    v0 = float(np.clip(speed_mps if np.isfinite(speed_mps) else 0.0, 0.0, cfg.v_max))
    horizon_m = max(cfg.horizon_s * max(v0, cfg.v_min) * 1.5, 40.0)

    # --- lateral: Hermite join from the ego pose onto the path at a look-ahead point, then the path
    p0 = np.array([pose_xy_yaw[0], pose_xy_yaw[1]])
    t0 = np.array([np.cos(pose_xy_yaw[2]), np.sin(pose_xy_yaw[2])])
    join_m = float(np.clip(cfg.join_time_s * v0, cfg.join_min_m, cfg.join_max_m))
    s_target = min(q.s_ego + join_m, float(route_map.s[-1]))
    if not q.on_path and q.s_ego <= float(route_map.s[0]) + 0.5:
        s_target = min(float(route_map.s[0]) + join_m, float(route_map.s[-1]))  # cold start: bridge to the start
    p1, t1 = route_map.point_at(s_target), route_map.tangent_at(s_target)
    join = hermite_join(p0, t0, p1, t1)
    rest = route_map.ahead(s_target, horizon_m)
    ref_raw = np.vstack([join, rest[1:]]) if len(rest) > 1 else join
    ref, s_ref = _resample(ref_raw, cfg.ds_m)
    if len(ref) < 3:
        return None

    # --- longitudinal: target speed per source, point-wise minimum, then accel/decel-feasible profile
    kappa = _curvature(ref, cfg.ds_m, cfg.curv_window_m)
    v_curv = np.minimum(np.sqrt(cfg.a_lat_max / np.maximum(kappa, 1e-4)), cfg.v_max)
    v_keep = np.full(len(ref), float(np.clip(max(v0, cfg.v_min), 0.0, cfg.v_max)))
    sources = {"keep": v_keep}
    if cfg.speed_src in ("min", "curv"):
        sources["curv"] = v_curv
    if cfg.speed_src in ("min", "vavam") and vavam_traj_rig is not None:
        sv, vv = speed_profile_from_trajectory(vavam_traj_rig)
        sources["vavam"] = np.interp(s_ref, sv, vv, right=float(vv[-1]))
    stack = np.vstack(list(sources.values()))
    v_tgt = stack.min(axis=0)
    limiting = list(sources.keys())[int(np.bincount(stack.argmin(axis=0), minlength=len(sources)).argmax())]
    # backward pass (decel feasibility), forward pass (accel feasibility) from the current speed
    v_lim = v_tgt.copy()
    for i in range(len(v_lim) - 2, -1, -1):
        v_lim[i] = min(v_lim[i], np.sqrt(v_lim[i + 1] ** 2 + 2.0 * cfg.d_max * cfg.ds_m))
    v = np.empty_like(v_lim)
    v[0] = v0
    for i in range(1, len(v)):
        # never brake harder than d_max, even when the current speed already exceeds the limit
        # (the initial state is what it is; the profile converges at the physical rate)
        floor = np.sqrt(max(v[i - 1] ** 2 - 2.0 * cfg.d_max * cfg.ds_m, 0.0))
        v[i] = max(min(v_lim[i], np.sqrt(v[i - 1] ** 2 + 2.0 * cfg.a_max * cfg.ds_m)), floor)
    # time along the reference with constant acceleration inside each grid segment (exact for the
    # v^2 = v0^2 + 2 a ds profile above); linear-in-s interpolation gave a speed staircase at low speed.
    v_safe = np.maximum(v, 0.0)
    a_seg = (v_safe[1:] ** 2 - v_safe[:-1] ** 2) / (2.0 * cfg.ds_m)
    vm = np.maximum(0.5 * (v_safe[1:] + v_safe[:-1]), 0.05)
    dt_seg = cfg.ds_m / vm
    t_ref = np.concatenate([[0.0], np.cumsum(dt_seg)])
    times = np.arange(0.0, cfg.horizon_s + 1e-9, cfg.dt_s)
    idx = np.clip(np.searchsorted(t_ref, times, side="right") - 1, 0, len(a_seg) - 1)
    tau = np.clip(times - t_ref[idx], 0.0, dt_seg[idx])
    s_t = s_ref[idx] + v_safe[idx] * tau + 0.5 * a_seg[idx] * tau ** 2
    s_t = np.minimum(np.maximum.accumulate(s_t), float(s_ref[-1]))
    xy = np.column_stack([np.interp(s_t, s_ref, ref[:, 0]), np.interp(s_t, s_ref, ref[:, 1])])
    d = np.diff(ref, axis=0)
    ang = np.unwrap(np.concatenate([[np.arctan2(d[0, 1], d[0, 0])], np.arctan2(d[:, 1], d[:, 0])]))
    yaws = np.interp(s_t, s_ref, ang)
    plan = CachedPlan(int(time_now_us), times, xy, yaws)
    return FollowResult(plan, q.s_ego, q.e_y, q.e_psi, q.dist, join_m, v0, float(np.interp(s_t[-1], s_ref, v)),
                        float(kappa.max()), limiting, ref)
