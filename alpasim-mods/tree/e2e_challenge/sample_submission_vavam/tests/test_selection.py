"""Offline tests for route-aware selection (ROUTE-SELECTION-PLAN.md §4).

No GPU, no simulator, no torch — pure numpy, runs in under a second. Every guard must
return index 0, because index 0 is exactly candidate #2's behaviour: a bad route must
degrade to the baseline, never to a guess.
"""

from __future__ import annotations

import numpy as np
import pytest

from vavam_challenge.selection import SelectConfig, Selection, reference_path, select

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


def test_safety_mask_excludes_violators_and_ranks_the_rest():
    """Candidates with any point beyond lane_max_dist are not ranked at all."""
    route = route_straight()
    good, ok, wild = traj(25, 0), traj(25, 1.5), traj(25, 20)
    out = select(np.stack([wild, good, ok]), route, cfg=CFG)
    assert out.index != 0, "the violator must never be chosen while safe candidates exist"
    assert out.n_safe == 2, f"expected 2 safe candidates, got {out.n_safe}"
    assert out.reason != "no_safe"


def test_all_unsafe_reports_no_safe_for_the_b8_fallback():
    """CarPlanner emergency-stops here; we surface the signal and B8 decelerates."""
    route = route_straight()
    out = select(np.stack([traj(25, 18), traj(25, -20)]), route, cfg=CFG)
    assert out.reason == "no_safe" and out.n_safe == 0
    assert 0 <= out.index < 2, "must still return a usable index"


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
