# SPDX-License-Identifier: Apache-2.0
"""AlpaSim e2e challenge driver backed by WA-JEPA.

Structure follows sample_submission_simscale_navsim_gtrs_dense/driver.py:
a gRPC servicer caches per-session observations, runs model inference only
when a new synchronized camera set appears (the renderer sends frames at
2 Hz = the model's native rate), and serves 10 Hz Drive requests from the
latest cached 4 s plan, with a straight-line fallback.

WA-JEPA deltas vs the GTRS sample:
  * four cameras (adds CAM_B0), in the model's slot order (preprocessing.CAMERA_IDS);
  * a history of the last 4 synchronized sets (padded by repeating the oldest
    during warm-up, like the upstream HUGSIM adapter);
  * ego_status = [command_one_hot(4), vx, vy, ax, ay] and a relative SE(2)
    history trajectory, both at the newest frame time.
"""

from __future__ import annotations

import logging
import math
import os
import signal
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from io import BytesIO
from typing import Protocol

import numpy as np
import torch
from alpasim_grpc import API_VERSION_MESSAGE
from alpasim_grpc.v0 import common_pb2, egodriver_pb2, egodriver_pb2_grpc
from PIL import Image

import grpc

from .batch_worker import BatchPolicy, BatchWorker
from .navigation import DriveCommand, command_from_route, command_one_hot
from .policy import (
    EGO_STATUS_DIM,
    NUM_HISTORY_FRAMES,
    InferenceInput,
    Prediction,
    WAJEPAPolicy,
)
from .preprocessing import (
    CAMERA_IDS,
    EXPECTED_HEIGHT,
    EXPECTED_WIDTH,
    image_to_model_tensor,
)
from .trajectory import (
    CachedPlan,
    build_trajectory_from_plan,
    cached_plan_covers_query,
    make_cached_plan,
    yaw_from_quat,
)

LOGGER = logging.getLogger(__name__)

_IMAGE_CACHE_PER_CAMERA = 3 * NUM_HISTORY_FRAMES
_POSE_HISTORY = 64

_RUNTIME_WRITE_DIR_DEFAULTS = {
    "XDG_CACHE_HOME": "/tmp/.cache",
    "TORCH_HOME": "/tmp/torch",
    "HF_HOME": "/tmp/huggingface",
    "MPLCONFIGDIR": "/tmp/matplotlib",
    "CUDA_CACHE_PATH": "/tmp/nv",
    "NUMBA_CACHE_DIR": "/tmp/numba",
    "ALPASIM_DRIVER_LOG_DIR": "/run/alpasim-driver",
}


def _configure_runtime_write_dirs() -> None:
    for key, value in _RUNTIME_WRITE_DIR_DEFAULTS.items():
        os.environ.setdefault(key, value)


def _configure_torch_threads() -> None:
    torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "1"))))
    torch.set_num_interop_threads(
        max(1, int(os.environ.get("TORCH_NUM_INTEROP_THREADS", "1")))
    )


def convert_absolute_to_relative_se2_array(
    origin_xyh: np.ndarray, state_se2_array: np.ndarray
) -> np.ndarray:
    """Global SE(2) rows -> coordinates relative to origin_xyh.

    Line-for-line equivalent to WA-JEPA's datasets.ego_trajectory_utils (via its
    HUGSIM adapter) so the relative pose convention matches training exactly.
    """
    state_se2_array = np.asarray(state_se2_array, dtype=np.float64).copy()
    if state_se2_array.shape[-1] != 3:
        raise ValueError(f"Expected last dim 3, got shape {state_se2_array.shape}")
    ox, oy, oh = float(origin_xyh[0]), float(origin_xyh[1]), float(origin_xyh[2])
    theta = -oh
    origin_array = np.array([[ox, oy, oh]], dtype=np.float64)
    rot = np.array(
        [[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]]
    )
    points_rel = state_se2_array - origin_array
    points_rel[..., :2] = points_rel[..., :2] @ rot.T
    points_rel[..., 2] = np.arctan2(
        np.sin(points_rel[..., 2]), np.cos(points_rel[..., 2])
    )
    return points_rel


def _pose_xyh(pose: common_pb2.PoseAtTime) -> np.ndarray:
    return np.array(
        [
            float(pose.pose.vec.x),
            float(pose.pose.vec.y),
            float(yaw_from_quat(pose.pose.quat)),
        ],
        dtype=np.float64,
    )


@dataclass
class SessionCounters:
    wajepa_inference: int = 0
    cached_plan: int = 0
    straight_fallback: int = 0
    dynamic_state_fallback: int = 0
    padded_history: int = 0
    inference_error: int = 0


@dataclass
class SessionState:
    images: dict[str, OrderedDict[int, np.ndarray]] = field(
        default_factory=lambda: {camera_id: OrderedDict() for camera_id in CAMERA_IDS}
    )
    poses: list[common_pb2.PoseAtTime] = field(default_factory=list)
    dynamics: list[tuple[int, common_pb2.DynamicState]] = field(default_factory=list)
    command_one_hot: np.ndarray = field(
        default_factory=lambda: command_one_hot(DriveCommand.UNKNOWN)
    )
    cached_plan: CachedPlan | None = None
    last_inference_timestamp_us: int | None = None
    inference_inflight_timestamp_us: int | None = None
    counters: SessionCounters = field(default_factory=SessionCounters)

    def add_image(self, camera_id: str, timestamp_us: int, tensor: np.ndarray) -> None:
        if camera_id not in self.images:
            raise ValueError(f"unknown camera_id: {camera_id}")
        cache = self.images[camera_id]
        cache[int(timestamp_us)] = tensor
        retained = sorted(cache.items())[-_IMAGE_CACHE_PER_CAMERA:]
        cache.clear()
        cache.update(retained)

    def synchronized_history(
        self, time_now_us: int
    ) -> tuple[list[int], np.ndarray, bool]:
        """Last NUM_HISTORY_FRAMES synchronized sets at or before time_now_us.

        Returns (timestamps oldest-first, images [T, V, 3, H, W], padded).
        Timestamps are repeated at the front while fewer than
        NUM_HISTORY_FRAMES sets exist (warm-up), mirroring the upstream
        HUGSIM adapter's history padding.
        """
        common: set[int] | None = None
        for camera_id in CAMERA_IDS:
            eligible = {
                timestamp
                for timestamp in self.images[camera_id]
                if timestamp <= time_now_us
            }
            common = eligible if common is None else (common & eligible)
            if not common:
                raise LookupError("no complete synchronized camera set")
        timestamps = sorted(common)[-NUM_HISTORY_FRAMES:]
        padded = len(timestamps) < NUM_HISTORY_FRAMES
        while len(timestamps) < NUM_HISTORY_FRAMES:
            timestamps.insert(0, timestamps[0])
        frames = np.stack(
            [
                np.stack(
                    [self.images[camera_id][ts] for camera_id in CAMERA_IDS], axis=0
                )
                for ts in timestamps
            ],
            axis=0,
        )
        return timestamps, frames, padded

    def add_egomotion(
        self,
        poses: list[common_pb2.PoseAtTime],
        dynamic_states: list[common_pb2.DynamicState],
    ) -> None:
        if dynamic_states and len(dynamic_states) != len(poses):
            raise ValueError("dynamic_states must be empty or correspond 1:1 with poses")
        incoming_poses = {int(pose.timestamp_us): pose for pose in poses}
        pose_by_time = {int(pose.timestamp_us): pose for pose in self.poses}
        pose_by_time.update(incoming_poses)
        self.poses = [
            pose_by_time[timestamp_us]
            for timestamp_us in sorted(pose_by_time)[-_POSE_HISTORY:]
        ]
        state_by_time = dict(self.dynamics)
        for timestamp_us in incoming_poses:
            state_by_time.pop(timestamp_us, None)
        if dynamic_states:
            state_by_time.update(
                {
                    int(pose.timestamp_us): state
                    for pose, state in zip(poses, dynamic_states, strict=True)
                }
            )
        self.dynamics = [
            (timestamp_us, state_by_time[timestamp_us])
            for timestamp_us in sorted(state_by_time)[-_POSE_HISTORY:]
        ]

    def pose_at_or_before(self, timestamp_us: int) -> common_pb2.PoseAtTime:
        eligible = [pose for pose in self.poses if pose.timestamp_us <= timestamp_us]
        if not eligible:
            raise LookupError("no ego pose at or before the requested time")
        return eligible[-1]

    def ego_snapshot(
        self, time_now_us: int
    ) -> tuple[common_pb2.PoseAtTime, np.ndarray, np.ndarray]:
        pose = self.pose_at_or_before(time_now_us)
        state = dict(self.dynamics).get(int(pose.timestamp_us))
        if state is not None:
            velocity = np.array(
                [state.linear_velocity.x, state.linear_velocity.y], dtype=np.float32
            )
            acceleration = np.array(
                [state.linear_acceleration.x, state.linear_acceleration.y],
                dtype=np.float32,
            )
            return pose, velocity, acceleration
        self.counters.dynamic_state_fallback += 1
        return pose, np.zeros(2, dtype=np.float32), np.zeros(2, dtype=np.float32)


class PredictionWorker(Protocol):
    def predict(
        self, request: InferenceInput, timeout: float | None = None
    ) -> Prediction: ...


class PolicyHandleLike(Protocol):
    def start(self) -> None: ...

    def wait_ready(self, timeout: float | None) -> bool: ...

    def load_error(self) -> BaseException | None: ...

    def worker(self) -> PredictionWorker | None: ...

    def stop(self) -> None: ...


class PolicyHandle:
    """Loads the policy on a background thread and owns the batch worker."""

    def __init__(
        self,
        *,
        loader: Callable[[], BatchPolicy],
        max_batch_size: int = 2,
        batch_window_s: float = 0.002,
    ) -> None:
        self._loader = loader
        self._max_batch_size = int(max_batch_size)
        self._batch_window_s = float(batch_window_s)
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._worker: BatchWorker | None = None
        self._load_error: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._stop_requested = False

    def start(self) -> None:
        with self._lock:
            if self._thread is not None or self._stop_requested:
                return
            self._thread = threading.Thread(
                target=self._load, name="wajepa-policy-loader", daemon=True
            )
            thread = self._thread
        thread.start()

    def wait_ready(self, timeout: float | None) -> bool:
        return self._ready.wait(timeout)

    def load_error(self) -> BaseException | None:
        with self._lock:
            return self._load_error

    def worker(self) -> BatchWorker | None:
        with self._lock:
            if self._stop_requested:
                return None
            return self._worker

    def stop(self) -> None:
        with self._lock:
            self._stop_requested = True
            worker = self._worker
            self._worker = None
        if worker is not None:
            worker.stop()

    def _load(self) -> None:
        try:
            policy = self._loader()
            worker = BatchWorker(
                policy,
                max_batch_size=self._max_batch_size,
                batch_window_s=self._batch_window_s,
            )
            worker.start()
            with self._lock:
                if self._stop_requested:
                    publish = False
                else:
                    self._worker = worker
                    publish = True
            if not publish:
                worker.stop()
        except BaseException as exc:
            with self._lock:
                self._load_error = exc
            LOGGER.exception("WA-JEPA policy load failed")
        finally:
            self._ready.set()


def _context_timeout(context: grpc.ServicerContext) -> float | None:
    time_remaining = getattr(context, "time_remaining", None)
    if not callable(time_remaining):
        return None
    remaining = time_remaining()
    if remaining is None:
        return None
    try:
        timeout = float(remaining)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isnan(timeout) or timeout >= threading.TIMEOUT_MAX:
        return None
    return max(0.0, timeout)


class WAJEPADriver(egodriver_pb2_grpc.EgodriverServiceServicer):
    def __init__(self, policy_handle: PolicyHandleLike) -> None:
        self._policy_handle = policy_handle
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.RLock()

    def start_session(
        self,
        request: egodriver_pb2.DriveSessionRequest,
        context: grpc.ServicerContext,
    ) -> common_pb2.SessionRequestStatus:
        available = {
            camera.logical_id
            for camera in request.rollout_spec.vehicle.available_cameras
        }
        missing = sorted(set(CAMERA_IDS) - available)
        if missing:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                f"missing required cameras: {missing}",
            )
            raise AssertionError("unreachable")
        with self._lock:
            previous = self._sessions.get(request.session_uuid)
            if previous is not None:
                previous.inference_inflight_timestamp_us = None
            self._sessions[request.session_uuid] = SessionState()
        LOGGER.info("started session %s", request.session_uuid)
        return common_pb2.SessionRequestStatus()

    def close_session(
        self,
        request: egodriver_pb2.DriveSessionCloseRequest,
        context: grpc.ServicerContext,
    ) -> common_pb2.Empty:
        with self._lock:
            session = self._sessions.pop(request.session_uuid, None)
            if session is not None:
                session.inference_inflight_timestamp_us = None
        LOGGER.info("closed session %s", request.session_uuid)
        return common_pb2.Empty()

    def submit_image_observation(
        self,
        request: egodriver_pb2.RolloutCameraImage,
        context: grpc.ServicerContext,
    ) -> common_pb2.Empty:
        session = self._get_session(request.session_uuid, context)
        grpc_image = request.camera_image
        if grpc_image.logical_id not in CAMERA_IDS:
            return common_pb2.Empty()
        try:
            with Image.open(BytesIO(grpc_image.image_bytes)) as decoded:
                if decoded.size != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
                    context.abort(
                        grpc.StatusCode.INVALID_ARGUMENT,
                        f"{grpc_image.logical_id} must decode to "
                        f"{EXPECTED_WIDTH}x{EXPECTED_HEIGHT} RGB; got {decoded.size}",
                    )
                    raise AssertionError("unreachable")
                image = np.asarray(decoded.convert("RGB"))
            tensor = image_to_model_tensor(grpc_image.logical_id, image)
        except (Image.DecompressionBombError, OSError, ValueError) as exc:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"failed to decode {grpc_image.logical_id}: {exc}",
            )
            raise AssertionError("unreachable") from exc
        with self._lock:
            if self._sessions.get(request.session_uuid) is session:
                session.add_image(
                    grpc_image.logical_id, int(grpc_image.frame_end_us), tensor
                )
        return common_pb2.Empty()

    def submit_egomotion_observation(
        self,
        request: egodriver_pb2.RolloutEgoTrajectory,
        context: grpc.ServicerContext,
    ) -> common_pb2.Empty:
        session = self._get_session(request.session_uuid, context)
        poses = list(request.trajectory.poses)
        dynamic_states = list(request.dynamic_states)
        try:
            with self._lock:
                if self._sessions.get(request.session_uuid) is session:
                    session.add_egomotion(poses, dynamic_states)
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            raise AssertionError("unreachable") from exc
        return common_pb2.Empty()

    def submit_route(
        self,
        request: egodriver_pb2.RouteRequest,
        context: grpc.ServicerContext,
    ) -> common_pb2.Empty:
        session = self._get_session(request.session_uuid, context)
        command = command_from_route(request.route)
        with self._lock:
            if self._sessions.get(request.session_uuid) is session:
                session.command_one_hot = command
        return common_pb2.Empty()

    def submit_recording_ground_truth(
        self,
        request: egodriver_pb2.GroundTruthRequest,
        context: grpc.ServicerContext,
    ) -> common_pb2.Empty:
        self._get_session(request.session_uuid, context)
        return common_pb2.Empty()

    def drive(
        self,
        request: egodriver_pb2.DriveRequest,
        context: grpc.ServicerContext,
    ) -> egodriver_pb2.DriveResponse:
        session = self._get_session(request.session_uuid, context)
        time_now_us = int(request.time_now_us)
        time_query_us = int(request.time_query_us)
        worker = self._policy_handle.worker()

        with self._lock:
            try:
                current_pose, current_velocity, _ = session.ego_snapshot(time_now_us)
            except LookupError as exc:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
                raise AssertionError("unreachable") from exc

            image_timestamp_us: int | None = None
            inference_input: InferenceInput | None = None
            inference_pose: common_pb2.PoseAtTime | None = None
            try:
                timestamps, frames, padded = session.synchronized_history(time_now_us)
                image_timestamp_us = timestamps[-1]
                inference_pose, velocity, acceleration = session.ego_snapshot(
                    image_timestamp_us
                )
                history_xyh = []
                for ts in timestamps:
                    try:
                        history_xyh.append(_pose_xyh(session.pose_at_or_before(ts)))
                    except LookupError:
                        history_xyh.append(_pose_xyh(inference_pose))
                history_xyh = np.stack(history_xyh, axis=0)
                history_trajectory = convert_absolute_to_relative_se2_array(
                    history_xyh[-1], history_xyh
                ).astype(np.float32)
                ego_status = np.zeros(EGO_STATUS_DIM, dtype=np.float32)
                ego_status[0:4] = session.command_one_hot
                ego_status[4] = float(velocity[0])
                ego_status[5] = float(velocity[1])
                ego_status[6] = float(acceleration[0])
                ego_status[7] = float(acceleration[1])
                if padded:
                    session.counters.padded_history += 1
                inference_input = InferenceInput(
                    history_images=frames,
                    ego_status=ego_status,
                    history_trajectory=history_trajectory,
                )
            except LookupError:
                inference_input = None

            cached_before = session.cached_plan
            timestamp_is_new = image_timestamp_us is not None and (
                session.last_inference_timestamp_us is None
                or image_timestamp_us > session.last_inference_timestamp_us
            )
            should_infer = (
                worker is not None
                and inference_input is not None
                and inference_pose is not None
                and timestamp_is_new
                and session.inference_inflight_timestamp_us is None
            )
            if should_infer:
                session.last_inference_timestamp_us = image_timestamp_us
                session.inference_inflight_timestamp_us = image_timestamp_us
                reserved_timestamp_us = image_timestamp_us
            else:
                reserved_timestamp_us = None

        fresh_plan: CachedPlan | None = None
        inference_error: Exception | None = None
        if reserved_timestamp_us is not None:
            assert worker is not None
            assert inference_input is not None
            assert inference_pose is not None
            try:
                try:
                    prediction = worker.predict(
                        inference_input, timeout=_context_timeout(context)
                    )
                    fresh_plan = make_cached_plan(
                        reserved_timestamp_us,
                        inference_pose,
                        prediction.trajectory,
                    )
                except Exception as exc:
                    inference_error = exc
                    LOGGER.exception(
                        "WA-JEPA inference failed for session %s timestamp_us=%d",
                        request.session_uuid,
                        reserved_timestamp_us,
                    )
            finally:
                with self._lock:
                    if session.inference_inflight_timestamp_us == reserved_timestamp_us:
                        session.inference_inflight_timestamp_us = None

        counter_values: SessionCounters | None = None
        with self._lock:
            active_session = self._sessions.get(request.session_uuid)
            if active_session is session:
                if inference_error is not None:
                    session.counters.inference_error += 1
                if fresh_plan is not None:
                    session.cached_plan = fresh_plan
                    session.counters.wajepa_inference += 1
                response_plan = session.cached_plan
                if fresh_plan is None:
                    if cached_plan_covers_query(
                        response_plan, time_now_us, time_query_us
                    ):
                        session.counters.cached_plan += 1
                    else:
                        session.counters.straight_fallback += 1
                counter_values = SessionCounters(**vars(session.counters))
            else:
                response_plan = fresh_plan if fresh_plan is not None else cached_before

        trajectory = build_trajectory_from_plan(
            response_plan,
            current_pose,
            time_now_us,
            time_query_us,
            fallback_speed_mps=float(np.linalg.norm(current_velocity)),
        )
        if counter_values is not None and fresh_plan is not None:
            LOGGER.info(
                "session=%s wajepa_inference=%d cached_plan=%d straight_fallback=%d "
                "dynamic_state_fallback=%d padded_history=%d inference_error=%d",
                request.session_uuid,
                counter_values.wajepa_inference,
                counter_values.cached_plan,
                counter_values.straight_fallback,
                counter_values.dynamic_state_fallback,
                counter_values.padded_history,
                counter_values.inference_error,
            )
        return egodriver_pb2.DriveResponse(trajectory=trajectory)

    def get_version(
        self,
        request: common_pb2.Empty,
        context: grpc.ServicerContext,
    ) -> common_pb2.VersionId:
        timeout = _context_timeout(context)
        timeout = 30.0 if timeout is None else min(timeout, 30.0)
        if not self._policy_handle.wait_ready(timeout):
            context.abort(
                grpc.StatusCode.UNAVAILABLE, "WA-JEPA policy readiness timed out"
            )
            raise AssertionError("unreachable")
        load_error = self._policy_handle.load_error()
        if load_error is not None:
            context.abort(
                grpc.StatusCode.UNAVAILABLE,
                f"WA-JEPA policy load failed: {load_error}",
            )
            raise AssertionError("unreachable")
        if self._policy_handle.worker() is None:
            context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "WA-JEPA policy reported ready without a batch worker",
            )
            raise AssertionError("unreachable")
        return common_pb2.VersionId(
            version_id=os.environ.get("WAJEPA_SERVICE_VERSION", "wajepa-e2e-local"),
            git_hash=os.environ.get("WAJEPA_GIT_HASH", "local"),
            grpc_api_version=API_VERSION_MESSAGE,
        )

    def stop(self) -> None:
        self._policy_handle.stop()

    def _get_session(
        self, session_uuid: str, context: grpc.ServicerContext
    ) -> SessionState:
        with self._lock:
            session = self._sessions.get(session_uuid)
        if session is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"unknown session {session_uuid}")
            raise AssertionError("unreachable")
        return session


def main() -> None:
    _configure_runtime_write_dirs()
    _configure_torch_threads()
    logging.basicConfig(
        level=os.environ.get("ALPASIM_DRIVER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = os.environ.get("ALPASIM_DRIVER_HOST", "0.0.0.0")
    port = int(os.environ.get("ALPASIM_DRIVER_PORT", "6789"))
    config_path = os.environ.get(
        "WAJEPA_CONFIG", "/app/assets/wajepa/wa_jepa_infer.yaml"
    )
    checkpoint_path = os.environ.get(
        "WAJEPA_CKPT", "/app/assets/wajepa/model_state_dict.pt"
    )
    device = os.environ.get("WAJEPA_DEVICE", "cuda")
    steps_env = os.environ.get("WAJEPA_STEPS", "")
    num_inference_steps = int(steps_env) if steps_env else None
    source_root = os.environ.get("WAJEPA_SOURCE_ROOT", "/app/wajepa_src")
    max_batch_size = int(os.environ.get("WAJEPA_MAX_BATCH_SIZE", "2"))
    batch_window_s = float(os.environ.get("WAJEPA_BATCH_WINDOW_MS", "2")) / 1000.0

    policy_handle = PolicyHandle(
        loader=lambda: WAJEPAPolicy(
            config_path,
            checkpoint_path,
            device=device,
            num_inference_steps=num_inference_steps,
            source_root=source_root,
        ),
        max_batch_size=max_batch_size,
        batch_window_s=batch_window_s,
    )
    service = WAJEPADriver(policy_handle)
    grpc_workers = max(1, int(os.environ.get("ALPASIM_DRIVER_GRPC_WORKERS", "4")))
    server = grpc.server(ThreadPoolExecutor(max_workers=grpc_workers))
    egodriver_pb2_grpc.add_EgodriverServiceServicer_to_server(service, server)
    bound_port = server.add_insecure_port(f"{host}:{port}")
    if bound_port == 0:
        server.stop(grace=0.0)
        service.stop()
        raise RuntimeError(f"failed to bind {host}:{port}")

    def request_stop(signum: int, frame: object) -> None:
        LOGGER.info("received signal %s, stopping", signum)
        server.stop(grace=0.0)
        service.stop()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        server.start()
        LOGGER.info(
            "WA-JEPA driver listening on %s:%d (steps=%s batch=%d)",
            host,
            bound_port,
            steps_env or "config-default",
            max_batch_size,
        )
        policy_handle.start()
        server.wait_for_termination()
    finally:
        server.stop(grace=0.0)
        service.stop()


if __name__ == "__main__":
    main()
