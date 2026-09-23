"""Download a pinned public checkpoint; never run inference or evaluation."""
import json
import os
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "60")

from huggingface_hub import HfApi, snapshot_download

REPO = "nvidia/Cosmos3-Edge"
REVISION = "344d602b128d1bbdacb43b08d0a3626f46343e29"
ROOT = Path("/media/skr/SeagateHub1/cosmos3-edge-feasibility-20260918")

if not Path("/media/skr/SeagateHub1").is_mount():
    raise SystemExit("Seagate is not mounted; refusing download")
ROOT.mkdir(exist_ok=True)
started = time.time()
print(f"Downloading {REPO}@{REVISION} to {ROOT / 'checkpoint'}", flush=True)
info = HfApi().model_info(REPO, revision=REVISION, files_metadata=True)
manifest = {
    "repo": REPO,
    "revision": info.sha,
    "started_at_unix": started,
    "files": [
        {"path": s.rfilename, "size": s.size,
         "sha256": getattr(s.lfs, "sha256", None)}
        for s in info.siblings
        if not s.rfilename.startswith(("assets/", "images/"))
    ],
}
(ROOT / "download-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
snapshot_download(
    REPO, revision=REVISION, local_dir=ROOT / "checkpoint", max_workers=2,
    ignore_patterns=["assets/*", "images/*"],
)
manifest["completed_at_unix"] = time.time()
manifest["elapsed_seconds"] = time.time() - started
(ROOT / "download-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"Completed in {manifest['elapsed_seconds']:.1f} seconds", flush=True)
