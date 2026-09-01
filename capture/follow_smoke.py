"""In-container smoke test of the route follower on a captured session (no simulator, no GPU work).

Feeds the recorded egomotion + route messages through the real driver servicer (VAVAM_FOLLOW_ROUTE=1,
VAVAM_FOLLOW_NO_MODEL=1 so no checkpoint is needed) and checks the Drive responses: trajectory starts
at the ego, follows the accumulated path, speed ~ current speed, no fallbacks once the path is ready.
Run:  docker run --rm -i -v <capture_dir>:/data:ro -e VAVAM_FOLLOW_ROUTE=1 -e VAVAM_FOLLOW_NO_MODEL=1 \
        -e VAVAM_FOLLOW_SPEED_SRC=curv --entrypoint python <image> /data/follow_smoke.py <session_dir>
"""
import json, math, os, sys
import numpy as np
sys.path.insert(0, "/app")
from alpasim_grpc.v0 import common_pb2, egodriver_pb2
from vavam_challenge import driver as drv

D = sys.argv[1]
R = [json.loads(l) for l in open(f"{D}/routes.jsonl")]
E = [json.loads(l) for l in open(f"{D}/egomotion.jsonl")]
sid = E[0]["sessionUuid"]

class Ctx:  # minimal grpc context stand-in
    def abort(self, code, msg): raise RuntimeError(msg)

handle = drv.VavamPolicyHandle(checkpoint_path="/nonexistent", tokenizer_path="/nonexistent", device="cpu")
svc = drv.VavamChallengeDriver(policy_handle=handle, camera_id=None, camera_candidates=("CAM_F0",),
                               inference_interval_us=500_000, enable_rectification=False)
svc.start_session(egodriver_pb2.DriveSessionRequest(session_uuid=sid), Ctx())

def pose_msg(p):
    v = p["pose"].get("vec", {}); q = p["pose"]["quat"]
    return common_pb2.PoseAtTime(timestamp_us=int(p.get("timestampUs", 0)),
        pose=common_pb2.Pose(vec=common_pb2.Vec3(x=v.get("x", 0.0), y=v.get("y", 0.0), z=v.get("z", 0.0)),
                             quat=common_pb2.Quat(w=q.get("w", 0.0), x=q.get("x", 0.0), y=q.get("y", 0.0), z=q.get("z", 0.0))))

def yaw(q): 
    return math.atan2(2*(q.get("w",0)*q.get("z",0)+q.get("x",0)*q.get("y",0)), 1-2*(q.get("y",0)**2+q.get("z",0)**2))

results = []
for e, r in zip(E, R):
    traj = common_pb2.Trajectory(poses=[pose_msg(p) for p in e["trajectory"]["poses"]])
    dyn = [common_pb2.DynamicState(linear_velocity=common_pb2.Vec3(x=d["linearVelocity"].get("x", 0.0), y=d["linearVelocity"].get("y", 0.0)))
           for d in e["dynamicStates"]]
    svc.submit_egomotion_observation(egodriver_pb2.RolloutEgoTrajectory(session_uuid=sid, trajectory=traj, dynamic_states=dyn), Ctx())
    route = egodriver_pb2.Route(timestamp_us=r["timestamp_us"], waypoints=[common_pb2.Vec3(x=w[0], y=w[1], z=w[2]) for w in r["waypoints"]])
    svc.submit_route(egodriver_pb2.RouteRequest(session_uuid=sid, route=route), Ctx())
    resp = svc.drive(egodriver_pb2.DriveRequest(session_uuid=sid, time_now_us=r["timestamp_us"], time_query_us=r["timestamp_us"] + 500_000), Ctx())
    P = np.array([[p.pose.vec.x, p.pose.vec.y] for p in resp.trajectory.poses]); T = np.array([p.timestamp_us for p in resp.trajectory.poses]) / 1e6
    last = e["trajectory"]["poses"][-1]; ex, ey = last["pose"].get("vec", {}).get("x", 0.0), last["pose"].get("vec", {}).get("y", 0.0)
    v = np.linalg.norm(np.diff(P, axis=0), axis=1) / np.diff(T)
    st = svc._sessions[sid]
    results.append((r["timestamp_us"] / 1e6, len(P), float(np.hypot(P[0, 0] - ex, P[0, 1] - ey)), float(v.mean()) if len(v) else 0.0, st.follow_fallbacks, st.route_map.n_updates,
                    float(st.route_map.s[-1]) if st.route_map.s is not None else 0.0))
print(f"{'t':>5} {'npose':>5} {'start_gap_m':>11} {'mean_v':>7} {'fallbacks':>9} {'updates':>7} {'path_len':>8}")
for row in results: print(f"{row[0]:5.1f} {row[1]:5d} {row[2]:11.3f} {row[3]:7.2f} {row[4]:9d} {row[5]:7d} {row[6]:8.1f}")
# final geometry check: last trajectory vs accumulated path
st = svc._sessions[sid]; rm = st.route_map
from vavam_challenge.route_map import _project
d, _, _ = _project(P, rm.path)
print(f"last trajectory: {len(P)} poses, horizon {T[-1]-T[0]:.1f}s, max dist to accumulated path {d.max():.2f} m (first 20 m: {d[:int(20/ max(v.mean(),1)/0.1)].max():.2f})")
ok = results[-1][4] == 0 or results[-1][4] < len(results) // 2
print("SMOKE", "OK" if ok and d.max() < 1.0 else "CHECK")
