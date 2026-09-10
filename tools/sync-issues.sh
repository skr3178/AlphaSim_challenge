#!/usr/bin/env bash
# Mirror NVlabs/alpasim issues locally. Idempotent: re-fetches the index every time,
# and re-fetches any issue whose updatedAt is newer than the local copy.
# usage: tools/sync-issues.sh [--all]     (--all re-fetches every issue body)
set -u
cd "$(dirname "$0")/.."; mkdir -p issues
gh issue list --repo NVlabs/alpasim --state all --limit 400 \
  --json number,title,state,labels,createdAt,updatedAt,author > issues/index.json || exit 1
python3 - "${1:-}" <<'PY'
import json, os, subprocess, sys
force = sys.argv[1] == "--all" if len(sys.argv) > 1 else False
idx = json.load(open("issues/index.json"))
new = stale = 0
for it in idx:
    n, up = it["number"], it.get("updatedAt")
    p = f"issues/{n}.json"
    if os.path.exists(p) and not force:
        try:
            if json.load(open(p)).get("_updatedAt") == up: continue
            stale += 1
        except Exception: pass
    else:
        new += 1
    r = subprocess.run(["gh","issue","view",str(n),"--repo","NVlabs/alpasim","--json",
        "number,title,state,body,labels,comments,createdAt,closedAt,author"],
        capture_output=True, text=True)
    if r.returncode: continue
    d = json.loads(r.stdout); d["_updatedAt"] = up
    json.dump(d, open(p,"w"), indent=1)
print(f"issues: {len(idx)} indexed, {new} new, {stale} updated")
PY
