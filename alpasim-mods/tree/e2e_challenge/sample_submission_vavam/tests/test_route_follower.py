"""Route accumulation + follower: pure numpy, no GPU. Scenarios mirror the sim's data flow:
the route arrives as a 40-80 m window in the rig frame at each tick; the ego moves along
the same lane-centre path; we must reconstruct the path and emit a plan that stays on it."""
from __future__ import annotations

import numpy as np
import pytest

from vavam_challenge.follower import FollowConfig, build_follow_plan, speed_profile_from_trajectory
from vavam_challenge.route_map import RouteMap, hermite_join, rig_to_local


def lane(kind: str, n: int = 400, ds: float = 1.0) -> np.ndarray:
    s = np.arange(n) * ds
    if kind == "straight":
        return np.column_stack([s, np.zeros_like(s)])
    if kind == "left90":  # 60 m straight, then a 40 m radius quarter circle, then straight
        pts = [np.column_stack([s[s < 60], np.zeros((s < 60).sum())])]
        th = np.linspace(0, np.pi / 2, 63)[1:]
        pts.append(np.column_stack([60 + 40 * np.sin(th), 40 - 40 * np.cos(th)]))
        tail = np.arange(1, 200) * ds
        pts.append(np.column_stack([100 + 0 * tail, 40 + tail]))
        return np.vstack(pts)
    raise ValueError(kind)


def cumlen(p):
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])


def pose_on_lane(L: np.ndarray, s: float, lateral: float = 0.0):
    cl = cumlen(L)
    x, y = np.interp(s, cl, L[:, 0]), np.interp(s, cl, L[:, 1])
    i = int(np.clip(np.searchsorted(cl, s) - 1, 0, len(L) - 2))
    t = L[i + 1] - L[i]
    yaw = float(np.arctan2(t[1], t[0]))
    n = np.array([-np.sin(yaw), np.cos(yaw)])
    return (float(x + lateral * n[0]), float(y + lateral * n[1]), yaw)


def route_window_local(L: np.ndarray, pose, start_m=40.0, length_m=80.0, spacing=80 / 19, noise=0.0, rng=None):
    """Lane points from start_m to length_m ahead of the ego's projection, in the local frame."""
    cl = cumlen(L)
    x, y, yaw = pose
    d = np.linalg.norm(L - np.array([x, y]), axis=1)
    s_e = cl[int(np.argmin(d))]
    arcs = s_e + np.arange(start_m, length_m + 1e-9, spacing)
    arcs = arcs[arcs <= cl[-1]]
    pts = np.column_stack([np.interp(arcs, cl, L[:, 0]), np.interp(arcs, cl, L[:, 1])])
    if noise and rng is not None:
        pts = pts + rng.normal(0, noise, pts.shape)
    return pts


def route_window(L: np.ndarray, pose, **kw):
    """What the sim sends: the same points expressed in the rig frame at `pose`."""
    pts = route_window_local(L, pose, **kw)
    x, y, yaw = pose
    c, s_ = np.cos(yaw), np.sin(yaw)
    rot = np.array([[c, -s_], [s_, c]])
    return (pts - np.array([x, y])) @ rot  # local -> rig (inverse rotation)


def test_rig_to_local_matches_inverse_of_route_window():
    L = lane("left90")
    pose = pose_on_lane(L, 70.0)
    win = route_window(L, pose)
    back = rig_to_local(win, pose)
    assert np.allclose(back, route_window_local(L, pose), atol=1e-6)
    assert 38.0 < np.linalg.norm(win[0]) < 42.0 and win[0, 0] > 0, "first waypoint ~40 m ahead in the rig frame"


@pytest.mark.parametrize("kind", ["straight", "left90"])
def test_accumulated_path_matches_lane_after_driving(kind):
    L = lane(kind)
    rm = RouteMap()
    rng = np.random.default_rng(0)
    v, dt = 10.0, 0.1
    s = 0.0
    for _ in range(80):  # 8 s at 10 Hz
        pose = pose_on_lane(L, s)
        rm.update(route_window(L, pose, noise=0.05, rng=rng), pose)
        s += v * dt
    assert rm.ready()
    q = rm.query(pose_on_lane(L, s))
    assert q is not None and q.on_path, "after 8 s the path must reach behind the ego"
    assert abs(q.e_y) < 0.25 and q.dist < 0.25
    # every accumulated point lies on the lane (perpendicular distance to the lane polyline)
    from vavam_challenge.route_map import _project
    d, _, _ = _project(rm.path, L)
    assert np.percentile(d, 95) < 0.15, f"p95 path error {np.percentile(d, 95):.2f} m"


def test_cold_start_accepts_a_turn_ahead():
    """F0 regression: the route start of a left turn sits ~35 m ahead and ~20 m left; must be followed."""
    L = lane("left90")
    rm = RouteMap()
    pose = pose_on_lane(L, 30.0)          # 30 m before the turn; route start = 70 m along = into the arc
    rm.update(route_window(L, pose), pose)
    r = build_follow_plan(rm, pose, 10.0, 0)
    assert r is not None, "turn ahead must not be rejected as off-lane"
    assert r.plan.positions_xy[-1, 1] > 2.0, "the plan bends left toward the route"


def test_cold_start_bridges_to_the_route_start():
    L = lane("straight")
    rm = RouteMap()
    pose = pose_on_lane(L, 0.0)
    rm.update(route_window(L, pose), pose)  # one window only: path starts 40 m ahead
    r = build_follow_plan(rm, pose, 10.0, 0)
    assert r is not None
    xy = r.plan.positions_xy
    assert np.allclose(xy[0], [0.0, 0.0], atol=1e-6)
    assert np.all(np.abs(xy[:, 1]) < 0.05), "straight lane: bridge must stay on the centre-line"
    assert xy[-1, 0] > 40.0, "5 s at 10 m/s reaches past the old 40 m gap"


def test_offset_ego_rejoins_the_path_smoothly():
    L = lane("straight")
    rm = RouteMap()
    for s in np.arange(0, 60, 1.0):
        p = pose_on_lane(L, s)
        rm.update(route_window(L, p), p)
    pose = pose_on_lane(L, 60.0, lateral=1.5)  # 1.5 m left of the lane, heading along it
    r = build_follow_plan(rm, pose, 10.0, 0)
    assert r is not None and abs(r.e_y - 1.5) < 0.1
    y = r.plan.positions_xy[:, 1]
    assert abs(y[0] - 1.5) < 1e-6 and abs(y[-1]) < 0.15, "ends on the lane"
    assert np.all(np.diff(y) <= 1e-6 + 0.0), "monotone return, no overshoot past the lane"
    # no lateral jerk: heading change per 0.1 s stays small at 10 m/s
    assert np.max(np.abs(np.diff(np.unwrap(r.plan.yaws)))) < np.deg2rad(4.0)


def test_curvature_cap_slows_before_the_turn():
    L = lane("left90")  # radius 40 m -> v_curv = sqrt(3*40) = 10.95 m/s
    rm = RouteMap()
    for s in np.arange(0, 45, 1.0):
        p = pose_on_lane(L, s)
        rm.update(route_window(L, p), p)
    pose = pose_on_lane(L, 45.0)
    # 13 m/s with ~15 m of runway is reachable at d_max; from 16 m/s it is not, and the profile then
    # (correctly) enters the turn above the cap rather than jumping the speed.
    r = build_follow_plan(rm, pose, 13.0, 0, FollowConfig(speed_src="curv"))
    assert r is not None
    xy = r.plan.positions_xy
    v = np.linalg.norm(np.diff(xy, axis=0), axis=1) / 0.1
    in_turn = xy[1:, 0] > 62
    assert in_turn.any()
    assert v[in_turn].max() < 11.6, f"in-turn speed {v[in_turn].max():.1f} exceeds the cap"
    assert v[0] > 12.0, "does not brake to the cap instantly (dilated curvature starts the cap ~3 m early)"
    assert np.all(np.diff(v) > -0.35), "decel bounded (d_max 3 m/s2 -> 0.3 m/s per 0.1 s)"
    assert r.limiting == "curv"


def test_keep_holds_speed_and_floor_lifts_a_crawl():
    L = lane("straight")
    rm = RouteMap()
    for s in np.arange(0, 60, 1.0):
        p = pose_on_lane(L, s)
        rm.update(route_window(L, p), p)
    pose = pose_on_lane(L, 60.0)
    r = build_follow_plan(rm, pose, 12.0, 0, FollowConfig(speed_src="keep"))
    v = np.linalg.norm(np.diff(r.plan.positions_xy, axis=0), axis=1) / 0.1
    assert np.allclose(v, 12.0, atol=0.2)
    r2 = build_follow_plan(rm, pose, 0.5, 0, FollowConfig(speed_src="keep", v_min=3.0))
    v2 = np.linalg.norm(np.diff(r2.plan.positions_xy, axis=0), axis=1) / 0.1
    assert v2[-1] > 2.5 and v2[0] < 1.6, "accelerates from a crawl toward v_min, bounded by a_max"
    assert np.all(np.diff(v2) < 0.35), "accel bounded (a_max 2 m/s2 -> 0.2 m/s per 0.1 s, plus sampling slack)"


def test_vavam_cue_brakes_the_follower():
    L = lane("straight")
    rm = RouteMap()
    for s in np.arange(0, 60, 1.0):
        p = pose_on_lane(L, s)
        rm.update(route_window(L, p), p)
    pose = pose_on_lane(L, 60.0)
    # camera model says: decelerate 10 -> 2 m/s over 3 s (waypoints every 0.5 s)
    vs = np.array([9.0, 7.5, 6.0, 4.5, 3.0, 2.0])
    traj = np.column_stack([np.cumsum(vs * 0.5), np.zeros(6)])
    r = build_follow_plan(rm, pose, 10.0, 0, FollowConfig(speed_src="min"), vavam_traj_rig=traj)
    v = np.linalg.norm(np.diff(r.plan.positions_xy, axis=0), axis=1) / 0.1
    assert v[-1] < 4.0 and r.limiting == "vavam"
    assert np.all(np.abs(r.plan.positions_xy[:, 1]) < 0.05), "lateral path untouched by the speed cue"
    s, vv = speed_profile_from_trajectory(traj)
    assert np.allclose(vv[1:], vs) and s[-1] == pytest.approx(np.sum(vs * 0.5))


def test_plan_shape_is_what_build_trajectory_expects():
    L = lane("straight")
    rm = RouteMap()
    for s in np.arange(0, 60, 1.0):
        p = pose_on_lane(L, s)
        rm.update(route_window(L, p), p)
    r = build_follow_plan(rm, pose_on_lane(L, 60.0), 10.0, 1_234_000)
    p = r.plan
    assert p.created_time_us == 1_234_000
    assert p.times_s[0] == 0.0 and abs(p.times_s[-1] - 5.0) < 1e-9 and len(p.times_s) == 51
    assert p.positions_xy.shape == (51, 2) and p.yaws.shape == (51,)


def test_unusable_route_returns_none():
    rm = RouteMap()
    assert build_follow_plan(rm, (0.0, 0.0, 0.0), 10.0, 0) is None  # nothing accumulated
    L = lane("straight")
    for s in np.arange(0, 60, 1.0):
        p = pose_on_lane(L, s)
        rm.update(route_window(L, p), p)
    assert build_follow_plan(rm, (30.0, 40.0, 0.0), 10.0, 0) is not None  # start 10 m ahead, 40 m left: a sharp turn ahead - follow it
    assert build_follow_plan(rm, (20.0, 0.0, np.pi), 10.0, 0) is None  # path start 20 m BEHIND the ego (heading away)
    assert build_follow_plan(rm, (80.0, 40.0, 0.0), 10.0, 0) is None  # interior projection 40 m off the path


def test_hermite_join_endpoints_and_tangents():
    j = hermite_join(np.array([0.0, 0.0]), np.array([1.0, 0.0]), np.array([20.0, 4.0]), np.array([1.0, 0.0]))
    assert np.allclose(j[0], [0, 0]) and np.allclose(j[-1], [20, 4])
    d0, d1 = j[1] - j[0], j[-1] - j[-2]
    assert abs(np.arctan2(d0[1], d0[0])) < np.deg2rad(3) and abs(np.arctan2(d1[1], d1[0])) < np.deg2rad(3)
