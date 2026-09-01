"""Driver load test: hit a running driver container with N concurrent Drive streams (official shape = 8 per GPU:
4 replicas x 2 rollouts) using the captured Singapore/Vegas frames, and report per-call latency percentiles.

  python capture/driver_loadtest.py --port 6789 --streams 8 --seconds 60
Run with ONLY the driver container up (no simulator) so the number is a clean contention measurement.
"""
import argparse, glob, json, time, threading, statistics as st, os, sys
import grpc
from google.protobuf.json_format import ParseDict
sys.path.insert(0, os.path.expanduser("~/alpasim-challenge/alpasim/src/grpc"))
from alpasim_grpc.v0 import egodriver_pb2, egodriver_pb2_grpc, common_pb2

ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=6789); ap.add_argument("--streams", type=int, default=8)
ap.add_argument("--seconds", type=int, default=60); ap.add_argument("--warmup", type=int, default=3)
ap.add_argument("--capture", default=sorted(glob.glob(os.path.expanduser("~/Downloads/alpasim_challenge/capture/captured/*")))[0])
a = ap.parse_args()

sess = json.load(open(f"{a.capture}/session.json"))
imgs = [open(f, "rb").read() for f in sorted(glob.glob(f"{a.capture}/images/*_CAM_F0.jpg"))]
route = json.loads(open(f"{a.capture}/routes.jsonl").readline())
ego = json.loads(open(f"{a.capture}/egomotion.jsonl").readline())
lat = {i: [] for i in range(a.streams)}; stop = time.time() + a.seconds

def stream(i):
    ch = grpc.insecure_channel(f"127.0.0.1:{a.port}"); stub = egodriver_pb2_grpc.EgodriverServiceStub(ch); U = f"load-{i}"
    req = ParseDict(sess, egodriver_pb2.DriveSessionRequest()); req.session_uuid = U; stub.start_session(req, timeout=60)
    e = ParseDict(ego, egodriver_pb2.RolloutEgoTrajectory()); e.session_uuid = U; stub.submit_egomotion_observation(e, timeout=30)
    stub.submit_route(egodriver_pb2.RouteRequest(session_uuid=U, route=egodriver_pb2.Route(timestamp_us=route["timestamp_us"],
        waypoints=[common_pb2.Vec3(x=w[0], y=w[1], z=w[2]) for w in route["waypoints"]])), timeout=30)
    k = 0; t_us = 17000
    while time.time() < stop:
        img = imgs[k % len(imgs)]; k += 1; t_us += 500000
        stub.submit_image_observation(egodriver_pb2.RolloutCameraImage(session_uuid=U, camera_image=egodriver_pb2.RolloutCameraImage.CameraImage(
            frame_start_us=t_us - 17000, frame_end_us=t_us, image_bytes=img, logical_id="CAM_F0")), timeout=30)
        t0 = time.perf_counter(); stub.drive(egodriver_pb2.DriveRequest(session_uuid=U, time_now_us=t_us, time_query_us=t_us), timeout=120); lat[i].append(time.perf_counter() - t0)
    stub.close_session(egodriver_pb2.DriveSessionCloseRequest(session_uuid=U), timeout=30)

th = [threading.Thread(target=stream, args=(i,), daemon=True) for i in range(a.streams)]
[t.start() for t in th]; [t.join() for t in th]
allv = sorted(v for i in lat for v in lat[i][a.warmup:])
if not allv: sys.exit("no measurements")
q = lambda p: allv[min(len(allv)-1, int(p*len(allv)))]*1000
print(f"streams={a.streams} calls={len(allv)} (excl. {a.warmup} warm-up/stream) | mean {st.mean(allv)*1000:.0f} ms  p50 {q(.5):.0f}  p90 {q(.9):.0f}  p99 {q(.99):.0f}  max {allv[-1]*1000:.0f} ms | share >100 ms: {100*sum(v>0.1 for v in allv)/len(allv):.1f}% | aggregate throughput {len(allv)/a.seconds:.1f} calls/s")
