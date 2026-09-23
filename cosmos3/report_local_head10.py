"""Plot and summarize saved local training results; never evaluates the simulator."""

import argparse
import json
from pathlib import Path

import numpy as np

from cosmos3.training.contracts import file_hash, write_json, pose_matrix
from cosmos3.training.dataset import DrivingDataset, read_npz
from cosmos3.training.export_asl import entries

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "cosmos3/artifacts/local-only-head10-v1"
PILOT = ROOT / "cosmos3/pilots/local-head10-v1/manifest.json"


def errors(predictions, targets, mask):
    xy = predictions[..., :2] - targets[..., :2]
    distances = np.linalg.norm(xy, axis=-1)
    return {
        "ade_m": float(distances[mask].mean()),
        "fde_4s_m": float(distances[:, -1][mask[:, -1]].mean()),
        "lateral_mae_m": float(np.abs(xy[..., 1][mask]).mean()),
        "longitudinal_mae_m": float(np.abs(xy[..., 0][mask]).mean()),
    }


def pose_velocity(past_poses, time_us):
    """Velocity from two received poses only, never future targets or raw dynamics."""
    if time_us not in past_poses:
        raise ValueError("Missing current received pose")
    previous = [t for t in past_poses if t < time_us]
    if not previous:
        raise ValueError("No past received pose for causal baseline")
    before = max(previous)
    dt = (time_us - before) / 1e6
    if not 0.01 <= dt <= 0.6:
        raise ValueError("Pose difference interval too short or across a gap")
    current = past_poses[time_us]
    velocity = current[:3, :3].T @ (current[:3, 3] - past_poses[before][:3, 3]) / dt
    if not np.isfinite(velocity).all():
        raise ValueError("Nonfinite causal pose velocity")
    return velocity[:2], dt


def causal_state_diagnostic(data):
    result = []
    for sample, (inputs, _) in zip(data.samples, data.items):
        source = next(
            row
            for row in data.manifest["sources"]
            if row["scene_id"] == sample["scene_id"]
        )
        if file_hash(source["path"]) != source["sha256"]:
            raise ValueError("Saved ASL changed")
        poses = {}
        for kind, value in entries(Path(source["path"])):
            if kind == "driver_ego_trajectory":
                poses.update(
                    {
                        int(p.timestamp_us): pose_matrix(p.pose)
                        for p in value.trajectory.poses
                        if p.timestamp_us <= sample["time_us"]
                    }
                )
            elif kind == "driver_request" and value.time_now_us == sample["time_us"]:
                break
        velocity, dt = pose_velocity(poses, sample["time_us"])
        result.append(
            {
                "scene_id": sample["scene_id"],
                "logged_velocity_xy_mps": inputs["ego_state"][:2].tolist(),
                "causal_pose_velocity_xy_mps": velocity.tolist(),
                "pose_interval_seconds": dt,
                "difference_mps": float(
                    np.linalg.norm(velocity - inputs["ego_state"][:2])
                ),
            }
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RUN / "diagnostics")
    args = parser.parse_args()
    data = DrivingDataset(RUN / "samples-route-mask-v2/dataset.json", PILOT)
    report = json.loads((RUN / "head/training.json").read_text())
    if (
        report.get("status") != "completed"
        or report.get("submission_allowed") is not False
    ):
        raise ValueError("Need a completed local-only training result")
    if report["dataset_sha256"] != file_hash(data.path):
        raise ValueError("Training dataset changed")
    path = RUN / "head/training_predictions.npz"
    if file_hash(path) != report["training_predictions_sha256"]:
        raise ValueError("Predictions changed")
    if report["training_prediction_sample_ids"] != [
        s["sample_id"] for s in data.samples
    ]:
        raise ValueError("Prediction/sample ordering changed")
    arrays = read_npz(path)
    predictions, targets, mask = (
        arrays["predictions"],
        arrays["targets"],
        arrays["target_mask"],
    )
    state_diagnostics = causal_state_diagnostic(data)
    baseline = (
        np.array([row["causal_pose_velocity_xy_mps"] for row in state_diagnostics])[
            :, None, :
        ]
        * np.arange(1, 41)[None, :, None]
        * 0.1
    )
    baseline4 = np.zeros_like(predictions)
    baseline4[..., :2] = baseline
    baseline4[..., 3] = 1
    per_sample = []
    for index, sample in enumerate(data.samples):
        sl = slice(index, index + 1)
        row = next(
            r for r in data.pilot["samples"] if r["scene_id"] == sample["scene_id"]
        )
        per_sample.append(
            {
                "scene_id": sample["scene_id"],
                "city": row["city"],
                "head": errors(predictions[sl], targets[sl], mask[sl]),
                "constant_velocity": errors(baseline4[sl], targets[sl], mask[sl]),
            }
        )
    result = {
        "interpretation": "Ten training examples only; no held-out/generalization, Indian-road, closed-loop or leaderboard claim",
        "samples": len(data),
        "head": errors(predictions, targets, mask),
        "constant_velocity_from_past_received_poses_no_fit": errors(
            baseline4, targets, mask
        ),
        "state_diagnostics": state_diagnostics,
        "logged_vs_pose_velocity_discrepancies_over_1mps": sum(
            row["difference_mps"] > 1 for row in state_diagnostics
        ),
        "state_contract_warning": "The logged dynamic states were consumed directly as rig-frame velocity. Their mismatch with causal received-pose motion needs diagnosis/correction before further fitting or deployment. No frame rotation was guessed and no extra optimizer steps were run.",
        "per_sample": per_sample,
        "submission_allowed": False,
        "training_report_sha256": file_hash(RUN / "head/training.json"),
    }
    output = args.output
    output.mkdir(exist_ok=False)
    write_json(output / "summary.json", result)

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(
        [0] + [r["step"] for r in report["updates"]],
        [report["initial_training_loss"]] + [r["loss"] for r in report["updates"]],
    )
    ax.scatter(
        [report["optimizer_steps"]],
        [report["final_training_loss"]],
        color="black",
        label="Final post-update loss",
    )
    ax.set(
        xlabel="Head optimizer update",
        ylabel="Training loss",
        title="Local-only ten-example head fit (not validation)",
    )
    ax.set_yscale("log")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / "training-loss.png", dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(2, 5, figsize=(16, 7))
    for index, ax in enumerate(axes.flat):
        valid = mask[index]
        ax.plot(
            targets[index, valid, 0],
            targets[index, valid, 1],
            color="black",
            label="Recorded target",
        )
        ax.plot(
            predictions[index, valid, 0],
            predictions[index, valid, 1],
            color="#1479b8",
            label="Fitted head",
        )
        ax.plot(
            baseline[index, valid, 0],
            baseline[index, valid, 1],
            color="#999999",
            linestyle="--",
            label="Causal pose-based constant velocity",
        )
        ax.scatter([0], [0], color="#14823b", s=12)
        ax.set(
            title=f"{index+1}: {per_sample[index]['city']}\nADE {per_sample[index]['head']['ade_m']:.2f} m",
            xlabel="Forward (m)",
            ylabel="Left (m)",
        )
        ax.axis("equal")
        ax.grid(alpha=0.2)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3)
    fig.suptitle(
        "Predictions on the ten training examples — not closed-loop driving",
        fontsize=14,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(output / "training-trajectories.png", dpi=150)
    plt.close(fig)
    print(
        json.dumps(
            {
                "output": str(output),
                "head": result["head"],
                "constant_velocity_from_received_poses": result[
                    "constant_velocity_from_past_received_poses_no_fit"
                ],
                "state_input_discrepancies": result[
                    "logged_vs_pose_velocity_discrepancies_over_1mps"
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
