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
    """Persistent lane-centre path built from route observations (local frame).

    Design (v2, after the arc-frame collapse bug): the path is a plain polyline that only
    EXTENDS at its end and PRUNES at its front. Arc labels (`self.s`) are recomputed from
    the geometry on every change and are never stored across updates, so no bookkeeping
    frame exists to drift. Interior points are not refined: successive windows overlap by
    ~35 m and agree to ~1 cm (measured), so the first window to cover a stretch fixes it.

    The v1 implementation kept an observation cloud labelled by arc length while
    `_rebuild` re-based the path arc to zero; after the first behind-the-ego prune the two
    frames mixed, the same road carried two labels, and the path collapsed to a ~20 m stub
    once the ego had driven ~100 m (found by the selector session with a 320 m repro).
    """

    bin_m: float = 1.0
    keep_behind_m: float = 30.0
    max_len_m: float = 250.0
    merge_tol_m: float = 8.0
    """First appended point of a window must project within this of the current path end."""
    path: np.ndarray | None = None               # (N,2) local-frame polyline, ~bin_m spacing
    s: np.ndarray | None = None                  # (N,) arc length, 0-based, fresh each change
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
        self.n_updates += 1
        if self.path is None or len(self.path) < 2:
            self._set_path(pts)
            self._prune(pose_xy_yaw)
            return True
        # points that reach past the current end: their clamped projection lands on the last
        # 25 cm of the path. Window points are ordered and ~4.2 m apart, and successive
        # windows overlap the path by ~35 m, so the first such point sits near the end.
        d, arc, _ = _project(pts, self.path)
        end = float(self.s[-1])
        beyond = np.flatnonzero(arc >= end - 0.25)
        changed = False
        if len(beyond):
            k = int(beyond[0])
            if d[k] <= self.merge_tol_m:
                ext = [self.path[-1]]
                for pnt in pts[k:]:
                    if np.linalg.norm(pnt - ext[-1]) > 0.3:
                        ext.append(pnt)
                if len(ext) > 1:
                    self._set_path(np.vstack([self.path, np.array(ext[1:])]))
                    changed = True
        if self._prune(pose_xy_yaw):
            changed = True
        return changed

    def _set_path(self, poly: np.ndarray) -> None:
        keep = np.concatenate([[True], np.linalg.norm(np.diff(poly, axis=0), axis=1) > 1e-6])
        poly = poly[keep]
        cl = _cumlen(poly)
        if cl[-1] > self.max_len_m:                      # cap total length from the front
            sel = cl >= cl[-1] - self.max_len_m
            poly, cl = poly[sel], cl[sel] - cl[sel][0]
        n = max(2, int(np.floor(cl[-1] / self.bin_m)) + 1)
        target = np.linspace(0.0, cl[-1], n)
        self.path = np.column_stack([np.interp(target, cl, poly[:, 0]), np.interp(target, cl, poly[:, 1])])
        self.s = target

    def _prune(self, pose_xy_yaw: tuple[float, float, float]) -> bool:
        """Drop path vertices more than keep_behind_m behind the ego's projection."""
        if self.path is None or len(self.path) < 3:
            return False
        _, arc_e, _ = _project(np.array([[pose_xy_yaw[0], pose_xy_yaw[1]]]), self.path)
        cut = float(arc_e[0]) - self.keep_behind_m
        if cut <= self.s[0] + self.bin_m:
            return False
        sel = self.s >= cut
        if sel.sum() < 3:
            return False
        self._set_path(self.path[sel])
        return True

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
