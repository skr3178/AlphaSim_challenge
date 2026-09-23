"""CLI: preflight -> export-asl -> cache-features -> train-head. All local."""

import argparse
import json
import os
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

DEFAULT_PILOT = (
    Path(__file__).resolve().parents[1] / "pilots/real-driving-v1/manifest.json"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, default=DEFAULT_PILOT)
    subs = parser.add_subparsers(dest="command", required=True)
    pre = subs.add_parser(
        "preflight", help="Read-only metadata checks, no models/authentication"
    )
    pre.add_argument(
        "--run-root",
        type=Path,
        help="Optionally inspect first request in saved approved ASL logs",
    )
    pre.add_argument(
        "--output", type=Path, help="Optional new report path; never overwrites"
    )
    export = subs.add_parser(
        "export-asl", help="Export approved expert-aligned frames from saved logs"
    )
    sources = export.add_mutually_exclusive_group(required=True)
    sources.add_argument("--asl", type=Path, action="append")
    sources.add_argument(
        "--source-report",
        type=Path,
        help="Saved preflight report with approved ASL paths",
    )
    export.add_argument("--max-samples", type=int, default=64)
    export.add_argument("--output", type=Path, required=True)
    cache = subs.add_parser(
        "cache-features", help="Run local frozen generator feature extraction"
    )
    cache.add_argument("--dataset", type=Path, required=True)
    cache.add_argument("--checkpoint", type=Path, required=True)
    cache.add_argument("--output", type=Path, required=True)
    cache.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    cache.add_argument("--max-seconds", type=int, default=600)
    train = subs.add_parser(
        "train-head", help="At most 100 updates; no backbone training or evaluation"
    )
    train.add_argument("--dataset", type=Path, required=True)
    train.add_argument("--cache", type=Path, required=True)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--steps", type=int, default=100)
    train.add_argument("--batch-size", type=int, default=8)
    train.add_argument("--learning-rate", type=float, default=0.0003)
    train.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    train.add_argument("--max-seconds", type=int, default=300)
    for sub in (export, cache, train):
        authorization = sub.add_mutually_exclusive_group(required=True)
        authorization.add_argument("--rules-evidence", type=Path)
        authorization.add_argument(
            "--local-only",
            action="store_true",
            help="Separate user-approved ten-sample local head test; no competition eligibility claim",
        )
    args = parser.parse_args()
    try:
        from .runner import preflight, cache_features, train_head

        if args.command == "preflight":
            if args.output is not None and args.output.exists():
                raise ValueError("Refusing to overwrite preflight report")
            result = preflight(args.pilot, args.run_root)
            if args.output is not None:
                from .contracts import write_json

                args.output.parent.mkdir(parents=True, exist_ok=True)
                write_json(args.output, result)
        elif args.command == "export-asl":
            from .export_asl import export as run_export

            paths = args.asl
            if args.source_report:
                from .contracts import file_hash, load_pilot

                report = json.loads(args.source_report.read_text())
                if report["pilot_manifest_sha256"] != file_hash(args.pilot):
                    raise ValueError("Source report belongs to another pilot")
                rows = report["saved_log_inventory"]
                if len(rows) != len(load_pilot(args.pilot)["samples"]) or any(
                    not r.get("source") for r in rows
                ):
                    raise ValueError(
                        "Source report must contain all approved ASL paths"
                    )
                paths = [Path(row["source"]) for row in rows]
            result = run_export(
                args.pilot,
                paths,
                args.output,
                args.rules_evidence,
                args.max_samples,
                local_only=args.local_only,
            )
        elif args.command == "cache-features":
            result = cache_features(
                args.pilot,
                args.dataset,
                args.checkpoint,
                args.output,
                args.rules_evidence,
                args.device,
                args.max_seconds,
                local_only=args.local_only,
            )
        else:
            result = train_head(
                args.pilot,
                args.dataset,
                args.cache,
                args.output,
                args.rules_evidence,
                args.steps,
                args.batch_size,
                args.learning_rate,
                args.device,
                args.max_seconds,
                local_only=args.local_only,
            )
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Pipeline stopped: {exc}\n")


if __name__ == "__main__":
    main()
