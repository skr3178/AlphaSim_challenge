"""Read and validate saved one-scene smoke artifacts; never starts inference."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics
import struct

from alpasim_grpc.v0.logging_pb2 import LogEntry


def validate(output):
    run = json.loads((output / "run-summary.json").read_text())
    driver = json.loads((output / "driver-summary.json").read_text())
    directory = Path(run["run_directory"])
    logs = list((directory / "rollouts").glob("*/*/rollout.asl"))
    counts = Counter()
    requests = []
    responses = []
    assert len(logs) == 1, f"Expected one rollout ASL, found {len(logs)}"
    with logs[0].open("rb") as stream:
        while prefix := stream.read(4):
            assert len(prefix) == 4, "Truncated ASL length"
            size = struct.unpack(">L", prefix)[0]
            assert size < 100_000_000
            payload = stream.read(size)
            assert len(payload) == size, "Truncated ASL record"
            entry = LogEntry.FromString(payload)
            kind = entry.WhichOneof("log_entry")
            counts[kind] += 1
            if kind == "driver_request":
                requests.append(entry.driver_request)
            elif kind == "driver_return":
                responses.append(entry.driver_return)
    assert requests and len(requests) == len(responses), "Missing driver requests or returns"
    assert len(requests) == driver["successful_predictions"] == driver["drive_attempts"] <= 20
    assert not driver["errors"] and driver["fallbacks"] == 0
    assert driver["status"] == "closed", driver["status"]
    assert run["compose_exit_code"] == 0, run
    assert counts["driver_session_request"] == 1
    assert counts["ground_truth_request"] == 0
    assert counts["controller_return"] > 0
    for request, response in zip(requests, responses):
        poses = response.trajectory.poses
        assert len(poses) == 41
        assert poses[0].timestamp_us == request.time_now_us
        assert poses[-1].timestamp_us == request.time_now_us + 4_000_000
        assert poses[0].timestamp_us <= request.time_query_us <= poses[-1].timestamp_us
        for index, pose in enumerate(poses):
            assert pose.timestamp_us == request.time_now_us + index * 100_000
            p, q = pose.pose.vec, pose.pose.quat
            assert all(math.isfinite(v) for v in (p.x, p.y, p.z, q.w, q.x, q.y, q.z))
            assert abs(sum(v*v for v in (q.w, q.x, q.y, q.z)) - 1) < 1e-5
    simulator_log = (output / "simulator.log").read_text(errors="replace")
    completed = simulator_log.count("Session COMPLETED")
    assert completed == 1, f"Expected one completed session, got {completed}"
    summary_path = directory / "aggregate/results-summary.json"
    summary = json.loads(summary_path.read_text())
    assert len(summary["rollouts"]) == 1
    row = summary["rollouts"][0]
    assert row["clipgt_id"] == run["scene"]
    times = [r["seconds"] for r in driver["requests"]]
    result = {
        "status": "compatibility_pass", "quality_claim": False,
        "scene": run["scene"], "completed_rollouts": completed,
        "successful_neural_policy_calls": len(requests), "fallbacks": 0,
        "asl_counts": dict(counts), "policy_time_now_us": [r.time_now_us for r in requests],
        "policy_mean_seconds": statistics.mean(times), "policy_median_seconds": statistics.median(times),
        "policy_min_seconds": min(times), "policy_max_seconds": max(times),
        "policy_peak_process_GiB": driver["sampled_peak_process_GiB"],
        "wall_seconds": run["wall_seconds"],
        "local_scene_score": row["score"], "local_failure_reason": row.get("failure_reason"),
        "local_rollout_metrics": row["metrics"],
        "summary_path": str(summary_path), "asl_path": str(logs[0]),
        "limitations": [
            "One existing public development scene, not a quality benchmark or held-out validation.",
            "Existing older local runtime/scorer; not current organizer scorer parity.",
            "Host driver process; not competition container/concurrency/throughput validation.",
            "Reduced resolution, first front image only; no explicit route, speed, history or multiview conditioning.",
            "Ground-plane projection: decoded x/y/yaw retained, roll/pitch removed, z held at current rig ground height.",
        ],
    }
    (output / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    validate(parser.parse_args().output)
