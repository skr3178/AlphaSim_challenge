"""Plot saved ablation predictions and losses; no model calls or optimization."""

import json

import numpy as np

from cosmos3.ablation_scope import RUN
from cosmos3.training.contracts import file_hash
from cosmos3.training.dataset import read_npz


def main():
    output = RUN / "plots"
    if output.exists():
        raise ValueError("Refusing to overwrite diagnostic plots")
    summary = json.loads((RUN / "evaluation-result/summary.json").read_text())
    prediction_file = RUN / "evaluation-result/predictions.npz"
    if file_hash(prediction_file) != summary["predictions_sha256"]:
        raise ValueError("Saved prediction hash changed")
    data = read_npz(prediction_file)
    for arm, digest in summary["training_report_hashes"].items():
        if file_hash(RUN / "fits" / arm / "training.json") != digest:
            raise ValueError("Training report changed")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output.mkdir()
    colors = {
        "cosmos": "#2376ae",
        "state_route_only": "#d27313",
        "constant_velocity": "#888888",
    }
    labels = {
        "cosmos": "Cosmos + state/route",
        "state_route_only": "State/route only",
        "constant_velocity": "Causal constant velocity",
    }
    fig, axes = plt.subplots(3, 3, figsize=(13, 12))
    for i, ax in enumerate(axes.flat):
        valid = data["target_mask"][i]
        target = data["targets"][i, valid]
        ax.plot(
            target[:, 0],
            target[:, 1],
            color="black",
            linewidth=2,
            label="Recorded target",
        )
        for arm in colors:
            pred = data[arm][i, valid]
            ax.plot(
                pred[:, 0],
                pred[:, 1],
                color=colors[arm],
                linestyle="--" if arm == "constant_velocity" else "-",
                label=labels[arm],
            )
        row = summary["per_scene"][i]
        ax.set(
            title=f"{i+1}. {row['city']} — unseen log\nADE: Cosmos {row['cosmos']['ade_m']:.2f} / state-route {row['state_route_only']['ade_m']:.2f} m",
            xlabel="Forward (m)",
            ylabel="Left (m)",
        )
        ax.scatter([0], [0], s=12, color="green")
        ax.axis("equal")
        ax.grid(alpha=0.2)
    handles, legend = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, legend, loc="lower center", ncol=4)
    fig.suptitle(
        "Nine unseen-log examples: open-loop predictions, not executed vehicle paths",
        fontsize=14,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.96))
    fig.savefig(output / "unseen-log-trajectories.png", dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for arm in ("cosmos", "state_route_only"):
        report = json.loads((RUN / "fits" / arm / "training.json").read_text())
        axes[0].plot(
            [0] + [r["step"] for r in report["updates"]],
            [report["initial_training_loss"]] + [r["loss"] for r in report["updates"]],
            color=colors[arm],
            label=labels[arm],
        )
        axes[0].scatter([100], [report["final_training_loss"]], color=colors[arm], s=20)
    axes[0].set(
        xlabel="Optimizer update",
        ylabel="Training loss",
        title="Matched 100-update fits",
        yscale="log",
    )
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.2)
    names = list(colors)
    axes[1].bar(
        ["Cosmos", "State/route", "Constant\nvelocity"],
        [summary["metrics"][a]["ade_m"] for a in names],
        color=[colors[a] for a in names],
    )
    axes[1].set(
        ylabel="Average position error (m), lower is better",
        title="Nine unseen source logs",
    )
    fig.tight_layout()
    fig.savefig(output / "matched-comparison.png", dpi=160)
    plt.close(fig)
    print(output)


if __name__ == "__main__":
    main()
