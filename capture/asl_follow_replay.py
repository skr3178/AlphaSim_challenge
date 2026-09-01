"""Geometric replay of one rollout.asl: routes (as received), ego track (truth), driver plans.
Answers: does the accumulated route match the ego's actual path? do the plans lie on the route?
does the ego follow the plans?  usage: asl_follow_replay.py <rollout.asl> [<baseline rollout.asl>]"""
import asyncio, math, sys
import numpy as np
from google.protobuf.json_format import MessageToDict
from alpasim_utils.logs import async_read_pb_log
sys.path.insert(0, "/home/skr/alpasim-challenge/alpasim/e2e_challenge/sample_submission_vavam")
from vavam_challenge.route_map import RouteMap, rig_to_local, _project

def yaw(q): 
    w,x,y,z=(q.get("w",0.0),q.get("x",0.0),q.get("y",0.0),q.get("z",0.0)); return math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
def pxyyaw(p): 
    v=p.get("vec",{}); return (v.get("x",0.0), v.get("y",0.0), yaw(p.get("quat",{})))

async def load(path):
    routes, egoposes, plans, truth = [], {}, [], []
    async for e in async_read_pb_log(path):
        kind = e.WhichOneof("log_entry"); d = MessageToDict(getattr(e, kind), preserving_proto_field_name=True)
        if kind == "route_request":
            r = d.get("route", d); ts = int(r.get("timestamp_us", 0))
            w = np.array([[p.get("x",0.0), p.get("y",0.0)] for p in r.get("waypoints", [])], float)
            routes.append((ts, w[np.isfinite(w).all(axis=1)]))
        elif kind == "driver_ego_trajectory":
            for p in d.get("trajectory", {}).get("poses", []):
                egoposes[int(p.get("timestamp_us", 0))] = pxyyaw(p.get("pose", {}))
        elif kind == "driver_return":
            ps = d.get("trajectory", {}).get("poses", []) or d.get("drive_response", {}).get("trajectory", {}).get("poses", [])
            plans.append((int(ps[0].get("timestamp_us", 0)) if ps else 0, np.array([[p["pose"]["vec"].get("x",0.0), p["pose"]["vec"].get("y",0.0)] for p in ps], float) if ps else np.zeros((0,2))))
        elif kind == "actor_poses":
            ts = int(d.get("timestamp_us", 0)); aps = d.get("actor_poses", [])
            ego = [a for a in aps if a.get("actor_id") == "EGO"]
            if ego: truth.append((ts, pxyyaw(ego[0].get("actor_pose", {}))))
    return routes, egoposes, plans, truth

def analyse(path, label):
    routes, egoposes, plans, truth = asyncio.run(load(path))
    print(f"\n=== {label}: {len(routes)} routes, {len(egoposes)} ego poses, {len(plans)} plans, {len(truth)} truth poses")
    rm = RouteMap(); overlap = []
    prev = None
    for ts, w in routes:
        pose = egoposes.get(ts) or egoposes[min(egoposes, key=lambda t: abs(t-ts))]
        loc = rig_to_local(w, pose)
        if prev is not None and len(prev) >= 2 and len(loc) >= 1:
            d,_,_ = _project(loc, prev); overlap.append(float(np.median(d[d < 30])) if (d < 30).any() else float("nan"))
        prev = loc; rm.update(w, pose)
    print("window-to-window overlap error (m):", np.round(overlap, 2))
    ts0, w0 = routes[0]; print(f"route@t0 in ego frame: first wp ({w0[0,0]:.1f},{w0[0,1]:.1f}) bearing {math.degrees(math.atan2(w0[0,1],w0[0,0])):+.0f} deg, last wp ({w0[-1,0]:.1f},{w0[-1,1]:.1f}), n={len(w0)}")
    T = np.array([[p[1][0], p[1][1]] for p in truth]); tt = np.array([p[0] for p in truth]) / 1e6
    d_tr, arc_tr, sgn = _project(T, rm.path)
    print("ego truth vs accumulated route: dist per step (m):", np.round(d_tr, 2))
    print("                              signed (+left):     ", np.round(sgn, 2))
    for i, (ts, P) in enumerate(plans):
        if len(P) < 2: continue
        dp,_,_ = _project(P, rm.path)
        k = int(np.argmin(np.abs(tt - ts/1e6))); e = T[k]
        print(f"  plan@{ts/1e6:4.1f}s: {len(P):2d} pts, start-gap to truth {np.hypot(*(P[0]-e)):.2f} m, plan->route dist max {dp.max():.2f} mean {dp.mean():.2f}, plan end ({P[-1,0]:.1f},{P[-1,1]:.1f}) len {np.sum(np.linalg.norm(np.diff(P,axis=0),axis=1)):.1f} m")
    return rm, T, tt

f0 = analyse(sys.argv[1], "F0 follower")
if len(sys.argv) > 2:
    rm_b, Tb, ttb = analyse(sys.argv[2], "baseline")
    # baseline's truth track vs F0's accumulated route (same scene -> same route geometry)
    d,_,s = _project(Tb, f0[0].path); print("\nbaseline ego truth vs F0's accumulated route (m):", np.round(d, 2))
    d2,_,_ = _project(f0[1], rm_b.path); print("F0 ego truth vs baseline-run accumulated route (m):", np.round(d2, 2))
