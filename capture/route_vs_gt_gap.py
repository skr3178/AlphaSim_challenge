"""Route-vs-human-line gap, per scene, from rollout.asl only (no simulator).
route  = all route_request windows transformed into the local frame with the ego pose of their tick (what the driver saw)
human  = rollout_metadata.ego_rig_recorded_ground_truth_trajectory (the recorded path the scorer measures against)
gap    = signed lateral offset of each human-path point from the route polyline (+ = human is left of the route)."""
import asyncio, glob, json, math, os, sys
import numpy as np
from google.protobuf.json_format import MessageToDict
from alpasim_utils.logs import async_read_pb_log
sys.path.insert(0, "/home/skr/alpasim-challenge/alpasim/e2e_challenge/sample_submission_vavam")
from vavam_challenge.route_map import rig_to_local, _project

def yaw(q): 
    w,x,y,z=(q.get("w",0.0),q.get("x",0.0),q.get("y",0.0),q.get("z",0.0)); return math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
def pxyyaw(p):
    v=p.get("vec",{}); return (v.get("x",0.0), v.get("y",0.0), yaw(p.get("quat",{})))

async def load(path):
    routes, egoposes, gt, ego_track = [], {}, None, []
    async for e in async_read_pb_log(path):
        kind = e.WhichOneof("log_entry")
        if kind == "rollout_metadata":
            d = MessageToDict(e.rollout_metadata, preserving_proto_field_name=True)
            gt = np.array([[p["pose"]["vec"].get("x",0.0), p["pose"]["vec"].get("y",0.0)] for p in d.get("ego_rig_recorded_ground_truth_trajectory",{}).get("poses",[])], float)
        elif kind == "route_request":
            d = MessageToDict(e.route_request, preserving_proto_field_name=True); r = d.get("route", d)
            w = np.array([[p.get("x",0.0), p.get("y",0.0)] for p in r.get("waypoints", [])], float)
            routes.append((int(r.get("timestamp_us",0)), w[np.isfinite(w).all(axis=1)]))
        elif kind == "driver_ego_trajectory":
            d = MessageToDict(e.driver_ego_trajectory, preserving_proto_field_name=True)
            for p in d.get("trajectory",{}).get("poses",[]): egoposes[int(p.get("timestamp_us",0))] = pxyyaw(p.get("pose",{}))
        elif kind == "actor_poses":
            d = MessageToDict(e.actor_poses, preserving_proto_field_name=True)
            for a in d.get("actor_poses",[]):
                if a.get("actor_id")=="EGO": ego_track.append(pxyyaw(a.get("actor_pose",{}))[:2])
    return routes, egoposes, gt, np.array(ego_track)

def analyse(path):
    routes, egoposes, gt, ego = asyncio.run(load(path))
    if gt is None or len(gt) < 3 or not routes or not egoposes: return None
    pts = []
    for ts, w in routes:
        if len(w) < 2: continue
        pose = egoposes.get(ts) or egoposes[min(egoposes, key=lambda t: abs(t-ts))]
        pts.append(rig_to_local(w, pose))
    if not pts: return None
    # build one ordered route polyline: windows are ordered in time and overlap; keep points beyond the running end
    poly = [pts[0]]
    for w in pts[1:]:
        cur = np.vstack(poly)
        d, arc, _ = _project(w, cur); cl = np.concatenate([[0],np.cumsum(np.linalg.norm(np.diff(cur,axis=0),axis=1))])
        beyond = w[arc >= cl[-1]-0.25]
        if len(beyond): poly.append(beyond)
    route = np.vstack(poly)
    keep = np.concatenate([[True], np.linalg.norm(np.diff(route,axis=0),axis=1) > 0.3]); route = route[keep]
    if len(route) < 2: return None
    # human path points that lie within the route's longitudinal extent (route starts ~40 m ahead of the start pose)
    d, arc, signed = _project(gt, route)
    cl = np.concatenate([[0],np.cumsum(np.linalg.norm(np.diff(route,axis=0),axis=1))])
    inside = (arc > 0.5) & (arc < cl[-1]-0.5)
    if inside.sum() < 3: return {"n_gt_in_route": int(inside.sum())}
    s = signed[inside]; a = np.abs(s)
    # driven ego (this run) vs human line, for reference
    dego = float(np.median(_project(ego, gt)[0])) if len(ego) > 2 else float("nan")
    return {"n_gt_in_route": int(inside.sum()), "gap_mean": float(a.mean()), "gap_p90": float(np.percentile(a,90)), "gap_max": float(a.max()),
            "gap_signed_mean": float(s.mean()), "frac_gt_over_0.75": float((a>0.75).mean()), "frac_gt_over_1.0": float((a>1.0).mean()), "ego_vs_gt_median": dego}

if __name__ == "__main__":
    run = sys.argv[1]; out = {}
    asls = sorted(glob.glob(f"/home/skr/alpasim-challenge/alpasim/runs/{run}/rollouts/*/*/rollout.asl"))
    for i, a in enumerate(asls):
        scene = a.split("/rollouts/")[1].split("/")[0]
        try: out[scene] = analyse(a)
        except Exception as ex: out[scene] = {"error": repr(ex)[:120]}
        if i % 50 == 0: print(f"{i}/{len(asls)}", flush=True)
    json.dump(out, open(f"/home/skr/alpasim-challenge/logs/route_vs_gt_gap-{run}.json","w"), indent=1)
    print("done", len(out))
