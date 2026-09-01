# SPDX-License-Identifier: Apache-2.0
"""Accumulate `submit_route` observations into one persistent lane-centre path.

Why: the challenge sends the route 40-80 m ahead of the ego every tick (rig frame at that
tick). Each window alone leaves a 40 m gap in front of the car, but successive windows,
transformed by the ego pose into the rollout's local frame, overlap and together cover the
path from behind the ego to 80 m ahead. The organizers allow this ("you can use all the
information provided over the interface", forum 380855). The route itself is the recorded
trajectory projected onto lane centres (route_generator.py), i.e. the path the scorer
measures dist_to_gt against, to within a lane-centre offset.

Frames: local = the rollout's fixed frame the ego poses are expressed in. The rig->local
transform is the one `trajectory.rig_offsets_to_local_positions` already uses for plans:
p_local = R(yaw) p_rig + t. Pure numpy, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = ["RouteMap", "PathQuery", "rig_to_local", "hermite_join"]


def rig_to_local(points_rig: np.ndarray, pose_xy_yaw: tuple[float, float, float]) -> np.ndarray:
    x, y, yaw = pose_xy_yaw
    c, s = np.cos(yaw), np.sin(yaw)
    rot = np.array([[c, -s], [s, c]])
    return np.asarray(points_rig, dtype=float).reshape(-1, 2) @ rot.T + np.array([x, y])


def _cumlen(p: np.ndarray) -> np.ndarray:
    if len(p) < 2:
        return np.zeros(len(p))
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])


def _project(points: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Perpendicular distance, arc-length at the foot, and signed lateral offset (+ = left)."""
    a, b = ref[:-1], ref[1:]
    ab = b - a
    denom = np.einsum("ij,ij->i", ab, ab)
    denom = np.where(denom > 1e-12, denom, 1.0)
    ap = points[:, None, :] - a[None, :, :]
    t = np.clip(np.einsum("psi,si->ps", ap, ab) / denom, 0.0, 1.0)
    foot = a[None] + t[:, :, None] * ab[None]
    d = np.linalg.norm(points[:, None, :] - foot, axis=2)
    best = np.argmin(d, axis=1)
    rows = np.arange(len(points))
    seg_len = np.sqrt(np.einsum("ij,ij->i", ab, ab))
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    arc = cum[best] + t[rows, best] * seg_len[best]
    tang = ab[best] / np.maximum(seg_len[best], 1e-9)[:, None]
    off = points - foot[rows, best]
    signed = tang[:, 0] * off[:, 1] - tang[:, 1] * off[:, 0]
    return d[rows, best], arc, signed


def hermite_join(p0: np.ndarray, t0: np.ndarray, p1: np.ndarray, t1: np.ndarray, n: int = 24) -> np.ndarray:
    """Cubic Hermite from p0 (tangent t0) to p1 (tangent t1); tangents scaled by the chord."""
    length = float(np.linalg.norm(p1 - p0))
    if length < 1e-6:
        return np.vstack([p0, p1])
    m0 = t0 / max(np.linalg.norm(t0), 1e-9) * length
    m1 = t1 / max(np.linalg.norm(t1), 1e-9) * length
    u = np.linspace(0.0, 1.0, n)[:, None]
    u2, u3 = u * u, u * u * u
    return (2 * u3 - 3 * u2 + 1) * p0 + (u3 - 2 * u2 + u) * m0 + (-2 * u3 + 3 * u2) * p1 + (u3 - u2) * m1


@dataclass(frozen=True)
class PathQuery:
    s_ego: float
    """Arc length of the ego's projection onto the path."""
    e_y: float
    """Signed cross-track error, + = ego is left of the path."""
    e_psi: float
    """Heading error ego - path tangent, wrapped to [-pi, pi]."""
    dist: float
    """Unsigned distance to the path."""
    on_path: bool
    """True when the projection is interior (path reaches behind the ego)."""


@dataclass
class RouteMap:
    """Persistent lane-centre path built from route observations (local frame)."""

    bin_m: float = 1.0
    keep_behind_m: float = 30.0
    max_len_m: float = 200.0
    recency: float = 0.3
    """Weight of a new observation against the accumulated estimate in an overlapping bin."""
    merge_tol_m: float = 6.0
    """A new window whose first point is further than this from the path is treated as a new segment."""
    _obs_s: list = field(default_factory=list)   # arc length per observed point
    _obs_xy: list = field(default_factory=list)  # local xy per observed point
    _obs_w: list = field(default_factory=list)   # weight per observed point
    path: np.ndarray | None = None               # (N,2) resampled path
    s: np.ndarray | None = None                  # (N,) arc length
    n_updates: int = 0

    # ----------------------------------------------------------------- update
    def update(self, route_rig_xy: np.ndarray | None, pose_xy_yaw: tuple[float, float, float] | None) -> bool:
        """Fold one route window in. Returns True when the path changed."""
        if route_rig_xy is None or pose_xy_yaw is None:
            return False
        r = np.asarray(route_rig_xy, dtype=float).reshape(-1, 2)
        r = r[np.isfinite(r).all(axis=1)]
        if len(r) < 2:
            return False
        pts = rig_to_local(r, pose_xy_yaw)
        u = _cumlen(pts)
        if self.path is None or len(self.path) < 2:
            s0 = 0.0
        else:
            d, arc, _ = _project(pts[:1], self.path)
            if d[0] > self.merge_tol_m:
                # the window does not overlap what we have; anchor it at its own distance past the end
                s0 = float(self.s[-1]) + float(np.linalg.norm(pts[0] - self.path[-1]))
            else:
                s0 = float(arc[0])
        # new observations get full weight; older ones decay through the bin average
        self._obs_s.extend((s0 + u).tolist())
        self._obs_xy.extend(pts.tolist())
        self._obs_w.extend([1.0] * len(pts))
        self.n_updates += 1
        self._rebuild(pose_xy_yaw)
        return True

    def _rebuild(self, pose_xy_yaw: tuple[float, float, float]) -> None:
        s = np.asarray(self._obs_s)
        xy = np.asarray(self._obs_xy)
        w = np.asarray(self._obs_w)
        # forget what is far behind the ego
        if self.path is not None and len(self.path) >= 2:
            _, arc_e, _ = _project(np.array([[pose_xy_yaw[0], pose_xy_yaw[1]]]), self.path)
            keep = s >= float(arc_e[0]) - self.keep_behind_m - 5.0
            if keep.sum() >= 2 and keep.sum() < len(s):
                s, xy, w = s[keep], xy[keep], w[keep]
                self._obs_s, self._obs_xy, self._obs_w = s.tolist(), xy.tolist(), w.tolist()
        # older observations weigh less: recency^(age in updates) approximated by order
        order_w = w * (1.0 - self.recency) ** (np.arange(len(w))[::-1] // 20)
        bins = np.floor((s - s.min()) / self.bin_m).astype(int)
        nb = bins.max() + 1
        sw = np.bincount(bins, weights=order_w, minlength=nb)
        sx = np.bincount(bins, weights=order_w * xy[:, 0], minlength=nb)
        sy = np.bincount(bins, weights=order_w * xy[:, 1], minlength=nb)
        filled = sw > 0
        centers = s.min() + (np.arange(nb) + 0.5) * self.bin_m
        bx = np.interp(centers, centers[filled], sx[filled] / sw[filled])
        by = np.interp(centers, centers[filled], sy[filled] / sw[filled])
        path = np.column_stack([bx, by])
        # drop consecutive duplicates, then resample at bin_m along actual arc length
        keep = np.concatenate([[True], np.linalg.norm(np.diff(path, axis=0), axis=1) > 1e-6])
        path = path[keep]
        cl = _cumlen(path)
        if cl[-1] > self.max_len_m:
            start = cl[-1] - self.max_len_m
            sel = cl >= start
            path, cl = path[sel], cl[sel] - cl[sel][0]
        n = max(2, int(np.floor(cl[-1] / self.bin_m)) + 1)
        target = np.linspace(0.0, cl[-1], n)
        self.path = np.column_stack([np.interp(target, cl, path[:, 0]), np.interp(target, cl, path[:, 1])])
        self.s = target

    # ----------------------------------------------------------------- queries
    def ready(self) -> bool:
        return self.path is not None and len(self.path) >= 4

    def query(self, pose_xy_yaw: tuple[float, float, float]) -> PathQuery | None:
        if not self.ready():
            return None
        p = np.array([[pose_xy_yaw[0], pose_xy_yaw[1]]])
        d, arc, signed = _project(p, self.path)
        tang = self.tangent_at(float(arc[0]))
        e_psi = float(np.arctan2(np.sin(pose_xy_yaw[2] - np.arctan2(tang[1], tang[0])),
                                 np.cos(pose_xy_yaw[2] - np.arctan2(tang[1], tang[0]))))
        on_path = 0.5 < float(arc[0]) < float(self.s[-1]) - 0.5
        return PathQuery(float(arc[0]), float(signed[0]), e_psi, float(d[0]), on_path)

    def point_at(self, arc: float) -> np.ndarray:
        arc = float(np.clip(arc, self.s[0], self.s[-1]))
        return np.array([np.interp(arc, self.s, self.path[:, 0]), np.interp(arc, self.s, self.path[:, 1])])

    def tangent_at(self, arc: float) -> np.ndarray:
        i = int(np.clip(np.searchsorted(self.s, arc) - 1, 0, len(self.s) - 2))
        v = self.path[i + 1] - self.path[i]
        n = float(np.linalg.norm(v))
        return v / n if n > 1e-9 else np.array([1.0, 0.0])

    def ahead(self, arc_from: float, length_m: float, step_m: float = 1.0) -> np.ndarray:
        arcs = np.arange(arc_from, min(arc_from + length_m, float(self.s[-1])) + 1e-9, step_m)
        if len(arcs) < 2:
            arcs = np.array([arc_from, float(self.s[-1])])
        return np.column_stack([np.interp(arcs, self.s, self.path[:, 0]), np.interp(arcs, self.s, self.path[:, 1])])

    def remaining_ahead(self, pose_xy_yaw) -> float:
        q = self.query(pose_xy_yaw)
        return float(self.s[-1] - q.s_ego) if q else 0.0
