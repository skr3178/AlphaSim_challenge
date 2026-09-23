"""One provenance-backed camera comparison; no inference, rendering or training.

Preserve original JPEG bytes. Build a code-native HTML comparison, not a
generated/retouched image. Read only an allow-listed local metadata pickle and
a bounded prefix of one pinned public archive; never extract archive paths.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import io
import json
from pathlib import Path
import pickle
import tarfile
import time
import urllib.request

import numpy as np
from PIL import Image
import pyarrow.compute as pc
import pyarrow.feather as feather
from pyquaternion import Quaternion

from cosmos3.training.contracts import pose_matrix
from cosmos3.training.export_asl import entries


SCENE = "2021.05.25.14.26.37_veh-27_04122_04279-303d452ddd2d58d1"
ROOT = Path("/home/skr/alpasim-challenge/nuplan-track")
RUN = Path("/media/skr/storage/alpasim-runs/confirm400-mup-g100")
REVISION = "a76f840b65e972bc45e56c2adced897498e9a026"
ARCHIVE = "openscene-v1.1/openscene_sensor_test_camera/openscene_sensor_test_camera_0.tgz"
URL = f"https://huggingface.co/datasets/OpenDriveLab/OpenScene/resolve/{REVISION}/{ARCHIVE}?download=true"
BYTE_CAP = 128 * 1024**2
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "artifacts/real-vs-mtgs-pair-20260919"


class MetadataReader(pickle.Unpickler):
    """Allow only the data constructors used by the local MTGS scene metadata."""

    def find_class(self, module, name):
        from numpy._core import multiarray

        allowed = {
            ("numpy.core.multiarray", "_reconstruct"): multiarray._reconstruct,
            ("numpy._core.multiarray", "_reconstruct"): multiarray._reconstruct,
            ("numpy.core.multiarray", "scalar"): multiarray.scalar,
            ("numpy._core.multiarray", "scalar"): multiarray.scalar,
            ("numpy", "ndarray"): np.ndarray,
            ("numpy", "dtype"): np.dtype,
            ("pyquaternion.quaternion", "Quaternion"): Quaternion,
            ("datetime", "date"): datetime.date,
            ("datetime", "datetime"): datetime.datetime,
        }
        if (module, name) not in allowed:
            raise ValueError(f"Unsupported metadata constructor: {module}.{name}")
        return allowed[(module, name)]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def jsonable(value):
    if isinstance(value, Quaternion):
        return value.elements.tolist()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(jsonable(value), stream, indent=2, allow_nan=False)
        stream.write("\n")


def inspect_source():
    from google.protobuf.json_format import MessageToDict

    asset = ROOT / "navtest/assets" / SCENE / "video_scene_dict.pkl"
    cache = ROOT / "nuplan_test" / SCENE / "agent_data_dt0.10.feather"
    sources = sorted((RUN / "rollouts" / SCENE).glob("*/rollout.asl"))
    if len(sources) != 1:
        raise ValueError("Expected exactly one saved rollout")
    asl = sources[0]
    with asset.open("rb") as stream:
        videos = MetadataReader(stream).load()
    if len(videos) != 1:
        raise ValueError("Ambiguous scene metadata")
    info = next(iter(videos.values()))
    table = feather.read_table(cache)
    ego = table.filter(pc.equal(table["agent_id"], "ego")).to_pylist()
    first = next(row for row in ego if row["scene_ts"] == 0)
    original_xyz = np.array([first[k] for k in ("x", "y", "z")])
    local_xyz = original_xyz - np.asarray(info["global2world_translation"])
    frames = info["frame_infos"]
    distances = np.array([
        np.linalg.norm(np.asarray(f["ego2global_original"])[:3, 3] - local_xyz)
        for f in frames
    ])
    matches = np.flatnonzero(distances < 1e-5)
    if len(matches) != 1:
        raise ValueError(f"Need one original-pose match within 10 micrometres, got {len(matches)}")
    index = int(matches[0])
    frame = frames[index]
    original_pose = np.asarray(frame["ego2global_original"])
    yaw = float(np.arctan2(original_pose[1, 0], original_pose[0, 0]))
    heading_delta = float(np.arctan2(np.sin(yaw-first["heading"]), np.cos(yaw-first["heading"])))
    if abs(heading_delta) > 1e-5:
        raise ValueError("Recorded pose heading does not match cache start")
    camera = frame["cams"]["CAM_F0"]
    if not camera.get("valid") or "CAM_F0" not in camera["data_path"]:
        raise ValueError("Invalid source camera metadata")
    metadata = None
    request = None
    saved = None
    for kind, value in entries(asl):
        if kind == "rollout_metadata":
            metadata = value
        elif kind == "aggregated_render_request":
            for rgb in value.rgb_requests:
                if rgb.camera_intrinsics.logical_id == "CAM_F0" and rgb.frame_start_us == 0:
                    request = rgb
        elif kind == "render_request":
            if value.camera_intrinsics.logical_id == "CAM_F0" and value.frame_start_us == 0:
                request = value
        elif kind == "driver_camera_image":
            c = value.camera_image
            if c.logical_id == "CAM_F0" and c.frame_start_us == 0:
                saved = c
                break
    if metadata is None or request is None or saved is None:
        raise ValueError("Missing saved metadata, first render request or image")
    if metadata.session_metadata.scene_id != SCENE or metadata.force_gt_duration < saved.frame_end_us:
        raise ValueError("Wrong scene or not an expert-primed observation")
    gt = metadata.ego_rig_recorded_ground_truth_trajectory.poses[0]
    gt_pose = pose_matrix(gt.pose)
    request_pose = pose_matrix(request.ego_pose.start_pose)
    if gt.timestamp_us != 0 or not np.allclose(gt_pose, request_pose, atol=1e-6):
        raise ValueError("Initial rendering request is not at the recorded expert pose")
    with Image.open(io.BytesIO(saved.image_bytes)) as image:
        image.load()
        rendered_size = list(image.size)
    record = {
        "schema": "real-render-comparison-v1",
        "purpose": "one_scene_visual_diagnostic_only",
        "training_allowed_by_this_artifact": False,
        "scene_id": SCENE,
        "source_log": info["log_name"],
        "city": info["map_location"],
        "camera": "CAM_F0",
        "simulator": "AlpaSim",
        "renderer": "MTGS",
        "saved_base_image_tag": "alpasim-base:0.89.0",
        "saved_run": str(RUN),
        "sources": [{"path": str(p.resolve()), "sha256": sha(p)} for p in (asset, cache, asl)],
        "source_frame_index": index,
        "source_lidar_token": frame["token"],
        "sim_start_source_pose_timestamp_us": int(frame["timestamp"]),
        "source_timestamp_mapping": "unique 3D original ego pose and yaw matching trajdata ego scene_ts=0; ASL first render pose checked against initial GT",
        "real_image_timestamp_us": int(camera["timestamp"]),
        "real_minus_sim_start_us": int(camera["timestamp"])-int(frame["timestamp"]),
        "sim_frame_start_us": int(saved.frame_start_us),
        "sim_frame_end_us": int(saved.frame_end_us),
        "initial_cache_original_pose_delta_m": float(distances[index]),
        "initial_cache_original_heading_delta_rad": heading_delta,
        "reconstruction_original_pose_delta_m": float(np.linalg.norm(np.asarray(frame["ego2global"])[:3, 3]-original_pose[:3, 3])),
        "raw_camera": jsonable(camera),
        "original_ego_pose_in_reconstruction_frame": original_pose.tolist(),
        "trajdata_initial_ego": first,
        "render_camera_intrinsics": MessageToDict(request.camera_intrinsics, preserving_proto_field_name=True),
        "render_sensor_pose": MessageToDict(request.sensor_pose, preserving_proto_field_name=True),
        "render_ego_pose": MessageToDict(request.ego_pose, preserving_proto_field_name=True),
        "rendered_size_wh": rendered_size,
        "rendered_sha256": hashlib.sha256(saved.image_bytes).hexdigest(),
        "original_archive_url": URL,
        "original_archive_revision": REVISION,
        "original_archive_member": "openscene-v1.1/sensor_blobs/test/" + camera["data_path"],
        "limits": [
            "Scene-matched, initial expert-state comparison; not a pixel-exact rendering benchmark.",
            "Real exposure precedes the source pose timestamp; camera intrinsics/distortion and reconstruction calibration differ.",
            "Saved historical renderer source revision is not proven by its image tag; current source need not equal the saved run.",
            "No new render, policy inference, training or evaluation is performed.",
            "No geometric warp, colour correction or generated image is used; original JPEG bytes are preserved.",
            "Do not compute PSNR/SSIM as renderer fidelity before exact camera/time/calibration alignment.",
            "This public-test recording remains diagnostic/evaluation-only; no split is reassigned.",
        ],
    }
    return record, saved.image_bytes


class BoundedReader:
    def __init__(self, stream, cap=BYTE_CAP):
        self.stream = stream
        self.cap = cap
        self.count = 0
        self.start = time.monotonic()

    def read(self, size=-1):
        if time.monotonic()-self.start > 240:
            raise TimeoutError("Archive prefix exceeded four-minute limit")
        left = self.cap-self.count
        if left <= 0:
            raise ValueError("Archive prefix byte cap reached")
        data = self.stream.read(min(left, size if size >= 0 else left))
        self.count += len(data)
        return data


def fetch_original(record):
    target = record["original_archive_member"]
    prefix = target.rsplit("/", 1)[0] + "/"
    request = urllib.request.Request(URL, headers={"Range": f"bytes=0-{BYTE_CAP-1}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        content_range = response.headers.get("Content-Range", "")
        if response.status != 206 or not content_range.startswith("bytes 0-"):
            raise ValueError("Server did not honor bounded range")
        reader = BoundedReader(response)
        scanned = 0
        with tarfile.open(fileobj=reader, mode="r|gz") as archive:
            for member in archive:
                if member.name.rstrip("/") == prefix.rstrip("/") and member.isdir():
                    continue
                if not member.name.startswith(prefix):
                    raise ValueError("Reached end of selected front-camera directory without exact frame")
                if member.name == target:
                    if not member.isfile() or not 0 < member.size <= 8*1024**2:
                        raise ValueError("Invalid target member")
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError("No image stream")
                    payload = source.read(member.size+1)
                    if len(payload) != member.size:
                        raise ValueError("Truncated image")
                    with Image.open(io.BytesIO(payload)) as image:
                        if image.size != tuple(record["rendered_size_wh"]):
                            raise ValueError("Different native image sizes")
                        image.load()
                    return payload, {"compressed_bytes_read": reader.count,
                                     "archive_members_scanned": scanned+1,
                                     "http_content_range": content_range,
                                     "whole_archive_checksum_verified": False}
                scanned += 1
                if scanned % 100 == 0:
                    print(f"Scanned {scanned} front-camera entries; {reader.count/1024**2:.1f} MiB read", flush=True)
        raise ValueError("Exact original image not found")


def report_html(record):
    e = html.escape
    delta = record["real_minus_sim_start_us"] / 1000
    title = "Real camera vs MTGS — one scene"
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{font:16px system-ui,sans-serif;margin:24px;background:#10161d;color:#e6edf3}}
h1{{font-size:25px}} p{{line-height:1.5}} code{{overflow-wrap:anywhere}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:16px;min-width:700px}}
.scroll{{overflow-x:auto}} figure{{margin:0}} img{{width:100%;height:auto;display:block;background:#000}}
figcaption{{padding:12px 0;line-height:1.5}} .notice{{background:#392e13;border-left:4px solid #e9bc50;padding:12px 16px}}
a{{color:#8acbff}} details{{margin-top:20px}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}
</style>
<h1>{title}</h1>
<p>Las Vegas · CAM_F0 · initial expert-primed observation<br><code>{e(SCENE)}</code></p>
<p class="notice"><strong>Near-matched view, not pixel-exact.</strong> The real camera timestamp is {abs(delta):.3f} ms earlier than the simulation's mapped starting pose. Camera calibration differs. Inspect scene content and appearance, not pixel-error scores.</p>
<div class="scroll"><div class="pair">
<figure><a href="real-camera.jpg"><img src="real-camera.jpg" alt="Original captured nuPlan front-camera photograph"></a>
<figcaption><strong>LEFT — real captured camera</strong><br>Original nuPlan image via OpenScene; unchanged JPEG bytes.<br>Exposure timestamp: {record['real_image_timestamp_us']} µs.</figcaption></figure>
<figure><a href="mtgs-render.jpg"><img src="mtgs-render.jpg" alt="Saved MTGS rendered front-camera observation"></a>
<figcaption><strong>RIGHT — simulated MTGS observation</strong><br>Saved AlpaSim image; unchanged JPEG bytes.<br>Simulation frame: 0–17,000 µs, before policy divergence.</figcaption></figure>
</div></div>
<p>Both images: 1920 × 1080, shown at equal display scale without cropping, warping, colour correction or AI generation. Click either image for its native-resolution file.</p>
<p>This pair is evaluation-only. No model inference, new simulation, training or split changes were performed.</p>
<p><a href="README.md">Method and caveats</a> · <a href="manifest.json">Provenance and calibration</a></p>
<details><summary>Matching and provenance details</summary><pre>{e(json.dumps(jsonable(record), indent=2))}</pre></details>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--download", action="store_true", help="Retrieve one JPEG from a maximum 128 MiB archive prefix")
    args = parser.parse_args()
    record, rendered = inspect_source()
    if not args.download:
        print(json.dumps(jsonable(record), indent=2))
        return
    if args.output.exists():
        raise ValueError("Refusing to overwrite comparison directory")
    original, receipt = fetch_original(record)
    record["download_receipt"] = receipt
    record["real_sha256"] = hashlib.sha256(original).hexdigest()
    record["script_sha256"] = sha(__file__)
    record["status"] = "completed_scene_matched_comparison_not_pixel_exact"
    args.output.mkdir(parents=True)
    for name, payload in (("real-camera.jpg", original), ("mtgs-render.jpg", rendered)):
        with (args.output / name).open("xb") as stream:
            stream.write(payload)
    write_json(args.output / "manifest.json", record)
    with (args.output / "comparison.html").open("x") as stream:
        stream.write(report_html(record))
    print(json.dumps({"output": str(args.output), "status": record["status"], **receipt}), flush=True)


if __name__ == "__main__":
    main()
