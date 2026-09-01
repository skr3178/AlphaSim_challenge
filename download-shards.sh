#!/usr/bin/env bash
# AlpaSim nuPlan track -- relocate the data root to /media/skr/storage and stream-extract extra
# MTGS asset shards there. Idempotent; safe to re-run (each phase checks its own result).
#
#   bash download-shards.sh plan       # print what would happen, change nothing
#   bash download-shards.sh relocate   # phase 1: move existing 42 GB root to storage + symlink + env
#   bash download-shards.sh shards     # phase 2: stream-extract shards (default 007 009 014), ~2.5-3 h
#   bash download-shards.sh groups     # phase 3: regenerate scene-group yamls from what is on disk
#   bash download-shards.sh all        # 1 -> 2 -> 3
#
# Run phase 2 detached so it survives terminal/session loss:
#   setsid nohup bash download-shards.sh shards > ~/alpasim-challenge/logs/shards.log 2>&1 < /dev/null &
#   tail -f ~/alpasim-challenge/logs/shards.log
set -euo pipefail

# Default: extract IN PLACE into the existing root on /home (no relocation).
# Set ALPASIM_NEW_ROOT=/media/skr/storage/alpasim-nuplan-track and run "relocate" to use the storage disk instead.
NEW_ROOT="${ALPASIM_NEW_ROOT:-$HOME/alpasim-challenge/nuplan-track}"
OLD_ROOT="$HOME/alpasim-challenge/nuplan-track"
REPO="$HOME/alpasim-challenge/alpasim"
SHARDS="${SHARDS:-007 009}"              # Boston, Pittsburgh (we already have Vegas part001); add 014 for Singapore later
HF=https://huggingface.co/datasets/OpenDriveLab/AlpasimChallenge2026_nuplan_track/resolve/main/MTGS_asset/navtest/assets

GRN=$'\033[32m'; YLW=$'\033[33m'; RED=$'\033[31m'; BLD=$'\033[1m'; RST=$'\033[0m'
ok(){ echo "${GRN}  ok${RST}   $*"; }; warn(){ echo "${YLW}  warn${RST} $*"; }; die(){ echo "${RED}  FAIL${RST} $*" >&2; exit 1; }
step(){ echo; echo "${BLD}==> $*${RST}"; }
free_gb(){ df -BG --output=avail "$1" | tail -1 | tr -dc '0-9'; }
DISK(){ df --output=target "$NEW_ROOT" 2>/dev/null | tail -1; }

plan() {
  step "Plan"
  echo "  data root  : $OLD_ROOT  ->  $NEW_ROOT"
  echo "  shards     : $SHARDS   (each ~31 GB download, ~38 GB extracted, streamed: no tarball on disk)"
  local disk; disk=$(df --output=target "$(dirname "$NEW_ROOT")" | tail -1)
  echo "  disk       : $(free_gb "$(dirname "$NEW_ROOT")") GB free on $disk"
  local need=$(( 38 * $(echo $SHARDS | wc -w) )); [ "$NEW_ROOT" = "$OLD_ROOT" ] || need=$((need+42))
  echo "  need       : ~${need} GB (38 per shard extracted$( [ "$NEW_ROOT" = "$OLD_ROOT" ] || echo " + 42 relocated root"))"
  [ "$(free_gb "$(dirname "$NEW_ROOT")")" -ge "$need" ] && ok "fits" || warn "does NOT fit -- drop a shard (SHARDS=\"007 009\") or free space"
  echo "  assets now : $(ls "$OLD_ROOT/navtest/assets" 2>/dev/null | wc -l) scenes at $OLD_ROOT"
}

relocate() {
  step "Phase 1: relocate data root to $NEW_ROOT"
  [ "$NEW_ROOT" != "$OLD_ROOT" ] || { ok "in-place mode (NEW_ROOT == existing root): nothing to relocate"; return; }
  if [ -L "$OLD_ROOT" ] && [ "$(readlink -f "$OLD_ROOT")" = "$NEW_ROOT" ]; then ok "already relocated (symlink in place)"; return; fi
  [ -d "$OLD_ROOT/navtest/assets" ] || die "expected $OLD_ROOT/navtest/assets"
  mkdir -p "$NEW_ROOT"
  rsync -a --info=progress2 "$OLD_ROOT/" "$NEW_ROOT/"
  local a b; a=$(find "$OLD_ROOT" -type f | wc -l); b=$(find "$NEW_ROOT" -type f | wc -l)
  [ "$a" -eq "$b" ] || die "file count mismatch after rsync: $a vs $b"
  ok "copied $b files"
  mv "$OLD_ROOT" "$OLD_ROOT.old"
  ln -s "$NEW_ROOT" "$OLD_ROOT"
  ok "symlink $OLD_ROOT -> $NEW_ROOT  (old copy kept at $OLD_ROOT.old; delete after a successful smoke run)"
  grep -q 'ALPASIM_NUPLAN_ROOT=' "$HOME/.bashrc" || echo "export ALPASIM_NUPLAN_ROOT=$NEW_ROOT" >> "$HOME/.bashrc"
  ok "ALPASIM_NUPLAN_ROOT=$NEW_ROOT added to ~/.bashrc (open a new shell, or export it now)"
}

shards() {
  step "Phase 2: stream-extract shards into $NEW_ROOT  (SHARDS=$SHARDS)"
  [ -d "$NEW_ROOT/navtest" ] || die "$NEW_ROOT/navtest missing -- run 'relocate' first"
  for p in $SHARDS; do
    local before after url="$HF/part$p.tar.gz"
    before=$(ls "$NEW_ROOT/navtest/assets" | wc -l)
    echo "  [$(date +%H:%M)] part$p: $(free_gb "$NEW_ROOT") GB free, $before scenes present"
    [ "$(free_gb "$NEW_ROOT")" -ge 45 ] || die "less than 45 GB free -- stopping before part$p"
    # stream: no tarball on disk. On failure, re-run this phase: tar simply overwrites the partial scene dirs.
    local try
    for try in 1 2 3; do
      if curl -L --fail --retry 5 --retry-delay 10 -sS "$url" | tar -xzf - -C "$NEW_ROOT"; then break; fi
      warn "part$p attempt $try failed; retrying"; sleep 30
      [ "$try" -eq 3 ] && die "part$p failed 3 times"
    done
    after=$(ls "$NEW_ROOT/navtest/assets" | wc -l)
    ok "[$(date +%H:%M)] part$p done: +$((after-before)) scenes (total $after)"
  done
  # every asset dir must be complete: background ckpt + height map + video dict
  local bad=0
  for d in "$NEW_ROOT"/navtest/assets/*/; do
    [ -f "$d/video_scene_dict.pkl" ] && [ -d "$d/background" ] && [ -f "$d/road_height_map/road_height_map.npy" ] || { warn "incomplete: $(basename "$d")"; bad=$((bad+1)); }
  done
  [ "$bad" -eq 0 ] && ok "all $(ls "$NEW_ROOT/navtest/assets" | wc -l) asset dirs complete" || warn "$bad incomplete asset dirs -- re-run 'shards'"
}

groups() {
  step "Phase 3: regenerate scene groups from assets on disk"
  local cfgdir="$REPO/src/wizard/configs/nuplan_scenes"
  local out="$cfgdir/navtest_local.yaml" n=0 miss=0
  { echo "# @package _global_"; echo "# LOCAL: every navtest scene whose MTGS assets are on this machine. Generated $(date +%F) by download-shards.sh"; echo "scenes:"; echo "  scene_ids:"; } > "$out"
  for s in $(ls "$NEW_ROOT/navtest/assets" | sort); do
    if [ -f "$NEW_ROOT/navtest/configs/$s.yaml" ]; then echo "    - $s" >> "$out"; n=$((n+1)); else miss=$((miss+1)); fi
  done
  ok "$out: $n scenes ($miss without config skipped)"
  # per-city groups, from the configs' city field
  python3 - "$NEW_ROOT" "$cfgdir" <<'PY'
import sys, os, re, collections
root, cfgdir = sys.argv[1], sys.argv[2]
by = collections.defaultdict(list)
for s in sorted(os.listdir(f"{root}/navtest/assets")):
    p = f"{root}/navtest/configs/{s}.yaml"
    if not os.path.exists(p): continue
    city = re.search(r"city: (\S+)", open(p).read()).group(1)
    key = {"us-nv-las-vegas-strip":"vegas","us-ma-boston":"boston","us-pa-pittsburgh-hazelwood":"pittsburgh","sg-one-north":"singapore"}.get(city, city)
    by[key].append(s)
for city, ids in by.items():
    with open(f"{cfgdir}/navtest_local_{city}.yaml", "w") as f:
        f.write(f"# @package _global_\n# LOCAL: on-disk navtest scenes in {city} ({len(ids)}). Generated by download-shards.sh\nscenes:\n  scene_ids:\n")
        f.writelines(f"    - {s}\n" for s in ids)
    print(f"  navtest_local_{city}.yaml: {len(ids)} scenes")
PY
  echo
  echo "  run:  ALPASIM_NUPLAN_ROOT=$NEW_ROOT uv run --no-sync alpasim_wizard +e2e_challenge_nuplan=dev nuplan_scenes=navtest_local scenes.limit_to_first_n=0 wizard.log_dir=./runs/<name>"
}

case "${1:-plan}" in
  plan) plan ;;
  relocate) relocate ;;
  shards) shards ;;
  groups) groups ;;
  all) plan; shards; groups ;;
  *) die "usage: $0 [plan|relocate|shards|groups|all]" ;;
esac
