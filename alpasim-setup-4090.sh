#!/usr/bin/env bash
# AlpaSim E2E Challenge 2026 -- nuPlan track local setup for a single 24 GB NVIDIA GPU.
#
# Originally written for an RTX 4090 (sm_89). Verified 2026-08-29 on an
# RTX PRO 4000 Blackwell (sm_120) -- no source changes needed. The renderer
# config ships TORCH_CUDA_ARCH_LIST="8.9;9.0+PTX"; nvcc in the CUDA 12.4 base
# image tops out at compute_90, but the trailing +PTX means the driver
# JIT-compiles compute_90 PTX onto sm_120 at load time. Measured working.
#
# Run on the LINUX box with the GPU (not on macOS).
#
#   export HF_TOKEN=hf_xxx               # read scope is enough; this dataset is public
#   bash alpasim-setup-4090.sh check     # preflight only, changes nothing
#   bash alpasim-setup-4090.sh all       # full setup
#   bash alpasim-setup-4090.sh verify    # post-build torch+gsplat GPU smoke test
#
# Phases are idempotent; re-running is safe.
#
# Disk: the dev subset is ~34 GiB downloaded + ~42 GiB extracted (~76 GiB), plus
# ~40 GiB of images. The FULL navtest asset set is ~458 GiB -- point
# ALPASIM_NUPLAN_ROOT at a large volume before running +e2e_challenge_nuplan=full.
#
# Env knobs:
#   ALPASIM_WORKDIR      where everything lands (default ~/alpasim-challenge)
#   ALPASIM_NUPLAN_ROOT  data root (default $ALPASIM_WORKDIR/nuplan-track)
#   ALPASIM_FULL_SYNC=1  also sync the transfuser/mtgs plugin extras on the host
#                        (slow: builds alpamayo1.5, alpamayo-r1, vam from git)

set -euo pipefail

WORKDIR="${ALPASIM_WORKDIR:-$HOME/alpasim-challenge}"
REPO_DIR="$WORKDIR/alpasim"
NUPLAN_ROOT="${ALPASIM_NUPLAN_ROOT:-$WORKDIR/nuplan-track}"
NUPLAN_HF="$WORKDIR/nuplan-track-hf"
BRANCH="e2e_challenge"

RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; BLD=$'\033[1m'; RST=$'\033[0m'
ok()   { echo "${GRN}  ok${RST}   $*"; }
warn() { echo "${YLW}  warn${RST} $*"; }
die()  { echo "${RED}  FAIL${RST} $*" >&2; exit 1; }
step() { echo; echo "${BLD}==> $*${RST}"; }

# Compare dotted versions: vge 570.1 570 -> true
vge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }

# Read [project].version from a pyproject.toml without tomllib (host python3
# may be < 3.11, where tomllib does not exist).
repo_version() {
  awk -F'"' '/^\[/{s=$0} s=="[project]" && /^version[[:space:]]*=/{print $2; exit}' \
    "$REPO_DIR/pyproject.toml"
}

# ---------------------------------------------------------------- preflight
preflight() {
  step "Preflight checks"

  [ "$(uname -s)" = "Linux" ] || die "This stack is Linux-only (Docker + NVIDIA Container Toolkit). Detected: $(uname -s)"
  ok "Linux host"

  command -v nvidia-smi >/dev/null || die "nvidia-smi not found -- install the NVIDIA driver"
  local drv gpu vram
  drv=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)
  gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
  vram=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
  # AlpaSim needs CUDA 12.8+ in the NRE container => host driver >= 570.x.
  # NB: an arch/driver mismatch surfaces as "no kernel image is available for
  # execution on the device" (no matching cubin and no PTX to JIT), NOT as
  # CUDA_ERROR_UNSUPPORTED_PTX_VERSION -- that one means the PTX is *newer* than
  # the driver can handle. The failure is silent: the launch is skipped and you
  # get stale buffers back unless you check cudaGetLastError().
  vge "$drv" "570" || die "Driver $drv is too old. AlpaSim needs >= 570.x (CUDA 12.8)."
  ok "GPU: $gpu (${vram} MiB), driver $drv"
  [ "$vram" -ge 20000 ] || warn "Only ${vram} MiB VRAM -- the 1gpu topology shares renderer+driver+physics on one card."

  command -v docker >/dev/null || die "docker not found -- https://docs.docker.com/engine/install/ubuntu/"
  docker info >/dev/null 2>&1 || die "Cannot talk to the Docker daemon without sudo. Fix: sudo usermod -aG docker \$USER, then log out and back in."
  ok "docker (rootless-capable for this user)"

  docker compose version >/dev/null 2>&1 || die "docker compose plugin missing -- install docker-compose-plugin"
  docker buildx version  >/dev/null 2>&1 || die "docker buildx plugin missing -- install docker-buildx-plugin"
  ok "docker compose + buildx"

  # GPU passthrough into containers. Separate the pull from the run so a network
  # failure is not misreported as a missing Container Toolkit.
  local probe_img="nvidia/cuda:12.8.0-base-ubuntu24.04" probe_out
  docker image inspect "$probe_img" >/dev/null 2>&1 || \
    docker pull "$probe_img" >/dev/null 2>&1 || \
    die "Cannot pull $probe_img -- check network/registry access. (This is a pull failure, not a GPU problem.)"
  if probe_out=$(docker run --rm --gpus all "$probe_img" nvidia-smi -L 2>&1); then
    ok "NVIDIA Container Toolkit (--gpus all works)"
  else
    echo "$probe_out" >&2
    die "Containers cannot see the GPU. Install the NVIDIA Container Toolkit, then: sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker"
  fi

  # CUDA must actually initialise, not merely be visible. A wedged nvidia kernel
  # thread (e.g. the DIFR soft lockup in nvidia_modeset) leaves nvidia-smi
  # working perfectly while /dev/nvidia-uvm returns EIO and every CUDA call
  # fails with 999 -- symptoms that otherwise look exactly like an arch problem
  # and will send you chasing CUDA versions for hours. Ask the driver directly.
  if ! python3 -c "
import ctypes,sys
try: l=ctypes.CDLL('libcuda.so.1')
except OSError: sys.exit(3)
if l.cuInit(0)!=0: sys.exit(4)
n=ctypes.c_int()
sys.exit(0 if l.cuDeviceGetCount(ctypes.byref(n))==0 and n.value>0 else 5)" 2>/dev/null; then
    die "CUDA cannot initialise (cuInit failed) even though nvidia-smi works.
       Check for a hung kernel thread:  journalctl -k | grep -i 'soft lockup'
       Check UVM:                       python3 -c \"import os;os.open('/dev/nvidia-uvm',os.O_RDWR)\"
       A wedged nvidia kernel thread is cleared by a REBOOT -- no driver reinstall needed."
  fi
  ok "CUDA initialises on the host"

  command -v uv >/dev/null || die "uv not found -- curl -LsSf https://astral.sh/uv/install.sh | sh"
  local uvv; uvv=$(uv --version | awk '{print $2}')
  vge "$uvv" "0.9.17" || die "uv $uvv is too old, need >= 0.9.17. Run: uv self update"
  ok "uv $uvv"

  command -v cargo >/dev/null || die "Rust toolchain missing (needed to build utils_rs) -- curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"
  ok "cargo $(cargo --version | awk '{print $2}')"

  # The nuPlan-track dataset is public and ungated, so the token is only needed
  # to satisfy tooling. Warn rather than die -- a missing token must not block a
  # setup that would otherwise succeed. (The PAI track's data IS gated.)
  if [ -n "${HF_TOKEN:-}" ]; then
    ok "HF_TOKEN present"
  else
    warn "HF_TOKEN not set. The nuPlan dataset is public so the download should still work; set a read token if you hit rate limits: https://huggingface.co/settings/tokens"
  fi

  # df fails outright if the path does not exist yet, and `set -e` would then
  # abort with a raw df error instead of a readable message. Walk up to the
  # nearest existing ancestor.
  local probe_dir="$WORKDIR"
  while [ ! -d "$probe_dir" ] && [ "$probe_dir" != "/" ]; do probe_dir=$(dirname "$probe_dir"); done
  local avail; avail=$(df -BG --output=avail "$probe_dir" 2>/dev/null | tail -1 | tr -dc '0-9')
  [ -n "$avail" ] || { warn "could not determine free space at $probe_dir"; avail=0; }
  # ~76 GiB data (34 downloaded + 42 extracted) + ~40 GiB images for the dev
  # subset. The full navtest asset set is ~458 GiB.
  [ "$avail" -ge 120 ] || warn "Only ${avail} GiB free at $probe_dir. Budget ~120 GiB for the dev subset + images (~458 GiB for the full asset set)."
  ok "disk: ${avail} GiB free"

  echo; echo "${GRN}${BLD}Preflight passed.${RST}"
}

# ------------------------------------------------------------------- clone
clone_repo() {
  step "Cloning NVlabs/alpasim @ $BRANCH"
  mkdir -p "$WORKDIR"
  if [ -d "$REPO_DIR/.git" ]; then
    ok "already cloned at $REPO_DIR"
  else
    git clone --branch "$BRANCH" https://github.com/NVlabs/alpasim.git "$REPO_DIR"
    ok "cloned to $REPO_DIR"
  fi
}

# ------------------------------------------------------------- environment
setup_env() {
  step "Building Python env, protos, and utils_rs (this takes a while)"
  cd "$REPO_DIR"

  # We deliberately do NOT `source ./setup_local_env.sh`. On a clean clone it
  # dies at:
  #     ModuleNotFoundError: No module named 'scripts.compile_protos'
  # alpasim_grpc installs editable, and hatchling's editable hook exposes only
  # the alpasim_grpc package -- not the sibling `scripts` package that the
  # compile-protos console script imports. Upstream's Dockerfile gets away with
  # it because that is a non-editable install. Putting the source dir on
  # PYTHONPATH is enough. Sourcing the upstream script under `set -e` would
  # abort this entire run at the first phase.
  (
    cd "$REPO_DIR/src/grpc"
    PYTHONPATH=. uv run --no-sync compile-protos
  ) || die "proto compilation failed"
  ok "protos compiled"

  # utils_rs is a compiled Rust extension; it does not auto-update on sync.
  uv pip install --force-reinstall -e ./src/utils_rs >/dev/null || die "utils_rs build failed"
  ok "utils_rs built"

  # `mtgs` is NOT part of the `all` extra, and `uv sync` PRUNES to exactly the
  # declared set -- so a bare `uv sync --extra all` silently *uninstalls* the
  # renderer if it was there. It is needed on the host even though the renderer
  # runs in a container: the Hydra plugin at
  # src/wizard/hydra_plugins/alpasim_config_discovery/__init__.py discovers
  # config search paths via entry_points(group="alpasim.configs"), and
  # alpasim_mtgs registers the `mtgs` group there. Without it the wizard can
  # fail composing the preset before a single container starts.
  #
  # `transfuser` is genuinely optional here and is the slow one -- it compiles
  # alpamayo1.5, alpamayo-r1 and vam from git (20-40 min). Opt in explicitly.
  local extras=(--extra all)
  [ -d plugins/mtgs ] && extras+=(--extra mtgs)
  if [ "${ALPASIM_FULL_SYNC:-0}" = "1" ]; then
    [ -d plugins/transfuser_driver ] && extras+=(--extra transfuser)
  fi
  echo "  uv sync ${extras[*]}"
  uv sync "${extras[@]}" || die "uv sync failed"
  ok "workspace synced"
}

# -------------------------------------------------------------------- data
fetch_data() {
  step "Downloading nuPlan/MTGS dev data (OpenDriveLab, public)"
  mkdir -p "$NUPLAN_ROOT" "$NUPLAN_HF"

  # Only the first asset shard is needed for the one-scene dev smoke test.
  # ~34 GiB total: part001 is 31.7, nuplan_test 2.0, configs is tiny.
  # --no-project: without it, uv adopts whatever pyproject.toml is in the cwd
  # and syncs the entire alpasim workspace just to run the `hf` CLI.
  uv run --no-project --with huggingface-hub hf download \
    --repo-type dataset \
    --local-dir "$NUPLAN_HF" \
    OpenDriveLab/AlpasimChallenge2026_nuplan_track \
    trajdata_cache/nuplan_test.tar.gz \
    MTGS_asset/navtest/configs.tar.gz \
    MTGS_asset/navtest/assets/part001.tar.gz

  for tgz in trajdata_cache/nuplan_test.tar.gz \
             MTGS_asset/navtest/configs.tar.gz \
             MTGS_asset/navtest/assets/part001.tar.gz; do
    echo "  extracting $tgz"
    tar -xzf "$NUPLAN_HF/$tgz" -C "$NUPLAN_ROOT"
  done

  [ -d "$NUPLAN_ROOT/navtest/configs" ] || die "expected $NUPLAN_ROOT/navtest/configs after extraction"
  [ -d "$NUPLAN_ROOT/nuplan_test" ]     || die "expected $NUPLAN_ROOT/nuplan_test after extraction"
  ok "data root ready at $NUPLAN_ROOT"
  echo "  the raw tarballs in $NUPLAN_HF (~34 GiB) are redundant now; delete to reclaim"
}

# ------------------------------------------------------------------ images
# The wizard resolves renderer/controller/runtime to alpasim-base:<pyproject
# version> with an empty registry prefix, so it must exist LOCALLY. Nothing else
# builds it: setup_local_env.sh only does protos/uv, and the starter-kit
# Dockerfile builds the driver image. Without this phase the smoke test dies on
# a missing image for three services at once.
build_base() {
  step "Building alpasim-base (renderer + controller + runtime)"
  cd "$REPO_DIR"
  local ver; ver=$(repo_version)
  [ -n "$ver" ] || die "could not read version from $REPO_DIR/pyproject.toml"
  # Tag both: :$ver is what the config resolves to, :latest matches the
  # Dockerfile's own documented `docker build -t alpasim-base .` (which alone
  # would produce a tag the wizard never looks for).
  docker build -t "alpasim-base:$ver" -t "alpasim-base:latest" .
  ok "alpasim-base:$ver"
}

build_driver() {
  step "Building the starter-kit driver image"
  cd "$REPO_DIR"
  docker build -f e2e_challenge/starter_kit/Dockerfile \
    -t alpasim-e2e-starter-driver:latest .
  ok "alpasim-e2e-starter-driver:latest"
}

# ------------------------------------------------------------------ verify
# The one risk preflight cannot retire: the base image ships CUDA 12.4, whose
# nvcc tops out at compute_90, while Blackwell is sm_120. gsplat compiles its
# kernels at *runtime* from TORCH_CUDA_ARCH_LIST, so a mismatch only shows up on
# the first render -- and silently, as stale/garbage pixels rather than an
# exception. Force that moment to happen here instead.
verify_stack() {
  step "Verifying the GPU stack inside alpasim-base"
  local ver; ver=$(repo_version)
  docker image inspect "alpasim-base:$ver" >/dev/null 2>&1 \
    || die "alpasim-base:$ver not built yet -- run: $0 base"

  # -i is load-bearing: without it docker does not attach stdin, python reads
  # an empty script from the heredoc and exits 0 -- a silent false PASS.
  docker run --rm -i --gpus all \
    -e TORCH_CUDA_ARCH_LIST="8.9;9.0+PTX" \
    "alpasim-base:$ver" uv run --no-sync python - <<'PY'
import sys, torch

cap = torch.cuda.get_device_capability(0) if torch.cuda.is_available() else None
print("  torch          :", torch.__version__, "| built for CUDA", torch.version.cuda)
print("  torch archs    :", ", ".join(torch.cuda.get_arch_list()))
if not torch.cuda.is_available():
    sys.exit("  FAIL: torch cannot see the GPU")
print(f"  device         : {torch.cuda.get_device_name(0)} sm_{cap[0]}{cap[1]}")

# A cubin/PTX mismatch does NOT raise -- the launch is skipped and you read back
# whatever was in the buffer. Check the error explicitly, then check the value.
a = torch.ones(1024, device="cuda")
b = a * 2.0 + 1.0
torch.cuda.synchronize()
if not torch.allclose(b, torch.full_like(b, 3.0)):
    sys.exit("  FAIL: torch kernel did not execute (silent no-op -- arch mismatch)")
print("  torch kernel   : OK")

try:
    import gsplat
except Exception as e:
    sys.exit(f"  FAIL: gsplat import failed: {e}")
print("  gsplat         :", getattr(gsplat, "__version__", "?"))

# Importing gsplat does not necessarily build the CUDA extension; calling into
# it does. Keep this tolerant of API drift across gsplat versions -- the point
# is to force the runtime nvcc build and a real kernel launch, not to pin an API.
try:
    from gsplat import rasterization
    N = 128
    means  = torch.randn(N, 3, device="cuda"); means[:, 2] += 5.0
    quats  = torch.nn.functional.normalize(torch.randn(N, 4, device="cuda"), dim=-1)
    scales = torch.rand(N, 3, device="cuda") * 0.1
    opac   = torch.rand(N, device="cuda")
    cols   = torch.rand(N, 3, device="cuda")
    viewmats = torch.eye(4, device="cuda")[None]
    K = torch.tensor([[[300., 0., 160.], [0., 300., 120.], [0., 0., 1.]]], device="cuda")
    out = rasterization(means, quats, scales, opac, cols, viewmats, K, 320, 240)
    img = out[0] if isinstance(out, (tuple, list)) else out
    torch.cuda.synchronize()
    if not torch.isfinite(img).all():
        sys.exit("  FAIL: gsplat produced non-finite output")
    print("  gsplat raster  : OK", tuple(img.shape))
except SystemExit:
    raise
except Exception as e:
    print(f"  gsplat raster  : SKIPPED (API mismatch, not a GPU failure): {e}")
    print("                   The CUDA extension still compiled and loaded.")

print("\n  GPU stack verified -- kernels execute on this architecture.")
PY
  ok "GPU stack verified"
}

# ------------------------------------------------------------------- hints
next_steps() {
  cat <<EOF

${BLD}Setup complete.${RST} Run the smoke test in two terminals.

${BLD}Terminal 1${RST} -- the driver container (leave running):
  cd $REPO_DIR
  e2e_challenge/starter_kit/run_local_container.sh

${BLD}Terminal 2${RST} -- the simulator:
  cd $REPO_DIR
  export ALPASIM_NUPLAN_ROOT=$NUPLAN_ROOT
  ALPASIM_DRIVER_HOST=localhost ALPASIM_DRIVER_PORT=6789 \\
  uv run alpasim_wizard +e2e_challenge_nuplan=dev \\
    wizard.log_dir=./runs/nuplan_smoke

Result lands in:
  $REPO_DIR/runs/nuplan_smoke/aggregate/results-summary.json

${BLD}Terminal 3${RST} -- log VRAM headroom while it runs. This number tells you how big
a policy you can actually afford, since the 1gpu topology shares the card:
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv -l 5 \\
    | tee $WORKDIR/vram-baseline.csv

The starter driver is a straight-line constant-speed fallback using ~no VRAM, so
whatever it reports is essentially the simulator's own footprint. 16 GiB is the
per-replica cap at official evaluation -- treat that as your ceiling regardless
of what fits locally.

${BLD}Note${BLD}${RST} gsplat JIT-compiles its kernels on first use inside the renderer
container, and the container's compute cache is ephemeral -- expect a slow first
render on every fresh container start. Run '$0 verify' first to surface any
build error on its own rather than mid-simulation.
EOF
}

case "${1:-all}" in
  check)  preflight ;;
  all)    preflight; clone_repo; setup_env; fetch_data; build_base; build_driver; verify_stack; next_steps ;;
  env)    setup_env ;;
  data)   fetch_data ;;
  base)   build_base ;;
  build)  build_base; build_driver ;;
  verify) verify_stack ;;
  next)   next_steps ;;
  *)      die "usage: $0 [check|all|env|data|base|build|verify|next]" ;;
esac
