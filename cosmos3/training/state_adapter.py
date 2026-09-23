"""Causal received-pose ego state; shared by export and future driver integration.

Never use recorded future targets, nominal GT derivatives, or guessed rotations
of ambiguous legacy DynamicState fields. This is an interval-average estimator,
not a certified instantaneous state estimator.
"""

import numpy as np
from scipy.spatial.transform import Rotation

STATE_RECIPE = "received-pose-backward-difference-current-rig-v1"


def received_pose_state(poses, time_us):
    if time_us not in poses:
        raise ValueError("Missing current received ego pose")
    earlier = [t for t in poses if t < time_us]
    if not earlier:
        raise ValueError("No past received pose for causal state")
    before = max(earlier)
    dt = (time_us - before) / 1e6
    if not 0.01 <= dt <= 0.6:
        raise ValueError("Received-pose interval too short or across a gap")
    previous, current = np.asarray(poses[before]), np.asarray(poses[time_us])
    for pose in (previous, current):
        if (
            pose.shape != (4, 4)
            or not np.isfinite(pose).all()
            or not np.allclose(pose[3], [0, 0, 0, 1], atol=1e-6)
            or not np.allclose(pose[:3, :3].T @ pose[:3, :3], np.eye(3), atol=1e-5)
            or not np.isclose(np.linalg.det(pose[:3, :3]), 1, atol=1e-5)
        ):
            raise ValueError("Invalid received rigid pose")
    velocity = current[:3, :3].T @ (current[:3, 3] - previous[:3, 3]) / dt
    # The rotation-vector axis is invariant under its own relative rotation;
    # this expresses interval angular velocity in the current body frame.
    omega = Rotation.from_matrix(previous[:3, :3].T @ current[:3, :3]).as_rotvec() / dt
    state = np.array([velocity[0], velocity[1], omega[2]], dtype=np.float32)
    if (
        not np.isfinite(state).all()
        or np.linalg.norm(state[:2]) > 80
        or abs(state[2]) > 3
    ):
        raise ValueError("Nonfinite or implausible causal state; no silent fallback")
    return state, {
        "recipe": STATE_RECIPE,
        "previous_received_timestamp_us": int(before),
        "current_received_timestamp_us": int(time_us),
        "interval_seconds": dt,
        "past_and_current_received_poses_only": True,
    }
