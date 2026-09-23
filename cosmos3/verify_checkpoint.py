"""Verify checkpoint weight sizes and SHA-256 against the pinned HF manifest."""
import hashlib
import json
from pathlib import Path
import time

root = Path("/media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918")
manifest = json.loads((root / "download-manifest.json").read_text())
results = []
for entry in manifest["files"]:
    if not entry["path"].endswith(".safetensors"):
        continue
    path = root / "checkpoint" / entry["path"]
    started = time.monotonic()
    if path.stat().st_size != entry["size"]:
        raise SystemExit(f"Size mismatch: {path}")
    with path.open("rb") as source:
        digest = hashlib.sha256()
        for block in iter(lambda: source.read(8 * 1024 ** 2), b""):
            digest.update(block)
        actual = digest.hexdigest()
    record = {"path": entry["path"], "size": path.stat().st_size, "sha256": actual,
              "matches": actual == entry["sha256"], "seconds": time.monotonic()-started}
    print(json.dumps(record), flush=True)
    results.append(record)
    if not record["matches"]:
        raise SystemExit(f"SHA-256 mismatch: {path}; preserved file, no automatic removal")
(root / "verification.json").write_text(json.dumps({"revision": manifest["revision"], "weights": results}, indent=2)+"\n")
