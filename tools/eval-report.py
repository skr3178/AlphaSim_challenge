#!/usr/bin/env python3
"""Print a board-shaped, reproducible report for a local AlpaSim result.

The local evaluator writes the same per-rollout ``score`` that the nuPlan
scene scorer uses.  It cannot compute Policy Capability Score (PCS): PCS is
an IRT fit over the private evaluation set and the other submissions.  This
tool deliberately reports *scene-score inputs*, never a made-up local PCS.

Examples:

    tools/eval-report.py /home/skr/alpasim-challenge/alpasim/runs/wajepa-s2-400
    tools/eval-report.py wajepa-s4-400 --baseline wajepa-s2-400
    tools/eval-report.py wajepa-s2-400 --calibration evaluation/wajepa-s2-official-calibration.json

Run names are resolved below ``$ALPASIM_RUNS_DIR`` (or the usual local runs
directory).  The optional calibration is a factual record of one submitted
policy, not a transfer model for another policy.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable


DEFAULT_RUNS_DIR = Path("/home/skr/alpasim-challenge/alpasim/runs")
# This was the published mix for navtest before the final private subset.  It
# is useful as a sensitivity view only; organizers have not published the
# final set's city counts, so calling it an official projection would be false.
HISTORIC_NUPLAN_CITY_WEIGHTS = {
    "vegas": 0.32,
    "boston": 0.31,
    "pittsburgh": 0.22,
    "singapore": 0.15,
}


def resolve_summary(value: str) -> Path:
    """Resolve a run directory, a result JSON, or a symbolic run name."""
    path = Path(value).expanduser()
    if path.is_file():
        return path
    if path.is_dir():
        candidate = path / "aggregate" / "results-summary.json"
        if candidate.is_file():
            return candidate
    runs_dir = Path(os.environ.get("ALPASIM_RUNS_DIR", DEFAULT_RUNS_DIR))
    candidate = runs_dir / value / "aggregate" / "results-summary.json"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(
        f"could not find results-summary.json for {value!r}; tried {path} and {candidate}"
    )


def load_rollouts(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(path.read_text())
    rollouts = payload.get("rollouts")
    if not isinstance(rollouts, list) or not rollouts:
        raise ValueError(f"{path} has no non-empty rollouts[]")
    bad = [r for r in rollouts if not isinstance(r, dict) or not isinstance(r.get("metrics"), dict)]
    if bad:
        raise ValueError(f"{path} has {len(bad)} malformed rollout(s)")
    return rollouts, payload


def city_for(clipgt_id: str) -> str:
    """Infer the city of the public local shards from their recording date.

    The exact configs contain the authoritative city string, but result files
    only retain ``clipgt_id``.  These four date groups are the public shards
    currently used by navtest_local400.  Unknown IDs remain explicit rather
    than silently being assigned a city.
    """
    prefixes = {
        "2021.05.": "vegas",
        "2021.09.09.": "boston",
        "2021.09.16.": "pittsburgh",
        "2021.10.06.": "singapore",
    }
    return next((city for prefix, city in prefixes.items() if clipgt_id.startswith(prefix)), "unknown")


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * q
    lo, hi = math.floor(index), math.ceil(index)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def bootstrap_mean_ci(values: list[float], *, draws: int, seed: int) -> tuple[float, float]:
    """Non-parametric 95% CI, conditional on this local scene sample."""
    if len(values) < 2 or draws <= 0:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(values)
    resampled = [sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(draws)]
    return percentile(resampled, 0.025), percentile(resampled, 0.975)


def recording_for(clipgt_id: str) -> str:
    """Return the source recording portion of a public clipgt identifier."""
    # The final ``-<hex>`` is the sampled clip id.  Clips before it share the
    # same recording/vehicle window and are visibly correlated, so treating all
    # 400 as iid makes local uncertainty look much smaller than it is.
    return clipgt_id.rsplit("-", 1)[0]


def cluster_bootstrap_mean_ci(
    values_by_recording: dict[str, list[float]], *, draws: int, seed: int
) -> tuple[float, float]:
    """95% block-bootstrap CI with source recordings as the resampling unit."""
    blocks = list(values_by_recording.values())
    if len(blocks) < 2 or draws <= 0:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    n_blocks = len(blocks)
    resampled: list[float] = []
    for _ in range(draws):
        sample = [blocks[rng.randrange(n_blocks)] for _ in range(n_blocks)]
        total = sum(sum(block) for block in sample)
        count = sum(len(block) for block in sample)
        resampled.append(total / count)
    return percentile(resampled, 0.025), percentile(resampled, 0.975)


def safe_float(row: dict[str, Any], key: str) -> float | None:
    value = row.get("metrics", {}).get(key)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fmt(value: float | None, places: int = 4) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    return f"{value:.{places}f}"


def fmt_percent(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    return f"{100 * value:.1f}%"


def metric_mean(rollouts: Iterable[dict[str, Any]], key: str) -> float | None:
    values = [v for r in rollouts if (v := safe_float(r, key)) is not None]
    return mean(values) if values else None


def board_metrics(rollouts: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, float | None]:
    """Return values whose aggregation matches the board/result-summary card."""
    metrics_results = payload.get("metrics_results")
    aggregate = metrics_results[0] if isinstance(metrics_results, list) and metrics_results else {}
    scores = [float(row["score"]) for row in rollouts]
    return {
        "average_scene_score": mean(scores),
        "dist_to_gt_trajectory_mean": safe_number(aggregate.get("dist_to_gt_trajectory"))
        or metric_mean(rollouts, "dist_to_gt_trajectory"),
        "lateral_dist_to_gt_trajectory_mean": safe_number(
            aggregate.get("lateral_dist_to_gt_trajectory")
        )
        or metric_mean(rollouts, "lateral_dist_to_gt_trajectory"),
        "avg_dist_between_incidents_at_fault": safe_number(
            aggregate.get("avg_dist_between_incidents_at_fault")
        ),
        "progress_clipped_rel_mean": safe_number(aggregate.get("progress_clipped_rel"))
        or metric_mean(rollouts, "progress_clipped_rel"),
    }


def safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def failure_counter(rollouts: Iterable[dict[str, Any]]) -> Counter[str]:
    reasons: Counter[str] = Counter()
    for row in rollouts:
        if float(row["score"]) != 0.0:
            continue
        reason = row.get("failure_reason") or "zero_without_failure_reason"
        reasons[str(reason)] += 1
    return reasons


def reweighted_city_view(rollouts: list[dict[str, Any]]) -> tuple[float | None, dict[str, float]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rollouts:
        groups[city_for(str(row.get("clipgt_id", "")))].append(row)
    if any(city not in groups for city in HISTORIC_NUPLAN_CITY_WEIGHTS):
        return None, {}
    city_means = {
        city: mean(float(row["score"]) for row in groups[city])
        for city in HISTORIC_NUPLAN_CITY_WEIGHTS
    }
    weighted = sum(HISTORIC_NUPLAN_CITY_WEIGHTS[city] * city_means[city] for city in city_means)
    return weighted, city_means


def print_card(name: str, path: Path, rollouts: list[dict[str, Any]], payload: dict[str, Any], *, draws: int, seed: int) -> None:
    metrics = board_metrics(rollouts, payload)
    scores = [float(row["score"]) for row in rollouts]
    nonzero = [score for score in scores if score > 0.0]
    d2gt = [v for row in rollouts if (v := safe_float(row, "dist_to_gt_trajectory")) is not None]
    lateral = [v for row in rollouts if (v := safe_float(row, "lateral_dist_to_gt_trajectory")) is not None]
    progress = [v for row in rollouts if (v := safe_float(row, "progress_clipped_rel")) is not None]
    zeros = sum(score == 0.0 for score in scores)
    ones = sum(score == 1.0 for score in scores)
    ci_lo, ci_hi = bootstrap_mean_ci(scores, draws=draws, seed=seed)
    scores_by_recording: dict[str, list[float]] = defaultdict(list)
    for row in rollouts:
        scores_by_recording[recording_for(str(row.get("clipgt_id", "")))].append(float(row["score"]))
    block_ci_lo, block_ci_hi = cluster_bootstrap_mean_ci(
        scores_by_recording, draws=draws, seed=seed + 1
    )
    failures = failure_counter(rollouts)
    weighted_score, city_scores = reweighted_city_view(rollouts)

    print(f"LOCAL BOARD CARD — {name}")
    print(f"source: {path}")
    print("scope: local scene-score evidence only; PCS/rank cannot be inferred locally")
    print()
    print("board-compatible fields")
    print(f"  average_scene_score             {metrics['average_scene_score']:.4f}  "
          f"(scene bootstrap 95% CI {fmt(ci_lo)}–{fmt(ci_hi)}; conditional on this sample)")
    print(f"  recording-block bootstrap 95%   {fmt(block_ci_lo)}–{fmt(block_ci_hi)}  "
          f"({len(scores_by_recording)} source recordings; use this wider uncertainty for go/no-go)")
    print(f"  avg_dist_between_at_fault_km    {fmt(metrics['avg_dist_between_incidents_at_fault'], 3)}")
    print(f"  dist_to_gt_trajectory_mean_m    {fmt(metrics['dist_to_gt_trajectory_mean'], 3)}")
    print(f"  lateral_dist_to_gt_mean_m        {fmt(metrics['lateral_dist_to_gt_trajectory_mean'], 3)}")
    print(f"  progress_clipped_rel_mean        {fmt(metrics['progress_clipped_rel_mean'])}")
    print()
    print("score distribution")
    print(f"  rollouts={len(scores)}  zero={zeros} ({fmt_percent(zeros / len(scores))})  "
          f"partial={len(scores) - zeros - ones} ({fmt_percent((len(scores) - zeros - ones) / len(scores))})  "
          f"one={ones} ({fmt_percent(ones / len(scores))})")
    print(f"  nonzero_mean={fmt(mean(nonzero) if nonzero else None)}  "
          f"p10/p50/p90={fmt(percentile(scores, .10))}/{fmt(percentile(scores, .50))}/{fmt(percentile(scores, .90))}")
    print(f"  progress<0.8={sum(v < .8 for v in progress)} ({fmt_percent(sum(v < .8 for v in progress) / len(progress) if progress else None)})")
    print("  zero causes=" + (", ".join(f"{reason}:{count}" for reason, count in sorted(failures.items())) or "none"))
    print()
    print("trajectory error distribution (metres; mean is the board-comparable value)")
    print(f"  d2gt     mean={fmt(mean(d2gt) if d2gt else None, 3)}  median={fmt(median(d2gt) if d2gt else None, 3)}  "
          f"p90={fmt(percentile(d2gt, .90), 3)}")
    print(f"  lateral  mean={fmt(mean(lateral) if lateral else None, 3)}  median={fmt(median(lateral) if lateral else None, 3)}  "
          f"p90={fmt(percentile(lateral, .90), 3)}")
    print()
    print("city stress view")
    city_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rollouts:
        city_groups[city_for(str(row.get("clipgt_id", "")))].append(row)
    for city in sorted(city_groups):
        group = city_groups[city]
        group_scores = [float(row["score"]) for row in group]
        group_zeros = sum(score == 0.0 for score in group_scores)
        group_d2gt = metric_mean(group, "dist_to_gt_trajectory")
        recordings = len({recording_for(str(row.get("clipgt_id", ""))) for row in group})
        print(f"  {city:<11} n={len(group):3d} score={mean(group_scores):.4f} "
              f"zero={fmt_percent(group_zeros / len(group))} d2gt_mean={fmt(group_d2gt, 3)} "
              f"recordings={recordings}")
    if weighted_score is None:
        print("  historic-navtest city reweight: unavailable (one or more known cities absent)")
    else:
        weights = ", ".join(f"{city}={weight:.0%}" for city, weight in HISTORIC_NUPLAN_CITY_WEIGHTS.items())
        print(f"  historic-navtest city reweight: {weighted_score:.4f} ({weights})")
        print("  NOTE: sensitivity view only; final private-set city mix is unpublished.")
    print()
    print("recording stress view (the public 400 are clustered, not 400 independent roads)")
    recording_rows: list[tuple[float, str, int, int]] = []
    for recording, values in scores_by_recording.items():
        recording_rows.append((mean(values), recording, len(values), sum(value == 0.0 for value in values)))
    for score, recording, count, zero_count in sorted(recording_rows)[:5]:
        print(f"  worst  {recording:<47} n={count:2d} score={score:.4f} zero={zero_count}")
    if len(recording_rows) > 5:
        print(f"  best   {max(recording_rows)[1]:<47} score={max(recording_rows)[0]:.4f}")


def exact_two_sided_sign_test(wins: int, losses: int) -> float:
    """Exact two-sided binomial sign test, ignoring tied paired rollouts."""
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(wins, losses) + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


def print_comparison(candidate: list[dict[str, Any]], baseline: list[dict[str, Any]], *, draws: int, seed: int) -> None:
    by_id = {str(row.get("clipgt_id")): row for row in baseline}
    pairs = [(row, by_id[str(row.get("clipgt_id"))]) for row in candidate if str(row.get("clipgt_id")) in by_id]
    if not pairs:
        raise ValueError("candidate and baseline have no shared clipgt_id values")
    delta = [float(c["score"]) - float(b["score"]) for c, b in pairs]
    wins = sum(value > 1e-12 for value in delta)
    losses = sum(value < -1e-12 for value in delta)
    ci_lo, ci_hi = bootstrap_mean_ci(delta, draws=draws, seed=seed)
    zero_delta = [float(c["score"]) == 0.0 for c, _ in pairs]
    base_zero = [float(b["score"]) == 0.0 for _, b in pairs]
    print()
    print("paired comparison (same clipgt_id only; this is the local decision signal)")
    print(f"  paired_n={len(pairs)}  mean_scene_score_delta={mean(delta):+.4f} "
          f"(bootstrap 95% CI {fmt(ci_lo)}–{fmt(ci_hi)})")
    print(f"  better/worse/tied={wins}/{losses}/{len(pairs) - wins - losses}  sign-test p={exact_two_sided_sign_test(wins, losses):.4g}")
    print(f"  zero scenes candidate={sum(zero_delta)} baseline={sum(base_zero)} delta={sum(zero_delta)-sum(base_zero):+d}")
    for metric in ("collision_at_fault", "left_corridor_laterally", "progress_clipped_rel", "dist_to_gt_trajectory"):
        c_value = metric_mean((c for c, _ in pairs), metric)
        b_value = metric_mean((b for _, b in pairs), metric)
        if c_value is not None and b_value is not None:
            print(f"  {metric:<30} candidate={fmt(c_value)} baseline={fmt(b_value)} delta={c_value - b_value:+.4f}")


def print_calibration(calibration_path: Path, run_name: str, board: dict[str, float | None]) -> None:
    record = json.loads(calibration_path.read_text())
    official = record.get("official")
    if not isinstance(official, dict):
        raise ValueError(f"{calibration_path} must contain official={{...}}")
    reference_run = str(record.get("local_run", ""))
    print()
    print("official calibration record")
    print(f"  source={calibration_path}  reference_local_run={reference_run or 'unspecified'}")
    for key in ("average_scene_score", "dist_to_gt_trajectory", "avg_dist_between_incidents_at_fault", "policy_capability_score"):
        if key in official:
            print(f"  official {key:<34} {official[key]}")
    official_score = safe_number(official.get("average_scene_score"))
    if reference_run == run_name and official_score is not None:
        print(f"  observed local→official scene-score gap {official_score - (board['average_scene_score'] or 0):+.4f}")
    else:
        print("  WARNING: one submitted policy calibrates no other policy; do not apply an offset to this run.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", help="run name, run directory, or results-summary.json")
    parser.add_argument("--baseline", help="paired baseline run name/directory/results JSON")
    parser.add_argument("--calibration", type=Path, help="factual official-result record; never used to predict PCS")
    parser.add_argument("--bootstrap-draws", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260910)
    args = parser.parse_args()
    if args.bootstrap_draws < 0:
        parser.error("--bootstrap-draws must be non-negative")

    try:
        summary = resolve_summary(args.run)
        rollouts, payload = load_rollouts(summary)
        run_name = summary.parent.parent.name
        print_card(run_name, summary, rollouts, payload, draws=args.bootstrap_draws, seed=args.seed)
        if args.baseline:
            baseline_path = resolve_summary(args.baseline)
            baseline, _ = load_rollouts(baseline_path)
            print_comparison(rollouts, baseline, draws=args.bootstrap_draws, seed=args.seed)
        if args.calibration:
            print_calibration(args.calibration, run_name, board_metrics(rollouts, payload))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
