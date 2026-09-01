#!/usr/bin/env bash
# Sync our modifications into this repo and commit+push them as one restore point.
#   tools/snapshot.sh "message"          (add --no-push to commit only)
# Sources of truth (edited in place, never edited inside this repo):
#   1. this directory's *.md / scripts        -> committed as-is
#   2. ~/alpasim-challenge/alpasim (NVlabs clone) -> our modified + new files exported to alpasim-mods/
#   3. ~/alpasim-challenge/logs/*.sh *.py     -> tools/
set -euo pipefail
MSG="${1:?usage: snapshot.sh \"message\" [--no-push]}"; PUSH=1; [ "${2:-}" = "--no-push" ] && PUSH=0
REPO="$(cd "$(dirname "$0")/.." && pwd)"; CLONE=/home/skr/alpasim-challenge/alpasim; LOGS=/home/skr/alpasim-challenge/logs
MODS="$REPO/alpasim-mods"

# ---- 2. export our changes from the NVlabs clone (full files at their relative paths + a patch of tracked edits)
rm -rf "$MODS/tree"; mkdir -p "$MODS/tree"
( cd "$CLONE"
  git rev-parse HEAD > "$MODS/BASE_COMMIT"
  git diff > "$MODS/tracked-changes.patch"
  { git ls-files -m; git ls-files --others --exclude-standard; } \
    | grep -v -E 'assets/(vavam|vavam-l)/|__pycache__|\.pyc$|\.pt$|\.jit$|\.safetensors$|^runs/|\.log$' | sort -u > "$MODS/files.txt"
  while read -r f; do mkdir -p "$MODS/tree/$(dirname "$f")"; cp -p "$f" "$MODS/tree/$f"; done < "$MODS/files.txt" )

# ---- 3. launcher scripts
cp -p "$LOGS"/*.sh "$REPO/tools/" 2>/dev/null || true; cp -p "$LOGS"/*.py "$REPO/tools/" 2>/dev/null || true

# ---- guards: no big files, no tokens
cd "$REPO"; git add -A
git diff --cached --quiet && { echo "nothing to commit"; exit 0; }
big=$(git diff --cached --name-only --diff-filter=AM | xargs -r -I{} find {} -size +5M 2>/dev/null || true)
[ -n "$big" ] && { echo "REFUSING: files > 5 MB staged:"; echo "$big"; git reset -q; exit 1; }
leak=$(git diff --cached --name-only --diff-filter=AM | xargs -r /bin/grep -l -E 'AKIA[0-9A-Z]{12}|hf_[A-Za-z0-9]{30,}|"token": *"[A-Za-z0-9_-]{40,}' 2>/dev/null || true)
[ -n "$leak" ] && { echo "REFUSING: token-like string in:"; echo "$leak"; git reset -q; exit 1; }

git commit -q -m "$MSG" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git log -1 --format='committed %h  %s'
if [ "$PUSH" = 1 ]; then git push -q origin HEAD && echo "pushed to $(git remote get-url origin)"; fi
