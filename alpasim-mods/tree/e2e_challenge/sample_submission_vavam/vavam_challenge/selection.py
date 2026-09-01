"""Route-aware selection among k sampled trajectories.

Design: `ROUTE-SELECTION-PLAN.md` §2. This is the "generator + scorer" pattern —
a frozen policy proposes k candidates, a rule-based scorer picks one. No retraining.
(Hydra-MDP / GTRS / TOAD use a learned scorer; ours is distance-to-route + progress.)

Pure numpy, no torch, no I/O — unit-testable without a GPU or a simulator.

Frames: everything is rig-frame at the same timestamp, x forward / y left. The driver
sends the route and drains before `drive()`, so route and candidates share a frame and
no transform is needed.

The one non-obvious thing: the challenge config sets `route_start_offset_m: 40.0`, so
the route the driver receives begins ~40 m ahead and the 3 s prediction (~15-35 m)
never reaches it. Scoring candidates directly against the route would compare them to
a path none of them touch. `_reference_path` bridges ego -> route start with a cubic
Hermite that honours both the current heading and the route's entry heading; a straight
chord would cut the corner (sagitta ~4 m for a 40 m chord at 50 m radius — the width of
the corridor we are trying not to leave).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = ["SelectConfig", "Selection", "select", "reference_path"]


@dataclass(frozen=True)
class SelectConfig:
    """Knobs, all surfaced as env vars by the driver. Defaults reproduce the plan."""

    tie_eps_m: float = 0.25
    """Candidates within this of the best cost are considered tied, then ranked by progress."""
    heading_w: float = 2.0
    """Weight on terminal heading error, metres per radian."""
    ref: str = "hermite"
    """`hermite` (default) or `chord` — the straight-line variant, kept for the A/B."""
    sample_step_m: float = 1.0
    """Arc-length spacing of the sampled reference path."""
    min_route_x_m: float = 5.0
    """Route start closer than this (or behind) is implausible -> fall back to index 0."""
    max_route_y_m: float = 12.0
    """Route start further off-axis than this is implausible -> fall back to index 0."""


@dataclass(frozen=True)
class Selection:
    index: int
    """Chosen candidate. Always 0 when a guard fires, so behaviour matches the baseline."""
    costs: np.ndarray
    """(k,) cost per candidate. All-zero when a guard fired."""
    spread_m: float
    """RMS distance of the k end points from their mean — the disagreement signal B2 keys on."""
    reason: str
    """Why this index: `selected`, `tie_progress`, or a guard name. For logging."""
    reference: np.ndarray | None = field(default=None, repr=False)
    """(m,2) sampled reference path, or None when a guard fired. For visualisation."""


# --------------------------------------------------------------------------- helpers


def _finite_route(route_xy: np.ndarray | None) -> np.ndarray:
    """Drop the NaN padding. The proto delivers up to 20 waypoints, ~10 of them real."""
    if route_xy is None:
        return np.empty((0, 2), dtype=float)
    r = np.asarray(route_xy, dtype=float).reshape(-1, 2)
    return r[np.isfinite(r).all(axis=1)]


def _resample(poly: np.ndarray, step: float) -> np.ndarray:
    """Resample a polyline to uniform arc-length spacing."""
    if len(poly) < 2:
        return poly
    seg = np.linalg.norm(np.diff(poly, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(s[-1])
    if total <= step:
        return poly
    n = max(2, int(np.ceil(total / step)) + 1)
    target = np.linspace(0.0, total, n)
    return np.column_stack([np.interp(target, s, poly[:, 0]), np.interp(target, s, poly[:, 1])])


def reference_path(route: np.ndarray, cfg: SelectConfig = SelectConfig()) -> np.ndarray:
    """Ego (0,0) heading +x, bridged to the route start, then along the route.

    `hermite` honours both endpoint headings; `chord` is the straight-line variant.
    """
    r0 = route[0]
    length = float(np.linalg.norm(r0))
    if cfg.ref == "chord" or length < 1e-6:
        bridge = np.array([[0.0, 0.0], r0])
    else:
        # entry tangent = direction of the route's own first segment
        t1 = route[1] - route[0]
        n1 = float(np.linalg.norm(t1))
        t1 = (t1 / n1) if n1 > 1e-9 else np.array([1.0, 0.0])
        p0, p1 = np.zeros(2), r0
        m0, m1 = np.array([1.0, 0.0]) * length, t1 * length
        t = np.linspace(0.0, 1.0, 32)[:, None]
        t2, t3 = t * t, t * t * t
        bridge = (
            (2 * t3 - 3 * t2 + 1) * p0
            + (t3 - 2 * t2 + t) * m0
            + (-2 * t3 + 3 * t2) * p1
            + (t3 - t2) * m1
        )
    full = np.vstack([bridge, route[1:]]) if len(route) > 1 else bridge
    # drop consecutive duplicates, which would produce zero-length segments
    keep = np.concatenate([[True], np.linalg.norm(np.diff(full, axis=0), axis=1) > 1e-9])
    return _resample(full[keep], cfg.sample_step_m)


def _project(points: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Perpendicular distance from each point to the polyline, and arc-length at the foot.

    Vectorised over (points x segments). Returns (dist (p,), arclen (p,)).
    """
    a, b = ref[:-1], ref[1:]              # (s,2) segment ends
    ab = b - a                            # (s,2)
    denom = np.einsum("ij,ij->i", ab, ab)  # (s,)
    denom = np.where(denom > 1e-12, denom, 1.0)
    ap = points[:, None, :] - a[None, :, :]                      # (p,s,2)
    t = np.clip(np.einsum("psi,si->ps", ap, ab) / denom, 0.0, 1.0)  # (p,s)
    foot = a[None, :, :] + t[:, :, None] * ab[None, :, :]        # (p,s,2)
    d = np.linalg.norm(points[:, None, :] - foot, axis=2)        # (p,s)
    best = np.argmin(d, axis=1)                                  # (p,)
    seg_len = np.linalg.norm(ab, axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])            # (s+1,)
    rows = np.arange(len(points))
    return d[rows, best], cum[best] + t[rows, best] * seg_len[best]


def _tangent_at(ref: np.ndarray, arclen: float) -> np.ndarray:
    seg_len = np.linalg.norm(np.diff(ref, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    i = int(np.clip(np.searchsorted(cum, arclen) - 1, 0, len(ref) - 2))
    v = ref[i + 1] - ref[i]
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.array([1.0, 0.0])


def _spread(candidates: np.ndarray) -> float:
    """RMS distance of the k end points from their mean."""
    if len(candidates) < 2:
        return 0.0
    ends = candidates[:, -1, :]
    return float(np.sqrt(np.mean(np.sum((ends - ends.mean(axis=0)) ** 2, axis=1))))


# ----------------------------------------------------------------------------- main


def select(
    candidates: np.ndarray,
    route_xy: np.ndarray | None,
    speed_mps: float | None = None,
    cfg: SelectConfig = SelectConfig(),
) -> Selection:
    """Pick the candidate that best agrees with the map route.

    Args:
        candidates: (k,p,2) rig-frame trajectories, p points each (6 at 0.5..3.0 s).
        route_xy: (n,2) route waypoints, possibly NaN-padded. May be None.
        speed_mps: current speed. Unused today; kept so callers need not change when
            a speed-aware term is added.
        cfg: knobs.

    Returns:
        A `Selection`. **Index 0 whenever anything is off** — an unusable route must
        reproduce baseline behaviour exactly, never guess.
    """
    c = np.asarray(candidates, dtype=float)
    if c.ndim == 2:  # a single (p,2) trajectory
        c = c[None, ...]
    k = len(c)
    zero = np.zeros(k, dtype=float)

    if k < 2:
        return Selection(0, zero, 0.0, "guard_single_candidate")
    if not np.isfinite(c).all():
        return Selection(0, zero, _spread(c), "guard_nonfinite_candidates")

    spread = _spread(c)
    route = _finite_route(route_xy)
    if len(route) < 2:
        return Selection(0, zero, spread, "guard_short_route")
    r0 = route[0]
    if r0[0] < cfg.min_route_x_m or abs(r0[1]) > cfg.max_route_y_m:
        return Selection(0, zero, spread, "guard_route_implausible")

    ref = reference_path(route, cfg)
    if len(ref) < 2:
        return Selection(0, zero, spread, "guard_short_reference")

    costs = np.empty(k, dtype=float)
    end_arclen = np.empty(k, dtype=float)
    for i in range(k):
        d, s = _project(c[i], ref)
        lateral = float(np.mean(d))
        tangent = _tangent_at(ref, float(s[-1]))
        last = c[i, -1] - c[i, -2]
        n = float(np.linalg.norm(last))
        if n > 1e-9:
            last = last / n
            # signed angle between the candidate's final heading and the reference tangent
            dh = abs(np.arctan2(
                last[0] * tangent[1] - last[1] * tangent[0],
                float(np.dot(last, tangent)),
            ))
        else:
            dh = 0.0
        costs[i] = lateral + cfg.heading_w * dh
        end_arclen[i] = s[-1]

    best = float(costs.min())
    tied = np.flatnonzero(costs <= best + cfg.tie_eps_m)
    # follow the route first, then go further: among ties, the one that gets furthest along it
    idx = int(tied[np.argmax(end_arclen[tied])])
    reason = "selected" if len(tied) == 1 else "tie_progress"
    return Selection(idx, costs, spread, reason, ref)
