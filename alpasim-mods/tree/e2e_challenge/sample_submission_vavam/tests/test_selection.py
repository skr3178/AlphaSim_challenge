"""Offline tests for route-aware selection (ROUTE-SELECTION-PLAN.md §4).

No GPU, no simulator, no torch — pure numpy, runs in under a second. Every guard must
return index 0, because index 0 is exactly candidate #2's behaviour: a bad route must
degrade to the baseline, never to a guess.
"""

from __future__ import annotations

import numpy as np
import pytest

from vavam_challenge.selection import (
    SelectConfig,
    Selection,
    _discontinuity,
    reference_path,
    discontinuity_reference,
    rebase_to_current_frame,
    select,
)

CFG = SelectConfig()


def traj(dx: float, dy: float, n: int = 6) -> np.ndarray:
    """A straight candidate ending at (dx, dy), sampled at n points."""
    t = np.linspace(1.0 / n, 1.0, n)[:, None]
    return np.hstack([t * dx, t * dy])


def route_straight(start: float = 40.0, n: int = 10, step: float = 4.0) -> np.ndarray:
    x = start + step * np.arange(n)
    return np.column_stack([x, np.zeros(n)])


def route_turn(sign: float, start: float = 40.0, n: int = 10) -> np.ndarray:
    """A route that begins 40 m ahead **on-axis** and curves beyond that.

    Note this does NOT discriminate candidates — see
    `test_curve_beyond_the_horizon_correctly_does_nothing`.
    """
    a = np.linspace(0.0, 0.6, n)
    return np.column_stack([start + 30.0 * np.sin(a), sign * 30.0 * (1.0 - np.cos(a))])


def route_offset(sign: float, start: float = 40.0, n: int = 8) -> np.ndarray:
    """A route whose **start is laterally offset** — the real "turn ahead" case.

    This is where selection has signal: the Hermite bridge must curve to reach it, so
    candidates that turn the right way score better over the 3 s horizon.
    """
    x = start + 4.0 * np.arange(n)
    y = sign * (10.0 + 1.5 * np.arange(n))
    return np.column_stack([x, y])


# ------------------------------------------------------------------ the core claim


@pytest.mark.parametrize(
    "route, want_y_sign",
    [(route_straight(), 0.0), (route_offset(+1), +1.0), (route_offset(-1), -1.0)],
)
def test_picks_the_candidate_that_agrees_with_the_route(route, want_y_sign):
    """Straight / left / right: the route-aligned candidate must win."""
    candidates = np.stack([traj(25, 0), traj(25, +6), traj(25, -6)])
    out = select(candidates, route, cfg=CFG)
    chosen_y = candidates[out.index, -1, 1]
    if want_y_sign == 0.0:
        assert out.index == 0, f"straight route chose {out.index} (costs {out.costs})"
    else:
        assert np.sign(chosen_y) == want_y_sign, f"chose y={chosen_y} (costs {out.costs})"
    assert out.reason in {"selected", "tie_progress"}
    assert np.isfinite(out.costs).all()


def test_curve_beyond_the_horizon_correctly_does_nothing():
    """A route that starts on-axis and curves past 40 m must NOT steer us early.

    `route_start_offset_m: 40` means the route begins ~40 m ahead while the 3 s
    prediction reaches only ~25 m. If the curve lies beyond the route start, the
    Hermite reference is near-straight across the whole horizon (< 0.2 m lateral), so
    going straight is right and selection should be a no-op. This is the behaviour, not
    a bug — and it bounds how often selection can help: **only when the route start is
    itself laterally offset.** S1 reports the argmin != 0 fraction for exactly this.
    """
    ref = reference_path(route_turn(+1), CFG)
    lateral = np.interp([5, 10, 15, 20, 25], ref[:, 0], ref[:, 1])
    assert np.abs(lateral).max() < 0.5, f"reference should be ~straight here: {lateral}"
    out = select(np.stack([traj(25, 0), traj(25, +6), traj(25, -6)]), route_turn(+1), cfg=CFG)
    assert out.index == 0, "should keep going straight; the turn is past the horizon"


def test_equal_route_agreement_resolves_to_the_further_candidate():
    """Equal agreement with the route -> take the one that gets further along it.

    Since the CarPlanner port, progress is a *scored* term (w_progress 0.5), so the longer
    candidate usually wins outright rather than through the tie-break. Either route to the
    right answer is fine; the index is what matters.
    """
    short, long_ = traj(15, 0), traj(30, 0)
    out = select(np.stack([short, long_]), route_straight(), cfg=CFG)
    assert out.index == 1, f"expected the longer candidate, got {out.index} ({out.costs})"
    assert out.reason in {"selected", "tie_progress"}
    assert out.terms["progress"][1] > out.terms["progress"][0]


# ------------------------------------------------------- the CarPlanner-derived terms


MASK = SelectConfig(use_safety_mask=True)   # the mask is an A/B arm, default OFF


def test_safety_mask_is_off_by_default():
    """`drivable` already scores this softly; the hard gate must be opted into."""
    assert SelectConfig().use_safety_mask is False


def test_safety_mask_excludes_violators_and_ranks_the_rest():
    """With the mask ON, candidates beyond lane_max_dist are not ranked at all."""
    route = route_straight()
    good, ok, wild = traj(25, 0), traj(25, 1.5), traj(25, 20)
    out = select(np.stack([wild, good, ok]), route, cfg=MASK)
    assert out.index != 0, "the violator must never be chosen while safe candidates exist"
    assert out.n_safe == 2, f"expected 2 safe candidates, got {out.n_safe}"
    assert out.reason != "no_safe"


def test_all_unsafe_falls_back_to_index_zero():
    """No safe candidate -> baseline behaviour, not a pick among ones we called unsafe.

    CarPlanner emergency-stops here. Until B8's decelerating fallback exists there is nothing
    safe to fall back TO, so return index 0 and surface the condition in `reason`.
    """
    route = route_straight()
    out = select(np.stack([traj(25, 18), traj(25, -20)]), route, cfg=MASK)
    assert out.reason == "no_safe" and out.n_safe == 0
    assert out.index == 0, "must fall back to baseline, not rank unsafe candidates"


def test_consensus_prefers_the_typical_draw():
    """Sample consensus stands in for CarPlanner's learned mode score."""
    cluster = [traj(25, 0), traj(25, 0.2), traj(25, -0.2)]
    outlier = traj(25, 7)
    out = select(np.stack(cluster + [outlier]), route_straight(), cfg=CFG)
    con = out.terms["consensus"]
    assert con[3] < con[:3].min(), f"outlier should be least typical: {con}"
    assert np.isclose(con.sum(), 1.0), "consensus is a distribution"


def test_comfort_penalises_jerk():
    smooth = traj(25, 0)
    jerky = smooth.copy()
    jerky[1::2, 1] += 2.0                      # zig-zag
    out = select(np.stack([smooth, jerky]), route_straight(), cfg=CFG)
    assert out.terms["comfort"][0] > out.terms["comfort"][1]


def test_progress_is_normalised_not_raw_metres():
    """CarPlanner's recorded bug: unnormalised progress dominates every other term ~60x."""
    out = select(np.stack([traj(25, 0), traj(10, 0)]), route_straight(), cfg=CFG)
    assert np.all(np.abs(out.terms["progress"]) <= 1.5), out.terms["progress"]


def test_discontinuity_penalises_switching_away_from_the_last_plan():
    route, a, b = route_straight(), traj(25, 0), traj(25, 2)
    without = select(np.stack([a, b]), route, cfg=CFG)
    with_prev = select(np.stack([a, b]), route,
                       cfg=SelectConfig(w_disc=5.0), previous_xy=b)
    assert without.terms["disc"].sum() == 0.0, "no previous plan -> no penalty"
    assert with_prev.terms["disc"][1] < with_prev.terms["disc"][0], "b was the last pick"


def test_weights_are_carplanners():
    c = SelectConfig()
    assert (c.w_rule, c.w_mode) == (1.0, 0.3), "paper SS A rule:mode ratio"
    assert (c.w_comfort, c.w_progress, c.w_drivable) == (0.1, 0.5, 0.3)
    assert c.lane_max_dist_m == 3.0


# ----------------------------------------------------------------------- the guards


@pytest.mark.parametrize(
    "route, expect",
    [
        (None, "guard_short_route"),
        (np.empty((0, 2)), "guard_short_route"),
        (np.array([[50.0, 0.0]]), "guard_short_route"),                      # n < 2
        (np.array([[2.0, 0.0], [6.0, 0.0]]), "guard_route_implausible"),     # starts behind
        (np.array([[50.0, 40.0], [54.0, 40.0]]), "guard_route_implausible"),  # far off-axis
        (np.full((10, 2), np.nan), "guard_short_route"),                     # all padding
    ],
)
def test_unusable_route_falls_back_to_index_zero(route, expect):
    candidates = np.stack([traj(25, 0), traj(25, +6), traj(25, -6)])
    out = select(candidates, route, cfg=CFG)
    assert out.index == 0 and out.reason == expect
    assert not out.costs.any(), "a guard must not report costs it never computed"


def test_nan_padding_is_stripped_not_fatal():
    """The proto NaN-pads to 20; the real waypoints must still be used."""
    route = np.vstack([route_straight(n=8), np.full((12, 2), np.nan)])
    out = select(np.stack([traj(25, 0), traj(25, 8)]), route, cfg=CFG)
    assert out.reason == "selected" and out.index == 0


def test_single_candidate_is_a_noop():
    out = select(traj(25, 0)[None], route_straight(), cfg=CFG)
    assert out.index == 0 and out.reason == "guard_single_candidate"


def test_nonfinite_candidate_falls_back():
    bad = np.stack([traj(25, 0), traj(25, 5)])
    bad[1, 2, 1] = np.nan
    out = select(bad, route_straight(), cfg=CFG)
    assert out.index == 0 and out.reason == "guard_nonfinite_candidates"


# ------------------------------------------------------------------- the bridge


def test_hermite_bridge_leaves_along_the_current_heading():
    """A straight chord to a laterally-offset route start would cut the corner."""
    route = np.array([[40.0, 10.0], [44.0, 11.0]])
    herm = reference_path(route, SelectConfig(ref="hermite"))
    chord = reference_path(route, SelectConfig(ref="chord"))
    near = 5.0
    hy = np.interp(near, herm[:, 0], herm[:, 1])
    cy = np.interp(near, chord[:, 0], chord[:, 1])
    assert hy < cy, f"hermite should hug the current heading near the ego ({hy} vs {cy})"
    assert abs(herm[0, 0]) < 1e-6 and abs(herm[0, 1]) < 1e-6, "must start at the ego"


def test_reference_reaches_the_route_and_is_uniformly_sampled():
    route = route_turn(+1)
    ref = reference_path(route, CFG)
    assert np.linalg.norm(ref[-1] - route[-1]) < 1.5, "reference must end on the route"
    step = np.linalg.norm(np.diff(ref, axis=0), axis=1)
    assert step.max() < 1.05 * CFG.sample_step_m + 1e-6


# --------------------------------------------------------------------- the signals


def test_spread_reports_candidate_disagreement():
    """B2's slow-down keys on this, so it must be reported even when a guard fires."""
    agree = np.stack([traj(25, 0), traj(25, 0.1)])
    disagree = np.stack([traj(25, -8), traj(25, +8)])
    assert select(agree, route_straight(), cfg=CFG).spread_m < 0.5
    assert select(disagree, route_straight(), cfg=CFG).spread_m > 3.0
    # still reported when the route is unusable
    assert select(disagree, None, cfg=CFG).spread_m > 3.0


def test_heading_weight_changes_the_ranking():
    """w_h is an A/B knob (S1b); it must actually do something."""
    route = route_turn(+1)
    # one candidate ends nearer the route but pointing away, one further but aligned
    near_wrong = np.vstack([traj(20, 3)[:-1], [[20.0, -2.0]]])
    far_right = traj(24, 5)
    cands = np.stack([near_wrong, far_right])
    off = select(cands, route, cfg=SelectConfig(heading_w=0.0))
    on = select(cands, route, cfg=SelectConfig(heading_w=8.0))
    assert not np.allclose(off.costs, on.costs), "heading term had no effect"


def test_costs_are_per_candidate_and_ordered_sanely():
    route = route_straight()
    cands = np.stack([traj(25, 0), traj(25, 3), traj(25, 9)])
    out = select(cands, route, cfg=CFG)
    assert out.costs.shape == (3,)
    assert out.costs[0] < out.costs[1] < out.costs[2], f"monotonic in offset: {out.costs}"


def test_selection_is_deterministic():
    route, cands = route_turn(-1), np.stack([traj(25, 0), traj(25, -6), traj(25, +6)])
    first = select(cands, route, cfg=CFG)
    for _ in range(5):
        again = select(cands, route, cfg=CFG)
        assert again.index == first.index and np.allclose(again.costs, first.costs)


def test_returns_the_dataclass_contract():
    out = select(np.stack([traj(25, 0), traj(25, 4)]), route_straight(), cfg=CFG)
    assert isinstance(out, Selection)
    assert isinstance(out.index, int) and 0 <= out.index < 2
    assert out.reference is not None and out.reference.shape[1] == 2


# ------------------------------------------------- regression: predict_k tensor ranks


def test_expand_arg_is_built_from_ndim_not_hardcoded():
    """Regression for the k>1 crash that cost a whole 100-scene run.

    Visual tokens are 4-D — (1, 1, 18, 32) = (batch, context, Hgrid, Wgrid) — but the
    first version of `predict_k` wrote `expand(k, -1, -1)`, a 3-size arg. That raises on
    every call; the driver caught it, served the stale plan, and 32 scenes "completed"
    with a plausible aggregate produced by a policy that never ran. Build the arg from
    `dim()` so it is rank-agnostic.
    """
    import torch

    for shape in [(1, 1, 18, 32), (1, 1, 576), (1, 1, 24, 24), (1, 1, 4, 8, 8)]:
        t = torch.zeros(shape, dtype=torch.long)
        out = t.expand(5, *([-1] * (t.dim() - 1)))
        assert out.shape[0] == 5 and out.shape[1:] == t.shape[1:], shape


# --------------------------------------------- review items: heading in scores, arc progress


def test_heading_term_reaches_the_score_not_just_costs():
    """Regression: `heading_w` lived only in `costs` and never affected ranking."""
    route = route_offset(+1)
    cands = np.stack([traj(24, 5), np.vstack([traj(20, 3)[:-1], [[20.0, -2.0]]])])
    a = select(cands, route, cfg=SelectConfig(heading_w=0.0))
    b = select(cands, route, cfg=SelectConfig(heading_w=8.0))
    assert not np.allclose(a.terms["route"], b.terms["route"]), "heading must move the route term"
    assert not np.allclose(a.scores, b.scores), "and therefore the score"


def test_progress_is_arc_length_along_the_reference_not_forward_x():
    """On a turn, progress must reward following the route, not raw forward x.

    The honest test is a candidate sampled FROM the reference (perfect follower) against one
    that drives straight past it. With x_end the straight one wins on a left turn; with arc
    length along the reference the follower does.
    """
    route = route_offset(+1)
    ref = reference_path(route, CFG)
    # perfect follower: 6 points along the reference out to ~25 m of arc
    seg = np.linalg.norm(np.diff(ref, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    take = [int(np.argmin(np.abs(arc - a))) for a in np.linspace(4, 25, 6)]
    follower = ref[take]
    straight = traj(25, 0)
    out = select(np.stack([straight, follower]), route, cfg=CFG)
    assert out.terms["progress"][1] >= out.terms["progress"][0] - 1e-9, (
        f"follower must not score less progress: {out.terms['progress']}"
    )
    assert out.terms["route"][1] > out.terms["route"][0], (
        f"follower must score better on route agreement: {out.terms['route']}"
    )
    assert out.index == 1, f"the follower should win outright, got {out.index}"


# --------------------------------------------------------------- frame rebasing
# Regression: `_discontinuity` compared a stored plan (previous tick's ego frame) against
# fresh candidates (current ego frame) with no transform. The driver re-plans every 500 ms
# of sim time, so the two frames differ by 2.5-7.5 m of travel plus any rotation. The term
# therefore measured ego motion, and biased selection toward short/slow candidates. Found
# 2026-09-01 before the w_disc sweep, so no run was ever scored with w_disc > 0.


def _straight(n=8, dx=1.0):
    return np.stack([np.arange(n) * dx, np.zeros(n)], axis=1)


def test_rebase_is_identity_when_the_ego_has_not_moved():
    xy = _straight()
    out = rebase_to_current_frame(xy, (10.0, -3.0, 0.7), (10.0, -3.0, 0.7))
    assert np.allclose(out, xy, atol=1e-9)


def test_rebase_puts_the_old_plan_behind_the_ego_after_driving_forward():
    # Ego drove 5 m along +x (global) with no rotation; the old plan must shift 5 m back.
    xy = _straight()
    out = rebase_to_current_frame(xy, (0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
    assert np.allclose(out, xy - np.array([5.0, 0.0]), atol=1e-9)
    assert out[0, 0] < 0.0  # the sign the driver's base_x check watches for


def test_rebase_handles_rotation():
    # Ego turned +90 deg in place: a plan pointing +x becomes a plan pointing -y.
    xy = _straight(n=3)
    out = rebase_to_current_frame(xy, (0.0, 0.0, 0.0), (0.0, 0.0, np.pi / 2))
    assert np.allclose(out, [[0.0, 0.0], [0.0, -1.0], [0.0, -2.0]], atol=1e-9)


def test_rebase_round_trips():
    rng = np.random.default_rng(0)
    xy = rng.normal(size=(12, 2)) * 5.0
    a, b = (3.0, -1.0, 0.4), (9.0, 2.5, -1.1)
    assert np.allclose(rebase_to_current_frame(rebase_to_current_frame(xy, a, b), b, a), xy, atol=1e-9)


def test_rebase_preserves_shape_so_only_pose_differences_show_up():
    # A rigid transform cannot change intra-plan distances; discontinuity must reflect plan
    # change only. This is the property the untransformed comparison violated.
    rng = np.random.default_rng(1)
    xy = rng.normal(size=(10, 2)) * 4.0
    out = rebase_to_current_frame(xy, (1.0, 2.0, 0.3), (7.0, -4.0, 1.9))
    d_in = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    d_out = np.linalg.norm(np.diff(out, axis=0), axis=1)
    assert np.allclose(d_in, d_out, atol=1e-9)


def test_discontinuity_after_rebasing_does_not_favour_the_slower_candidate():
    # Two candidates: one continues the previous plan, one brakes hard. Driving forward 5 m
    # and rebasing must rank the continuing one as MORE continuous. Without the rebase the
    # stale plan sits 5 m behind, and the braking candidate wins.
    # 2 m per plan step; one step elapses between replans, so the ego advanced 2 m.
    prev = _straight(n=10, dx=2.0)
    keep = _straight(n=10, dx=2.0)                       # same trajectory, re-issued
    brake = _straight(n=10, dx=0.4)                      # brakes hard
    cands = np.stack([keep, brake])
    ref = discontinuity_reference(prev, (0.0, 0.0, 0.0), (2.0, 0.0, 0.0), shift=1)
    good = _discontinuity(cands, ref, 1.0)
    assert good[0] == pytest.approx(0.0, abs=1e-9), "re-issuing the same plan is zero change"
    assert good[0] < good[1], "the continuing candidate must be the continuous one"


def test_naive_discontinuity_picked_the_wrong_candidate_on_a_turn():
    """The defect had teeth on turns, where the frame error is a rotation.

    Ego is mid-turn: it advanced 2 m and rotated +30 deg since the plan was made. Candidate A
    is that plan continued - the same world path, which in the new ego frame runs off at
    -30 deg. Candidate B goes straight ahead in the new frame, i.e. it abandons the planned
    path and commits to the new heading. The corrected reference scores A as perfectly
    continuous. The old comparison, which held the stored plan in a stale frame, scored B as
    perfectly continuous instead - so w_disc > 0 would have pushed the planner to keep
    turning rather than to hold its line.
    """
    prev = _straight(n=10, dx=2.0)                       # world: (0,0) .. (18,0)
    cur = (2.0, 0.0, np.pi / 6)
    cont = discontinuity_reference(prev, (0.0, 0.0, 0.0), cur, shift=1)
    a = np.concatenate([cont, cont[-1:] + (cont[-1] - cont[-2])])   # A: pad back to 10
    b = _straight(n=10, dx=2.0)                                     # B: straight in new frame
    cands = np.stack([a, b])
    good = _discontinuity(cands, cont, 1.0)
    assert good[0] < good[1], "corrected: continuing the planned path is the continuous one"
    naive = _discontinuity(cands, prev, 1.0)
    assert naive[1] < naive[0], "old behaviour: abandoning the path looked continuous"


def test_discontinuity_reference_declines_when_the_shift_eats_the_plan():
    assert discontinuity_reference(_straight(n=3), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 3) is None
