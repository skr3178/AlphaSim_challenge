"""Capture driver: the starter driver, plus it saves everything the simulator sends.

Writes to $CAPTURE_DIR/<session>/:
  images/<time_us>_<logical_id>.jpg     every camera JPEG, byte-for-byte as received
  session.json                          camera calibration handed over at start_session
  routes.jsonl                          one line per submit_route (rig-frame waypoints)
  egomotion.jsonl                       one line per submit_egomotion_observation
  drive.jsonl                           one line per Drive query
"""
from __future__ import annotations
import json, os, sys, threading
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/alpasim-challenge/alpasim/e2e_challenge/starter_kit"))
import driver as starter  # noqa: E402
from alpasim_grpc.v0 import common_pb2, egodriver_pb2  # noqa: E402
from google.protobuf.json_format import MessageToDict  # noqa: E402

ROOT = Path(os.environ.get("CAPTURE_DIR", "./captured"))


class CaptureDriver(starter.StarterDriver):
    def __init__(self):
        super().__init__()
        self._io = threading.Lock()

    def _dir(self, uuid: str) -> Path:
        d = ROOT / uuid
        (d / "images").mkdir(parents=True, exist_ok=True)
        return d

    def _append(self, uuid: str, name: str, obj: dict) -> None:
        with self._io, open(self._dir(uuid) / name, "a") as f:
            f.write(json.dumps(obj) + "\n")

    def start_session(self, request, context):
        d = self._dir(request.session_uuid)
        (d / "session.json").write_text(json.dumps(MessageToDict(request), indent=1))
        return super().start_session(request, context)

    def submit_image_observation(self, request, context):
        ci = request.camera_image
        p = self._dir(request.session_uuid) / "images" / f"{ci.frame_end_us:010d}_{ci.logical_id}.jpg"
        p.write_bytes(ci.image_bytes)
        return super().submit_image_observation(request, context)

    def submit_route(self, request, context):
        r = request.route
        self._append(request.session_uuid, "routes.jsonl",
                     {"timestamp_us": r.timestamp_us,
                      "waypoints": [[w.x, w.y, w.z] for w in r.waypoints]})
        return super().submit_route(request, context)

    def submit_egomotion_observation(self, request, context):
        self._append(request.session_uuid, "egomotion.jsonl", MessageToDict(request))
        return super().submit_egomotion_observation(request, context)

    def drive(self, request, context):
        resp = super().drive(request, context)
        self._append(request.session_uuid, "drive.jsonl",
                     {"time_now_us": request.time_now_us, "time_query_us": request.time_query_us,
                      "n_poses_returned": len(resp.trajectory.poses)})
        return resp


if __name__ == "__main__":
    starter.StarterDriver = CaptureDriver
    starter.main()
