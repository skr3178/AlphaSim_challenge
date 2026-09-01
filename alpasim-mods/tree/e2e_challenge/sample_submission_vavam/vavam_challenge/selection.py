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
    """Knobs, all surfaced as env vars by the driver.

    Weights are CarPlanner's (CVPR 2025, `RuleAugmentedSelector`, paper SS A: rule:mode = 1:0.3),
    ported in ROUTE-SELECTION-PLAN.md SS 2b. They were tuned for a *learned* mode score;
    ours substitutes sample consensus, so `w_mode` is inherited-but-unvalidated - sweep it.

    Every term is normalised to roughly [-1, 1] before weighting. CarPlanner records the
    bug that motivates this: without normalising progress, it "dominates mode_scores by ~60x".
    """

    # --- combination (CarPlanner SS A) ---
    w_rule: float = 1.0
    w_mode: float = 0.3
    """Weight on consensus. Inherited from a learned mode score - validate at S0/S1."""
    w_disc: float = 0.0
    """Discontinuity penalty. No CarPlanner analogue (they fix the mode across the rollout);
    start at 0 and set it from the measured tick-to-tick switching rate."""

    # --- rule terms (CarPlanner weights) ---
    w_comfort: float = 0.1
    w_progress: float = 0.5
    w_drivable: float = 0.3
    w_route: float = 1.0
    """Fine-grained route alignment. Ours - CarPlanner has no analogue because their
    candidates already follow enumerated lane routes."""

    # --- scales, so the weights above mean something ---
    lane_max_dist_m: float = 3.0
    """Beyond this from the reference a point counts as a violation (CarPlanner: 3.0)."""
    max_progress_m: float = 30.0
    """Normaliser for progress: ~max reachable in the 3 s horizon."""
    jerk_scale_m: float = 1.0
    consensus_scale_m: float = 2.0

    # --- behaviour ---
    use_safety_mask: bool = False
    """A/B arm, default OFF. `drivable` already scores the same signal softly, and the mask
    gates on distance to an *assumed* bridged reference — a hard gate on an inferred quantity
    is a strong claim. Turn on to test it against the soft term (S1b)."""
    min_progress_frac: float = 0.0
    """Reject candidates below this fraction of the best candidate's progress."""
    tie_eps_m: float = 0.25
    heading_w: float = 2.0
    ref: str = "hermite"
    sample_step_m: float = 1.0
    min_route_x_m: float = 5.0
    max_route_y_m: float = 30.0
    """route[0] sits ~`route_start_offset_m` (40 m) ALONG the path, not 40 m straight ahead, so
    on a curve it is far off-axis: a 40 deg turn puts it at 13.4 m, 60 deg at 19.1 m, 90 deg at
    25.5 m. The old 12 m bound fired on 27 % of S0 ticks - disabling selection precisely on the
    turns it exists for. 30 m admits a 90 deg turn and still rejects a genuinely broken route."""


@dataclass(frozen=True)
class Selection:
    index: int
    """Chosen candidate. Always 0 when a guard fires, so behaviour matches the baseline."""
    costs: np.ndarray
    """(k,) route cost per candidate, lower is better. All-zero when a guard fired."""
    spread_m: float
    """RMS distance of the k end points from their mean - the disagreement signal B2 keys on."""
    reason: str
    """`selected`, `tie_progress`, `no_safe`, or a guard name. For logging."""
    reference: np.ndarray | None = field(default=None, repr=False)
    """(m,2) sampled reference path, or None when a guard fired."""
    scores: np.ndarray | None = field(default=None, repr=False)
    """(k,) combined score, higher is better. This is what selection ranks on."""
    terms: dict[str, np.ndarray] | None = field(default=None, repr=False)
    """Per-candidate breakdown: comfort, progress, drivable, route, consensus, disc."""
    n_safe: int = -1
    """Candidates passing the safety mask. -1 when a guard fired or the mask is off."""


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


def _comfort(c: np.ndarray, scale: float) -> np.ndarray:
    """-mean |jerk|, normalised. CarPlanner `model.py`: 3rd finite difference on xy."""
    if c.shape[1] < 4:                       # need >= 4 points for a jerk estimate
        return np.zeros(len(c))
    vel = np.diff(c, axis=1)
    acc = np.diff(vel, axis=1)
    jerk = np.diff(acc, axis=1)
    return -np.linalg.norm(jerk, axis=2).mean(axis=1) / max(scale, 1e-6)


def _progress(c: np.ndarray, max_m: float) -> np.ndarray:
    """Final forward displacement, normalised. Unnormalised it swamps every other term."""
    return c[:, -1, 0] / max(max_m, 1e-6)


def _consensus(c: np.ndarray, scale: float) -> np.ndarray:
    """Softmax over -distance-from-medoid: how typical each draw is.

    Stands in for CarPlanner's *learned* mode score. VaVAM's sampler is already a learned
    prior, so the density of k draws is its confidence - no training needed. Uses the
    coordinate-wise median (robust) rather than the mean as the consensus point.
    """
    ends = c[:, -1, :]
    d = np.linalg.norm(ends - np.median(ends, axis=0), axis=1) / max(scale, 1e-6)
    e = np.exp(-(d - d.min()))
    return e / e.sum()


def rebase_to_current_frame(
    prev_xy: np.ndarray,
    prev_pose: tuple[float, float, float],
    cur_pose: tuple[float, float, float],
) -> np.ndarray:
    """Re-express a plan from a past ego frame in the current ego frame.

    Both frames are ego-local: origin at the ego, +x along its heading. `prev_pose` and
    `cur_pose` are the two ego poses in the global frame as (x, y, yaw).

    This exists because the driver re-plans every `VAVAM_INFERENCE_INTERVAL_US` (500 ms of
    sim time), during which the ego travels 2.5-7.5 m and, on a turn, rotates. Comparing a
    stored plan against fresh candidates without this transform does not measure "how much
    did the plan change" - it mostly measures how far the ego drove, and it does so with a
    direction bias: the stale plan sits behind the new origin, so short/slow candidates look
    artificially continuous. See `_discontinuity`.
    """
    px, py, pyaw = prev_pose
    cx, cy, cyaw = cur_pose
    d = pyaw - cyaw
    cos_d, sin_d = np.cos(d), np.sin(d)
    rot = np.array([[cos_d, -sin_d], [sin_d, cos_d]])
    cos_c, sin_c = np.cos(cyaw), np.sin(cyaw)
    inv_cur = np.array([[cos_c, sin_c], [-sin_c, cos_c]])
    offset = inv_cur @ np.array([px - cx, py - cy])
    return prev_xy @ rot.T + offset[None]


def _discontinuity(c: np.ndarray, previous: np.ndarray | None, scale: float) -> np.ndarray:
    """Mean point distance from the previously chosen plan, normalised.

    `previous` must be a discontinuity REFERENCE built by `discontinuity_reference`, not the
    raw stored plan: rebased into the current ego frame and advanced by the number of plan
    steps that elapsed. It is therefore shorter than a candidate, so the comparison runs over
    the overlapping prefix.
    """
    if previous is None or previous.ndim != 2 or previous.shape[1] != c.shape[2]:
        return np.zeros(len(c))
    m = min(c.shape[1], previous.shape[0])
    if m == 0:
        return np.zeros(len(c))
    return np.linalg.norm(c[:, :m] - previous[None, :m], axis=2).mean(axis=1) / max(scale, 1e-6)


def discontinuity_reference(
    prev_xy: np.ndarray,
    prev_pose: tuple[float, float, float],
    cur_pose: tuple[float, float, float],
    shift: int,
) -> np.ndarray | None:
    """The previous plan, made directly comparable to a fresh candidate.

    Two corrections, both needed. `rebase_to_current_frame` removes the ego's translation and
    rotation since the plan was made. `shift` then removes the receding horizon: the planner
    emits points at a fixed rate, so after `shift` plan steps have elapsed, index i of a new
    candidate describes the same instant as index i + shift of the old plan.

    Without the shift the term still prefers slow candidates even in the right frame, because
    a plan that keeps driving is displaced by one step from the stored one while a plan that
    brakes stays near it. With both corrections, re-issuing the same trajectory scores exactly
    zero discontinuity, which is the property the term is supposed to have.
    """
    if prev_xy is None or shift < 0 or shift >= len(prev_xy):
        return None
    out = rebase_to_current_frame(prev_xy, prev_pose, cur_pose)
    return out[shift:] if shift else out


# ----------------------------------------------------------------------------- main


def select(
    candidates: np.ndarray,
    route_xy: np.ndarray | None,
    speed_mps: float | None = None,
    cfg: SelectConfig = SelectConfig(),
    previous_xy: np.ndarray | None = None,
) -> Selection:
    """Pick the candidate that best follows the route, among those the model believes in.

    Ports CarPlanner's `RuleAugmentedSelector` (ROUTE-SELECTION-PLAN.md SS 2b):

        rule  = w_comfort*comfort + w_progress*progress + w_drivable*drivable + w_route*route
        score = w_rule*rule + w_mode*consensus - w_disc*discontinuity
        safe  = zero violations                      <- HARD gate, ranked among survivors only

    Their `collision` term has no equivalent: no actor data reaches the driver. Their learned
    `mode_scores` is replaced by sample consensus, which needs no training.

    Args:
        candidates: (k,p,2) rig-frame trajectories, p points each (6 at 0.5..3.0 s).
        route_xy: (n,2) route waypoints, possibly NaN-padded. May be None.
        speed_mps: current speed. Unused today; kept so callers need not change.
        cfg: knobs.
        previous_xy: (p,2) previously selected trajectory, for the discontinuity term.
            MUST already be expressed in the CURRENT ego frame - pass it through
            `rebase_to_current_frame` first. Passing the raw stored plan silently
            biases selection toward slower candidates.

    Returns:
        A `Selection`. **Index 0 whenever anything is off** - an unusable route must
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

    # --- route cost (unchanged, still reported as `costs`) and violation rate --------
    costs = np.empty(k, dtype=float)
    end_arclen = np.empty(k, dtype=float)
    violation = np.empty(k, dtype=float)
    mean_lat = np.empty(k, dtype=float)
    for i in range(k):
        d, arc = _project(c[i], ref)
        mean_lat[i] = float(np.mean(d))
        violation[i] = float(np.mean(d > cfg.lane_max_dist_m))
        tangent = _tangent_at(ref, float(arc[-1]))
        last = c[i, -1] - c[i, -2]
        n = float(np.linalg.norm(last))
        if n > 1e-9:
            last = last / n
            dh = abs(np.arctan2(
                last[0] * tangent[1] - last[1] * tangent[0],
                float(np.dot(last, tangent)),
            ))
        else:
            dh = 0.0
        costs[i] = mean_lat[i] + cfg.heading_w * dh
        end_arclen[i] = arc[-1]

    # --- CarPlanner terms, each normalised to roughly [-1, 1] -----------------------
    terms = {
        "comfort": _comfort(c, cfg.jerk_scale_m),
        # Arc length along the reference, not x_end: on a turn a candidate that correctly
        # follows the route has small x but large progress. end_arclen is already computed.
        "progress": np.clip(end_arclen / max(cfg.max_progress_m, 1e-6), 0.0, 1.5),
        "drivable": -violation,
        # `costs` (mean lateral + heading) is the quantity that ranks, normalised. Before this
        # the heading term lived only in `costs` and never reached `scores`, so w_heading was
        # silently inert - the tests only checked `costs`.
        "route": -np.clip(costs / max(cfg.lane_max_dist_m, 1e-6), 0.0, 2.0),
        "consensus": _consensus(c, cfg.consensus_scale_m),
        "disc": _discontinuity(c, previous_xy, cfg.consensus_scale_m),
    }
    rule = (cfg.w_comfort * terms["comfort"]
            + cfg.w_progress * terms["progress"]
            + cfg.w_drivable * terms["drivable"]
            + cfg.w_route * terms["route"])
    scores = cfg.w_rule * rule + cfg.w_mode * terms["consensus"] - cfg.w_disc * terms["disc"]

    # --- hard safety mask: rank only among candidates with zero violations ----------
    eligible = np.ones(k, dtype=bool)
    if cfg.use_safety_mask:
        eligible = violation == 0.0
    if cfg.min_progress_frac > 0.0:
        best_prog = terms["progress"].max()
        eligible &= terms["progress"] >= cfg.min_progress_frac * best_prog
    n_safe = int(eligible.sum())

    reason = "selected"
    if not eligible.any():
        # CarPlanner emergency-stops here. Until B8's decelerating fallback exists there is
        # nothing safe to fall back TO, so return index 0 (baseline behaviour) and surface the
        # signal in `reason` rather than ranking among candidates we have just called unsafe.
        return Selection(0, costs, spread, "no_safe", ref, scores, terms, 0)

    masked = np.where(eligible, scores, -np.inf)
    best = float(masked.max())
    tied = np.flatnonzero(masked >= best - cfg.tie_eps_m * cfg.w_route / max(cfg.lane_max_dist_m, 1e-6))
    idx = int(tied[np.argmax(end_arclen[tied])])
    if reason == "selected" and len(tied) > 1:
        reason = "tie_progress"
    return Selection(idx, costs, spread, reason, ref, scores, terms, n_safe)
