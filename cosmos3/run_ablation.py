"""Bounded local stages: corrected export, frozen cache, two fits, one evaluation.

No renderer, simulator evaluation, network access, backbone optimizer or automatic
hyperparameter search. Each stage refuses overwrite. Evaluation occurs only after
both fixed-budget checkpoints exist and never feeds back into fitting.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from cosmos3.ablation_scope import ASL_ROOT, PILOT, RUN
from cosmos3.training.contracts import (
    file_hash,
    load_pilot,
    require_run_authorization,
    write_json,
)
from cosmos3.training.dataset import CachedDrivingDataset, DrivingDataset

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def require_role(data, pilot, role):
    actual = [s["scene_id"] for s in data.samples]
    if actual != pilot[f"{role}_scene_ids"] or len(actual) != len(set(actual)):
        raise ValueError(f"Dataset is not the exact ordered {role} split")


class FeatureArm:
    """Remove visual values only; architecture, masks and other inputs unchanged."""

    def __init__(self, data, arm):
        if arm not in ("cosmos", "state_route_only"):
            raise ValueError("Unknown fixed ablation arm")
        self.data, self.arm = data, arm

    def __len__(self):
        return len(self.data)

    def batch(self, indices, device="cpu"):
        import torch

        inputs, targets = self.data.batch(indices, device)
        if self.arm == "state_route_only":
            inputs["features"] = torch.zeros_like(inputs["features"])
        return inputs, targets


def state_hash(model):
    digest = hashlib.sha256()
    for name, value in model.state_dict().items():
        digest.update(name.encode())
        digest.update(value.detach().cpu().numpy().tobytes())
    return digest.hexdigest()


def export_stage(pilot):
    from cosmos3.training.export_asl import export

    if RUN.exists():
        raise ValueError("Refusing to overwrite ablation artifacts")
    RUN.mkdir(parents=True)
    for role in ("training", "evaluation"):
        paths = []
        for scene in pilot[f"{role}_scene_ids"]:
            candidates = sorted((ASL_ROOT / scene).glob("*/rollout.asl"))
            if not candidates:
                raise ValueError(f"Missing selected ASL: {scene}")
            paths.append(candidates[0])
        result = export(
            PILOT, paths, RUN / role / "samples", None, len(paths), local_only=True
        )
        data = DrivingDataset(result["dataset"], PILOT)
        require_role(data, pilot, role)
        print(json.dumps({"role": role, **result}), flush=True)


def data_for(role):
    return CachedDrivingDataset(
        RUN / role / "samples/dataset.json", RUN / role / "features/cache.json", PILOT
    )


def audit_stage(pilot):
    """Data-quality audit only; no model outcomes or split selection."""
    rows = []
    for role in ("training", "evaluation"):
        data = DrivingDataset(RUN / role / "samples/dataset.json", PILOT)
        require_role(data, pilot, role)
        for sample, (inputs, targets) in zip(data.samples, data.items):
            state = inputs["ego_state"]
            # Future targets are a diagnostic cross-check ONLY, never state inputs.
            reference_interval_velocity = targets["waypoints"][0, :2] / 0.1
            reference_interval_yaw_rate = float(
                np.arctan2(targets["waypoints"][0, 2], targets["waypoints"][0, 3]) / 0.1
            )
            rows.append(
                {
                    "role": role,
                    "scene_id": sample["scene_id"],
                    **sample["ego_state_provenance"],
                    "first_target_interval_velocity_xy_mps_diagnostic_only": reference_interval_velocity.tolist(),
                    "past_vs_next_interval_velocity_difference_mps": float(
                        np.linalg.norm(state[:2] - reference_interval_velocity)
                    ),
                    "past_vs_next_interval_yaw_rate_difference_radps": abs(
                        float(state[2]) - reference_interval_yaw_rate
                    ),
                    "history_mask": inputs["history_mask"].tolist(),
                }
            )
    result = {
        "mode": "data_consistency_only_no_model_or_training",
        "recipe": pilot["ego_state_recipe"],
        "samples": rows,
        "pilot_sha256": file_hash(PILOT),
        "dataset_hashes": {
            role: file_hash(RUN / role / "samples/dataset.json")
            for role in ("training", "evaluation")
        },
        "legacy_velocity_discrepancies_over_1mps": sum(
            r["velocity_difference_mps"] > 1 for r in rows
        ),
        "max_past_vs_next_interval_velocity_difference_mps": max(
            r["past_vs_next_interval_velocity_difference_mps"] for r in rows
        ),
        "max_past_vs_next_interval_yaw_rate_difference_radps": max(
            r["past_vs_next_interval_yaw_rate_difference_radps"] for r in rows
        ),
        "caveat": "Past-pose interval estimate; not a certified instantaneous sensor state. Future-label derivatives appear in this report only and never enter exported inputs or feature caches. Exact legacy-runtime cause remains unresolved.",
    }
    write_json(RUN / "state-audit.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, indent=2))


def cache_stage(pilot):
    from cosmos3.profile_edge import CHECKPOINT
    from cosmos3.training.runner import cache_features

    for role in ("training", "evaluation"):
        dataset = RUN / role / "samples/dataset.json"
        require_role(DrivingDataset(dataset, PILOT), pilot, role)
        result = cache_features(
            PILOT,
            dataset,
            CHECKPOINT,
            RUN / role / "features",
            None,
            device="cuda",
            max_seconds=600,
            local_only=True,
        )
        print(json.dumps({"role": role, **result}), flush=True)


def fit_stage(pilot):
    import torch
    from safetensors.torch import load_file, save_file

    from cosmos3.training.head import WaypointHead
    from cosmos3.training.runner import fit_head

    require_run_authorization(PILOT, None, local_only=True)
    audit = json.loads((RUN / "state-audit.json").read_text())
    if audit["pilot_sha256"] != file_hash(PILOT) or any(
        file_hash(RUN / role / "samples/dataset.json") != digest
        for role, digest in audit["dataset_hashes"].items()
    ):
        raise ValueError("Data-quality audit is missing or stale")
    data = data_for("training")  # Evaluation samples/labels are never loaded here.
    require_role(data.dataset, pilot, "training")
    protocol = pilot["ablation"]
    output = RUN / "fits"
    output.mkdir(exist_ok=False)
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    first_initial_hash = None
    reports = {}
    for arm in protocol["arms"]:
        print(f"Fitting {arm}: fixed 100 updates, ten training examples", flush=True)
        torch.manual_seed(protocol["seed"])
        model = WaypointHead()
        initial = state_hash(model)
        if first_initial_hash is not None and initial != first_initial_hash:
            raise ValueError("Arms did not start with identical weights")
        first_initial_hash = initial
        view = FeatureArm(data, arm)
        directory = output / arm
        directory.mkdir()
        result = fit_head(
            model,
            view,
            steps=protocol["optimizer_steps_per_arm"],
            batch_size=protocol["batch_size"],
            learning_rate=protocol["learning_rate"],
            device="cpu",
            seed=protocol["seed"],
            max_seconds=300,
        )
        checkpoint = directory / "head.safetensors"
        save_file(
            {k: v.detach().cpu().contiguous() for k, v in model.state_dict().items()},
            checkpoint,
        )
        model.eval()
        replay = WaypointHead(**model.config).eval()
        replay.load_state_dict(load_file(checkpoint), strict=True)
        with torch.no_grad():
            inputs, _ = view.batch(list(range(len(view))))
            delta = float((model(**inputs) - replay(**inputs)).abs().max())
        if delta > 1e-5:
            raise ValueError("Checkpoint reload changed predictions")
        result.update(
            status="completed",
            arm=arm,
            submission_allowed=False,
            competition_training_permission="unverified",
            initial_weights_sha256=initial,
            final_weights_sha256=state_hash(model),
            head_config=model.config,
            parameter_count=sum(p.numel() for p in model.parameters()),
            head_sha256=file_hash(checkpoint),
            checkpoint_reload_max_abs_difference=delta,
            protocol=protocol,
            pilot_sha256=file_hash(PILOT),
            dataset_sha256=file_hash(data.dataset.path),
            cache_sha256=file_hash(data.path),
            runner_source_sha256=file_hash(__file__),
            head_source_sha256=file_hash(Path(__file__).parent / "training/head.py"),
            numerical_runner_sha256=file_hash(
                Path(__file__).parent / "training/runner.py"
            ),
            state_adapter_sha256=file_hash(
                Path(__file__).parent / "training/state_adapter.py"
            ),
            frozen_feature_spec=data.spec,
            batch_order="numpy default_rng(seed), one permutation of all ten samples per update; identical both arms",
            inference_visual_input=(
                "cached Cosmos features"
                if arm == "cosmos"
                else "zeros_like(features), no image values"
            ),
            heldout_used_for_optimizer_or_selection=False,
        )
        if result["final_weights_sha256"] == initial:
            raise ValueError("Head weights did not change")
        write_json(directory / "training.json", result)
        reports[arm] = {
            "training_loss": result["final_training_loss"],
            "ade_m": result["final_training_metrics"]["ade_m"],
        }
    write_json(
        output / "COMPLETED.json",
        {
            "status": "both_fixed_budget_heads_fitted_before_evaluation",
            "pilot_sha256": file_hash(PILOT),
            "total_optimizer_steps": 200,
            "arms": {
                arm: file_hash(output / arm / "training.json")
                for arm in protocol["arms"]
            },
            "submission_allowed": False,
        },
    )
    print(json.dumps(reports, indent=2), flush=True)


def metrics(predictions, targets, mask):
    from cosmos3.report_local_head10 import errors

    result = errors(predictions, targets, mask)
    yaw = np.arctan2(predictions[..., 2], predictions[..., 3]) - np.arctan2(
        targets[..., 2], targets[..., 3]
    )
    result["heading_mae_deg"] = float(
        np.degrees(np.abs(np.arctan2(np.sin(yaw), np.cos(yaw)))[mask]).mean()
    )
    return result


def evaluation_stage(pilot):
    import torch
    from safetensors.torch import load_file

    from cosmos3.training.head import WaypointHead

    output = RUN / "evaluation-result"
    if output.exists():
        raise ValueError("Evaluation already exists; no iterative holdout tuning")
    complete = json.loads((RUN / "fits/COMPLETED.json").read_text())
    if (
        complete["pilot_sha256"] != file_hash(PILOT)
        or complete["total_optimizer_steps"] != 200
    ):
        raise ValueError("Both fixed training arms must finish before evaluation")
    train, evaluation = data_for("training"), data_for("evaluation")
    require_role(train.dataset, pilot, "training")
    require_role(evaluation.dataset, pilot, "evaluation")
    if train.spec != evaluation.spec:
        raise ValueError("Training/evaluation feature recipes differ")
    train_images = {
        im["sha256"] for s in train.dataset.samples for im in s["images"] if im
    }
    eval_images = {
        im["sha256"] for s in evaluation.dataset.samples for im in s["images"] if im
    }
    if train_images & eval_images:
        raise ValueError("Training/evaluation image bytes overlap")
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    results, predictions, reports = {}, {}, {}
    for arm in pilot["ablation"]["arms"]:
        record = RUN / "fits" / arm / "training.json"
        if file_hash(record) != complete["arms"][arm]:
            raise ValueError("Training report changed after fitting")
        report = json.loads(record.read_text())
        reports[arm] = report
        path = record.parent / "head.safetensors"
        if file_hash(path) != report["head_sha256"] or report["optimizer_steps"] != 100:
            raise ValueError("Checkpoint or fixed budget changed")
        head = WaypointHead(**report["head_config"]).eval()
        head.load_state_dict(load_file(path), strict=True)
        with torch.no_grad():
            inputs, target = FeatureArm(evaluation, arm).batch(
                list(range(len(evaluation)))
            )
            pred = head(**inputs).cpu().numpy()
        if not np.isfinite(pred).all():
            raise ValueError("Nonfinite held-out predictions")
        targets, mask = target["waypoints"].numpy(), target["target_mask"].numpy()
        predictions[arm] = pred
        results[arm] = metrics(pred, targets, mask)
    if (
        reports["cosmos"]["initial_weights_sha256"]
        != reports["state_route_only"]["initial_weights_sha256"]
    ):
        raise ValueError("Initial weights differ")
    states = np.stack([item[0]["ego_state"] for item in evaluation.dataset.items])
    cv = np.zeros_like(predictions["cosmos"])
    cv[..., :2] = states[:, None, :2] * (np.arange(1, 41) * 0.1)[None, :, None]
    cv[..., 3] = 1
    predictions["constant_velocity"] = cv
    results["constant_velocity"] = metrics(cv, targets, mask)
    rows = []
    public = json.loads(Path(pilot["public_manifest"]).read_text())
    for i, sample in enumerate(evaluation.dataset.samples):
        rows.append(
            {
                "scene_id": sample["scene_id"],
                "source_log": sample["source_log"],
                "city": public["scenes"][sample["scene_id"]]["city"],
                **{
                    arm: metrics(pred[i : i + 1], targets[i : i + 1], mask[i : i + 1])
                    for arm, pred in predictions.items()
                },
            }
        )
    deltas = np.array(
        [r["cosmos"]["ade_m"] - r["state_route_only"]["ade_m"] for r in rows]
    )
    rng = np.random.default_rng(20260919)
    bootstrap = rng.choice(deltas, (10000, len(deltas)), replace=True).mean(axis=1)
    summary = {
        "status": "completed",
        "mode": "one_fixed_open_loop_unseen_source_log_check",
        "training_samples": len(train),
        "evaluation_samples": len(evaluation),
        "training_source_logs": pilot["training_source_logs"],
        "evaluation_source_logs": pilot["evaluation_source_logs"],
        "source_log_overlap": [],
        "image_hash_overlap": [],
        "metrics": results,
        "per_scene": rows,
        "paired_cosmos_minus_state_route_ade_m": float(deltas.mean()),
        "paired_bootstrap_95_percent_interval_m": np.quantile(
            bootstrap, [0.025, 0.975]
        ).tolist(),
        "cosmos_lower_ade_scene_count": int((deltas < 0).sum()),
        "bootstrap_caveat": "Exploratory nine-log interval, one scene per log, one initialization; not a confirmatory population or leaderboard interval",
        "interpretation": "Unseen by these fitted heads; pretraining overlap unknown. One current image per sample; not closed-loop, India, competition, or large-data validation.",
        "state_recipe": pilot["ego_state_recipe"],
        "protocol": pilot["ablation"],
        "training_metrics": {
            arm: report["final_training_metrics"] for arm, report in reports.items()
        },
        "training_report_hashes": complete["arms"],
        "pilot_sha256": file_hash(PILOT),
        "evaluation_dataset_sha256": file_hash(evaluation.dataset.path),
        "evaluation_cache_sha256": file_hash(evaluation.path),
        "evaluation_source_sha256": file_hash(__file__),
        "submission_allowed": False,
        "competition_training_permission": "unverified",
        "no_hyperparameter_or_checkpoint_selection_from_evaluation": True,
    }
    output.mkdir()
    with (output / "predictions.npz").open("xb") as stream:
        np.savez_compressed(stream, **predictions, targets=targets, target_mask=mask)
    summary["predictions_sha256"] = file_hash(output / "predictions.npz")
    write_json(output / "summary.json", summary)
    print(
        json.dumps(
            {
                k: v
                for k, v in summary.items()
                if k
                in (
                    "metrics",
                    "paired_cosmos_minus_state_route_ade_m",
                    "paired_bootstrap_95_percent_interval_m",
                    "cosmos_lower_ade_scene_count",
                )
            },
            indent=2,
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=("export", "audit", "cache", "fit", "evaluate")
    )
    args = parser.parse_args()
    pilot = load_pilot(PILOT)
    require_run_authorization(PILOT, None, local_only=True)
    {
        "export": export_stage,
        "audit": audit_stage,
        "cache": cache_stage,
        "fit": fit_stage,
        "evaluate": evaluation_stage,
    }[args.stage](pilot)


if __name__ == "__main__":
    main()
