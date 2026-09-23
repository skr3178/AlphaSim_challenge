"""Cosmos AV camera deltas -> AlpaSim local rig poses (compatibility only).

Uses the pinned NVIDIA decoder, not an inferred normalization scheme.
See COMPATIBILITY.md for source revisions and the explicit planar projection.
"""
import numpy as np
from scipy.spatial.transform import Rotation

from vendor.pose_utils import pose_rel_to_abs

AV_TRANSLATION_SCALE = 1.35


def validate_timestamps(ego_time, image_start, image_end, now, query):
    """The policy tick occurs when the current camera exposure has finished."""
    if ego_time != now:
        raise ValueError("Ego pose timestamp does not match Drive time")
    if image_end != now or not 0 <= image_end - image_start <= 100_000:
        raise ValueError("Front image exposure end does not match Drive time")
    if not now <= query <= now + 4_000_000:
        raise ValueError("Control query is outside the predicted horizon")


def pose_matrix(pose):
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_quat(
        [pose.quat.x, pose.quat.y, pose.quat.z, pose.quat.w]
    ).as_matrix()
    matrix[:3, 3] = [pose.vec.x, pose.vec.y, pose.vec.z]
    return matrix


def decode_rig_poses(actions, camera_in_rig, rig_in_local):
    """Return full SE(3) poses before any controller-specific projection.

    camera_in_rig is the sensor2ego transform, despite the protobuf field
    being named rig_to_camera. This follows MTGS artifact_adapter.py.
    """
    actions = np.asarray(actions, dtype=np.float64)
    if actions.ndim != 2 or actions.shape[1] != 9 or len(actions) < 2:
        raise ValueError(f"Expected N x 9 actions, got {actions.shape}")
    if not np.isfinite(actions).all():
        raise ValueError("Nonfinite Cosmos actions")
    for col0, col1 in zip(actions[:, 3:6], actions[:, 6:9]):
        if np.linalg.norm(col0) < 1e-6 or np.linalg.norm(np.cross(col0, col1)) < 1e-6:
            raise ValueError("Degenerate rot6d output; no fallback permitted")
    camera_relative = pose_rel_to_abs(
        actions, rotation_format="rot6d", pose_convention="backward_framewise",
        translation_scale=AV_TRANSLATION_SCALE, normalize_rotation=True,
    )
    poses = rig_in_local @ camera_in_rig @ camera_relative @ np.linalg.inv(camera_in_rig)
    if not np.isfinite(poses).all():
        raise ValueError("Nonfinite decoded poses")
    return poses


def build_trajectory(actions, calibration, latest_pose, time_now_us):
    from alpasim_grpc.v0 import common_pb2

    full_poses = decode_rig_poses(actions, pose_matrix(calibration), pose_matrix(latest_pose.pose))
    trajectory = common_pb2.Trajectory()
    for i, matrix in enumerate(full_poses):
        yaw = np.arctan2(matrix[1, 0], matrix[0, 0])
        # Driving controller is planar: preserve decoded x/y/yaw, hold ground z.
        # No progress/speed/corridor correction and no straight-line fallback.
        trajectory.poses.add(
            timestamp_us=time_now_us + i * 100_000,
            pose=common_pb2.Pose(
                vec=common_pb2.Vec3(x=float(matrix[0, 3]), y=float(matrix[1, 3]), z=latest_pose.pose.vec.z),
                quat=common_pb2.Quat(z=float(np.sin(yaw / 2)), w=float(np.cos(yaw / 2))),
            ),
        )
    return trajectory, full_poses
