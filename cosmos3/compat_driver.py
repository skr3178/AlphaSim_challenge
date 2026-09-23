"""Single-session full Cosmos3-Edge driver for a bounded local smoke rollout.

Host process, not a competition container. No fallback, cached-plan reuse,
training, ground-truth conditioning, or online/network model access.
"""
import argparse
from concurrent import futures
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import signal
import sys
import threading
import time

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
RUNTIME = Path("/home/skr/alpasim-challenge/alpasim")
sys.path.insert(0, str(RUNTIME / "src/grpc"))
sys.path.insert(0, str(RUNTIME / "e2e_challenge/starter_kit"))

import grpc
import numpy as np
from google.protobuf.json_format import MessageToDict
from PIL import Image
import torch
from diffusers import Cosmos3OmniPipeline, CosmosActionCondition, UniPCMultistepScheduler
from alpasim_grpc import API_VERSION_MESSAGE
from alpasim_grpc.v0 import common_pb2, egodriver_pb2, egodriver_pb2_grpc
import driver as starter
from action_adapter import build_trajectory, validate_timestamps
from profile_edge import CHECKPOINT, GIB, MemorySampler, save_json

LOGGER = logging.getLogger("cosmos_compat")
PROMPT = "You are an autonomous vehicle planning system."


class CosmosDriver(starter.StarterDriver):
    def __init__(self, output):
        super().__init__()
        self.output = output
        self.active_uuid = None
        self.image_observation = None
        self.calibration = None
        self.total_sessions = 0
        self.report = {"status": "loading", "drive_attempts": 0, "successful_predictions": 0,
                       "fallbacks": 0, "route_messages": 0, "ground_truth_messages": 0,
                       "requests": [], "errors": [], "pid": os.getpid(),
                       "conditioning": "current CAM_F0 plus fixed AV prompt; route/ego not conditioned into model",
                       "checkpoint_revision": "344d602b128d1bbdacb43b08d0a3626f46343e29",
                       "scope": "one scene; <=20 drive calls; 40 actions/10Hz; 30 denoising steps; resolution tier256"}
        torch.set_num_threads(4)
        torch.cuda.set_per_process_memory_fraction(12 * GIB / torch.cuda.get_device_properties(0).total_memory)
        self.sampler = MemorySampler()
        self.sampler.thread.start()
        self.pipe = Cosmos3OmniPipeline.from_pretrained(CHECKPOINT, torch_dtype=torch.bfloat16, local_files_only=True)
        self.pipe.to("cuda")
        self.pipe.scheduler = UniPCMultistepScheduler.from_config(self.pipe.scheduler.config, flow_shift=10.0, use_karras_sigmas=False)
        self.pipe.set_progress_bar_config(disable=True)
        self.report["status"] = "ready"
        self.flush()

    def flush(self):
        self.report["sampled_peak_process_GiB"] = self.sampler.peak()
        save_json(self.output / "driver-summary.json", self.report)

    def start_session(self, request, context):
        with self._lock:
            if self.total_sessions:
                context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "Only one session authorized")
            self.total_sessions += 1
            cameras = [c for c in request.rollout_spec.vehicle.available_cameras if c.logical_id == "CAM_F0"]
            if len(cameras) != 1:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Missing unique CAM_F0 calibration")
            self.calibration = common_pb2.Pose()
            self.calibration.CopyFrom(cameras[0].rig_to_camera)
            self.active_uuid = request.session_uuid
            save_json(self.output / "session.json", MessageToDict(request, preserving_proto_field_name=True))
            self.report["session_uuid"] = request.session_uuid
            self.report["status"] = "session_started"
            self.flush()
            return super().start_session(request, context)

    def submit_image_observation(self, request, context):
        self._get_session(request.session_uuid, context)
        if request.camera_image.logical_id == "CAM_F0":
            with self._lock:
                self.image_observation = egodriver_pb2.RolloutCameraImage.CameraImage()
                self.image_observation.CopyFrom(request.camera_image)
        return common_pb2.Empty()

    def submit_route(self, request, context):
        self._get_session(request.session_uuid, context)
        with self._lock:
            self.report["route_messages"] += 1
        return common_pb2.Empty()

    def submit_recording_ground_truth(self, request, context):
        self.report["ground_truth_messages"] += 1
        self.flush()
        context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Ground truth must be disabled")

    def drive(self, request, context):
        with self._lock:
            self.report["drive_attempts"] += 1
            index = self.report["drive_attempts"]
            entry = {"index": index, "time_now_us": request.time_now_us, "time_query_us": request.time_query_us}
            start = time.monotonic()
            try:
                if index > 20:
                    raise RuntimeError("Bounded compatibility drive-call budget exhausted")
                session = self._get_session(request.session_uuid, context)
                camera = self.image_observation
                if session.latest_pose is None or camera is None:
                    raise RuntimeError("Missing current ego pose or front image; no fallback")
                # AlpaSim's query time is the END of the upcoming control tick,
                # not a planner-delay timestamp. The returned horizon must cover it.
                validate_timestamps(session.latest_pose.timestamp_us, camera.frame_start_us,
                                    camera.frame_end_us, request.time_now_us, request.time_query_us)
                image = Image.open(io.BytesIO(camera.image_bytes)).convert("RGB")
                entry.update({"image_sha256": hashlib.sha256(camera.image_bytes).hexdigest(),
                              "image_start_us": camera.frame_start_us, "image_end_us": camera.frame_end_us,
                              "latest_ego": MessageToDict(session.latest_pose, preserving_proto_field_name=True),
                              "observed_speed_mps": session.latest_speed_mps})
                if index == 1:
                    image.save(self.output / "first-input.png")
                torch.cuda.reset_peak_memory_stats()
                prediction = self.pipe(
                    prompt=PROMPT,
                    action=CosmosActionCondition(mode="policy", domain_name="av", chunk_size=40,
                                                resolution_tier=256, image=image, view_point="ego_view"),
                    fps=10, num_inference_steps=30, guidance_scale=1.0, use_system_prompt=False,
                    output_type="np", generator=torch.Generator(device="cuda").manual_seed(20260918 + index),
                )
                torch.cuda.synchronize()
                if not prediction.action:
                    raise RuntimeError("No action prediction")
                actions = prediction.action[0].float().cpu().numpy()
                if actions.shape != (40, 9):
                    raise RuntimeError(f"Unexpected action shape {actions.shape}")
                trajectory, full_poses = build_trajectory(actions, self.calibration, session.latest_pose, request.time_now_us)
                save_json(self.output / f"prediction-{index:02d}.json", {
                    "raw_actions": actions.tolist(), "full_local_rig_poses": full_poses.tolist(),
                    "returned_trajectory": MessageToDict(trajectory, preserving_proto_field_name=True),
                })
                entry.update({"status": "ok", "seconds": time.monotonic() - start,
                              "returned_poses": len(trajectory.poses),
                              "torch_peak_allocated_GiB": torch.cuda.max_memory_allocated() / GIB,
                              "torch_peak_reserved_GiB": torch.cuda.max_memory_reserved() / GIB,
                              "sampled_process_peak_GiB": self.sampler.peak(start),
                              "last_position_local": full_poses[-1, :3, 3].tolist(),
                              "max_unprojected_z_change_m": float(np.abs(full_poses[:, 2, 3] - full_poses[0, 2, 3]).max())})
                self.report["successful_predictions"] += 1
                del prediction
                # Release unused allocator blocks to leave room for the shared renderer.
                torch.cuda.empty_cache()
                self.report["requests"].append(entry)
                self.flush()
                LOGGER.info("COSMOS_PREDICTION %s", json.dumps(entry))
                return egodriver_pb2.DriveResponse(trajectory=trajectory)
            except Exception as exc:
                entry.update({"status": "failed", "error": repr(exc), "seconds": time.monotonic() - start})
                self.report["requests"].append(entry)
                self.report["errors"].append(repr(exc))
                self.report["status"] = "failed"
                self.flush()
                LOGGER.exception("COSMOS_INFERENCE_FAILED no fallback")
                context.abort(grpc.StatusCode.INTERNAL, repr(exc))

    def close_session(self, request, context):
        result = super().close_session(request, context)
        self.report["status"] = "closed" if not self.report["errors"] else "failed"
        self.flush()
        return result

    def get_version(self, request, context):
        return common_pb2.VersionId(version_id="cosmos3-edge-compat-only", git_hash="local", grpc_api_version=API_VERSION_MESSAGE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=6795)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    service = CosmosDriver(args.output)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4), options=[("grpc.max_receive_message_length", 32 * 1024**2)])
    egodriver_pb2_grpc.add_EgodriverServiceServicer_to_server(service, server)
    if not server.add_insecure_port(f"127.0.0.1:{args.port}"):
        raise RuntimeError("Could not bind localhost port")
    service.attach_server(server)
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    server.start()
    LOGGER.info("COSMOS_READY port=%s", args.port)
    try:
        stopped.wait(1200)
    finally:
        server.stop(grace=5).wait(6)
        service.sampler.stop.set()
        service.sampler.thread.join(4)
        service.flush()


if __name__ == "__main__":
    main()
