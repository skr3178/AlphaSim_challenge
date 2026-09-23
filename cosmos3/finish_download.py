"""Resume the slow final shard using validated HTTP ranges; preserve partials."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import urllib.request

ROOT = Path("/media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918")
MANIFEST = ROOT / "download-manifest.json"
PREFIX = ROOT / "checkpoint/.cache/huggingface/download/transformer/vk2LiEyDcQ1hxk9SVeqFhwEoIws=.116134e5492c514df79a2f07214e577c397aa961387dbe1c5dda488e7994ff6b.3a0a083c.incomplete"
manifest = json.loads(MANIFEST.read_text())
entry = next(x for x in manifest["files"] if x["path"] == "transformer/diffusion_pytorch_model-00001-of-00002.safetensors")
destination = ROOT / "checkpoint" / entry["path"]
if destination.exists():
    raise SystemExit("Final shard already exists; use verify_checkpoint.py")
if not PREFIX.is_file() or PREFIX.is_symlink():
    raise SystemExit("Expected owned partial file not found")
prefix_size = PREFIX.stat().st_size
if not 0 < prefix_size < entry["size"]:
    raise SystemExit("Unexpected partial size")
parts = ROOT / f"ranges-from-{prefix_size}"
parts.mkdir(exist_ok=True)
url = f"https://huggingface.co/nvidia/Cosmos3-Edge/resolve/{manifest['revision']}/{entry['path']}"
chunk_size = 512 * 1024 ** 2
ranges = [(start, min(start + chunk_size, entry["size"]) - 1)
          for start in range(prefix_size, entry["size"], chunk_size)]
print(f"Preserving {prefix_size} existing bytes; downloading {len(ranges)} ranges with 4 workers", flush=True)

def fetch(bounds):
    start, end = bounds
    path = parts / f"{start}-{end}.part"
    expected = end - start + 1
    for attempt in range(8):
        completed = path.stat().st_size if path.exists() else 0
        if completed == expected:
            return path
        if completed > expected:
            raise RuntimeError(f"Oversized range file: {path}")
        offset = start + completed
        request = urllib.request.Request(
            url + f"?range_start={offset}", headers={"Range": f"bytes={offset}-{end}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                actual_range = response.headers.get("Content-Range")
                required_range = f"bytes {offset}-{end}/{entry['size']}"
                if response.status != 206 or actual_range != required_range:
                    raise RuntimeError(f"Unexpected range response: {response.status}, {actual_range}")
                with path.open("ab") as target:
                    copied = completed
                    while block := response.read(1024 * 1024):
                        copied += len(block)
                        if copied > expected:
                            raise RuntimeError("Range response exceeded expected length")
                        target.write(block)
            if path.stat().st_size != expected:
                raise RuntimeError("Incomplete range")
            print(f"Range completed: {start}-{end}", flush=True)
            return path
        except Exception as exc:
            print(f"Range {start}-{end}: retry {attempt+1}: {type(exc).__name__}", flush=True)
            if attempt == 7:
                raise
            time.sleep(min(10 * (attempt+1), 60))

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    completed_parts = list(pool.map(fetch, ranges))
if PREFIX.stat().st_size != prefix_size:
    raise SystemExit("Original downloader still writing; refusing assembly")
assembled = ROOT / "checkpoint/transformer/assembled-first-shard.partial"
if not assembled.exists():
    with assembled.open("xb") as target:
        with PREFIX.open("rb") as source:
            shutil.copyfileobj(source, target, length=8 * 1024 ** 2)
        for part in completed_parts:
            with part.open("rb") as source:
                shutil.copyfileobj(source, target, length=8 * 1024 ** 2)
        target.flush()
        os.fsync(target.fileno())
if assembled.stat().st_size != entry["size"]:
    raise SystemExit("Assembled size mismatch")
with assembled.open("rb") as source:
    digest = hashlib.sha256()
    for block in iter(lambda: source.read(8 * 1024 ** 2), b""):
        digest.update(block)
    actual = digest.hexdigest()
if actual != entry["sha256"]:
    raise SystemExit("Assembled hash mismatch; all files preserved")
assembled.rename(destination)
manifest["completed_at_unix"] = time.time()
manifest["elapsed_seconds"] = time.time() - manifest["started_at_unix"]
manifest["final_shard_download"] = "HTTP range resume, SHA-256 verified; original partial and ranges preserved"
MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
print(f"Complete: {destination}; SHA-256 verified", flush=True)
