"""Read-only rollout checks, writing a separate validation artifact."""
import collections
import json
import math
from pathlib import Path
import struct
import sys

from alpasim_grpc.v0.logging_pb2 import LogEntry


def main(output):
    report = json.loads((output / 'report.json').read_text())
    assert report['simulation_exit_code'] == 0
    logs = list((output / 'simulation/rollouts').glob('*/*/rollout.asl'))
    assert len(logs) == 1
    counts = collections.Counter()
    requests, responses = [], []
    with logs[0].open('rb') as stream:
        while prefix := stream.read(4):
            assert len(prefix) == 4
            size = struct.unpack('>L', prefix)[0]
            payload = stream.read(size)
            assert len(payload) == size
            entry = LogEntry.FromString(payload)
            kind = entry.WhichOneof('log_entry')
            counts[kind] += 1
            if kind == 'driver_request':
                requests.append(entry.driver_request)
            elif kind == 'driver_return':
                responses.append(entry.driver_return)
    assert requests and len(requests) == len(responses)
    assert counts['ground_truth_request'] == 0
    assert counts['controller_return'] > 0
    for request, response in zip(requests, responses):
        assert len(response.trajectory.poses) == 41
        for i, pose in enumerate(response.trajectory.poses):
            assert pose.timestamp_us == request.time_now_us + i * 100_000
            p, q = pose.pose.vec, pose.pose.quat
            assert all(math.isfinite(v) for v in (p.x, p.y, p.z, q.w, q.x, q.y, q.z))
            assert abs(sum(v*v for v in (q.w, q.x, q.y, q.z)) - 1) < 1e-5
    lines = (output / 'driver.log').read_text().splitlines()
    counters = [line for line in lines if 'gtrs_inference=' in line and 'session=probe-' not in line]
    assert counters
    final = counters[-1]
    for field in ('cached_plan', 'straight_fallback', 'dynamic_state_fallback', 'inference_error'):
        assert f'{field}=0' in final, final
    assert f'gtrs_inference={len(requests)} ' in final
    assert (output / 'simulator.log').read_text().count('Session COMPLETED') == 1
    result = dict(status='local_smoke_pass', official_parity=False,
                  successful_neural_calls=len(requests), asl_counts=dict(counts),
                  policy_timestamps_us=[r.time_now_us for r in requests],
                  final_driver_counters=final, rollout=report['rollout'])
    (output / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main(Path(sys.argv[1]))
