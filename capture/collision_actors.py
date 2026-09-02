"""For the follower's new at-fault scenes: which actor was hit, was it moving, where was it relative to the lane-centre
route and to the human path? (all from rollout.asl + the per-timestep parquet; no simulator)"""
import asyncio, glob, json, math, sys
import numpy as np, polars as pl
from google.protobuf.json_format import MessageToDict
from alpasim_utils.logs import async_read_pb_log
sys.path.insert(0, "/home/skr/alpasim-challenge/alpasim/e2e_challenge/sample_submission_vavam")
from vavam_challenge.route_map import rig_to_local, _project
R="/home/skr/alpasim-challenge/alpasim/runs"
def yaw(q): 
    w,x,y,z=(q.get("w",0.0),q.get("x",0.0),q.get("y",0.0),q.get("z",0.0)); return math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
def pxy(p): v=p.get("vec",{}); return (v.get("x",0.0), v.get("y",0.0))
async def load(path):
    routes, egoposes, gt, actors, sizes = [], {}, None, {}, {}
    async for e in async_read_pb_log(path):
        k=e.WhichOneof("log_entry")
        if k=="rollout_metadata":
            d=MessageToDict(e.rollout_metadata, preserving_proto_field_name=True)
            gt=np.array([pxy(p["pose"]) for p in d.get("ego_rig_recorded_ground_truth_trajectory",{}).get("poses",[])],float)
            for a in d.get("actor_definitions",{}).get("actor_aabb",[]): sizes[a["actor_id"]]=(a["aabb"].get("size_x",4.5),a["aabb"].get("size_y",2.0))
        elif k=="route_request":
            d=MessageToDict(e.route_request, preserving_proto_field_name=True); r=d.get("route",d)
            w=np.array([[p.get("x",0.0),p.get("y",0.0)] for p in r.get("waypoints",[])],float); routes.append((int(r.get("timestamp_us",0)), w[np.isfinite(w).all(axis=1)]))
        elif k=="driver_ego_trajectory":
            d=MessageToDict(e.driver_ego_trajectory, preserving_proto_field_name=True)
            for p in d.get("trajectory",{}).get("poses",[]):
                v=p.get("pose",{}).get("vec",{}); egoposes[int(p.get("timestamp_us",0))]=(v.get("x",0.0),v.get("y",0.0),yaw(p.get("pose",{}).get("quat",{})))
        elif k=="actor_poses":
            d=MessageToDict(e.actor_poses, preserving_proto_field_name=True); ts=int(d.get("timestamp_us",0))
            actors[ts]={a["actor_id"]:pxy(a.get("actor_pose",{})) for a in d.get("actor_poses",[])}
    return routes, egoposes, gt, actors, sizes
def route_poly(routes, egoposes):
    pts=[rig_to_local(w, egoposes.get(ts) or egoposes[min(egoposes,key=lambda t:abs(t-ts))]) for ts,w in routes if len(w)>=2]
    poly=[pts[0]]
    for w in pts[1:]:
        cur=np.vstack(poly); d,arc,_=_project(w,cur); cl=np.concatenate([[0],np.cumsum(np.linalg.norm(np.diff(cur,axis=0),axis=1))])
        b=w[arc>=cl[-1]-0.25]
        if len(b): poly.append(b)
    r=np.vstack(poly); keep=np.concatenate([[True],np.linalg.norm(np.diff(r,axis=0),axis=1)>0.3]); return r[keep]
run, base = sys.argv[1], sys.argv[2]
f3={r["clipgt_id"]:r["metrics"] for r in json.load(open(f"{R}/{run}/aggregate/results-summary.json"))["rollouts"]}
mup={r["clipgt_id"]:r["metrics"] for r in json.load(open(f"{R}/{base}/aggregate/results-summary.json"))["rollouts"]}
new=[i for i in f3 if f3[i]["collision_at_fault"]>0 and mup[i]["collision_at_fault"]==0]
df=pl.read_parquet(f"{R}/{run}/aggregate/metrics_unprocessed.parquet")
print(f"{'scene':40s} {'t_coll':>6} {'actor':>10} {'actor v':>7} {'actor->route lat':>16} {'human clearance':>15} {'ego->route':>10} {'ego->human':>10}")
kinds={"stationary_on_route":0,"stationary_off_route":0,"moving":0}
for i in new:
    asl=glob.glob(f"{R}/{run}/rollouts/{i}/*/rollout.asl")[0]
    routes,egoposes,gt,actors,sizes=asyncio.run(load(asl)); route=route_poly(routes,egoposes)
    d=df.filter((pl.col("clipgt_id")==i)&(pl.col("name").is_in(["collision_front","collision_lateral"]))&(pl.col("values")>0)).sort("timestamps_us")
    tcol=int(d["timestamps_us"][0]) if len(d) else None
    if tcol is None: print(i[:40],"no collision timestamp"); continue
    ts=min(actors,key=lambda t:abs(t-tcol)); ego=np.array(actors[ts]["EGO"])
    others={a:np.array(p) for a,p in actors[ts].items() if a!="EGO"}
    aid=min(others,key=lambda a:np.linalg.norm(others[a]-ego)); apos=others[aid]
    tprev=max([t for t in actors if t<=ts-900_000], default=None)
    v=np.linalg.norm(apos-np.array(actors[tprev][aid]))/((ts-tprev)/1e6) if tprev is not None and aid in actors[tprev] else float('nan')
    _,_,lat=_project(apos[None],route); dlat=float(abs(lat[0]))
    clear=float(np.min(np.linalg.norm(gt-apos,axis=1))) if gt is not None and len(gt) else float('nan')
    er=float(_project(ego[None],route)[0][0]); eh=float(np.min(np.linalg.norm(gt-ego,axis=1)))
    kind="moving" if v>1.0 else ("stationary_on_route" if dlat<1.5 else "stationary_off_route"); kinds[kind]+=1
    print(f"{i[:40]:40s} {tcol/1e6:6.1f} {aid[:10]:>10} {v:7.1f} {dlat:16.2f} {clear:15.2f} {er:10.2f} {eh:10.2f}")
print("\nhit-actor kinds:", kinds, "| 'human clearance' = min distance of the recorded human path (rig point) to the hit actor's position at impact; 'actor->route lat' = the actor's lateral offset from the lane-centre route")
