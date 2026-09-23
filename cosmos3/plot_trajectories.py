"""Plot saved Cosmos/AlpaSim trajectories on CPU; never runs a policy or eval.

Use the existing AlpaSim .venv (protobuf, numpy, scipy, pandas, matplotlib).
Coordinates are rear-axle poses in an initial-ego-aligned frame. Saved scorer
distances, shown separately, measure box-centre distance instead.
"""
import argparse
import csv
import json
from pathlib import Path
import struct

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation
import yaml

from alpasim_grpc.v0.logging_pb2 import LogEntry
from alpasim_grpc.v0.common_pb2 import Trajectory
from google.protobuf.json_format import ParseDict


def pose_matrix(pose):
    result = np.eye(4)
    result[:3, :3] = Rotation.from_quat(
        [pose.quat.x, pose.quat.y, pose.quat.z, pose.quat.w]
    ).as_matrix()
    result[:3, 3] = [pose.vec.x, pose.vec.y, pose.vec.z]
    return result


def trajectory_arrays(trajectory):
    return (
        np.array([p.timestamp_us for p in trajectory.poses], dtype=np.int64),
        np.array([pose_matrix(p.pose) for p in trajectory.poses]),
    )


def read_asl(path):
    retained = {k: [] for k in (
        "rollout_metadata", "actor_poses", "controller_request", "driver_return"
    )}
    with path.open("rb") as stream:
        while prefix := stream.read(4):
            if len(prefix) != 4:
                raise ValueError("Truncated ASL length")
            size = struct.unpack(">L", prefix)[0]
            if size > 100_000_000:
                raise ValueError("Unexpectedly large ASL entry")
            payload = stream.read(size)
            if len(payload) != size:
                raise ValueError("Truncated ASL entry")
            entry = LogEntry.FromString(payload)
            kind = entry.WhichOneof("log_entry")
            if kind in retained:
                retained[kind].append(getattr(entry, kind))
    return retained


def arc_length(xy):
    return float(np.linalg.norm(np.diff(xy, axis=0), axis=1).sum())


def main(artifacts):
    manifest = json.loads((artifacts / "run-summary.json").read_text())
    driver = json.loads((artifacts / "driver-summary.json").read_text())
    run = Path(manifest["run_directory"])
    logs = list(run.glob("rollouts/*/*/rollout.asl"))
    assert len(logs) == 1, "This plotter expects one saved compatibility rollout"
    entries = read_asl(logs[0])
    assert len(entries["rollout_metadata"]) == 1
    metadata = entries["rollout_metadata"][0]
    gt_t, gt_poses = trajectory_arrays(metadata.ego_rig_recorded_ground_truth_trajectory)
    aabb_to_rig = np.linalg.inv(pose_matrix(metadata.transform_ego_coords_rig_to_aabb))
    actual = {}
    for entry in entries["actor_poses"]:
        for actor in entry.actor_poses:
            if actor.actor_id == "EGO":
                actual[entry.timestamp_us] = pose_matrix(actor.actor_pose) @ aabb_to_rig
    actual_t = np.array(sorted(actual), dtype=np.int64)
    actual_poses = np.array([actual[t] for t in actual_t])
    assert np.all(np.diff(actual_t) > 0)
    origin_inverse = np.linalg.inv(actual_poses[0])

    def xy(poses):
        return (origin_inverse @ poses)[:, :2, 3]

    gt_xy, actual_xy = xy(gt_poses), xy(actual_poses)
    predictions = sorted(artifacts.glob("prediction-*.json"))
    controllers, returns = entries["controller_request"], entries["driver_return"]
    assert len(predictions) == len(controllers) == len(returns) == len(driver["requests"])
    plans, rows = [], []
    for index, (path, ctrl, response, request) in enumerate(
        zip(predictions, controllers, returns, driver["requests"]), 1
    ):
        saved = json.loads(path.read_text())
        times, matrices = trajectory_arrays(ParseDict(saved["returned_trajectory"], Trajectory()))
        asl_times, asl_matrices = trajectory_arrays(response.trajectory)
        np.testing.assert_array_equal(times, asl_times)
        np.testing.assert_allclose(matrices, asl_matrices, atol=1e-5, rtol=0)
        assert len(times) == 41 and np.all(np.diff(times) == 100_000)
        assert times[0] == ctrl.state.timestamp_us == request["time_now_us"]
        # Runtime transforms estimated-local plans into the current true rig
        # frame. Reproduce that anchoring, then verify against the logged input
        # to the controller. No plotting-only alignment to future ground truth.
        relative = np.linalg.inv(matrices[0]) @ matrices
        anchored = pose_matrix(ctrl.state.pose) @ relative
        ct, cm = trajectory_arrays(ctrl.planned_trajectory_in_rig)
        priming = times[0] < metadata.session_metadata.start_timestamp_us + metadata.force_gt_duration
        controller_error = None
        if not priming:
            np.testing.assert_array_equal(ct, times)
            np.testing.assert_allclose(cm, relative, atol=2e-5, rtol=0)
            controller_error = float(np.abs(cm - relative).max())
        plan_xy = xy(anchored)
        plan_speeds = np.linalg.norm(np.diff(plan_xy, axis=0), axis=1) / (np.diff(times) / 1e6)
        plans.append((times, plan_xy, priming))
        rows.append({
            "call": index, "time_s": float(times[0] / 1e6),
            "used_by_controller": not priming,
            "observed_speed_mps": request["observed_speed_mps"],
            "plan_first_100ms_speed_mps": float(plan_speeds[0]),
            "plan_4s_mean_speed_mps": float(plan_speeds.mean()),
            "plan_4s_path_length_m": arc_length(plan_xy),
            "plan_4s_displacement_m": float(np.linalg.norm(plan_xy[-1] - plan_xy[0])),
            "controller_vs_relative_plan_max_matrix_difference": controller_error,
        })

    metrics = pd.read_parquet(logs[0].with_name("metrics.parquet"))

    def metric(name):
        return metrics.loc[metrics.name.eq(name)].sort_values("timestamps_us")

    lateral = metric("lateral_dist_to_gt_trajectory")
    failed = metric("left_corridor_laterally")
    failed = failed.loc[failed.valid.astype(bool) & failed["values"].ge(1)]
    exit_us = int(failed.timestamps_us.iloc[0]) if len(failed) else None
    config = yaml.safe_load((run / "eval-config.yaml").read_text())
    corridor = float(config["aggregation_modifiers"]["max_dist_to_gt_trajectory"])
    priming_end_s = controllers[1].state.timestamp_us / 1e6 if plans[0][2] else 0
    summary = json.loads((run / "aggregate/results-summary.json").read_text())["rollouts"][0]
    report = {
        "source_asl": str(logs[0].resolve()), "scene": manifest["scene"],
        "method": "Read saved predictions, ASL poses and existing metrics; no inference or evaluator run.",
        "plot_frame": "Initial rear-axle pose; x forward, y left. ASL AABB poses converted to rear axle.",
        "scorer_frame": "Saved lateral-distance metric measures box centres, not rear axles.",
        "saved_predictions": len(plans),
        "plans_used_by_controller": sum(not p[2] for p in plans),
        "priming_end_s": priming_end_s,
        "first_recorded_corridor_exit_s": exit_us / 1e6 if exit_us is not None else None,
        "saved_corridor_threshold_m": corridor,
        "lateral_distance_at_first_exit_m": float(lateral.loc[lateral.timestamps_us.eq(exit_us), "values"].iloc[0]) if exit_us is not None else None,
        "full_run_last_lateral_distance_m": float(lateral["values"].iloc[-1]),
        "full_run_end_s": float(actual_t[-1] / 1e6),
        "full_run_rear_axle_sampled_path_length_m": arc_length(actual_xy),
        "saved_scene_score": summary["score"],
        "saved_aggregate_dist_to_gt_trajectory_m": summary["metrics"]["dist_to_gt_trajectory"],
        "per_plan": rows,
        "cautions": [
            "First Cosmos prediction is generated during GT priming and is not executed.",
            "Each later prediction is replanned after 0.5 s; its full 4 s path is not executed.",
            "GT beyond the simulation end is shown dashed; no GT is extrapolated past the recording.",
            "Actual path connects logged poses at 0.5 s spacing, not an exact continuous trace.",
            "One image-only development scene; does not isolate checkpoint, conditioning, adapter or controller causes.",
        ],
    }
    output = artifacts / "plots"
    output.mkdir(exist_ok=True)
    (output / "trajectory-diagnostics.json").write_text(json.dumps(report, indent=2) + "\n")
    with (output / "per-plan.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    colors = plt.get_cmap("tab10")(np.arange(len(plans)))
    gt_color, actual_color, exit_color = "#166534", "#111827", "#dc2626"
    legend = [Line2D([], [], color=gt_color, lw=2.5, label="Recorded reference"),
              Line2D([], [], color=actual_color, lw=2.5, marker="o", ms=4, label="Actual driven path"),
              Line2D([], [], color="#7c3aed", lw=1.5, label="Cosmos 4 s plans (numbered)"),
              Line2D([], [], color=exit_color, marker="X", ls="", ms=8, label="First scored corridor exit")]

    def base_map(ax):
        until = gt_t <= actual_t[-1]
        reference_end = np.array([np.interp(actual_t[-1], gt_t, gt_xy[:, j]) for j in range(2)])
        during = np.vstack([gt_xy[until], reference_end])
        after = np.vstack([reference_end, gt_xy[~until]])
        ax.plot(during[:, 0], during[:, 1], color=gt_color, lw=2.6, zorder=3)
        ax.plot(after[:, 0], after[:, 1], color=gt_color, lw=2, ls="--", alpha=.6)
        ax.plot(actual_xy[:, 0], actual_xy[:, 1], "o-", color=actual_color, ms=3.5, lw=2.3, zorder=5)
        if exit_us is not None:
            pos = actual_xy[np.flatnonzero(actual_t == exit_us)[0]]
            ax.scatter(*pos, color=exit_color, marker="X", s=100, zorder=8)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel("Forward from initial pose (m)")
        ax.set_ylabel("Left from initial pose (m)")
        ax.grid(alpha=.18)

    fig = plt.figure(figsize=(15, 9.5), layout="constrained")
    grid = fig.add_gridspec(2, 2, height_ratios=[1.4, 1])
    ax = fig.add_subplot(grid[0, :])
    base_map(ax)
    for i, ((_, points, priming), color) in enumerate(zip(plans, colors), 1):
        ax.plot(points[:, 0], points[:, 1], color=color, lw=1.6, alpha=.8, ls="--" if priming else "-")
        ax.scatter(*points[-1], color=color, s=22)
        ax.annotate(str(i), points[-1], xytext=(3, 5 if i % 2 else -11), textcoords="offset points", color=color, weight="bold")
    ax.legend(handles=legend, loc="upper center", ncol=4, frameon=False, fontsize=9)
    ax.set_title("Top-down paths | Numbers mark ends of predicted horizons, not driven endpoints", loc="left", fontsize=11)
    ax.margins(x=.04, y=.23)

    speed_ax = fig.add_subplot(grid[1, 0])
    seconds = np.array([r["time_s"] for r in rows])
    speed_ax.plot(seconds, [r["observed_speed_mps"] for r in rows], "o-", color=actual_color, label="Observed ego speed at each call")
    speed_ax.plot(seconds, [r["plan_first_100ms_speed_mps"] for r in rows], "s--", color="#7c3aed", label="Speed implied by first 0.1 s of plan")
    speed_ax.set(xlabel="Simulation time (s)", ylabel="Speed (m/s)", title="Plans start much slower than the moving vehicle")
    speed_ax.legend(fontsize=9, frameon=False)

    lat_ax = fig.add_subplot(grid[1, 1])
    lat_ax.plot(lateral.timestamps_us / 1e6, lateral["values"], "o-", color=actual_color)
    lat_ax.axhline(corridor, color=exit_color, ls="--", label=f"Saved local threshold: {corridor:g} m")
    if exit_us is not None:
        lat_ax.axvline(exit_us / 1e6, color=exit_color, ls=":", label=f"First flagged sample: {exit_us / 1e6:.3f} s")
    lat_ax.set(xlabel="Simulation time (s)", ylabel="Box-centre distance to reference (m)", title="Saved scorer: corridor exit, followed by further drift")
    lat_ax.legend(fontsize=9, frameon=False, loc="upper left")
    for panel in (speed_ax, lat_ax):
        panel.axvspan(0, priming_end_s, color="#94a3b8", alpha=.15)
        panel.set_xlim(0, actual_t[-1] / 1e6 + .1)
        panel.grid(alpha=.18)
    fig.suptitle("Cosmos3-Edge | Saved one-scene compatibility run\n10 predictions; 9 used after GT priming. No inference or evaluation rerun.", fontsize=15, weight="bold")
    fig.supxlabel("Top-down plots use rear-axle poses; scorer uses box centres. Shaded time = GT priming.\nDashed reference tail is beyond simulation end. Each plan is replaced after 0.5 s.", fontsize=9)
    for suffix in ("png", "svg"):
        fig.savefig(output / f"trajectory-overview.{suffix}", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(2, 5, figsize=(18, 8.6), layout="constrained")
    for i, (panel, (times, points, priming), color, row) in enumerate(zip(axes.flat, plans, colors, rows), 1):
        # Global aligned coordinates, zoomed consistently across the ten calls.
        base_map(panel)
        panel.plot(points[:, 0], points[:, 1], color=color, lw=2, ls="--" if priming else "-", zorder=6)
        panel.scatter(*points[0], color=color, marker="s", s=32, zorder=7)
        panel.scatter(*points[-1], color=color, marker="^", s=35, zorder=7)
        segment = (actual_t >= times[0]) & (actual_t <= times[0] + 500_000)
        panel.plot(actual_xy[segment, 0], actual_xy[segment, 1], color="#f97316", lw=4, zorder=6)
        status = "not executed (GT priming)" if priming else "used for next 0.5 s"
        panel.set_title(f"#{i} at {times[0] / 1e6:.3f} s\n{status}\n4 s plan length: {row['plan_4s_path_length_m']:.1f} m", fontsize=10, color=color)
        panel.set_xlim(-1, 35)
        panel.set_ylim(-18, 5)
        panel.tick_params(labelsize=8)
        panel.set_xlabel("Forward (m)", fontsize=9)
        panel.set_ylabel("Left (m)", fontsize=9)
    fig.suptitle("All 10 saved Cosmos plans | Same coordinate frame and zoom", fontsize=16, weight="bold")
    fig.supxlabel("Green: reference. Black: entire driven path. Coloured: predicted 4 s path (square start, triangle end).\nOrange: actual next 0.5 s. Red X: first scored corridor exit. Reference continues beyond this 35 m zoom.", fontsize=11)
    for suffix in ("png", "svg"):
        fig.savefig(output / f"all-ten-plans.{suffix}", dpi=180)
    plt.close(fig)
    print(json.dumps(report, indent=2))
    print(f"Plots saved under {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    main(parser.parse_args().artifacts.resolve())
