"""Run exactly one bounded development rollout, preserving existing runs.

Invoke with the existing AlpaSim .venv Python (PyYAML and protobuf installed).
Only this script's driver PID and uniquely generated Compose project are stopped.
"""
import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

import yaml

ROOT = Path(__file__).resolve().parent
RUNTIME = Path("/home/skr/alpasim-challenge/alpasim")
DRIVER_PYTHON = Path("/media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python")
SCENE = "2021.05.25.14.24.08_veh-25_04059_04203-5395d42cc65e5c06"
PORT = 6795


def run():
    lock = open("/home/skr/alpasim-challenge/logs/.run-eval.lock", "a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if subprocess.check_output(["docker", "ps", "-q"], text=True).strip():
        raise RuntimeError("Refusing to start while other Docker containers run")
    probe = socket.socket()
    probe.bind(("127.0.0.1", PORT))
    probe.close()
    free = int(subprocess.check_output(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], text=True).strip())
    if free < 22000:
        raise RuntimeError(f"GPU is not idle: {free} MiB free")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = "cosmos3-compat-" + stamp.lower()
    output = ROOT / "artifacts" / (stamp + "_alpasim_compat")
    output.mkdir()
    run_dir = RUNTIME / "runs" / name
    if run_dir.exists():
        raise RuntimeError("Run directory already exists")
    report = {"status": "starting", "scene": SCENE, "expected_rollouts": 1,
              "max_sim_steps": 12, "control_timestep_us": 500000,
              "driver_max_calls": 20, "wall_limit_seconds": 900,
              "run_directory": str(run_dir), "artifacts": str(output),
              "runtime_git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=RUNTIME, text=True).strip()}
    def save():
        (output / "run-summary.json").write_text(json.dumps(report, indent=2) + "\n")
    save()
    print(f"COMPAT_ARTIFACTS={output}", flush=True)
    print(f"ALPASIM_RUN={run_dir}", flush=True)
    env = dict(os.environ, ALPASIM_NUPLAN_ROOT="/home/skr/alpasim-challenge/nuplan-track",
               ALPASIM_DRIVER_HOST="localhost", ALPASIM_DRIVER_PORT=str(PORT))
    command = [str(RUNTIME / ".venv/bin/alpasim_wizard"), "+e2e_challenge_nuplan=dev_fast",
               f"scenes.scene_ids=[{SCENE}]", "scenes.limit_to_first_n=1", "scenes.test_suite_id=null",
               "runtime.nr_workers=1", "runtime.simulation_config.n_rollouts=1",
               "runtime.simulation_config.n_sim_steps=12", "defines.nre_cache_size=2",
               "eval.allow_aggregation_with_failed_rollouts=false", "eval.video.render_video=false",
               f"wizard.log_dir={run_dir}", "wizard.run_method=NONE"]
    driver = compose_process = None
    compose = None
    try:
        with (output / "config-generation.log").open("w") as log:
            subprocess.run(command, cwd=RUNTIME, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
        # This config controls the selected scenes before any GPU inference begins.
        config = yaml.safe_load((run_dir / "wizard-config.yaml").read_text())
        assert config["scenes"]["scene_ids"] == [SCENE], config["scenes"]
        assert config["scenes"]["limit_to_first_n"] == 1
        assert config["runtime"]["simulation_config"]["n_rollouts"] == 1
        assert config["runtime"]["simulation_config"]["n_sim_steps"] == 12
        for service in ("renderer", "driver", "controller"):
            assert config["runtime"]["endpoints"][service]["n_concurrent_rollouts"] == 1
        assert config["runtime"]["simulation_config"]["send_recording_ground_truth"] is False
        compose = ["docker", "compose", "-p", name, "-f", str(run_dir / "docker-compose.yaml")]
        report["compose_project"] = name
        report["config_verified"] = True
        save()
        with (output / "driver.log").open("w") as driver_log, (output / "simulator.log").open("w") as sim_log:
            driver = subprocess.Popen([str(DRIVER_PYTHON), "-u", str(ROOT / "compat_driver.py"),
                                       "--output", str(output), "--port", str(PORT)],
                                      cwd=ROOT, env=env, stdout=driver_log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if driver.poll() is not None:
                    raise RuntimeError(f"Driver exited during startup: {driver.returncode}")
                try:
                    with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                        break
                except OSError:
                    time.sleep(1)
            else:
                raise TimeoutError("Driver startup timeout")
            report["status"] = "running"
            save()
            print("Single-scene config verified; driver ready; starting renderer/controller/runtime", flush=True)
            begin = time.monotonic()
            compose_process = subprocess.Popen(compose + ["up", "--pull", "never", "--no-build", "--exit-code-from", "runtime-0"],
                                               cwd=run_dir, env=env, stdout=sim_log, stderr=subprocess.STDOUT,
                                               start_new_session=True)
            report["compose_exit_code"] = compose_process.wait(timeout=900)
            report["wall_seconds"] = time.monotonic() - begin
            if report["compose_exit_code"] != 0:
                raise RuntimeError(f"Simulator exited with {report['compose_exit_code']}; no successful run claimed")
            report["status"] = "finished_needs_artifact_validation"
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = repr(exc)
        raise
    finally:
        if compose_process is not None and compose_process.poll() is None:
            os.killpg(compose_process.pid, signal.SIGTERM)
            try:
                compose_process.wait(20)
            except subprocess.TimeoutExpired:
                os.killpg(compose_process.pid, signal.SIGKILL)
                compose_process.wait(5)
        if compose is not None:
            with (output / "cleanup.log").open("w") as cleanup:
                subprocess.run(compose + ["down", "--timeout", "10"], cwd=run_dir, stdout=cleanup, stderr=subprocess.STDOUT, timeout=60)
        if driver is not None and driver.poll() is None:
            driver.terminate()
            try:
                driver.wait(20)
            except subprocess.TimeoutExpired:
                driver.kill()
                driver.wait(5)
        save()
        print(json.dumps(report), flush=True)
    # Never equate a zero container exit code with a valid neural-policy run.
    from validate_compatibility import validate
    validate(output)
    report["status"] = "compatibility_pass"
    save()


if __name__ == "__main__":
    run()
