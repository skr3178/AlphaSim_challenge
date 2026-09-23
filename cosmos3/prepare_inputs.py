"""Extract first clean front-camera observation from two existing public ASL logs."""
import hashlib
import io
import json
from pathlib import Path
import struct

from alpasim_grpc.v0.logging_pb2 import LogEntry
from PIL import Image

BASE = Path(__file__).resolve().parent / "artifacts" / "inputs"
SOURCES = [
    Path("/home/skr/alpasim-challenge/alpasim/runs/confirm400-mup-g100/rollouts/2021.05.25.14.24.08_veh-25_04059_04203-5395d42cc65e5c06/2c84f1fc-a527-11f1-815b-7bf8f4305fac/rollout.asl"),
    Path("/home/skr/alpasim-challenge/logs/success-videos/asl/turn__2021.09.16.14.39.34_veh-42_00297_00935-c7a44a2e52bc5e22/b17043a2-a528-11f1-815b-7bf8f4305fac/rollout.asl"),
]
BASE.mkdir(exist_ok=True, parents=True)
manifest = []
for index, path in enumerate(SOURCES):
    with path.open("rb") as stream:
        while prefix := stream.read(4):
            if len(prefix) != 4:
                raise RuntimeError("Truncated ASL prefix")
            size = struct.unpack(">L", prefix)[0]
            if size > 100_000_000:
                raise RuntimeError("Unexpected ASL message size")
            payload = stream.read(size)
            if len(payload) != size:
                raise RuntimeError("Truncated ASL entry")
            entry = LogEntry.FromString(payload)
            if entry.WhichOneof("log_entry") != "driver_camera_image":
                continue
            camera = entry.driver_camera_image.camera_image
            if camera.logical_id != "CAM_F0" or not camera.image_bytes:
                continue
            image = Image.open(io.BytesIO(camera.image_bytes)).convert("RGB")
            destination = BASE / f"front_{index}.png"
            if destination.exists():
                raise RuntimeError(f"Refusing to overwrite {destination}")
            image.save(destination)
            manifest.append({"source_asl": str(path.resolve()), "output": str(destination),
                             "camera": camera.logical_id, "frame_start_us": camera.frame_start_us,
                             "frame_end_us": camera.frame_end_us, "size": list(image.size),
                             "source_image_bytes_sha256": hashlib.sha256(camera.image_bytes).hexdigest(),
                             "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                             "selection": "first logged nonempty CAM_F0 observation; no overlays or future frames"})
            print(json.dumps(manifest[-1]), flush=True)
            break
        else:
            raise RuntimeError(f"No front camera bytes in {path}")
(BASE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
