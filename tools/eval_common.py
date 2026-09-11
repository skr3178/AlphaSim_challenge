"""Read-only shared helpers for local evaluation integrity and public-suite metadata."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import yaml

WORKSPACE = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = WORKSPACE / "evaluation/public-suite.json"
DEFAULT_DATA_ROOT = Path("/home/skr/alpasim-challenge/nuplan-track")
DEFAULT_RUNS_ROOT = Path("/home/skr/alpasim-challenge/alpasim/runs")
SCENE_RE = re.compile(r"^(?P<log>\d{4}(?:\.\d{2}){5}_veh-\d+)_(?P<start>\d+)_(?P<end>\d+)-[0-9a-f]+$")
CITY_NAMES = {
    "us-nv-las-vegas-strip": "vegas", "us-ma-boston": "boston",
    "us-pa-pittsburgh-hazelwood": "pittsburgh", "sg-one-north": "singapore",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_log(scene: str) -> str:
    match = SCENE_RE.fullmatch(scene)
    if not match:
        raise ValueError(f"Unrecognized nuPlan scene ID: {scene!r}; supply explicit metadata")
    return match.group("log")


def recording_window(scene: str) -> str:
    source_log(scene)  # validate before splitting the vehicle's hyphen
    return scene.rsplit("-", 1)[0]


def load_yaml(path: Path):
    # BaseLoader also reads MTGS CentralConfig's Python-tagged YAML as inert
    # mappings/scalars. Never instantiate Python objects from dataset metadata.
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


def scene_ids(path: Path) -> list[str]:
    data = load_yaml(path)
    scenes = data.get("scenes", {})
    ids = scenes.get("scene_ids") if isinstance(scenes, dict) else None
    if not isinstance(ids, list) or not ids or any(not isinstance(s, str) for s in ids):
        raise ValueError(f"{path}: expected non-empty scenes.scene_ids")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate scene IDs")
    for scene in ids:
        source_log(scene)
    return ids


def asset_missing(root: Path, scene: str) -> list[str]:
    source_log(scene)
    base = root / "navtest/assets" / scene
    required = [root / "navtest/configs" / f"{scene}.yaml",
                base / "video_scene_dict.pkl", base / "road_height_map/road_height_map.npy"]
    missing = [str(p.relative_to(root)) for p in required if not p.is_file() or p.stat().st_size == 0]
    if not any(p.stat().st_size for p in (base / "background").glob("*.ckpt") if p.is_file()):
        missing.append(f"navtest/assets/{scene}/background/*.ckpt")
    return missing


def load_manifest(path: Path | None = None) -> dict:
    path = path or DEFAULT_MANIFEST
    if not path.is_file():
        return {"scenes": {}, "suites": {}}
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1 or not isinstance(data.get("scenes"), dict):
        raise ValueError(f"{path}: unsupported scene manifest")
    for scene, meta in data["scenes"].items():
        if meta.get("source_log") != source_log(scene):
            raise ValueError(f"{path}: inconsistent source log for {scene}")
    return data


def driver_diagnostics(path: Path | None) -> dict:
    result = {"path": str(path) if path else None, "available": False,
              "failure_events": 0, "unclassified_errors": 0, "affected_sessions": {},
              "explicit_fallback_events": 0, "fallback_count_known": False,
              "cached_plan_reuse_count_known": False}
    if path is None or not path.is_file() or path.stat().st_size == 0:
        return result
    result["available"] = True
    sessions: Counter[str] = Counter()
    # Match event headlines, not traceback exception messages (no double-count).
    failure = re.compile(r"failed to plan|inference failed|refusing to serve|not planning", re.I)
    error = re.compile(r"\[ERROR\]|\bERROR[:\s]|Traceback \(most recent call last\)")
    in_traceback = False
    for line in path.read_text(errors="replace").splitlines():
        if failure.search(line):
            result["failure_events"] += 1
            session = re.search(r"session(?:_uuid)?[ =:]\s*([0-9a-f-]{36})", line, re.I)
            if session:
                sessions[session.group(1)] += 1
            in_traceback = True
        elif error.search(line):
            if "Traceback (most recent call last)" not in line or not in_traceback:
                result["unclassified_errors"] += 1
            in_traceback = True
        elif line.startswith("["):
            in_traceback = False
        if re.search(r"\b(?:using|serving|emitting)\b.*\bfallback\b", line, re.I):
            result["explicit_fallback_events"] += 1
    result["affected_sessions"] = dict(sessions)
    return result


def discover_driver_log(summary: Path) -> Path | None:
    run = summary.parent.parent
    for path in (run / "driver.log", Path("/home/skr/alpasim-challenge/logs") / f"driver-{run.name}.log"):
        if path.is_file():
            return path
    return None


def run_contract(summary: Path) -> dict:
    root = summary.parent.parent
    result = {"hashes": {}, "expected_scene_ids": None, "n_rollouts": None,
              "simulation": None, "eval": None, "controller": None}
    for name, key in (("eval-config.yaml", "eval"), ("controller-config.yaml", "controller")):
        path = root / name
        if path.is_file():
            result["hashes"][name] = sha256(path)
            result[key] = load_yaml(path)
    paths = sorted(root.glob("generated-user-config-*.yaml"))
    expected = []
    simulations = []
    for path in paths:
        result["hashes"][path.name] = sha256(path)
        data = load_yaml(path)
        if not isinstance(data.get("scenes"), list):
            raise ValueError(f"{path}: missing resolved scenes list")
        expected.extend(row["scene_id"] for row in data["scenes"])
        simulations.append(data["simulation_config"])
    if simulations:
        if any(s != simulations[0] for s in simulations[1:]):
            raise ValueError("Resolved worker simulation configs differ")
        if len(expected) != len(set(expected)):
            raise ValueError("Duplicate scenes across resolved worker configs")
        result["simulation"] = simulations[0]
        result["n_rollouts"] = int(simulations[0]["n_rollouts"])
        result["expected_scene_ids"] = expected
    return result


def integrity(rollouts: list[dict], contract: dict, diagnostics: dict) -> dict:
    issues = []
    if diagnostics["failure_events"]:
        issues.append(f"{diagnostics['failure_events']} driver planning/inference failures or skipped plans")
    if diagnostics["unclassified_errors"]:
        issues.append(f"{diagnostics['unclassified_errors']} unclassified driver errors")
    actual = Counter(row["clipgt_id"] for row in rollouts)
    expected = contract["expected_scene_ids"]
    coverage_known = expected is not None and contract["n_rollouts"] is not None
    if coverage_known:
        counts = {scene: contract["n_rollouts"] for scene in expected}
        if dict(actual) != counts:
            issues.append("scored scene/repeat coverage differs from resolved runtime config")
    for row in rollouts:
        if row.get("status") not in ("pass", "fail"):
            issues.append(f"unscored/unknown rollout status: {row.get('status')!r}")
            break
    return {"status": "INVALID" if issues else ("CHECKED" if coverage_known and diagnostics["available"] else "UNVERIFIED"),
            "issues": issues, "coverage_known": coverage_known,
            "expected_rollouts": len(expected) * contract["n_rollouts"] if coverage_known else None,
            "actual_rollouts": len(rollouts), "driver": diagnostics,
            "note": "CHECKED means complete scored coverage and no detected log failures; absence of log errors is not proof of zero fallbacks."}
