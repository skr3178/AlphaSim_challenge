# AlpaSim E2E Challenge 2026 — nuPlan track, local setup notes

Host: `skr@linux` · Working dir: `~/alpasim-challenge` · Setup script: `alpasim-setup-4090.sh`
Last updated: **2026-08-29 ~12:20 IST**

> **🏆 2026-08-30 — team-lucifer is on the official nuPlan leaderboard: rank 6, PCS 1590.4** (stock
> VaVAM-B, first submission, calibration successful — see §6.11).
>
> **🏁 MILESTONE 2026-08-29 12:12 — the full nuPlan smoke test PASSED end to end on this
> machine.** One scene, all four services, real renders, real metrics, video output, zero
> collisions, exit 0. The question this document existed to answer — *can this machine run
> the challenge?* — is closed: **yes**. Results in §6.5; peak simulator VRAM was **5.6 GiB
> of 24.5** (§6.5). Two more defects were found and fixed on the way (Defects 4 and 5).

This records what is actually on the box, what has been verified, what is broken and
why, and what is predicted but not yet reproduced. Claims are tagged:

- **[VERIFIED]** — observed directly on this machine, command given.
- **[INFERRED]** — deduced from file contents/timestamps, not observed running.
- **[PREDICTED]** — reasoned from source + hardware, **not yet reproduced**.

---

## 0. Status at a glance

Legend: 🟢 done / passing · 🟡 partial or unverified · 🔴 not done / broken

### Setup phases

- 🟢 **DONE** — Clone repo — `e2e_challenge` @ `f012862`, clean tree
- 🟢 **DONE** — Download + extract data — navtest 38 G, nuplan_test 4.4 G, all 3 tarballs
- 🟢 **DONE** — Preflight gates — **10/10 pass** as of 12:30, `HF_TOKEN` now set and validated (`skr3178`, role `read`)
- 🟢 **DONE** — Python env (home clone) — protos ✅, `utils_rs` ✅, wizard ✅, torch 2.8.0+cu128 ✅, MTGS restored ✅ (gsplat 1.5.3). Downloads clone still has no venv (by choice)
- 🟢 **DONE 12:05** — `alpasim-base:0.89.0` built, 20.8 GB (also tagged `:latest`)
- 🟢 **DONE 2026-08-29 ~11:49** — `alpasim-e2e-starter-driver:latest` built (261 MB) and sanity-checked: container starts, listens on 0.0.0.0:6789, port open
- 🟢 **PASSED 12:12** — smoke test (attempt 2): one scene, 200 sim-steps config, all services healthy, `results-summary.json` + videos produced, wizard exit 0. Attempt 1 had failed on Defect 5 (controller import)
- 🟢 **DONE** — VRAM baseline: **peak 5 594 MiB / 24 467** during the passing run (`~/alpasim-challenge/logs/vram-baseline.csv`) → ~18.9 GiB headroom for a local policy next to the simulator

### Defects

- 🟢 **FIXED** — Defect 1: `build_base` used `tomllib` on host Python 3.10 → aborted the whole `all` run after 42 GB of work. Patched to awk, verified → `0.89.0`
- 🟢 **FIXED 2026-08-29 ~11:50** — Defect 2: `alpasim_mtgs` + `gsplat` were pruned by a "lean sync". Restored via `bash alpasim-setup-4090.sh env` — gate verified: `import alpasim_mtgs` OK, gsplat 1.5.3, utils_rs + wizard intact
- 🔴 **OPEN** — Defect 3 **(new)**: `setup_local_env.sh` fails on a clean run — `ModuleNotFoundError: No module named 'scripts.compile_protos'`. This invalidates the fix previously recommended for Defect 2
- 🟢 **FIXED, verified end-to-end** — Defect 5: upstream leaves `casadi` **unconstrained** (and `uv.lock` is gitignored), so a fresh resolve picks **casadi 3.8.0**, incompatible with **do-mpc 5.1.1** — controller container dies at import (`casadi.tools has no attribute 'SX'`). Reproduced on host venv too, so it hits any fresh build of `e2e_challenge` HEAD (`f012862`). Fix: `casadi<3.8` in `src/controller/pyproject.toml` → lock now 3.7.2; verified `do_mpc` + `mpc_controller` import. **Worth filing upstream.**
- 🟢 **FIXED** — Defect 4: `verify_stack()` false PASS — `docker run` without `-i` never delivered the heredoc; python ran an empty script and exited 0. Fixed with `-i` (marked load-bearing in the script)
- 🟢 **FOUND 2026-08-30, FIX VALIDATED 2026-08-31** (at-fault distance 0.51→1.11 km on 300 scenes) — Defect 7: **the VAVAM sample discards the μP base shapes.** `vavam_policy.py` sets `gpt_mup_base_shapes = action_mup_base_shapes = None`, but the checkpoint carries them (`ckpt["gpt_mup_base_shapes"]`, `ckpt["action_mup_base_shapess"]`, base width 256) and the repo's own loader applies them. The action decoder is a `MuReadout` (output ÷ `width_mult`): B runs with width_mult 1 instead of **4**, L with 1 instead of **8**. Effect on one frame (CPU, seed 0): B endpoint 34.7 m → 27.5 m at 3 s with correct shapes; **L is garbage without them** (20 m lateral jump) and a clean straight path with them. Fix: opt-in patch `VAVAM_MUP_SHAPES_DIR` in `vavam_policy.py` + `assets/mup_shapes/*.bsh`; images `:local-mup` (B) and `:local-l-mup` (L). **Measured 2026-08-31 00:14, same 300 scenes (Vegas/Boston/Pittsburgh), stock sample vs μP-corrected B:**
at-fault distance **0.51 → 1.11 km (2.2×)**, at-fault collisions **6 % → 3 %**, any collision 8 % → 4 %,
dist_to_gt 3.40 → 2.16 m, lateral 1.84 → 1.33 m, wrong-lane 37 % → 29 %, progress 1.05 → 1.01 (drives at
human speed instead of 5 % fast). Every metric improved. **This is the first validated submission
candidate.** The submitted image and every team using the sample carry this bug
- 🟢 **Fast eval preset validated 2026-08-31** — `dev_fast` (CAM_F0 only + no eval video): 7.4 s/scene vs ~13 s, identical benchmark (stock B on the same 300: 26 vs 27 at-fault incidents, 291/300 identical per-scene outcomes). Standard for all local evals; `archive/strategy.md` has the tier ladder
- 🟢 **VaVAM-L ruled out 2026-08-31** — on the same 300 scenes L+μP: 0.39 km at-fault, 8 % at-fault collisions (worse than stock B), and 3000/3000 `Drive` calls > 0.1 s (mean 107 ms) vs a 9.7 % official margin. Images deleted. Not a submission candidate
- 🟢 **Singapore checked 2026-08-31** — submitted model on 100 one-north scenes: 2.90 km at-fault, 1 % at-fault, 0 offroad, progress 1.06. Left-hand traffic is not a failure mode; Singapore is the easiest slice (sparse traffic), drift is large (median 4.4 m) but consequence-free
- 🟢 **VERIFIED — RISK RETIRED** — §4 Blackwell: the pinned `8.9;9.0+PTX` arch list **executes correctly on sm_120** inside the exact CUDA 12.4 base image. Measured, not predicted. **Do not bump the base image or the arch list** — the previously-proposed diff is unnecessary and would diverge from the competition environment for no gain

### Decisions

- 🟢 **DECIDED** — Track: **nuPlan / MTGS** (see §0.2 — driver VRAM cap is 16 GiB on *both* tracks; nuPlan wins on public data, not GPU size)
- 🟢 **RESOLVED** — Downloads clone was on `main` (no challenge code); switched to `e2e_challenge` @ `f012862`, now identical to the home clone. It still has **no venv** — see §0.2

### Challenge-side (competition, not local setup)

- 🟢 **APPROVED** — team **team-lucifer**, user `skr3178` as **captain** (verified via CLI `me`, 2026-08-29)
- 🟢 **AUTHENTICATED** — CLI token saved to `~/.alpasim/challenge.json` (2026-08-29 ~12:30; **tokens expire after 12 h** — re-run `auth-url` → `configure-token` each submission day). API live; quota shows **5/month, 0 used**. `ecr-login` untested until first push
- 🏆 **ON THE LEADERBOARD — 2026-08-30: nuPlan rank 6 of 19 teams, PCS 1590.4**, at-fault distance 1.62 km, dist_to_gt 3.05 m. Submission `6ba9c546…` (stock VaVAM-B, `vavam-stock-20260829`) SUCCEEDED overnight. Landed inside the predicted 1550–1620 band → **local setup is validated**; the local 100-scene set is **unrepresentative, not just harder**: the starter scores 0.68 km locally (vs 0.28 official) while VaVAM scores 0.38 (vs 1.62) — straight Strip scenes reward a straight-line driver and punish VaVAM's lateral drift. 4 August submissions remain (expire Sept 1)
- 🟢 **N/A** — Simulator images are never submitted; only the driver container is graded (§0.5)

### Individual checks

- 🟢 GPU visible — RTX PRO 4000 Blackwell, 24 467 MiB, driver 595.84
- 🟢 Driver ≥ 570 gate — 595.84
- 🟢 VRAM ≥ 20 000 MiB gate — 24 467
- 🟢 Docker daemon reachable without sudo — 28.1.1 CE
- 🟢 uv ≥ 0.9.17 gate — 0.12.7
- 🟢 cargo present — 1.91.0
- 🟢 venv Python in `>=3.11,<3.13` — 3.12.8
- 🟢 torch has sm_120 support — 2.8.0+cu128
- 🟢 Repo version resolves — `alpasim-base:0.89.0`
- 🟢 gRPC protos compiled — 9 × `*_pb2.py` under `src/grpc/alpasim_grpc/v0/`
- 🟢 `utils_rs` built + importable — Rust/maturin extension is fine (module is `utils_rs`, *not* `alpasim_utils_rs`)
- 🟢 `import alpasim_wizard` — OK
- 🟢 Docker images — starter driver ✅ (261 MB) + `alpasim-base:0.89.0` ✅ (20.8 GB)
- 🟡 Disk — 183 GiB free vs ~120 GiB revised budget; 79% used, reclaimable images present
- 🟢 `HF_TOKEN` — set and validated: user `skr3178`, role `read`. **Rotate it** — it was pasted into a chat transcript
- 🟢 `import alpasim_mtgs` — OK (restored 11:50)
- 🟢 `import gsplat` — 1.5.3
- 🟢 NVIDIA Container Toolkit (`--gpus all`) — `nvidia-ctk` 1.20.0, GPU visible in containers
- 🟢 Host `cuInit()` probe — SUCCESS, 1 device, `cuCtxCreate` OK (**failed with 999 before a reboot — see §3 Defect 0**)
- 🟢 **sm_120 kernel execution in the CUDA 12.4 base image** — verified with the repo's exact arch list (§4)
- 🟢 HF dataset is public + ungated — `gated: False`, anonymous fetch returns HTTP 302

---

## 0.2 Track decision and canonical working copy  [DECIDED 2026-08-29]

### Track: **nuPlan / MTGS**

Rationale as stated: it fits the available GPU.

**Refinement — the VRAM cap does not differ between tracks.** Both tracks share one image
contract and the same **16 GiB per-driver-instance** limit (§0.5); the track is a flag at
submission time. So GPU size does not favour one track over the other for the *submitted*
image. What actually makes nuPlan the lower-barrier choice is **data access**:

- **nuPlan/MTGS** — scenes are public (`OpenDriveLab/AlpasimChallenge2026_nuplan_track`),
  already downloaded here. Locally testable end to end.
- **PAI AV** — "uses an **internal** set of NuRec-compatible scenes." Not publicly
  distributed, so there is no equivalent local smoke test.

The decision stands; the reasoning is data availability, not VRAM. Budget the policy against
16 GiB either way.

### Two clones — both now on `e2e_challenge`  [UPDATED 2026-08-29 ~11:20]

The `~/Downloads` copy was originally cloned on **`main`**, which contains **none** of the
challenge code — no `e2e_challenge/`, no `e2e_challenge_nuplan` configs, no `plugins/mtgs`,
and version 0.134.0 instead of 0.89.0. It has since been switched:

```bash
cd ~/Downloads/alpasim_challenge/alpasim
git fetch origin e2e_challenge && git checkout -B e2e_challenge FETCH_HEAD
```

(Fetch + checkout rather than a fresh clone — same repo, so the objects were already local.)

| | `~/alpasim-challenge/alpasim` | `~/Downloads/alpasim_challenge/alpasim` |
|---|---|---|
| Branch | `e2e_challenge` ✅ | `e2e_challenge` ✅ |
| Commit | `f012862` | `f012862` — **identical**, = origin HEAD |
| Version | 0.89.0 | 0.89.0 |
| Challenge code | present | present ✅ |
| `.venv` | **9.2 G, built** | **none** |
| Adjacent data | 42 G at `../nuplan-track` | none (reuse via env var) |

Verified present in the Downloads copy: `e2e_challenge/`, `src/wizard/configs/e2e_challenge_nuplan`,
`plugins/mtgs`, `starter_kit/Dockerfile`, `competitor_cli`. No unresolved LFS pointers — the
repo's LFS rules cover only `*.asl` / `*.rclog` test fixtures under `src/ddb`, irrelevant here.

**Lesson worth keeping: `main` is not the challenge.** Any fresh clone of this repo defaults to
`main` and will silently lack everything. Always `--branch e2e_challenge` (as
`alpasim-setup-4090.sh` does) or check out explicitly.

### Which one to work in

The only remaining difference is the built environment. The two clones are byte-identical at
the git level, so this is purely about where you want the 9.2 GB venv to live.

- **`~/alpasim-challenge/alpasim`** — ready now. Venv built, data adjacent, and it is the
  script's default `WORKDIR`. Nothing further needed.
- **`~/Downloads/alpasim_challenge/alpasim`** — needs its env built first:

  ```bash
  cd ~/Downloads/alpasim_challenge/alpasim
  source setup_local_env.sh                                      # ~9 GB, several minutes
  export ALPASIM_NUPLAN_ROOT=~/alpasim-challenge/nuplan-track    # reuse the 42 GB
  ```

One convenience symlink in the project dir so the IDE sees the whole working location:
`~/Downloads/alpasim_challenge/workdir → ~/alpasim-challenge` (runs at `workdir/alpasim/runs/`, logs at
`workdir/logs/`, data at `workdir/nuplan-track/`, weights at `workdir/vavam-weights/`).

The **data root is independent of the clone** and never needs downloading twice — point
`ALPASIM_NUPLAN_ROOT` at the existing one from whichever copy you use.

Note both venvs would cost ~18 GB combined against 183 GiB free, before the `alpasim-base`
image build. Not a problem yet, but do not build a third.

---

## 0.5 The challenge itself — official constraints  [VERIFIED from repo + HF Space]

Confirmed: this is **NVIDIA AlpaSim E2E Closed-Loop Challenge 2026**
([HF Space](https://huggingface.co/spaces/nvidia/AlpasimE2EClosedLoopChallenge2026)).
Two tracks — **Physical AI (PAI) AV** and **nuPlan/MTGS**. You are on the **nuPlan** track.
Prizes: two NVIDIA DGX per track. Sources: `e2e_challenge/README.md` (local, authoritative)
and the Space README/landing page.

### You submit a driver container — and nothing else

> "contestants submit only a driver container that serves the AlpaSim driver gRPC API.
> Depending upon the requested submission type, the evaluator starts the appropriate
> simulator stack and connects to the submitted driver image."

The image contract is **identical across both tracks**; the track is chosen at submission
time (`pai` vs `nuplan`). Submission limits are shared across tracks.

**This reframes §4 and §4.5.** `alpasim-base` — the CUDA image, the MTGS renderer, the whole
Blackwell/sm_120 question — is **local-validation-only infrastructure**. It is never
submitted and never graded. NVIDIA runs the simulator side on their own hardware. So the
Blackwell risk can block your *local* smoke test, but it cannot invalidate a submission.

### Hard constraints on the submitted image

| Constraint | Value |
|---|---|
| VRAM per driver instance | **≤ 16 GiB** |
| Image size | ≤ 40 GiB |
| Model work per `Drive` call | **target ≤ 0.1 s** (10 Hz loop), enforced as a per-track throughput budget |
| Outbound network | **blocked** |
| Root filesystem | read-only |
| Writable scratch | `/tmp` (2 GiB), `/run` (64 MiB) only |
| Host volumes / Docker socket / scene data / cloud creds | none exposed |

Must implement `egodriver.EgodriverService` (`src/grpc/alpasim_grpc/v0/egodriver.proto`),
listen on the configured host/port, and **support concurrent calls across multiple replicas**.
Each replica gets `ALPASIM_DRIVER_HOST`, `ALPASIM_DRIVER_PORT`,
`ALPASIM_CONTESTANT_REPLICA_INDEX`, `ALPASIM_CONTESTANT_REPLICAS`. GPU access is provided.

**Official evaluation shape:** the `ec2` preset starts **16 replicas across GPUs 4–7, with 2
concurrent rollouts per replica**. Your local 1-GPU smoke test is a much smaller shape — a
policy that passes locally can still fail the throughput budget under 32 concurrent rollouts.

Local smoke tests apply the official container restrictions **except** outbound network blocking.

### Dates  [from the Space landing page]

| Date | Event |
|---|---|
| 2026-06-15 | Competition live |
| **2026-08-31 → 09-06** | Planned evaluation downtime (tentative) |
| 2026-09-15 | Rules + submission format freeze |
| 2026-10-31 | Public leaderboard closes; select final submission + technical report |
| 2026-11-15 | Final results |
| NeurIPS 2026 | Results presented |

**Today is 2026-08-29** — the evaluation downtime starts in ~2 days.

### nuPlan track specifics

- Described as "a lower-barrier track for teams building on the widely used nuPlan ecosystem."
- **The dataset is provisional.** "The nuPlan leaderboard will be cleared and each team's best
  submission will be resubmitted by the organizers" when updated data lands. The
  `OpenDriveLab/AlpasimChallenge2026_nuplan_track` data you downloaded is that provisional set.
- Submission limit currently 5, "will soon be reduced to three".
- Leaderboard metrics: **Policy Capability Score** and **Avg Distance Between At-Fault Incidents**.

### Local setup vs the official instructions — reconciliation  [VERIFIED]

The setup script matches `e2e_challenge/starter_kit/README.md` on every substantive point:

- 🟢 Same dataset, same three tarballs, same extraction layout
- 🟢 Same smoke-test invocation (`+e2e_challenge_nuplan=dev`, `ALPASIM_DRIVER_HOST/PORT`)
- 🟢 Same driver build command
- 🟡 Script uses `uv run --no-project` where the README uses plain `uv run` — a deliberate
  local fix (see §5)
- 🟡 Only `part001.tar.gz` is downloaded. That is correct for `dev` (one scene). The **full**
  navtest sweep needs every `MTGS_asset/navtest/assets/part*.tar.gz`, then
  `nuplan_scenes=navtest_full scenes.limit_to_first_n=0`

### Repo version  [VERIFIED]

Local clone is at `f012862` (2026-08-24), which is **exactly `origin/e2e_challenge` HEAD —
0 commits behind** (verified with `git fetch origin e2e_challenge`).

> A scrape of the Space's `app.py` appeared to reference a pinned commit
> `6b24e0159e5f92a1d9150ddab81f933745e24758`. **That object does not exist in the repository**
> (`git cat-file -t` fails after a fresh fetch). Treat it as a bad read of the page, not a
> real pin — do not chase it.

### Reference links

- [Challenge README](https://github.com/NVlabs/alpasim/blob/e2e_challenge/e2e_challenge/README.md)
  · [Submission constraints](https://github.com/NVlabs/alpasim/blob/e2e_challenge/e2e_challenge/README.md#submission-image-requirements-and-constraints)
- [Starter kit](https://github.com/NVlabs/alpasim/blob/e2e_challenge/e2e_challenge/starter_kit/README.md)
  · [Competitor CLI](https://github.com/NVlabs/alpasim/tree/e2e_challenge/e2e_challenge/competitor_cli)
- [Capability scoring docs](https://ln2697.github.io/navhard-leaderboard-2/docs/)
- [HF Space](https://huggingface.co/spaces/nvidia/AlpasimE2EClosedLoopChallenge2026)
  · [Dataset](https://huggingface.co/datasets/OpenDriveLab/AlpasimChallenge2026_nuplan_track)

---

## 1. Machine inventory  [VERIFIED]

| Component | Value | Notes |
|---|---|---|
| GPU | **NVIDIA RTX PRO 4000 Blackwell** | **Not a 4090.** Blackwell = compute capability **sm_120** |
| VRAM | 24 467 MiB (~403 MiB used by Xorg + gnome-shell) | passes the script's ≥20 000 MiB gate |
| Driver | 595.84 | CUDA 13.2; well above the ≥570 gate |
| Docker | 28.1.1 CE, daemon reachable without sudo | |
| uv | 0.12.7 | above the ≥0.9.17 gate |
| cargo | 1.91.0 | needed for `utils_rs` maturin build |
| Host python3 | **3.10.12** | matters — see Defect 1 |
| venv python | 3.12.8 | repo requires `>=3.11,<3.13` |
| Disk | 183 GiB free of 916G (79% used) | script budgets ~150 GiB; tight but passing |

```bash
nvidia-smi --query-gpu=driver_version,name,memory.total --format=csv
docker info | head -5;  uv --version;  cargo --version;  python3 --version
```

The GPU being Blackwell rather than Ada is the single most consequential fact here.
The script's filename, header comment and every "4090" reference are inaccurate for
this host. All of the script's *gates* still pass — it's the CUDA architecture
assumptions further down the stack that don't hold (§4).

---

## 2. What is done  [VERIFIED]

| Phase | Status | Evidence |
|---|---|---|
| `clone_repo` | done | `~/alpasim-challenge/alpasim`, branch `e2e_challenge`, HEAD `f012862` "Port public-compatible mid-Aug changes (#163)", clean tree |
| `fetch_data` | done | `nuplan-track/navtest` 38 G, `nuplan-track/nuplan_test` 4.4 G; all three tarballs present in `nuplan-track-hf/` |
| `setup_env` | **partial — see Defect 2** | `uv sync` finished 2026-08-29 ~11:00 (log: `~/alpasim-challenge/logs/sync.log`) |
| `build_base` | **not run — would have failed, see Defect 1** | no `alpasim-base` image in `docker images` |
| `build_driver` | not run | no `alpasim-e2e-starter-driver` image |

Repo version is **0.89.0** (`pyproject.toml` `[project].version`), so the wizard
resolves images to `alpasim-base:0.89.0`.

### Installed in the venv after the sync  [VERIFIED]

```
alpasim-driver==0.51.0     alpasim_eval==1.36.0     alpasim_utils==0.52.0
alpasim-physics==1.47.0    alpasim_grpc==0.54.0     alpasim_wizard==0.0.1
alpasim-runtime==1.116.0   alpasim_plugins==0.1.0   trajdata-alpasim==1.4.3
alpasim-tools==0.1.0       alpasim_controller==0.53.0
torch 2.8.0+cu128 (CUDA 12.8)
```

**Absent:** `alpasim_mtgs`, `gsplat`, `alpasim-transfuser`.

---

## 3. Confirmed defects

### Defect 0 — CUDA was dead machine-wide  [VERIFIED 2026-08-28] — **FIXED by reboot**

Worth recording because it cost hours and **mimicked an architecture problem precisely**.

**Symptom:** `cudaGetDeviceCount → -1, err=999 (unknown error)` — on the host *and* in every
container, under CUDA 12.4 *and* 12.8, with `--privileged`, and even running a **natively
compiled sm_120 binary**. Meanwhile `nvidia-smi` worked perfectly everywhere, the kernel
modules were loaded, and every `/dev/nvidia*` node was present with correct permissions.

That combination sent the investigation down a false path — CUDA version, then arch list —
before the host was checked directly. **The decisive test was `cuInit()` on the host, outside
Docker.** It failed there too, which immediately ruled out the container bridge, the toolkit,
and the arch list in one step.

**Root cause:**
```
watchdog: BUG: soft lockup - CPU#28 stuck for 31502s! [nvidia-modeset/:1024]
RIP: 0010:nvWriteGpEntry+0xf9/0x370 [nvidia_modeset]
Call Trace:  nvPushKickoff → PrefetchHelperSurfaceEvo
             → nvDIFRPrefetchSurfaces → DifrPrefetchEventDeferredWork
```
An `nvidia-modeset` kernel thread wedged in the **DIFR** (Display Idle Frame Refresh) path
for ~8.75 hours, logged **1,209 times** at ~28 s intervals. `/dev/nvidia-uvm` returned
`EIO` on open; CUDA requires UVM, so every CUDA call failed. `nvidia-smi` was unaffected
because NVML uses a different path — which is exactly what made it so misleading.

**Fix: a reboot.** No driver reinstall, no version change, no config change. `modprobe -r`
is not an option: a module with a locked-up kernel thread cannot be unloaded, and
`nvidia_modeset` had refcount 11 from `nvidia_drm`.

**Prevention:** `preflight()` now probes `cuInit()` via ctypes rather than trusting
`nvidia-smi`, and its failure message points at `journalctl -k | grep 'soft lockup'` and at
reboot-not-reinstall.

If it recurs, DIFR can be disabled without touching the driver install:
```
# /etc/modprobe.d/nvidia-difr.conf
options nvidia-modeset NVreg_EnableDIFR=0
```

---

### Defect 1 — `build_base` crashed on `tomllib` (host python is 3.10)  [VERIFIED] — **FIXED**

`build_base()` read the repo version with:

```bash
ver=$(python3 -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
```

`tomllib` is stdlib only from **Python 3.11**. Host `python3` is 3.10.12:

```console
$ python3 -c "import tomllib; print('ok')"
ModuleNotFoundError: No module named 'tomllib'
```

`set -euo pipefail` means this aborts the whole `all` run at the `build_base` step —
after the ~40 min of cloning, syncing and 42 GB of downloads had already succeeded.
The venv's 3.12 interpreter would have worked, but the script calls bare `python3`.

**Fix applied** in `alpasim-setup-4090.sh:155-159` — parse `[project].version` with awk,
no interpreter version dependency:

```bash
ver=$(awk -F'"' '/^\[/{s=$0} s=="[project]" && /^version[[:space:]]*=/{print $2; exit}' pyproject.toml)
```

Verify: `bash -c 'cd ~/alpasim-challenge/alpasim && awk -F\" "/^\[/{s=\$0} s==\"[project]\" && /^version[[:space:]]*=/{print \$2; exit}" pyproject.toml'` → `0.89.0`

---

### Defect 2 — the venv has no MTGS renderer  [VERIFIED] — **OPEN**

The nuPlan `dev` preset runs "a managed MTGS renderer"
(`src/wizard/configs/e2e_challenge_nuplan/dev.yaml`), and the renderer service's
command is `uv run alpasim-mtgs-server`
(`src/wizard/configs/e2e_challenge_nuplan_common/base.yaml:31`).

But in `pyproject.toml` the `all` extra contains **only** the ten core packages:

```toml
all = ["alpasim_plugins","alpasim_controller","alpasim_eval","alpasim_grpc",
       "alpasim-runtime","alpasim_utils","alpasim-physics","alpasim-tools",
       "alpasim_driver","alpasim_wizard"]
```

`mtgs = ["alpasim-mtgs[server]"]` and `transfuser = ["alpasim_transfuser"]` are
**separate extras, not members of `all`**. So `uv sync --extra all` does not install
the renderer — and because `uv sync` prunes the environment to exactly the declared
set, it *removes* it if it was there.

That is what happened. The sync that ran 10:52→11:00 was **`uv sync --extra all`**
(observed as PID 32610), not the command `setup_local_env.sh` would have issued.

```console
$ .venv/bin/python -c "import alpasim_mtgs"
ModuleNotFoundError: No module named 'alpasim_mtgs'
$ .venv/bin/python -c "import gsplat"
ModuleNotFoundError: No module named 'gsplat'
```

`plugins/mtgs/alpasim_mtgs.egg-info/` and `plugins/transfuser_driver/alpasim_transfuser.egg-info/`
are both dated **Aug 29 00:31**, i.e. an editable install of both plugins did happen
earlier and has since been pruned away. **[INFERRED]**

This is corroborated: the compiled protos (9 × `*_pb2.py`) and the working `utils_rs`
extension are both present, and **only `setup_local_env.sh` produces those** — a bare
`uv sync` does neither. So the sequence was: `setup_local_env.sh` ran successfully around
00:31 (installing MTGS), then the bare `uv sync --extra all` at 10:52 pruned MTGS back out
while leaving the protos and `utils_rs` untouched. **[INFERRED]**

**The setup script is not at fault here.** `setup_local_env.sh` detects plugin dirs and
appends the extras — and both `plugins/mtgs/pyproject.toml` and
`plugins/transfuser_driver/pyproject.toml` exist, so detection would succeed. **Running
`uv sync --extra all` manually in this repo silently un-installs the renderer.**

#### Cause identified  [2026-08-29 — answers §8's open question]

**The bare `uv sync --extra all` (PID 32610, 10:52) was run deliberately in an assistant
session, not by a stray tool.** It was a "lean sync" intended to cut setup time, on the
reasoning that the heavy ML runs inside `alpasim-base` and the host only needs the wizard.

**That reasoning was wrong**, and §4.5 of this document is why: the host *does* need
`alpasim_mtgs` installed, because `alpasim_config_discovery` resolves Hydra search paths via
`entry_points(group="alpasim.configs")`. Trading it away breaks config composition on the
host before any container starts. Nothing else in the workflow issues that command — the
source is accounted for, and it will not recur.

**Fix applied to the script:** `setup_env()` now always includes `--extra mtgs` when
`plugins/mtgs` exists. Only `transfuser` is opt-in via `ALPASIM_FULL_SYNC=1`, since that is
the genuinely slow extra (it compiles alpamayo1.5, alpamayo-r1 and vam from git, 20–40 min)
and is not needed to run the nuPlan preset.

```bash
bash alpasim-setup-4090.sh env                 # preferred — protos + utils_rs + correct extras
# or, minimally, by hand:
uv sync --extra all --extra mtgs
```

⚠️ **Do not use `source setup_local_env.sh` for this** — it fails on this box. See Defect 3.

---

### Defect 3 — `setup_local_env.sh` fails on a clean run  [VERIFIED] — **OPEN (upstream)**

```console
$ source setup_local_env.sh
Setting up GRPC...
Traceback (most recent call last):
  File "/home/skr/alpasim-challenge/alpasim/.venv/bin/compile-protos", line 4, in <module>
    from scripts.compile_protos import compile_protos
ModuleNotFoundError: No module named 'scripts.compile_protos'
❌ Failed to compile protobufs. Exiting.
```

`src/grpc/pyproject.toml` declares `packages = ["alpasim_grpc", "scripts"]` and the console
script entry point `compile-protos = "scripts.compile_protos:compile_protos"`. But
`alpasim_grpc` installs **editable** (`_editable_impl_alpasim_grpc.pth`), and hatchling's
editable hook exposes only the `alpasim_grpc` package — **not** the sibling `scripts`
package. A console script does not get the cwd on `sys.path`, so the import fails even when
run from `src/grpc`. Upstream's Dockerfile escapes this because `RUN uv sync` there produces
a **non-editable** install, where `scripts/` really is in site-packages.

Confirmed both halves:
```console
$ ls .venv/lib/python3.12/site-packages/scripts     → does not exist
$ cd src/grpc && .venv/bin/python -c "import scripts.compile_protos"   → OK (cwd on path)
```

**Workaround** (now baked into `setup_env()` in the script):
```bash
cd ~/alpasim-challenge/alpasim/src/grpc && PYTHONPATH=. uv run --no-sync compile-protos
```

**Consequence for this document:** the previously recommended fix for Defect 2
(`source setup_local_env.sh`) would abort at the protos step and never reach the sync. The
setup script no longer sources it at all — under `set -e` that failure killed the whole run
at the first phase.

**Corrects an earlier inference.** §3 Defect 2 previously reasoned that because compiled
protos and a working `utils_rs` exist, "`setup_local_env.sh` ran successfully around 00:31".
It did not — it cannot on this box. Those artefacts came from the `PYTHONPATH` workaround and
an explicit `uv pip install -e src/utils_rs`, run manually in the same session. The
artefacts were real; the attribution was wrong.

---

## 4. The Blackwell problem  [VERIFIED 2026-08-29 — RESOLVED, works as shipped]

**Outcome first: the stack works on sm_120 with no source changes.** The reasoning below
was sound; the conclusion it hedged on has now been measured directly, and the optimistic
branch is the correct one.

### The measurement

Compiled and ran a kernel inside the **exact** base image
(`nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04`) on **this** GPU, using the **exact** flags
that `TORCH_CUDA_ARCH_LIST=8.9;9.0+PTX` expands to:

```console
### A. the repo's actual arch list ###
$ nvcc -gencode arch=compute_89,code=sm_89 \
       -gencode arch=compute_90,code=sm_90 \
       -gencode arch=compute_90,code=compute_90  strict.cu -o a && ./a
  cudaGetLastError after launch: no error
  result[0]=3.0 (expect 3.0)  => KERNEL RAN                              ✅

### B. control: sm_89 cubin only, no PTX ###
$ nvcc -gencode arch=compute_89,code=sm_89 strict.cu -o b && ./b
  cudaGetLastError after launch: no kernel image is available for execution on the device
  result[0]=1.0 (expect 3.0)  => KERNEL DID NOT RUN                      ❌
```

The trailing `+PTX` is doing exactly its job: driver 595.84 JIT-compiles the compute_90 PTX
onto sm_120 at load time. Confirmed independently that `nvcc --list-gpu-arch` under CUDA 12.4
stops at `compute_90`, so no native sm_120 cubin is possible — the PTX path is the whole
mechanism, and it works.

### ⚠️ The failure mode is SILENT

Case B returned **wrong numbers with no exception**. `cudaDeviceSynchronize()` reported
success; only `cudaGetLastError()` immediately after the launch revealed anything. A first
version of this very test printed "KERNEL EXECUTED OK" for case B because it checked only
the sync. **Any future change to the arch list must be validated by checking
`cudaGetLastError()` and asserting on the output value — never by "it ran without crashing".**

### Do NOT apply the base-image bump

The diff proposed in the earlier revision of this section — moving to
`nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04` and adding `12.0` to the arch list — is
**unnecessary**. It would pull a ~7 GB image, lengthen the build, and diverge the local
environment from the competition one, all to replace a working JIT path with a native
cubin. The only reason to revisit it is if gsplat specifically turns out to fail (below).

### What is still not proven

Two residual unknowns, both narrower than the original risk:

1. **gsplat specifically.** The test used a trivial kernel. gsplat is a large extension and
   could still fail to build under nvcc 12.4 + gcc-11 for unrelated reasons, or hit JIT
   compile-time/memory limits at scale.
2. **Container-side torch.** The *host* venv's `torch 2.8.0+cu128` has native sm_120 kernels
   and is fine. The base image resolves its own torch from PyPI, unpinned — if that lands on
   a pre-cu128 wheel it has no sm_120 cubins either. Same silent failure mode.

Both are covered by the new `verify` phase, which forces the runtime nvcc build and a real
launch before the smoke test rather than mid-simulation:

```bash
bash alpasim-setup-4090.sh verify
```

Also note: gsplat's JIT output caches to `~/.nv/ComputeCache`, which is **ephemeral inside a
container**. Expect a slow first render on every fresh container start, not just the first.

---

### Residual unknowns — RETIRED  [VERIFIED 2026-08-29 ~12:08, inside alpasim-base:0.89.0]

Both §4 residual unknowns are now measured, in the built image, on this GPU:

```
torch          : 2.8.0+cu128 | built for CUDA 12.8
torch archs    : ..., sm_100, sm_120        ← native sm_120, JIT not even needed
device         : NVIDIA RTX PRO 4000 Blackwell sm_120
torch kernel   : OK                          (value-checked, not "didn't crash")
gsplat         : 1.5.3 — CUDA extension compiled in 138.3 s, rasterization OK (1,240,320,3)
```

- The unpinned container torch resolved to **cu128 with native sm_120 cubins** — the
  pre-cu128-wheel worry did not materialise.
- gsplat's real kernels **compile under nvcc 12.4 and execute** — and the 138 s extension
  build confirms the predicted slow first render on every fresh container (ephemeral
  `~/.nv/ComputeCache`).

**⚠️ Defect 4 (found and fixed in the process): `verify_stack()` itself produced a false
PASS on its first run.** `docker run` without `-i` does not attach stdin, so the heredoc
never reached `python -` — an empty script exited 0 and the phase printed "ok" having
tested nothing. The tell: none of the diagnostic lines appeared. Fixed by adding `-i`
(comment in the script marks it load-bearing). The §4 lesson generalises: **a verifier
that prints nothing but "ok" has not necessarily run — require positive evidence, not
absence of failure.**

### Original analysis (retained — the reasoning was correct)

**The chain:**

1. `alpasim-base` is built from `Dockerfile:11` →
   `FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04`. That image's **nvcc is CUDA 12.4**,
   whose newest supported architecture is **sm_90**. `sm_100`/`sm_120` arrived in CUDA 12.8.
2. `Dockerfile:29` — *"gsplat builds CUDA extensions **at runtime**."* So the rasterizer
   is nvcc-compiled inside that container, on first render, against that 12.4 toolkit.
3. `e2e_challenge_nuplan_common/base.yaml:29` pins the arch list for that build:
   ```yaml
   - "TORCH_CUDA_ARCH_LIST=8.9;9.0+PTX"   # 8.9 = Ada/4090, 9.0 = Hopper
   ```

**What this means on sm_120.** Because the arch list is pinned explicitly rather than
derived from the device, nvcc 12.4 will *not* error out — it emits sm_89 and sm_90
cubins plus **compute_90 PTX**. There is no sm_120 cubin, so every kernel launch depends
on the driver **JIT-compiling the 9.0 PTX up to sm_120** at runtime. Driver 595.84 can do
that, so this may well work — but it is an untested path, it costs a long stall on the
first render, and it is the likeliest source of a confusing failure (a bare
"no kernel image is available for execution on the device" if the PTX fallback is missed).

**The trap:** adding `12.0` to `TORCH_CUDA_ARCH_LIST` *without* also moving the base image
to CUDA ≥12.8 produces `nvcc fatal: Unsupported gpu architecture 'compute_120'`. The two
changes go together:

```diff
- FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04 AS base-amd64
+ FROM nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04 AS base-amd64
```
```diff
- - "TORCH_CUDA_ARCH_LIST=8.9;9.0+PTX"
+ - "TORCH_CUDA_ARCH_LIST=8.9;9.0;12.0+PTX"
```

`nvidia/cuda:12.8.0-devel-ubuntu24.04` and `12.8.0-base-ubuntu24.04` are already pulled
locally; the `12.8.0-cudnn-devel-ubuntu22.04` variant is not, and would need pulling.

**Not affected:** the host venv's `torch 2.8.0+cu128` ships sm_120 kernels natively —
host-side torch is fine. The risk is confined to what nvcc compiles *inside* the base image.

**Do not "fix" this pre-emptively** — build the image and run the smoke test first, and
capture the actual error. Changing both the base image and the arch list is a real
divergence from the competition environment and should be a deliberate, recorded choice.

> **[RESOLVED 2026-08-29]** The "do not fix pre-emptively" instruction was correct and is now
> vindicated: the PTX fallback is *not* missed, and the JIT path works. The `12.8` + `12.0`
> diff above is documented for reference only — **do not apply it**. The one prediction that
> did not hold is the guess that the JIT costs "a long stall on the first render": the trivial
> kernel JIT'd imperceptibly. Whether gsplat's much larger kernels stall noticeably is
> unmeasured — expect it on every fresh container start, since the compute cache is ephemeral
> inside the container.

---

## 4.5 What runs where — containers vs host  [VERIFIED from source]

Almost the whole stack is Docker. The wizard does **not** run the simulator in-process;
it generates a `docker-compose.yaml` into `wizard.log_dir` and shells out to
`docker compose up --exit-code-from runtime-0`
(`src/wizard/alpasim_wizard/deployment/docker_compose.py:42-82`).

| Piece | Where it runs | Image |
|---|---|---|
| `alpasim_wizard` | **host**, in `.venv` — not containerised | — |
| renderer (`uv run alpasim-mtgs-server`) | container | `alpasim-base:0.89.0` |
| controller | container | `alpasim-base:0.89.0` |
| runtime | container | `alpasim-base:0.89.0` |
| **your driver / policy** | container, **you launch it** | `alpasim-e2e-starter-driver:latest` |

So there are only **two images to build**: one CUDA image serving three services, and the
driver image, which is the one you replace with your policy. The starter driver is
`python:3.12-slim` with no CUDA at all — grpc + numpy + `driver.py` on port 6789.

Three details that explain the smoke-test shape:

- **The driver is not owned by the wizard.** `driver_source: external_static` —
  *"The driver process is not launched or owned by Wizard."* That is why the smoke test
  needs two terminals: you start the driver container, the wizard connects out to it.
- **`network_mode: host`.** `wizard.debug_flags.use_localhost: true` puts every service on
  the host network, which is why `ALPASIM_DRIVER_HOST=localhost:6789` reaches your container.
- **`src/` and `plugins/` are bind-mounted** from the host into the containers
  (`e2e_challenge_nuplan_common/base.yaml:24-25`), so host-side source edits take effect
  inside the containers without a rebuild.

### The closed loop — who talks to whom

```
 ┌───────────────────────────────── alpasim-base (3 containers) ─────────────────────────────────┐
 │                                                                                                │
 │   renderer ──renders 8 cams──▶  runtime  ──executes plan──▶ controller (MPC → steer/throttle)  │
 │   (MTGS splats)                 (sim loop,                       │                             │
 │        ▲                         scoring)                        │                             │
 │        └───────────── new ego pose ◀─────────────────────────────┘                             │
 └───────────────────────────────────────┬──────────────────▲─────────────────────────────────────┘
                                         │ gRPC             │ gRPC
                        images (JPEG), ego pose, route      │  Trajectory (next ~5 s)
                                         ▼                  │
                        ┌─────────────────────────────────────────┐
                        │  driver container  (port 6789)          │
                        │  policy checkpoint + driver.py          │
                        │  → submit_image_observation             │
                        │  → Drive() ⇒ trajectory                 │
                        └─────────────────────────────────────────┘
```

One loop, every 0.5 s of sim time (nuPlan preset):

1. **Runtime** asks the **renderer** for the camera views at the ego's *current* pose → 8 JPEGs
2. Runtime pushes them to the **driver** (`submit_image_observation`), plus ego pose and route
3. Runtime calls `Drive()` → the driver answers with a **trajectory** (waypoints ~5 s out — a path, not steering)
4. Runtime hands it to the **controller**, which converts path → steer/throttle and advances the vehicle
5. New pose → step 1, now rendering from wherever *the driver's* trajectory took the car

It is a **request model, not a stream**: the simulator owns the clock and calls the driver; the driver
only serves. That is what makes it replicable (16 replicas × 2 rollouts at official eval).

### Ownership split — the point of the design

| | Local (this machine) | Official evaluation |
|---|---|---|
| Simulator side (renderer / runtime / controller) | our `alpasim-base` on our GPU | **NVIDIA's** stack on their GPUs 0–3 |
| Driver side | our container on the same GPU | **our pushed image**, 16 replicas on their GPUs 4–7 |
| gRPC contract between them | identical | identical |

The last row is why local testing is meaningful: same interface, so a driver that works here works
there. Only the hardware underneath changes — which is also why the Blackwell issue is purely local.

| Image | Role | Submitted? |
|---|---|---|
| `alpasim-base:0.89.0` (20.8 GB) | renderer + controller + runtime — NVIDIA's side | **never** |
| `alpasim-e2e-starter-driver` (261 MB) | the driver slot, straight-line baseline | this slot is what gets submitted |
| `alpasim-e2e-vavam-driver` (not yet built) | the driver slot, VAVAM-backed | replaces the starter in that slot |

The driver is standalone by contract (no host mounts, no scene data, no simulator env), so its
Dockerfile starts from a plain `pytorch/pytorch` base — it never inherits from `alpasim-base`.

### Correction: `docker compose up` builds `alpasim-base` on its own

Because the renderer sets `external_image: false` (`base.yaml:20`) and `pull_policy`
defaults to `"missing"` (`schema.py:156-157`), the generated compose file carries a
`build:` block pointing at the repo root `Dockerfile`. So a missing `alpasim-base` is
built automatically by `docker compose up` — the script's `build_base()` is a
**convenience pre-build, not a hard requirement**, which softens the §5 rationale below.

Pre-building is still worth it: a ~40-minute image build that fails inside
`docker compose up` is far harder to read than one that fails on its own.

### This also sharpens Defect 2

The base image installs MTGS itself (`Dockerfile:55` — `uv sync --extra all --extra mtgs`),
so the **renderer container is fine** regardless of the host venv. What the missing host-side
`alpasim_mtgs` breaks is **config composition on the host**: the Hydra plugin at
`src/wizard/hydra_plugins/alpasim_config_discovery/__init__.py:79` discovers config search
paths via `importlib.metadata.entry_points(group="alpasim.configs")`, and `alpasim_mtgs`
registers the `mtgs` group there. Not installed on the host → that config group is never
registered → the wizard can fail composing the preset before a single container starts.
The fix is unchanged; the failure mode is a host-side Hydra error, not a renderer error.

---

## 5. Earlier round of fixes (already in the script)  [INFERRED from `alpasim-setup-4090.sh.bak`]

`diff alpasim-setup-4090.sh.bak alpasim-setup-4090.sh` shows a prior debugging pass.
Each change implies a failure that was hit and worked around:

| Change | Implied failure |
|---|---|
| GPU probe now pulls `nvidia/cuda:12.8.0-base` explicitly and prints `probe_out` on failure | a registry/network pull failure was being misreported as "containers cannot see the GPU" |
| Added host `cuInit()` check via ctypes | a wedged nvidia kernel thread — `nvidia-smi` works, `/dev/nvidia-uvm` returns EIO, every CUDA call fails with 999. Cleared by reboot |
| `uv run` → `uv run --no-project` for the HF download | `uv run` was picking up the repo project context and trying to resolve/sync it |
| Disk check walks up to the first existing dir | `df` on a not-yet-created `$WORKDIR` parent failed |
| **Added `build_base()` entirely** | the wizard resolves `base_image` to `alpasim-base:0.89.0` with an empty registry prefix, and neither `setup_local_env.sh` nor the starter-kit Dockerfile builds it. **Caveat — see §4.5:** `docker compose up` *will* build it automatically, so this is a pre-build convenience rather than a strict requirement |

That last one is confirmed in source: `src/wizard/configs/base_config.yaml:25-26`

```yaml
image_registry: ""
base_image: "${defines.image_registry}alpasim-base:${repo-version:}"
```

---

## 6. Verification commands

```bash
# machine
nvidia-smi --query-gpu=driver_version,name,memory.total --format=csv
python3 --version && ~/alpasim-challenge/alpasim/.venv/bin/python --version

# venv completeness (Defect 2)
cd ~/alpasim-challenge/alpasim
.venv/bin/python -c "import alpasim_mtgs, gsplat; print('renderer deps OK')"
.venv/bin/python -c "import torch;print(torch.__version__, torch.version.cuda)"

# images
docker images | grep -E 'alpasim|nvidia/cuda'

# data
du -sh ~/alpasim-challenge/nuplan-track/*
ls ~/alpasim-challenge/nuplan-track/navtest/configs ~/alpasim-challenge/nuplan-track/nuplan_test
```

---

## 6.5 Smoke test result  [VERIFIED 2026-08-29 12:12]

`uv run alpasim_wizard +e2e_challenge_nuplan=dev` against the hardened starter driver:
**exit 0, "Alpasim finished"**. Output: `runs/nuplan_smoke2/aggregate/` — `results-summary.json`,
metrics parquet/png/txt, and rendered videos (`videos/all`, `videos/violations`).

Key numbers (starter driver = straight-line constant-speed fallback):

| Metric | Value | Reading |
|---|---|---|
| `collision_any` / `at_fault` / `offroad` | **0.0** | clean run |
| `dist_to_gt_trajectory` (lateral, max) | **0.15 m** | tracks the recorded path closely |
| `dist_to_gt_location` (max) | 2.80 m | falls behind GT longitudinally — expected for constant speed |
| `dist_traveled` | 56.9 m vs GT 65.7 m | same story |
| `img_is_black` | **0.0** | renders are real — gsplat produced actual imagery on sm_120 |
| `driver_drive_rpc_duration_mean` | **0.49 ms** | vs the 100 ms budget; the trivial driver costs nothing |
| `avg_dist_between_incidents` | inf | no incidents |

**VRAM: peak 5 594 MiB of 24 467** (logger at 5 s cadence, so brief spikes may be missed).
Renderer + controller + runtime + driver on one GPU leaves **~18.9 GiB** for a policy when
developing locally. The official 16 GiB driver cap remains the binding constraint for the
submitted image — locally you have almost exactly that much to play with while the sim runs.

Timing: ~2 min wall for one scene, dominated by the gsplat first-render JIT (~2 min compile
in a fresh container). The 10 sim-steps of driving itself took seconds. Full-suite local
runs will amortise the JIT per container start, not per scene.

**What this closes:** every layer — data, configs (Hydra composition with mtgs group), all
four containers, gRPC to the hardened driver, MTGS rendering on Blackwell, scoring, video.
The machine can run the challenge. Remaining work is competition-side (registration, CLI,
policy development), not environment.

---

## 6.7 VAVAM sample submission — local build + Blackwell measurement  [2026-08-29 ~13:40]

Leaderboard analysis (§ leaderboard snapshot in `leaderboard/SUMMARY.md`): the top 3 nuPlan teams all
run VaVAM; the *stock* sample scores ~1587 vs ~1000 for the starter and ~1731 at the apparent cap.
So VaVAM is the template. Checkpoint links: `archive/VAVAM-CHECKPOINTS.md`.

| Step | Status |
|---|---|
| Weights (VaVAM-B 139k `.pt` 1.75 GB + VQ encoder `.jit` 118 MB) | 🟢 downloaded from GitHub release v1.0.0, byte-exact, staged via `prepare_assets.sh` → `assets/vavam/` (originals kept in `~/alpasim-challenge/vavam-weights/`) |
| **Submission image** `alpasim-e2e-vavam-driver:latest` (as-shipped Dockerfile, torch 2.6.0+cu124) | 🟢 **built, 8.96 GB** (< 40 GiB cap). This is the one to push/submit |
| Run that image on this GPU | 🔴 **FAILS — measured, not predicted**: torch warns `sm_120 is not compatible… supports sm_50…sm_90`, then `RuntimeError: CUDA error: no kernel image is available for execution on the device` on the first kernel. Loud failure (unlike the PTX case). Irrelevant at official eval (their GPUs are not Blackwell) |
| **Local twin** `alpasim-e2e-vavam-driver:local` (`Dockerfile.local`: only `FROM` → `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime`) | 🟢 **built, 10.6 GB**. Probe inside it: torch 2.8.0+cu128, archs incl. `sm_120`, elementwise/cuDNN/cuBLAS all value-checked OK, VQ `.jit` loads on CUDA, checkpoint loads (Lightning ckpt, `state_dict`) |
| Swap driver container + nuPlan dev smoke with VaVAM | 🟢 **PASSED 14:04** — `runs/nuplan_vavam1/`, exit 0. Driver loaded 318.77 M + 37.95 M params (= VaVAM-B spec) |

### VaVAM vs starter on the one dev scene  [VERIFIED 2026-08-29 14:04]

| Metric | Starter (straight line) | **VaVAM-B stock** | Note |
|---|---|---|---|
| collision_any / at_fault / offroad / left_corridor | 0 / 0 / 0 / 0 | **0 / 0 / 0 / 0** | both clean |
| dist_to_gt_trajectory (lateral, max) | 0.15 m | **1.61 m** | VaVAM drifts more laterally — the route-conditioning weakness seen leaderboard-wide |
| dist_to_gt_location (max) | 2.80 m | 3.58 m | |
| dist_traveled / GT | 56.9 / 65.7 m | 56.6 / 65.7 m | both under-drive the recorded speed |
| img_is_black | 0 | 0 | renders real |
| **driver_drive_rpc_duration_mean** | 0.49 ms | **238 ms** | ⚠️ **2.4× over the 0.1 s target**, single rollout, sm_120, no CUDA graphs |
| Drive calls | 10 | 10 | |
| VRAM peak (sim + driver, one GPU) | 5.6 GB | **7.9 GB** | driver alone ~2.2 GB idle |

Read-outs:
- **One scene cannot rank policies** — both are incident-free; the starter "wins" on lateral
  deviation only because this stretch is nearly straight. Leaderboard-scale comparison needs the
  full navtest set.
- **Throughput — corrected by the per-call histogram** (`telemetry/metrics_worker_0.prom`,
  `rpc_duration_seconds{method="drive"}`): the 238 ms *mean* is a warm-up artefact, not steady state.
  Of 10 calls: **7 ≤ 100 ms**, 1 in 100–500 ms, **2 in 0.5–1 s** — the first calls pay cuDNN
  autotune / lazy CUDA init / tokenizer JIT, and with only 10 samples they dominate the mean.
  Steady-state `Drive` is already inside the 100 ms target on this GPU at 1 rollout.
  **Not a container/gRPC effect:** `rpc_blocking_seconds` (runtime-side transport wait) is
  ≤ 0.1 ms on all 10 calls (sum 0.28 ms), and the starter driver over the identical path measured
  0.49 ms/call. Cheapest fix: **warm up at container start** (a few dummy inferences before
  serving); then plan caching (`inference_interval_us`), autocast, CUDA graphs only if 2 concurrent
  rollouts push steady state over budget.
- `camera CAM_F0 is not f-theta; skipping rectification` — nuPlan cameras are already pinhole, so the
  f-theta rectifier (written for the PAI track) is a no-op here. Fine.
- VRAM: 7.9 GB total with the simulator sharing the card → the driver is far inside the 16 GiB cap.



Why cu128 is safe for the same checkpoint: the `.pt` is torch-version-agnostic tensors; the `.jit` is
TorchScript (forward-compatible); VideoActionModel's `torch==2.4.0` pin is an *optional extra* the
sample never installs — the sample already runs on 2.6, two versions past that pin.

Two findings from the local `VideoActionModel` copy (`~/Downloads/alpasim_challenge/VideoActionModel`, main = v1.0.0+8):
- **Post-tag hot-fix** `738050e` corrects rolling-context slicing (v1.0.0 kept the *oldest* frames when
  the history exceeded the context window). The sample pins `@v1.0.0` but is **unaffected — it feeds a
  single frame** (`tokens.unsqueeze(1)`). Any multi-frame extension must move the pin to `@738050e`.
- **The sample runs a video model as a single-image policy** (no temporal history, no KV cache across
  `Drive` calls) and reduces the challenge's 40–80 m route to a 3-way command (`_command_from_route`,
  3 m lateral threshold). Temporal context and route conditioning are the two obvious headroom items;
  the #1 tag `vavam-route-cudagraph` points at exactly those.

## 6.8 What the driver actually sees — visuals  [2026-08-29 15:55]

`~/Downloads/alpasim_challenge/viz/` — built from the two dev-scene runs with ffmpeg (inside `alpasim-base`):

| File | What |
|---|---|
| `starter_vs_vavam_CAM_F0.mp4` | side-by-side, labelled, 2 fps: the eval video of both drivers on the same scene |
| `starter_contact_sheet.png`, `vavam_contact_sheet.png` | all 12 frames of each run as a 4×3 grid |
| `starter_f01..12.png`, `vavam_f01..12.png` | individual frames (900×1000) |

Each eval frame is a composite: **top** = bird's-eye view (blue = lanes, grey boxes = other agents,
green = ego, **orange = the driver's planned trajectory**, green dashed = recorded human path) plus the
live metrics table; **bottom** = the MTGS render of `CAM_F0` the driver received at that tick.
The dev scene is the Las Vegas Strip (city `us-nv-las-vegas-strip`), following a green box truck toward
an intersection, ~5.5 s / 10 decisions. In the VaVAM sheet the orange plan visibly drifts left of the
green dashed path in frames 9–12 (`dist_to_gt_trajectory` climbing to 1.61 m); the starter's stays on it.

The driver's input, per the protos (`egodriver.proto`, `sensorsim.proto`):

| Stream | RPC | Content | Cadence (nuPlan) |
|---|---|---|---|
| Session spec | `start_session` | `rollout_spec.vehicle.available_cameras[]` — per camera: `logical_id`, `CameraSpec` intrinsics, `rig_to_camera` pose; a `random_seed`; **no scene id** in benchmark runs | once |
| Images | `submit_image_observation` | one `CameraImage` per call: `logical_id`, `frame_start/end_us`, JPEG `image_bytes` (1920×1080) — 8 cameras `CAM_F0, L0, L1, L2, R0, R1, R2, B0` | 8 calls / 0.5 s |
| Ego motion | `submit_egomotion_observation` | `Trajectory` of estimated poses (`local→rig_est`) + matching `DynamicState`s (velocities, accelerations, rig frame) | per tick |
| Route | `submit_route` | `Route.waypoints[]` as `Vec3` **in the rig frame** at `timestamp_us` — the 40–80 m lookahead | per tick |
| Query | `Drive` | `time_now_us`, `time_query_us`, optional `renderer_data` → driver returns a `Trajectory` (+ optional debug, `terminate_session`) | 1 / 0.5 s |

Notes: the eval mp4 is a 900×1000 downscale of the 1920×1080 JPEG the driver got. The VAVAM
sample keeps only `CAM_F0`, then resizes/center-crops it to the model's expected resolution
(`vavam_policy._resize_and_center_crop`); the other 7 cameras are discarded. The starter ignores all
images. The per-frame JPEGs themselves are not persisted by the simulator — tap `submit_image_observation`
in the driver to collect them.

## 6.9 What goes into the model — the exact VaVAM-B input/output path  [VERIFIED from code + checkpoint]

Traced through `vavam_policy.py`, `NeuroNCAPTransform`, `forward_inference`, and the checkpoint's own
`hyper_parameters` (dumped from the `.pt` inside the container).

```
CAM_F0 JPEG 1920×1080 (from the sim, every 0.5 s)
  → resize to height 900, center-crop width to 1600            (vavam_policy._resize_and_center_crop)
  → SafeResize ÷3.125 → 288×512, float, normalise to [-1,1]      (NeuroNCAPTransform, nuScenes recipe)
  → VQ encoder (LlamaGen, ds16, 16 384-word codebook)           → 18×32 = 576 discrete tokens
  → tokens[1, 1, 576]  +  high_level_command ∈ {0 right, 1 left, 2 straight}
  → GPT-2 video backbone (24 layers, d=1024, 318 M; context up to 8 frames — sample uses 1)
  → action expert (24 layers, d=256, 38 M) — FLOW MATCHING:
        start: Gaussian noise action [1, 6, 2]; 10 forward-Euler steps; × action_scaling = 70
  → 6 waypoints (x, y) in metres, rig frame, at 2 Hz  →  a 3 s horizon
  → trajectory.py: rotate into the rollout's local frame at the current pose, cache,
     resample at 10 Hz for the controller (max_horizon 5 s; straight-line fallback if no plan)
```

Facts that matter for tuning:
- The model sees **one 288×512 frame** and a **3-way command** — nothing else. No ego speed, no route
  geometry, no other cameras, no history (the backbone supports 8 frames; `finetuning_timesteps: 8`).
- Output is **stochastic**: it starts from Gaussian noise and integrates 10 Euler steps, so the same
  frame gives slightly different trajectories run to run. Seeded/multi-sample averaging is a cheap knob.
- `action_scaling: 70` — the raw network output is scaled ×70 into metres; `final_action_clip_value: None`.
  The leaderboard tag `gain105` is almost certainly a further ×1.05 on this output.
- The horizon is **3 s** at 2 Hz (6 points); the controller wants up to 5 s at 10 Hz — the wrapper
  interpolates/extends, and the straight-line fallback is used when no plan exists yet.

**Correction to §6 / VAVAM-CHECKPOINTS.md:** the checkpoint's own config records
`gpt_checkpoint_path: …/finetuned/Finetuned_0000139763_mixOpendvNuplanNuscenes_…/end_of_epoch_epoch=001_step=0000155294_fused.pt`
— i.e. **the released VaVAM-B sits on the nuPlan/nuScenes-fine-tuned 155k backbone, not the OpenDV-only
139k one.** The "pretrained_139k" in the filename is the pretraining step count. The earlier
"rebase on the fine-tuned backbone" idea is therefore already what the release did — strike it.
The action expert was trained for `global_step: 7251` on top of it.

### 6.9.1 Captured real inputs + stage-by-stage visuals  [2026-08-29 16:15]

**Capture tool:** `capture/capture_driver.py` — the starter driver subclassed to persist everything the
simulator sends (runs on the host venv, no image build). One dev-scene run against it produced
`capture/captured/<session>/`: **88 JPEGs** (8 cams × 11 ticks, true 1920×1080), `session.json`
(camera calibration), `routes.jsonl`, `egomotion.jsonl`, `drive.jsonl`. This is also the collection path
for any sim-domain fine-tuning set.

**Stage visuals:** `capture/visualize_stages.py` run inside `alpasim-e2e-vavam-driver:local` (decoder
`.jit` mounted; not part of the image) → `viz/stages/`: per frame `_0_raw`, `_1_crop_1600x900`,
`_2_input_288x512`, `_3_tokens_18x32` (.png + .txt grid), `_4_vq_reconstruction`, `_5_waypoints_topdown`,
and `_STAGES.png` (all in one strip); plus `ALL_8_CAMERAS_*.png` and `summary.json`.
`viz/drive_latency_histogram.png` charts the per-call `Drive` buckets from the `.prom` files.

Observed on the first 4 frames: command = straight (route y ∈ ±0.6 m at 43–65 m); ~560 of 576 tokens
unique per frame; predicted endpoint ≈ 35–37 m at 3 s (≈ 12 m/s). VQ reconstruction is visually near
identical to the input — the 16× tokenizer loses little at 288×512; the information loss is the
downscale from 1920×1080, not the quantisation.

### 6.9.2 The three data layers, superimposed  [2026-08-29 16:45]

`viz/three_layers_superimposed.png` — one scene, one coordinate frame (local: origin = first ego pose,
UTM axes). What each part of the dataset is, verified by loading it:

| Layer | Files | Content | Frame |
|---|---|---|---|
| **1 Trajectory cache** (`trajdata_cache/nuplan_test.tar.gz`, 2 GB, **all 1,485 scenes**) | `nuplan_test/<scene>/agent_data_dt0.10.feather` (+ dt0.05, scene_index, metadata, `tls_data`) and `nuplan_test/maps/las_vegas.pb` etc. | ego + every agent's x,y,z,v,a,heading at 10/20 Hz for 5.5 s; traffic lights; the city vector map (lanes) | UTM |
| **2 Scene config** (`configs.tar.gz`, tiny, all scenes) | `navtest/configs/<scene>.yaml` | `central_log`, `central_tokens` (the nuPlan lidar_pc tokens forming the clip), `city`, **`road_block`** = the UTM bbox the reconstruction covers, reconstruction flags | UTM |
| **3 Renderer asset** (`assets/part001..015.tar.gz`, ~456 GB, **100 scenes local**) | `navtest/assets/<scene>/background/<scene>.ckpt` (422 MB), `road_height_map/{.npy,sim2.json}`, `video_scene_dict.pkl` | **1.5 M Gaussians** (means/quats/scales/opacities/SH colour) for the static world + a `skybox` + **24 `rigid_object_<id>` sub-models** — one per dynamic actor, each with its own Gaussians in object frame plus per-timestamp (111 @ 20 Hz) pose; a 780×480 road height raster at 3.33 px/m | recon frame + `recon2world_translation` → UTM |

Key link: the renderer's `rigid_object_<id>` ids **are** the trajectory cache's `agent_id`s — the
actors are rendered where the trajectory cache says they are (replay, not simulation).
The `road_block` bbox (44 m × 134 m here) is the extent the Gaussians were fit to; outside it the
render degrades — which bounds how far off the recorded path a closed-loop policy can wander.

## 6.10 First real local eval — VaVAM-B over the 100 local scenes  [VERIFIED 2026-08-29 17:05]

`runs/local100-vavam/` — `+e2e_challenge_nuplan=dev nuplan_scenes=navtest_local scenes.limit_to_first_n=0`,
stock VAVAM sample (`:local` twin), hardened container, 1 replica, 1 concurrent rollout.
**100/100 scenes completed, 0 failures**, ~11 s per scene once warm.

Official-style aggregate (`aggregate/metrics_results.txt`, after the eval modifiers that truncate a
rollout at first collision/offroad or once lateral deviation ≥ 4 m):

| Metric | Value | Read |
|---|---|---|
| `avg_dist_between_incidents_at_fault` | **0.38** (km) | the leaderboard's second metric; all incidents were at-fault |
| `collision_any` / `at_fault` (scene rate) | **0.09 / 0.09** | 9 % of scenes end in a collision VaVAM caused (7 % front, 2 % lateral, 0 rear) |
| `offroad` | 0.00 | never leaves the road |
| `wrong_lane` | 0.20 | in the wrong lane at some point in 20 % of scenes |
| `left_corridor_laterally` | 0.08 | |
| `dist_to_gt_trajectory` (max, mean over scenes) | 3.45 m | lateral: 1.60 m |
| `dist_to_gt_location` | 6.58 m | |
| `progress` / `progress_rel_to_total` | 0.96 / 1.08 | keeps driving; slightly *faster* than the human overall |
| `dist_traveled` vs GT | 33.9 m vs 32.8 m | (truncated rollouts) |
| `min_distance_to_obstacle_m` | 3.22 | |
| `plan_deviation` | 1.17 | |
| **`driver_drive_rpc_duration_mean_s`** | **0.089 s** over **1000 calls** | histogram: **992 ≤ 0.1 s**, 6 in 0.1–0.5 s, 2 in 0.5–1 s (warm-up) |

Raw (pre-modifier) per-scene view, 99 scenes: 11 collisions (9 front, 2 lateral, 3 rear), 12 left-corridor,
22 wrong-lane; lateral deviation mean 5.4 m / median 4.3 m / p90 10.7 m / max 32.8 m. Strongly
log-dependent: `veh-27_04122` averages 13.6 m deviation, `veh-25_00934` 2.0 m with no incidents.

Read-outs:
- **The failure mode is steering, not speed or safety margin**: 0 offroad, progress ≈ 1, but wrong-lane
  20 % and median 4 m lateral drift → the 3-way route command is not enough guidance. This is the
  route-conditioning gap, now measured, and it produces the at-fault collisions.
- **Throughput is fine**: steady state 99.2 % of `Drive` calls under 0.1 s on this GPU at 1 rollout.
  The 238 ms dev-scene mean was warm-up, as predicted. Still untested: 2 concurrent rollouts.
- **Stochastic**: the dev scene (`f02b15…`) was collision-free in the single run and collided here.
  Same weights, same scene — flow-matching starts from noise. Seed/average before A/B-ing changes.
- **Not a leaderboard number**: 100 scenes from one day/city. Comparable only to other local runs
  on `navtest_local`. Baseline for the starter over the same 100 scenes: see 6.11 when run.

## 6.11 First official submission  [2026-08-29 ~17:50 IST]

| | |
|---|---|
| Image | `696254625193.dkr.ecr.us-east-1.amazonaws.com/teams/team-lucifer:vavam-stock-20260829` — the as-shipped cu124 sample, 8.35 GiB, digest `sha256:0d49b3ff…` |
| Submission id | `6ba9c546-377a-437d-bafd-64de8892392e` (track `nuplan`) |
| Initial status | `QUEUED`, queue 1/1, `state_machine_started: false`; artifacts → `s3://alpasim-logs-s3-bucket-use1/tracks/nuplan/teams/team-lucifer/<id>/` |
| Quota | 1 of August's 5 used (they expire Sept 1) |

**Gotcha — Defect 6: the competitor CLI's `submit` pre-check is broken on Docker CLI 28.1.x.**
`ensure_image_exists()` shells out to `docker manifest inspect <uri>`, which on 28.1.1 fails with
`unsupported manifest format` for plain schema-2 manifests (OCI indexes work, so public images pass and
our ECR image does not). The check is purely local; the server validates on its own. Workarounds, in
order of cleanliness: upgrade Docker CLI ≥ 28.2; or POST `/submissions` through the CLI's own
`ChallengeClient` (what we did, after verifying the manifest with `docker buildx imagetools inspect`).
`docker buildx imagetools create` (OCI re-tag server-side) does **not** work: the team ECR role is
push-only (no `ecr:GetDownloadUrlForLayer`). Worth filing upstream.

**Result (checked 2026-08-30 12:51 UTC): `SUCCEEDED`.** Evaluated overnight (submitted 12:46 UTC per the
board; no evaluation timestamps visible without a fresh token).

| | Official (1,485 scenes) | Local (100 scenes) |
|---|---|---|
| Policy Capability Score | **1590.4 → rank 6 / 19 teams** | n/a (not computable locally) |
| avg dist between at-fault incidents | **1.62 km** | 0.38 km |
| dist_to_gt_trajectory | 3.05 m | 3.45 m |

Calibration verdict: inside the predicted 1550–1620 band (`vavam-sample-v2` = 1587). **The local
build, the cu128 twin, fp16 autocast, and the ECR/contract path are all validated.** The 4× gap in at-fault distance is the scene subset, not the setup — and the local starter run
(`local100-starter2`, 100/100) shows the subset is *unrepresentative* rather than merely hard:
starter **0.68 km** local vs 0.28 official, VaVAM **0.38** local vs 1.62 official. On mostly-straight
Strip scenes the straight-line driver crashes less (4 % at-fault) than VaVAM (9 %), whose lateral drift
is the failure mode there. Local ranking of policies on this subset is therefore **not trustworthy**;
more shards (curves, other logs) are needed before local A/B has meaning.
Standings snapshot saved: `leaderboard/nuplan-20260830.json`.

**Official throughput record for submission 1 (read 2026-08-31 with a fresh token):**
`observed_wall_time_s 2265.3` vs `limit_wall_time_s 2485.4` → **margin 220 s = 9.7 %**, `passed: True`.
Evaluation ran 12:01 → 12:46 UTC (45 min for 1,485 scenes). `image_size_bytes` 5.36 GB (compressed).
Implication: the budget is a *total wall-time* budget for the whole run (renderer + driver + everything), and stock B
used 91 % of it. A driver that is X % slower per call raises wall time by less than X % (the renderer dominates
per-scene time locally: ~0.9 s of `Drive` in ~11 s per scene), but with 4 driver replicas per GPU × 2 rollouts at
official eval the driver's share is unknown. **VaVAM-L measured 22 % slower per call than B locally** — a real
risk of a throughput FAIL; μP-B has the same compute as the passing B and is safe.

Poll: `alpasim_challenge.py status <id>` / `submissions --track nuplan`. Status reports observed
throughput wall time vs the per-track limit once evaluated.

## 6.12 Three-city local baselines — 300 scenes (Vegas/Boston/Pittsburgh × 100)  [2026-08-31]

| Driver (same 300 scenes) | at-fault dist ↑ | at-fault coll. ↓ | wrong lane ↓ | dist_to_gt ↓ | progress (→1.0) | notes |
|---|---|---|---|---|---|---|
| Starter (straight line) | 0.38 km | 7 % | 21 % | 2.29 m | **0.77** | floor; official 0.28 km |
| VaVAM-B, sample as submitted | 0.51 km | 6 % | 37 % | 3.40 m | 1.05 | official 1.62 km / PCS 1590 |
| **VaVAM-B + μP shapes** | **1.11 km** | **3 %** | 29 % | 2.16 m | 1.01 | submission candidate #2 |
| VaVAM-L + μP shapes | running (started ~11:22, alone) | | | | | latency probe 111 ms vs B 91 ms |

**Convention:** this 3-city/300 series is closed as-is; all subsequent evals use `navtest_local400` (4 cities).

Legend — direction of "better": **at-fault distance ↑** (km driven per at-fault incident; leaderboard metric),
**at-fault collisions ↓**, **wrong lane ↓**, **dist_to_gt ↓** (m from the recorded path), **progress → 1.0**
(distance driven ÷ human's; <1 under-drives, >1 over-drives — neither is good), PCS ↑ (official only), rank ↓.

Read-outs: the 3-city set restores the official ordering (VaVAM > starter), unlike the Vegas-only 100 — the yardstick
now ranks correctly. The starter's low progress (0.77) is its constant-speed under-driving; its at-fault rate (7 %) is
close to stock VaVAM's (6 %), i.e. stock VaVAM barely beats "drive straight" on safety — the μP fix is what
separates them. A parallel L run was attempted and **OOM'd the renderer** (two sim stacks + L driver > 24 GB);
one simulator stack per GPU on this machine.

## 6.13 Leaderboard forensics 2026-08-31 — what PCS actually rewards  [from the full 62-row nuPlan board]

Snapshot: `leaderboard/nuplan-20260831.json` (62 submissions, 20 teams). Evaluator hardware: our record shows
`dispatch_blocked_reason: p5_ssm_not_online` → the evaluator is an AWS **p5** (8× H100 80 GB).

| Fact | Numbers |
|---|---|
| Gain scales PCS monotonically | SymPhi: stock 1587.7 → gain1.05 **1679.6** → gain1.075 **1690.5** (#3). at-fault km 1.43 → 1.67 → 1.75, dist_to_gt 3.06 → 3.48 → 3.72 (worse!) |
| **μP + gain1.20 scored *below* stock** | SymPhi `vavam-mup-g120-v1` (08-30): **1559.6**, at-fault 1.63, dist_to_gt 3.02 |
| Safety ≠ score | `vf-team v2`: at-fault **12.75 km** (best on board), PCS **1095**. foxhihi `nu-driver-c6`: 5.69 km, PCS 1447. All low-PCS/high-safety rows also have *low* dist_to_gt (0.5–1.6 m) — cautious, slow, path-hugging drivers |
| Correlations (62 rows) | Spearman(PCS, at-fault km) +0.52; Spearman(PCS, dist_to_gt) **+0.69** (drifting *more* correlates with scoring *higher* — a proxy for driving faster) |

**Reading:** the per-scene score behind `zoib` is dominated by **progress** (distance/route completion), with collisions
as the zero branch. Driving faster than the human raises PCS even at the cost of more drift and slightly more
incidents; driving cautiously is punished hard. This is consistent with a NAVSIM-style PDMS where ego-progress
carries large weight.

**Implication for submission candidate #2 (μP-B):** our μP fix makes B drive at *human* speed (progress 1.05 → 1.01)
while halving at-fault collisions. Locally that is "better on every metric"; officially the speed loss may cost more
than the safety gain earns — SymPhi's μP entry is the warning. **Do not submit μP-B alone.** The candidate has to be
**μP + gain**, with the gain chosen so progress lands ≥ stock's 1.05 — and the local A/B must be read on *progress and
at-fault together*, not at-fault alone. SymPhi's g1.20 on top of μP overshot (dist_to_gt back to 3.0, PCS down); the
sweet spot is probably μP × 1.05–1.10, to be measured.

Local numbers to steer by (300 scenes): stock B progress 1.05 / at-fault 6 %; μP-B progress 1.01 / at-fault 3 %.

## 6.14 Driver load test — the sample serialises inference  [2026-08-31 13:20, μP-B `:local-mup`, RTX PRO 4000, GPU shared with a running eval]

`capture/driver_loadtest.py`, 40 s per setting, 3 warm-up calls/stream excluded:

| streams | mean | p50 | p90 | p99 | aggregate throughput |
|---|---|---|---|---|---|
| 1 | 93 ms | 90 | 104 | 110 | 9.4 calls/s |
| 2 | 176 ms | 175 | 191 | 203 | 10.7 calls/s |
| 8 (official per-GPU shape) | 772 ms | 773 | 834 | 884 | 9.8 calls/s |

**Throughput is flat; latency scales linearly with streams** → the sample's `_inference_lock` serialises
`predict()`; concurrent sessions queue for one GPU pass at a time. No batching across sessions.

**What the official budget actually needs (demand vs capacity):** 1,485 scenes × 10 `Drive` calls = 14,850
calls over the whole run, spread across 16 replicas → ~930 calls per replica; the passing run took 2,265 s →
**demand ≈ 0.4 calls/s per replica**, against a capacity of ~10 calls/s per replica on *this* GPU (and 4
replicas share one H100 there, so ≈ 2.5+ calls/s each even if H100 were no faster). The driver is
**not** the wall-time bottleneck for B-class models — the renderer is — which is consistent with the
measured local Drive share of wall — **2.3 % on the slow preset** (88.6 s of ~3,900 s), **11.2 % on `dev_fast`**
(272 s of 2,419 s), **~21 % on `dev_fast2`** (Σ over both workers; 153.5 s per worker of 1,465 s). The share *rises* as the
simulator gets faster because the driver's absolute time is constant — so local share is preset-dependent and not
directly the official figure; the transferable statement is demand vs capacity (0.4 vs ~10 calls/s per replica, above).
Note: `DRIVER` lines logged before 13:55 report the *renderer's* VRAM (attribution fixed since; driver B = 2.7 GB).

Consequences:
- Per-call latency under contention is the wrong yardstick for the throughput budget; **aggregate
  calls/s vs ~0.4 calls/s demand** is the right one. B-class models have ~20× headroom.
- The per-call "≤ 0.1 s target" in the README is advisory; enforcement is total wall time.
- Batching across concurrent sessions (one backbone pass, many flow samples/sessions) is how the
  `k5-medoid` teams afford multi-sample inference — a later optimisation, not needed for B.
- Warm-up (first calls 0.5–1 s) is irrelevant to the budget at this headroom; still worth doing for hygiene.

## 6.15 Submitted model — official vs local, side by side  [2026-08-31]

Same image (stock VaVAM-B, `vavam-stock-20260829`). "Official-style" = the evaluator's aggregation (rollouts truncated at
first collision/offroad or ≥ 4 m lateral deviation); "raw" = per-scene maxima without truncation. Local runs used the
original `dev` preset (8 cameras, video on) — the slow one, i.e. no fast-preset caveats apply.

| Scope | Scenes | At-fault dist ↑ | At-fault coll. ↓ | dist_to_gt ↓ | Progress →1 | PCS ↑ |
|---|---|---|---|---|---|---|
| **Official** | 1,485 (4 cities) | **1.62 km** | — (not exposed) | **3.05 m** | — | **1592.2, #8/20** |
| Local, official-style aggregate | 300 (Vegas/Boston/Pittsburgh) | 0.51 km | 6 % | 3.40 m | 1.05 | n/a |
| Local, official-style aggregate | 100 (Singapore) | 2.90 km | 1 % | 3.79 m | 1.06 | n/a |
| Local, raw per-scene, combined | **400 (4 cities)** | 0.49 km | 7.0 % (28) | 5.69 m (untruncated) | 1.07 | n/a |

Per city (raw): Vegas 0.36 km / 10 % at-fault / 24 % wrong-lane · Boston 0.43 / 8 % / **62 %** · Pittsburgh 0.44 / 8 % / 48 % ·
Singapore **1.58 / 2 % / 25 %**. Offroad 0 everywhere.

Reading: the local 400 is ~3× harsher than the official set on at-fault distance (0.49 vs 1.62 km) even with all four
cities represented — the local scenes are proportionally more dense-urban than the full navtest mix (the official set has
long incident-free stretches where a policy accrues kilometres). dist_to_gt matches better (3.4–3.8 local vs 3.05 official).
**Use local numbers as ratios on identical scenes; the absolute local↔official mapping needs a second submitted image.**

## 6.16 A1 driver patch (gain / seed / warm-up) + A2 gain screen  [2026-08-31 15:15]

Patch in `e2e_challenge/sample_submission_vavam/vavam_challenge/` (local working tree, uncommitted), all **opt-in / inert by default**:
- `vavam_policy.py`: `VAVAM_OUTPUT_GAIN` (default 1.0) multiplies the 6 predicted waypoints; `VAVAM_SEED` (default −1 = off)
  seeds `torch.manual_seed(seed + call_index)` before each flow-matching sample (predict is serialised by the driver lock).
- `driver.py`: `VAVAM_WARMUP` (default 3) dummy inferences after load, before the policy is published; call counter reset so
  the seeded sequence is independent of warm-up.
- Verification (CPU, cu128 image): same seed twice → max |Δ| = **0.0**; gain 1.05 → endpoint ×**1.050**; live container log:
  `Policy options: output_gain=1.000 seed=1234`, `warm-up: 3 inferences in 1.7s`.
- Launcher: `DRIVER_ENV="…"` passes env into the driver container (no rebuild per variant). Submission images bake ENV instead.

A2: `screen-mup-g100 / g105 / g110` — μP-B, seed 1234, `navtest_local100`, `dev_fast2`, sequential (~10 min each incl. warm-up).
Decision rule: pick the gain with **progress ≥ 1.05** and the **lowest at-fault rate**, read with dist_to_gt; confirm on `navtest_local400`.

**Interim (g1.00 vs g1.05, same seed, same 100 scenes — 15:45):**

| gain | at-fault dist | at-fault (count) | any coll | wrong lane | dist_to_gt | progress |
|---|---|---|---|---|---|---|
| ×1.00 | 0.94 km | 3 % (4 raw) | 3 % | 33 % | 2.71 m | 1.05 |
| ×1.05 | 0.58 km | 5 % (7 raw) | 5 % | 34 % | 3.02 m | 1.06 |

Per scene (paired, identical noise): identical collision outcome 97/100; the **3 changed scenes all became collisions** under
×1.05, all at already-high-drift scenes (dist_to_gt 4.5–8.5 m); Δprogress mean **+0.016**, median **0.000** (38 scenes
faster, 7 slower); Δdist_to_gt mean **+0.39 m** (57 scenes worse, 14 better). → on the μP-*correct* model, +5 % gain buys
almost no progress and costs path accuracy and safety. SymPhi's gain wins were on the μP-*broken* model (4× overshoot in
the velocity field), where the interaction is different.

**Final A2 (15:51, all three on the identical seeded 100 scenes):**

| gain | at-fault dist | at-fault (raw) | any coll | wrong lane | dist_to_gt (raw mean) | progress |
|---|---|---|---|---|---|---|
| **×1.00** | **0.75 km** | **4** | 4 | 36 | **4.35 m** | 1.052 |
| ×1.05 | 0.44 km | 7 | 7 | 39 | 4.74 m | 1.068 |
| ×1.10 | 0.46 km | 7 | 7 | 38 | 5.42 m | 1.079 |

Paired vs ×1.00: ×1.05 → 3 new collisions / 0 removed, Δprogress +0.016 (median 0), Δdist_to_gt +0.39 m (57 worse / 14 better);
×1.10 → 3 new / 0 removed, Δprogress +0.026 (median 0), Δdist_to_gt **+1.07 m** (71 worse / 9 better). Monotonic: more gain =
more lateral error, more collisions, negligible progress. **Decision: gain stays 1.00. Candidate #2 = μP-B ×1.00.**
Confirm on `navtest_local400` (`confirm400-mup-g100`, seed 1234, dev_fast2) launched 15:53.
Submission image rebuilt 15:55 with the patched code: `alpasim-e2e-vavam-driver:submit-mup` (as-shipped cu124 base + μP
shapes + warm-up 3; gain 1.0 / seed off by default), 8.35 GiB; CPU check: `Applied muP base shapes`, endpoint 29.25 m straight.
**Not yet pushed/submitted.** (The `vavam-b-mup-20260831` tag already in ECR is the pre-patch build without warm-up — supersede it.)



## 7. Next steps, in order

> **The forward plan now lives in `archive/strategy.md` §8** (fixes needed to compete locally, policy work in
> evidence-ranked order, submission strategy). This section is kept for history.


Local environment is **done** (§6.5). What remains is competition-side:

1. **Register the team** on the [HF Space](https://huggingface.co/spaces/nvidia/AlpasimE2EClosedLoopChallenge2026)
   and wait for approval — the only step with external latency, and evaluation downtime
   starts **2026-08-31**.
2. Authenticate the competitor CLI (`auth-url` → `configure-token` → `me`), then `ecr-login`.
3. **Develop the actual policy** — replace `starter_kit/driver.py`'s straight-line fallback.
   Constraints: 16 GiB VRAM, 0.1 s/`Drive` call under 2 rollouts/replica, no network,
   read-only rootfs, 2 GiB `/tmp`. Sample submissions (vavam, transfuser, diffusiondrive,
   gtrs_dense) are reference points under `e2e_challenge/`.

   → **Start from VaVAM.** Rationale, evidence and the rejected alternatives are in
   [`archive/RANKING.md` §10](archive/RANKING.md). Summary: it is the only sample that matches the driver
   API with no adapter; it is **pinhole-native and 2 Hz-native**, both of which are free wins
   on the nuPlan track specifically (the 546-line `rectification.py` and the plan-cache
   staleness are PAI-only concerns); its video pretraining survives MTGS novel viewpoints
   where open-loop NAVSIM models do not (`opendrivelab-org`'s 17-model sweep peaked at 1377
   vs VaVAM's 1587-1731); and the tuning surface is ~162 lines. **CarPlanner does not fit** —
   the driver API supplies no map and no agent tracks, so a privileged vector planner would
   need a full perception stack built in front of it (`archive/RANKING.md` §10.7).

   What to optimise once it runs is [`archive/RANKING.md` §3 and §9](archive/RANKING.md): progress saturates
   at 80%, and exactly three conditions zero a scene.
4. Iterate locally: build policy image → `run_local_container.sh` → smoke test → metrics.
5. When ready: push to ECR with a **specific tag** (`latest` rejected), `submit --track nuplan`.
6. Optional, later: full navtest sweep (~458 GiB → SeagateHub1) for local scoring at scale.

Housekeeping (safe, whenever):
- delete `~/alpasim-challenge/nuplan-track-hf` tarballs (~34 GB, already extracted+verified)
- `docker image prune` the 19.5 GB dangling image; unrelated project images are the user's call
- rotate the HF token (it appeared in a chat transcript)
- file the upstream issues: Defect 3 (editable `scripts` pkg) and Defect 5 (casadi 3.8 lock)

## 9. Change ledger — every fix applied, and where it lives

Everything below is the complete set of modifications made on this machine beyond stock upstream.
Anything not listed here is unmodified upstream `e2e_challenge` @ `f012862`.

### A. Repo working tree — `~/alpasim-challenge/alpasim`  ⚠️ **uncommitted**

| File | Change | Why | Defect |
|---|---|---|---|
| `src/controller/pyproject.toml` | `+ "casadi<3.8"` in `dependencies` (4 lines incl. comment) | casadi 3.8.0 removed the `casadi.tools` re-exports (`SX`/`MX`) that do-mpc 5.1.1 imports at load; controller container crashed at import. Upstream leaves casadi unconstrained | 5 |
| `uv.lock` (**gitignored** — local artefact, never upstream's) | casadi 3.8.0 → 3.7.2 via `uv lock` | consequence of the above | 5 |
| `e2e_challenge/sample_submission_vavam/Dockerfile.local` (**new**) | copy of `Dockerfile` with `FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime` + a LOCAL-ONLY comment | torch 2.6+cu124 has no sm_120 kernels — measured `no kernel image is available` on this GPU. **Test with `:local`, submit the original `Dockerfile`** | — |
| `e2e_challenge/sample_submission_vavam/Dockerfile.local.dockerignore` (**new**) | copy of `Dockerfile.dockerignore` | docker looks up `<Dockerfile>.dockerignore` per Dockerfile name | — |
| `e2e_challenge/sample_submission_vavam/assets/vavam/*.pt, *.jit` (gitignored) | staged VaVAM-B weights | build input | — |

**Risk:** `git pull` can conflict with the pyproject edit; `git checkout -- .` / `reset --hard` silently
reverts it and the controller crash returns. **Recommended:** commit these to a local branch
(`git checkout -b local-fixes && git add -A src/controller/pyproject.toml e2e_challenge/sample_submission_vavam/Dockerfile.local* && git commit`).
When upstream constrains casadi or do-mpc supports 3.8, drop the pin rather than carry it.

The `~/Downloads/alpasim_challenge/alpasim` clone has **none** of these — it is pristine upstream.

### B. Setup script — `~/Downloads/alpasim_challenge/alpasim-setup-4090.sh` (ours, not upstream)

| Function | Change | Why | Defect |
|---|---|---|---|
| `build_base()` | version read via `awk` instead of `python3 -c "import tomllib"` | host python is 3.10; `tomllib` is 3.11+; killed the whole `all` run under `set -e` | 1 |
| `setup_env()` | **no longer sources `setup_local_env.sh`**; runs `PYTHONPATH=. uv run --no-sync compile-protos` from `src/grpc`, `uv pip install -e src/utils_rs`, then `uv sync --extra all --extra mtgs` | upstream's script dies at `compile-protos` (`No module named 'scripts.compile_protos'` — editable install omits the `scripts` pkg) | 3 |
| `setup_env()` | `--extra mtgs` always included when `plugins/mtgs` exists; `transfuser` only with `ALPASIM_FULL_SYNC=1` | `all` excludes `mtgs`; `uv sync` prunes → bare `--extra all` uninstalls the renderer the host needs for Hydra config discovery | 2 |
| `preflight()` | host `cuInit()` probe via ctypes; GPU probe pulls the image explicitly and prints the error | a wedged `nvidia-modeset` thread left `nvidia-smi` working while every CUDA call failed with 999 — only a reboot clears it | 0 |
| `preflight()` | `HF_TOKEN` warns instead of dying; disk check walks up to an existing dir | dataset is public/ungated; `df` on a not-yet-created `$WORKDIR` failed | — |
| `fetch_data()` | `uv run --no-project` | plain `uv run` picked up the repo project and tried to sync it | — |
| `verify_stack()` (**new phase**) | value-checked torch + gsplat rasterization inside `alpasim-base` | prove sm_120 execution before a smoke run; arch mismatches fail **silently** | §4 |
| `verify_stack()` | `docker run -i` | without `-i` the heredoc never reaches `python -`; empty script exits 0 → **false PASS** | 4 |
| phases | `env`, `verify`, `next` added; `all` = preflight → clone → env → data → base → driver → verify | | |

### C. Not changed, deliberately

- **`Dockerfile` (alpasim-base) and `TORCH_CUDA_ARCH_LIST=8.9;9.0+PTX`** — left stock. Measured to work on sm_120 via PTX JIT; the once-proposed CUDA-12.8 bump is unnecessary and would diverge from the competition environment.
- **`sample_submission_vavam/Dockerfile`** — left stock; it is the submission image. Only the `.local` twin differs.
- **`requirements.txt` pin `VideoActionModel@v1.0.0`** — left stock; the post-tag rolling-slice hot-fix only matters for multi-frame inference, which the sample does not do. Move to `@738050e` if that changes.

### D. Machine-level

- One **reboot** (Defect 0). No driver/toolkit reinstall, no config change.
- Docker cleanup: removed `nvidia/cuda:12.8.0-devel-ubuntu24.04` (control-test image), the pre-casadi `alpasim-base`, both smoke runs' stopped containers, build cache, and a superseded `robotic-grounding` dangling image. Nothing challenge-critical removed; `12.4.1-cudnn-devel` (the FROM layer) kept.
- `~/.alpasim/challenge.json` — CLI token (12 h expiry). `~/.cache/huggingface/token` — HF token (**rotate**).

### E. Worth filing upstream (NVlabs/alpasim issues)

1. **Defect 3** — `setup_local_env.sh` fails on a clean clone: editable `alpasim_grpc` omits the `scripts` package the `compile-protos` console script imports.
2. **Defect 5** — `src/controller` leaves `casadi` unconstrained; casadi 3.8.0 breaks do-mpc 5.1.1 at import. Suggest `casadi<3.8` until do-mpc catches up.

## 8. Open questions

**Resolved since the last revision:**

- ~~Who ran the bare `uv sync --extra all`?~~ → **Answered.** A deliberate "lean sync" in an
  assistant session, on reasoning that §4.5 disproves. Not an automated source; will not
  recur. Script default corrected. See §3 Defect 2.
- ~~`HF_TOKEN` unset~~ → **Set and validated** (`skr3178`, role `read`). Separately confirmed
  the dataset is **public and ungated** (`gated: False`, anonymous fetch → HTTP 302), so a
  token is not strictly required for this track at all — `preflight` now warns instead of
  hard-failing. **Rotate the token**: it was pasted into a chat transcript.
- ~~Will the Blackwell/sm_120 path work?~~ → **Yes, measured.** See §4.

**Still open:**

- **Does gsplat specifically compile and run under nvcc 12.4?** The §4 proof used a trivial
  kernel. `alpasim-setup-4090.sh verify` answers this.
- **What torch does the base image resolve to?** Unpinned from PyPI. Host-side is
  `2.8.0+cu128` (sm_120 native, fine), but the container resolves independently, and a
  pre-cu128 wheel would fail the same silent way. Same `verify` phase covers it.
- **Disk** at 79% with 183 GiB free. Revised budget is ~120 GiB for the dev subset + images
  (was ~150). Large unrelated images are reclaimable: `nemo` 37 G, `catk-spacer` 22.4 G,
  `nomad-gpudrive` 22.3 G, `isaac-lab` 17.6 G, two 19.5 G images. Also
  `~/alpasim-challenge/nuplan-track-hf` holds **~34 GB of tarballs** now redundant since
  extraction succeeded.
- **Full navtest sweep needs ~458 GiB** (measured from the HF API — the whole dataset is 20
  files totalling 457.7 GiB, versus 33.7 GiB for the three dev shards). That will not fit on
  `/home`; point `ALPASIM_NUPLAN_ROOT` at SeagateHub1 (1.9 TB free) before attempting
  `+e2e_challenge_nuplan=full`.
- **Evaluation downtime starts 2026-08-31**, i.e. in ~2 days.

## 6.17 Candidate #2 confirm gate + route-selection exploration  [2026-08-31 16:24–16:45]

**Confirm run** `confirm400-mup-g100`: μP-B, gain ×1.00, seed 1234, `navtest_local400` (100/city), `dev_fast2`. 400/400 completed,
1886 s wall (4.2 s/scene), Drive 103 ms mean = 21.8 % of wall, driver VRAM 2.7 GiB, GPU total peak 23.0 GiB (the 2-rollout ceiling).
Paired against stock B on the identical 400 scene ids (`local300-vavam` + `sg100-vavam-submitted`):

| metric (400 scenes) | stock B | μP ×1.00 |
|---|---|---|
| at-fault collisions (count / rate) | 20 / 5.0 % | **13 / 3.3 %** (13 removed, 6 new) |
| rear collisions | 5 | 1 |
| left corridor laterally (≥ 4 m) | 40 | 33 |
| offroad | 0 | 0 |
| wrong-lane rate | 33.5 % | 28.2 % |
| dist_to_gt_trajectory (m) | 3.50 | **2.35** |
| lateral dist to GT (m) | 1.83 | 1.37 |
| dist_to_gt_location (m) | 6.49 | 5.23 |
| progress_clipped_rel | 1.053 | 1.020 (−3.1 %) |
| km per at-fault incident | 0.63 | 0.90 |

Gate rule was "at-fault ≈ half, progress within a few %": at-fault −35 % (beyond the ±4/400 noise floor), progress −3 %. **Gate met.**
Ship = push `alpasim-e2e-vavam-driver:submit-mup` + submit, on explicit go only (August quota expires 00:00 UTC Sept 1).

**Exploration for the next round** (recorded in `archive/ROUTE-SELECTION-PLAN.md`), three facts that change the design:
1. `route_start_offset_m: 40.0` in every challenge config → the route the driver sees spans 40–80 m ahead (≈10 finite waypoints,
   NaN-padded to 20). The 3 s prediction never overlaps it; `waypoints[0]` is not the ego's cross-track error. Scoring needs a bridged
   reference (Hermite from ego pose to route start).
2. `forward_inference` batches: `bsz` from the token tensor, `torch.randn((bsz,1,6,2))`, GPT trunk KV-cached once per call → k samples in
   one call, cost ≈ 1 trunk + 10·k action-expert steps; VRAM of the k× visual KV cache (900×1600 input, ~5.6k tokens/row) is the limit.
   Inference already runs only on 1 of 5 Drive calls (500 ms interval vs 100 ms tick). Row 0 of a seeded batch equals the seeded single
   draw → a k>1 run with "select index 0" reproduces the baseline exactly (used as the Stage-0 identity check).
3. The driver gets no actor/obstacle data (images, ego pose + rig-frame `DynamicState`, route only). The MPC follows pose *timing*
   (velocity weights are 0; penalty only on 1.0–2.0 s ahead), so speed control = compress the whole 3 s plan. Today's fallback is a
   ≥ 2 m/s straight line — the driver cannot stop; the plan replaces it with a decelerating continuation, never `terminate_session`.
Scorer: at-fault = front ∪ lateral; rear truncates progress but is not a fail; scene score saturates at 80 % progress.

**Push + submit attempt (16:45–16:48, on explicit go):** `docker tag submit-mup → …team-lucifer:vavam-b-mup-20260831b`, `docker push`
succeeded on cached ECR credentials (only the app layer uploaded; digest `sha256:d24a7a78bbfb…`, schema-2 manifest verified with
`buildx imagetools inspect`). But the API's `ecr-login` and `POST /submissions` both returned **HTTP 403
`Competition status is CLOSED; expected one of OPEN`**; `limits`: status CLOSED, 4/5 August remaining; `me`: token fine until 17:11 UTC.
So the announced Aug 31 – Sep 6 downtime closes the whole submission API. Candidate #2 is staged in ECR; submit when `limits` says OPEN.

---

## §7 Doc consolidation (2026-09-01)

`LOCAL-PLAN.md` and `SHARDS-RUNBOOK.md` retired; content redistributed. Backup of every file touched:
`.doc-backup-20260901/`.

| Was in LOCAL-PLAN | Now |
|---|---|
| Fix 1 (representative scene set) | **Done** — 400 scenes, 4 cities. Inventory + download in `EVAL-RUNBOOK.md` §1 |
| Fix 2 (repeatable runs) | **Done** — `VAVAM_SEED` shipped in the A1 patch (2026-08-31 15:15) |
| Fix 3 (per-scene official metrics) | **Blocked** — artifacts in a private S3 bucket; tracked as C4 in `archive/strategy.md` §8 |
| Fast eval loop findings + exact YAML | `EVAL-RUNBOOK.md` §2-3 |
| Policy work (P-series) | `archive/strategy.md` §8 (as A/B/C/D + N + X rows) |
| Submission strategy | `archive/strategy.md` §6 |
| Housekeeping | `archive/strategy.md` §8 D-rows; practices in `EVAL-RUNBOOK.md` §4 |
| Next round after candidate #2 | `archive/ROUTE-SELECTION-PLAN.md` |

**Doc set after consolidation** — one file per question:

| File | Question it answers |
|---|---|
| `CURRENT-BEST.md` | What are we submitting, and against what baseline? |
| `archive/strategy.md` | What do we do next, and how do we decide? |
| `EVAL-RUNBOOK.md` | How do I run a local evaluation? |
| `archive/RANKING.md` | Why does the score behave this way? |
| `METRICS.md` | What does this term/metric mean? |
| `archive/ROUTE-SELECTION-PLAN.md` | How is the in-flight B1/B2/B4 change designed? (retire on ship) |
| `SETUP-NOTES.md` | What happened, and what broke? |

## 6.18 Defect 8 — silent inference fallback manufactured a complete, wrong run  [2026-09-01 14:10–14:30, peer session]

First S0 launch (`screen-s0-k5`, k=5) ran 32 scenes with **zero** policy calls succeeding: `predict_k` did
`tokens.expand(k, -1, -1)` on a 4-D token tensor (1, 1, 18, 32) → `RuntimeError` on every call. `driver._maybe_run_inference`
catches all exceptions (`LOGGER.exception; return`) and keeps serving the stale plan — which, before the first successful inference,
is the ≥ 2 m/s straight-line fallback. The wizard saw healthy sessions; the aggregate would have looked plausible. Detected only
because the "S0 k=" log count stayed at 0 while scenes completed. 447 failures in the container log.
Fixes (in `local-mup-k` 6854e313): expand sizes built from `ndim`; warm-up now runs `predict_k` at the configured k, asserts k
candidates, and **re-raises** ("refusing to serve") so a broken inference path kills the container at start-up; regression test added
(29 tests). Aborted run parked at `runs/screen-s0-k5-ABORTED-broken-expand` — do not read metrics from it.
**Rule from now on:** every run's early check = `docker logs local-driver | grep -c "inference failed"` must be 0 and the policy's own
per-call log line count must be > 0 once scenes complete; an aggregate is not evidence that the policy ran. Also note the
`pgrep -f` self-match trap (EVAL-RUNBOOK "Is the GPU free?").

## 6.19 S0 screen result + Defect 9 (seed not reproducible)  [2026-09-01 14:29–14:55]

`screen-s0-k5` (k=5, seed 1234, 100 scenes, dev_fast2): 100/100, 604 s, 0 inference failures, warm-up logged "(k=5 verified)".
Aggregate vs `screen-mup-g100`: at-fault 3 vs 3 (2 swaps), progress 1.0472 vs 1.0484, dist_to_gt 2.75 vs 2.71, corridor 7 vs 7,
wrong-lane 31 vs 33, Drive 126 vs 103 ms. Per-scene: 0/100 bit-identical, |ddist| median 0.52 m (unchanged stock-B reruns: 0.26–0.30),
at-fault flips 2/100 (reruns: 10–12/300). S0 log (1000 lines): spread median 1.742 / mean 1.824 / p90 2.915 m; argmin≠0 0.60;
reasons tie_progress 608, guard_route_implausible 270, selected 106, no_safe 11, no_route 5; infer_ms mean 113 / p95 138.
**Defect 9:** `_seed_for` offsets by `hash(session_uuid)`; PYTHONHASHSEED unset → different noise every launch even with VAVAM_SEED set, and
session_uuid is fresh per run anyway. Fix: key on `scene_id` (present locally, stripped officially → fall back to session_uuid) with
`zlib.crc32`. Until fixed no A/B is paired. Offline check (in-container, same process/seed): row 0 of k=5 vs k=1 max diff 0.0044 m; k=5
bit-deterministic. Verdict: k path sound; S0 PASS; identity vs the old baseline unreachable by design (schedule changed).
`guard_route_implausible` (|y|>12 m or x<5 m on route[0]) fires on 27 % of ticks — at 40 m lookahead any turn > ~40° exceeds 12 m, so it
disables selection exactly on turns; loosen/curvature-based. Review of selection.py (heading term not in scores; progress = x_end;
no_safe ranks all; drivable≡route) sent to the selector session for S1.

## 6.20 S1 sequence (peer session `alpasim-challenge-ad`, image `local-mup-k` v3, scene-keyed seeding)  [2026-09-01 15:01–15:26]

| run | scenes | wall | Drive mean | note |
|---|---|---|---|---|
| `s1a-k1` (k=1, new baseline) | 100/100 | 606 s | 102 ms | at-fault **7**, rear 1, corridor 6, wrong-lane 27, progress 1.031, dist_to_gt 2.66 |
| `s1b-k5-off` (identity control) | **2/100** | 195 s | — | renderer died: `CUDA error: the launch timed out and was terminated` (display-GPU watchdog; peak GPU 22.8 GiB on s1c → memory pressure plausible). Wizard exited 0 and wrote an aggregate with 98 failed rows — **`RUN DONE` is not proof of a valid run; gate on completed count.** Moved to `s1b-k5-off-FAILED-cuda-timeout`; rerun launched 15:35 |
| `s1c-k5-on` (selection ON — first run where the selector steers) | 100/100 | 624 s | 126 ms | at-fault **6** (2 removed, 1 new front), rear 0, corridor 6, wrong-lane 29, progress **1.058**, dist_to_gt 2.69, lateral 1.29; log: applied 87 % of ticks (guard 12 %), argmin≠0 80 %, spread median 1.69 m, consecutive-tick switch rate ≈ 0.78, infer 111 ms / p95 135 |

Interim read (s1c vs s1a; valid to ~4 mm as identity proxy because row 0 of k=5 == k=1 under scene-keyed seeds): safety within noise
(−1 at-fault), progress +0.026 mean (44 up / 9 down), path accuracy unchanged → neutral-to-slightly-positive. The selector switches plan
almost every tick → `w_disc` is the first S1b arm.
**Seed-variance finding:** `s1a-k1` (7 at-fault) vs `screen-mup-g100` (3) — same config, same 100 scenes, only the noise draw differs.
The 100-scene at-fault count therefore carries **±4 seed noise, not ±2**; earlier `screen-*` numbers were single draws and may have been
optimistic. Consequence for the eval standard: read arms on 400 scenes, or on two seeds, before believing a ≤ 4-incident delta.

**S1 formal tables (s1b rerun 15:27–15:35, 100/100, 481 s, Drive 129 ms, peak GPU 22.1 GiB):**

| pairing (100 scenes) | at-fault | rear | corridor | wrong-lane | progress | dist_to_gt | scene-score proxy |
|---|---|---|---|---|---|---|---|
| **identity** `s1a-k1` → `s1b-k5-off` (same seeds; only batched-fp16 numerics differ) | 7 → **5** (0 new, 2 removed) | 1→1 | 6→8 | 27→30 | 1.031→1.030 | 2.66→2.56 | 0.858→0.859, fails 13→13 |
| **experiment** `s1b-k5-off` → `s1c-k5-on` (proper control) | 5 → **6** (1 new, 0 removed) | 1→**0** | 8→**6** | 30→29 | 1.030→**1.058** (+0.027; 45 up / 7 down) | 2.56→2.69 (+0.13; 42 worse / 46 better) | 0.859→**0.878**, fails 13→12 |

Identity control per scene: 0/100 within 1 mm, |ddist| median 0.14 m, max 3.0 m — a 4 mm per-call numeric difference (batch-5 vs batch-1
fp16 kernels) is amplified by the closed loop into a **2-incident change in at-fault count with zero policy change**. The numerics-only
noise floor on 100 scenes is therefore ±2 at-fault; with seed variation it is ±4 (`screen-mup-g100` 3 vs `s1a-k1` 7). No 100-scene delta
below that is evidence.
**S1 verdict: NEUTRAL on safety (+1 at-fault, −1 rear, −2 corridor — all inside the floor), POSITIVE on progress (+2.7 %, 45 up / 7 down,
scene-score proxy +0.019), slightly worse path (+0.13 m dist_to_gt).** Selector applied 87 % of ticks, switches plan on ≈ 78 % of
consecutive ticks (w_disc = 0). Per plan §7 → "neutral" branch: S1b = `w_disc` sweep {0.1, 0.3} (+ consensus gate) on **two seeds × 100**,
then B3 temporal context.

## 6.21 S1b — `w_disc` sweep, seed 1234, 100 scenes, image v4 (peer session)  [2026-09-01 16:05–17:04]

Control `disc-d00` is **bit-identical to `s1c-k5-on`** (100/100 scenes) → v3/v4 image caveat closed. `base_x` early-check corrected
(plan point 0 is one step ahead of the ego, so ≈ +5 m is right; the "must be negative" version aborted a correct run at 14/100).

| w_disc | at-fault | corridor | wrong-lane | progress | dist_to_gt | score proxy | vs control | d_end median / >1 m | disc share of margin |
|---|---|---|---|---|---|---|---|---|---|
| 0 (control) | 6 | 6 | 29 | 1.0575 | 2.692 | 0.878 | — | 1.90 / 0.75 | 0 |
| 0.05 | 6 | 6 | 30 | 1.0552 | 2.725 | 0.878 | 57 scenes identical; no-op | 1.75 / 0.71 | 0.15 |
| 0.2 | **5** | **5** | 29 | 1.0518 | 2.676 | **0.897** | −1 at-fault (removed), −1 corridor, −0.6 % progress | 1.55 / 0.66 | 0.54 |
| 0.4 | **4** | 5 | 29 | 1.0521 | 2.686 | **0.906** | −2 at-fault (removed, 0 new), −1 corridor, −0.5 % progress | 1.31 / 0.60 | 0.77 |

Monotone: more plan continuity → fewer at-fault and corridor exits, progress cost flat at −0.5 %, path accuracy unchanged, Drive 127–130 ms.
Effect size (−2/100) equals the numerics floor, so it is "consistent with helping", not proof; the monotone trend across four arms and the
falling `d_end` are the evidence that it is real. **Measurement note:** the candidate-index "switch rate" stays 0.80 at every weight and is
meaningless — with fresh noise each tick index i has no identity across ticks; `d_end` is the continuity measure. (The peer's alternative —
persistent noise vectors so candidates are persistent modes — would make the index meaningful; parked, not rejected.)
Next candidates: w_disc = 1.0 at seed 1234 (does the trend continue or does progress start paying?), then the best weight + its control at
seed 5678; then S3 on 400 if two seeds agree.

## 6.22 Leaderboard forensics 2 — what the top nuPlan entries most likely did  [2026-09-01 17:30]

Sources: `leaderboard/nuplan-20260901.json` (tags + metrics), `leaderboard/pai.json`, NVIDIA forum thread 380855 (route accumulation),
NVlabs/alpasim issues #133 / #138 / #166, `route_generator.py` (`RouteGeneratorMap`).

| entry | PCS | at-fault km | dist_to_gt | profile → inferred approach |
|---|---|---|---|---|
| NaLa `sub1` | 1715 | 3.36 | **0.98** | MEASURED: 2.1× stock's at-fault km, dist_to_gt 3× tighter than any `vavam-*` entry (2.65–3.72). INFERRED: progress not sacrificed (equally tight but slow entries score 1420–1450). HYPOTHESIS (unverified — no writeup exists): a driver that **follows the route/GT path directly** (route = recorded trajectory snapped to lane centres, `route_generator.py:355-377`) with a speed policy; alternatives: a map-input model, or a VaVAM hybrid with trajectory-level route correction |
| 메타몽 `vavam-route-cudagraph-v5` | 1715 | 3.09 | 2.65 | VaVAM **plus real route conditioning** (halved incidents vs stock, path a bit tighter) + CUDA graphs for speed. The same score as NaLa via a different route |
| SymPhi `gain1075` | 1691 | 1.75 | 3.72 | stock VaVAM × 1.075 — pure speed; same safety as stock |
| stock VaVAM (us, foxhihi b1, Host) | 1590–1600 | 1.5–1.7 | 3.05 | baseline cluster |
| foxhihi `c*`, Cothlory, vf-team | 1095–1478 | 3.9–12.8 | 0.6–1.6 | cautious path-huggers: safe, slow → punished on progress |

**Key facts that make the path-follower reading plausible:** (1) the challenge route is the *recorded ego trajectory projected onto lane
centre-lines*, extended along the lane after the recording ends — it is the GT path to within a lane-centre offset; (2) the driver may
**accumulate `submit_route` observations over time** (organizer, forum 380855, 2026-08-24: "you can use all the information provided over
the interface") — successive 40–80 m windows, ego-motion-compensated, reconstruct the path *through and behind* the ego, closing the
40 m gap; (3) a driver that tracks that path at roughly the recorded speed gets dist_to_gt ≈ lane-centre offset (~1 m), avoids the
drift-induced lateral/corridor failures that dominate VaVAM's incidents, and keeps progress ≥ 0.8 → full progress score on most scenes.
Its residual failures are front collisions (no perception), which is why NaLa is 3.4 km, not 10.
**PAI-board tags corroborate the toolbox:** `baseline-k5-medoid` / `v1-k5medoid` (k-sample medoid — what we built), `v1-leadguard` (#1 PAI:
lead-vehicle guard = B2), `p9-apf-cg` (potential field + CUDA graphs), `ors10-context-risk`. The PAI spread is tiny (1580–1650); the
nuPlan spread is where structure (route following) pays.
**Organizer clarifications (issue #166, 08-28/31):** rank = posterior rank-interval upper bound (ties → at-fault km); scene score is
"the most important aspect", not its plain mean (IRT weighting); "a policy can get a very high distance-between-at-fault-incidents by
simply braking hard … this will not result in a very high scene score"; final = rerun of the top ~5 on a private set.
**Where we went wrong:** we optimised VaVAM's sampling around a 3-way command and never used the route *geometry* for control. The two
1715 entries both put the route into the loop — one as the trajectory itself, one as conditioning.

## 6.23 Route follower F0 v1 — `f0-follow-curv`  [2026-09-01 20:07–20:17]  and the bug it exposed

Image `local-follow` (route_map.py + follower.py, `VAVAM_FOLLOW_ROUTE=1 VAVAM_FOLLOW_NO_MODEL=1 SPEED_SRC=curv`), 100 scenes, 573 s,
Drive **1 ms**/call. Result vs `s1a-k1`: lateral at-fault 1 → **0**, wrong-lane 27 → 23, rear 1 → 0, dist_to_gt better in 58 / worse in
38 (median 2.66 → 2.47), **but corridor exits 6 → 19**, progress 1.031 → 0.961 (22 scenes < 0.8), at-fault 5 (all front; 3 new / 5
removed), score proxy 0.858 → 0.750.
Per-timestep view of the 19 exits: dist_to_gt grows monotonically from t = 0 (≈1 m @1.5 s, 3–6 m @3 s, 5–15 m @5 s) at normal speed —
a diverging *path*, in scenes where the baseline stays at 1–3 m. ASL replay of `…veh-35_01100_01664-1893f` (routes as received, ego
truth, returned plans; tool `capture/asl_follow_replay.py`): route windows consistent to 1 cm; route at t=0 starts at (33.5, +22.7) m in
the ego frame — bearing +34°, a left turn ahead — and **every returned plan was the straight-line fallback** along the heading
(`fallback` logged 56×): `build_follow_plan` rejected the cold start because its lateral gate (`|lat| ≤ 15 m`) treated a turn ahead as
"not our lane". Same class of mistake as the selector's `|y| > 12 m` guard. Fix: reject only a route start behind the ego (or > 90 m /
> 100° off the bow); the Hermite join handles any bearing ahead. Regression test added (`test_cold_start_accepts_a_turn_ahead`), fallback
reason now logged per tick. Also learned: nuPlan-track Drive is **2 Hz** (10 ticks per 5 s scene), so the first ~3–4 s of every scene run
on the cold-start bridge and the accumulated path only takes over near the end — the bridge quality *is* the follower on this track.
F0 v2 (`f0b-follow-curv`) launched with the fix and per-tick logging.

**F0 v2 (`f0b-follow-curv`, gate fixed) [23:42–23:52]:** 100/100, 577 s, Drive **2 ms**. vs `s1a-k1`:
| | at-fault | corridor | wrong-lane | progress | dist_gt mean/median | lateral | score proxy |
|---|---|---|---|---|---|---|---|
| s1a-k1 (VaVAM) | 7 | 6 | 27 | 1.031 | 2.66 / — | 1.39 | 0.858 |
| F0 v1 (bug) | 5 | 19 | 23 | 0.961 | 2.48 | 1.61 | 0.750 |
| **F0 v2** | 8 (7 front, 1 lat) | 6 | **20** | 0.987 | **2.19 / 1.84** | **1.08** | 0.848 |

**Path thesis validated:** best path metrics of any run so far (dist_to_gt better in 62/37 scenes, median 1.84 m, lateral 1.08 m,
wrong-lane 20). **Residual exactly as predicted:** the new at-fault scenes are front collisions at low progress and tiny dist
(0.38–0.84 prog, 0.75–1.6 m dist) — the pure follower drives into stopped/slow traffic because nothing brakes for it; 18 scenes
still < 0.8 progress (stopped starts crawling at v_min). The 6 corridor exits are new scenes (baseline's 6 all fixed) — likely
end-of-path/fallback cases (62 remaining "straight" fallbacks besides tick-1 no_path). Next: **F1 = SPEED_SRC=min** (VaVAM speed cue
brakes for what the camera sees, route keeps the path); diagnostics enabled by the log-cadence fix.

**F1 (`f1-follow-min`, route path + min(keep, curv, vavam)) [23:54–00:05]:** 100/100, 618 s, Drive 106 ms. vs the fair baseline
`s1a-k1`: score proxy **0.874 vs 0.858**, corridor **3 vs 6**, wrong-lane **19 vs 27**, dist_to_gt **1.49 vs 2.66**, lateral **0.93 vs
1.39** (the NaLa-profile numbers), at-fault 7 = 7 (4 new — still the veh-48 09.09 front-collision scenes — 4 removed), rear 2 vs 1,
progress **0.951 vs 1.031**. vs candidate #2's lucky-seed screen (3 at-fault, 0.907): not yet ahead. Diagnosis from 930 per-tick lines:
`keep` (which holds the *initial* speed) was the binding limit on **61 %** of ticks — as a min() term it forbids accelerating for the
whole horizon; that is the progress leak. `vavam` limited 31 % (the brake works), `curv` 1 %. Fallbacks 70 (to the model plan — fine).
Next arm: **F1b `SPEED_SRC=cv`** = min(curv, vavam) without the keep cap.

**F1b (`f1b-follow-cv`) [09-02 16:36–16:44] — INVALID as a cv test:** the driver's pass-through tuple lacked "cv", so the VaVAM speed
cue was never handed over (lim: keep 901 / curv 27 / vavam 0). What it accidentally measured = route path + keep/curv without a brake:
progress recovered to **1.001** (keep no longer bound by the min with vavam) but front collisions rose to 9 and d2gt mean 2.21 (overshoot
past the GT end inflates the clamped metric at higher speed; lateral stayed 0.99). Confirms both mechanisms: the vavam cue is what brakes
(F1: 7 front), and the keep-cap was the progress leak. Driver fixed (one line), rerun as `f1c-follow-cv`. route_map v2 (no persistent arc
labels) was in this build; 54 tests incl. the 300 m collapse regression.

**F1c (`f1c-follow-cv`, cv with the cue connected) [09-02 16:45–16:55]:** 100/100, Drive 109 ms, vavam limited **91 %** of ticks.
at-fault **6** (all front; the 3 stubborn veh-48 stopped-traffic scenes remain), rear **0**, corridor 4, wrong-lane 21, progress **1.011**,
d2gt 2.16, lateral **0.98**, score proxy **0.893**, fails 10. Reading vs candidate #2: its two same-config draws bracket 0.858–0.907, so
F1c is a **statistical tie on the proxy** at n=100 — decisively better on path (lat 0.98 vs ~1.4, wrong-lane 21 vs 27–33, corridor 4),
~2 % slower. Vs the *uploaded* stock entry: +0.023 proxy, d2gt better in 77/100. F3 = F1c on `navtest_local400` launched 17:04
(`f3-follow-cv-400`) with the Codex gate vs `confirm400-mup-g100`.

## 6.24 F3 — F1c on the 400-scene confirm (`f3-follow-cv-400`)  [09-02 17:04–17:35] — **GATE FAILED**

| n=400, seed 1234 | at-fault | rear | corridor | wrong-lane | progress | d2gt | lateral | score proxy | fails |
|---|---|---|---|---|---|---|---|---|---|
| stock (uploaded, PCS 1592) | 20 (f18/l2) | 5 | 40 | 134 | 1.053 | 3.50 | 1.83 | 0.8496 | 60 |
| cand#2 μP (`confirm400-mup-g100`) | **13** (f11/l2) | 1 | 33 | 113 | **1.020** | 2.35 | 1.37 | 0.8813 | 46 |
| F1c follower | 18 (f17/l1) | 1 | **23** | **98** | 0.988 | **2.07** | **1.20** | **0.8896** | **41** |

Paired vs cand#2: at-fault **+5** (12 new / 7 removed — the reruns' flip noise was ~±2 net, so this is a real regression), progress
−3.1 % (at the gate limit), score proxy +0.008 (fewer corridor zeros outweigh the extra at-fault zeros *in our proxy*). Per city:
Vegas 3→2 (score 0.899→0.933), **Boston 4→8** (the regression concentrates here), Pittsburgh 6→7, Singapore 0→1.
**Codex gate (≥5 fewer at-fault, progress ≥ −3 %, no city regression): FAILED on all three.** The official zoib scorer weights the
zero branch sharply, so +5 at-fault likely costs more than 10 fewer corridor exits earn, despite the proxy's +0.008.
**Verdict: candidate #2 remains the submission. F1c is not candidate #3.** The follower's path advantage is real and stable
(lat 1.20, corridor 23, wrong-lane 98 — all best-ever at n=400) but its front-collision cost at scale (f17) shows the VaVAM speed cue
alone under-brakes, most visibly in Boston. If this line continues, the lever is longitudinal: a more conservative cue (min over the
k sampled speed profiles instead of row 0, or a scaled-down vavam profile, or an explicit lead guard) — not more lateral work.

**Mechanism of F1c's 12 new at-fault scenes (per-timestep, 09-02 18:00):** all low-speed, dense-traffic events — speed at collision
median **3.1 m/s** (0.9–8.6), 1.5–5 s into the scene; F1c's speed at 1 s equals candidate #2's (4.7 vs 5.2 m/s; slower in only 2/12) →
**not under-braking**. Candidate #2 threads the same scenes with a median closest approach of **0.86 m** (0.45–2.0) while hugging the GT
line (dist_to_gt 0.1–0.6 m at the same instant in 7/12); F1c was **1.48 m median off the human line** when it hit. So the route —
the human path *snapped to lane centres* — is not the human line where the human squeezed past parked/stopped vehicles, and the
follower has no perception to correct it. The correct earlier reading "speed cue under-brakes" is withdrawn: the missing piece is
**lateral arbitration in tight traffic** (defer to the camera model's path when it deviates from the route), a new design, not a tune.
Decision: park the follower code (kept, env-gated, inert), no further speed-cue arms; revisit only as a route/VaVAM lateral
arbitration after B3.

## 6.25 Offline diagnostics on the F3 failure — route-vs-human-line gap and hit-actor census  [09-02 18:20, no GPU]

Tools (new, ASL-only, no simulator): `capture/route_vs_gt_gap.py`, `capture/collision_actors.py`.

**(a) Route-vs-human-line gap** — the recorded GT path (`rollout_metadata.ego_rig_recorded_ground_truth_trajectory`) vs the route as the
driver saw it (all `route_request` windows put into the local frame with that tick's pose), signed lateral, per scene. Computable in
95/400 scenes (the route starts 40 m ahead and short scenes never overlap it — itself a finding: **the route can only be checked against
the human line in ~24 % of scenes**).

| group | n | gap mean (median of scenes) | p90 | % of GT points > 0.75 m off route |
|---|---|---|---|---|
| **NEW at-fault (follower collides, cand#2 does not)** | 3 | **2.74 m** | 2.77 | **100 %** |
| REMOVED at-fault (cand#2 collides, follower does not) | 2 | 0.23 | 0.23 | 0 % |
| corridor exit fixed by the follower | 4 | 0.21 | 0.35 | 0 % |
| all other scenes | 86 | 0.27 | 0.30 | 0 % |

Whole set: gap median **0.27 m**, p90 2.52 m; 15/95 scenes have >50 % of the human path more than 1 m off the route; correlation with the
follower's dist_to_gt +0.35. **So the lane-centre route is an excellent proxy for the human line in ~85 % of scenes (27 cm) and badly
wrong in a thin tail — and the follower's new collisions live entirely in that tail (2.74 m, 100 % of points off).** A gap this large is
detectable *online* without perception (the ego's own offset from the accumulated route), which makes "trust the route only while the gap
is small" a concrete, testable rule rather than a hunch.

**(b) Hit-actor census (all 12 new at-fault scenes):** actor speed at impact ~0.1–0.3 m/s in 11 of 12 (**stationary**), one moving
(12 m/s). Lateral offset of the hit actor from the lane-centre route: **> 2.2 m in 10 of 12** (2.2–3.3 m typical, two >24 m = cross-street
actors). The recorded human passed those actors with **2.9–9.8 m clearance** (median 3.2 m). Ego-to-human-line distance at impact 0.7–5.9 m.
**Reading: these are not "the route drives into a car parked in our lane".** The obstacles sit *beside* the lane centre and the human had
metres of room; the follower still hit them, i.e. its lateral error at that moment (and in two cases a route that had drifted onto a
cross-street) put the car where the human never was. Combined with (a): the failure is the thin tail where the route itself is the wrong
line, plus follower lateral error on top — **not** under-braking (confirmed) and **not** simple lane-centre-vs-parked-car geometry.
Implication for any revival: a route-trust gate keyed on the *measurable* ego-vs-route offset would have disabled the follower in exactly
the scenes it fails, at zero perception cost. That is the one untried lateral idea the data actually supports.

## 6.26 Offline video rendering from stored rollouts (no simulator, no GPU)  [09-03]

The eval renders its camera+BEV overlay video directly from a `rollout.asl`, so any past run can be visualised after the fact:

```bash
# 1. copy the run's eval-config.yaml, set video.render_video/overlay_plans_on_camera/generate_combined_video: true
#    (keep run_metadata.yaml next to it — get_metadata() reads the config's parent dir)
# 2. stage the scenes you want as symlinks, each in <clipgt_id>/<rollout_id>/rollout.asl, plus an empty `_complete`
#    marker in each rollout dir (main.py filters on TRACKER_FILE_NAME and errors out without it)
cd ~/alpasim-challenge/alpasim && uv run --no-sync python -m eval.main \
  --asl_search_glob "<stage>/*/*/rollout.asl" --config_path <cfg>/eval-config.yaml \
  --trajdata_cache_dir ~/alpasim-challenge/nuplan-track --usdz_glob "~/alpasim-challenge/nuplan-track/**/*.usdz"
```
~1 s/scene with `num_processes: 6`; output `<rollout dir>/videos/...CAM_F0_default.mp4` (6 s, camera + BEV with GT path, route,
agents, ego box, metrics table). Video config knobs are in the run's own `eval-config.yaml` (`video.map_video.map_elements_to_plot`
already includes GT_LINESTRING / ROUTE / DRIVER_RESPONSES / AGENTS).

**Rendered sets for candidate #2 (in `viz/`, gitignored):** `failures-cand2/` = all 13 at-fault collisions + the 8 worst drift-outs;
`successes-cand2/` = 22 representative passes (6 scenes stock crashes but μP passes, 5 tight-traffic passes at 0.21–0.54 m clearance,
5 clean ~80° turns, 3 cm-accurate tracking, 3 longest runs), each with an `INDEX.md`.

**Failure taxonomy behind those clips (400 scenes):** 46 zeros = 13 at-fault collisions + 33 pure corridor exits (no collision) + 0
offroad; progress costs only 0.4 % of the score. 4 of the 13 collisions happened while already > 2 m off the human line, so
**lateral tracking is implicated in 37/46 = 80 % of all lost scenes** — the same axis the leaderboard leaders win on
(NaLa dist_to_gt 0.98 m vs our 3.05 official / 2.35 local for μP).

## 6.27 run-eval.sh hardened against concurrent-run clobbering  [09-03, raised by a peer session]

**The hazard (real):** the script did an unguarded `docker rm -f local-driver` at start *and* at teardown, and the box fits exactly one
`dev_fast2` stack (peaks 22.5–23.6 of 24.5 GiB). Two sessions launching would silently destroy each other's driver, and the wizard still
exits 0 and writes a plausible aggregate over empty rollouts (Defect 8). Only a chat claim prevented it.

**Fix (installed atomically with `mv`, since bash reads a running script by byte offset — never truncate one in place):**
`flock -n` on `logs/.run-eval.lock` + an owner file; refusal if a container named `local-driver` already exists (prints who owns it;
`FORCE=1` overrides); teardown now removes the driver **by container id**, not by name, so a later session's container can never be
killed by an earlier one's cleanup; and a **validity gate** that prints `VALIDITY <run>: completed N/EXPECTED | driver inference
failures F` and shouts `RUN INVALID` when the completed count is short or the driver logged failures. Expected count is parsed from the
scene-group yaml (verified: 20/100/400). Guard tested live against a running peer job: refused with exit 1, container untouched.

**Correction to the incident attribution.** The peer believed this clobbering killed `s1b-k5-off` on 09-01. The log says otherwise:
`s1b-k5-off-FAILED.log` has **508 renderer "CUDA error: the launch timed out"** entries and **zero** driver-side gRPC failures
(`UNAVAILABLE` / connection refused / socket closed), the first error in file order is the renderer's, and the driver's own log stream
was still emitting S0 lines at 09:44:39 UTC — 5 s *before* the renderer's first error. A force-removed driver produces the opposite
signature. No second `run-eval.sh` was active (log mtimes: s1a finished 15:11, s1b started after). **Cause remains the display-GPU
watchdog under memory pressure**, as recorded in §6.20. The guard is still worth having — the hazard is real even though it did not fire.

## 6.28 The official per-scene score is in the results file — stop proxying it  [09-03]

Two peer sessions independently re-derived the scene score from `metrics_unprocessed.parquet` and got ~0.035 below our numbers,
which prompted the right question. The answer: **the evaluator already writes the official score.** `results-summary.json` →
`rollouts[]` carries `score`, `passed`, `failure_reason` and `score_metrics` next to `metrics` (written by
`aggregation/processing.py:301` calling `scene_score.score_rollout`), and the file's own `score_criteria` block documents the formula.

Mean of `rollouts[].score` — the canonical numbers, to be used everywhere from now on:

| run | official mean scene score |
|---|---|
| `screen-mup-g100` (candidate #2, lucky draw) | **0.9067** |
| `s1a-k1` (candidate #2, other draw) | **0.8582** |
| `f1c-follow-cv` (route follower, best arm) | **0.8926** |
| `confirm400-mup-g100` (candidate #2, 400) | **0.8813** |
| `f3-follow-cv-400` (follower, 400) | **0.8896** |
| S1b arms w_disc 0 / 0.05 / 0.2 / 0.4 | 0.8779 / 0.8779 / 0.8973 / 0.9062 |

Our proxy (zero on `collision_at_fault | offroad | left_corridor_laterally`, else `min(progress_clipped_rel/0.8, 1)`) reproduces the
official score on **100/100 scenes to < 1e-6**, so every proxy figure recorded earlier in these notes stands unchanged — but the proxy
is now redundant and should not be re-implemented.

**Why re-derivation from the raw parquet reads low:** `rollouts[].metrics` are the *post-modifier* per-scene values (the eval has
already applied `RemoveTimestepsBeforeEvent(eval_relevant)`, `RemoveTimestepsAfterEvent(offroad_or_collision)` **and** the separately
configured corridor modifier `dist_to_gt_trajectory >= 4.0` from `aggregation/main.py`). Reading them gets truncation for free;
re-deriving requires reproducing every modifier, and the corridor one — which truncates on drift with no collision at all — is the easy
one to miss. Corroboration that they are post-modifier: counting `collision_at_fault > 0` over them reproduces
`metrics_results[0].collision_at_fault` to 1e-9 on four runs.

**Rule:** read `rollouts[].score` (and `failure_reason` / `passed`) directly. Also for tail analysis use
`lateral_dist_to_gt_trajectory`, not `dist_to_gt_trajectory` — the latter clamps at the recording's end, and 67/100 scenes in
`screen-mup-g100` out-run the GT, which inflates its p90 (5.73 m vs 3.17 m lateral).

**S1b re-read on official scores (verified independently, 09-03).** Paired per-scene on `rollouts[].score`:

| w_disc | mean score | zero scenes | scenes changed vs w=0 | better / worse | sign test |
|---|---|---|---|---|---|
| 0 | 0.8779 | 12 | — | — | — |
| 0.05 | 0.8779 | 12 | 1 | 0 / 1 | — |
| 0.2 | 0.8973 | 10 | 5 | 3 / 2 | p = 1.00 |
| **0.4** | **0.9062** | **9** | 6 | 4 / 2 | p = 0.69 |

Effect is **+0.028** (not the +0.018 the earlier hand-rolled proxy showed) and clean in direction: the three recovered scenes were
2 × `collision_at_fault` and 1 × `left_corridor_laterally`, with **none newly zeroed**. **But the decisive comparison is scale, not
sign:** candidate #2's own two same-config draws span **0.8582 – 0.9067, a spread of 0.0485 — nearly twice the effect**. A 6-scene
change at p = 0.69 inside a 0.049 seed band is not evidence, so the parked verdict stands; the branch failed on 400 scenes, not here.
This is the cleanest statement of the n=100 limit: *the noise band of an unchanged config exceeds every effect we have measured on it.*

## 6.29 WA-JEPA T1 screen — independently verified  [09-03, peer session's runs, our verification]

Four arms on `navtest_local100` / `dev_fast2`, all 100/100 with zero driver inference failures (the new VALIDITY gate).
Scores are the official `rollouts[].score`; candidate #2's three same-config draws bracket **0.8582–0.9067**.

| arm | score | zeros | at-fault | corridor | wrong-lane | progress | lat med / p90 | Drive ms | % wall |
|---|---|---|---|---|---|---|---|---|---|
| cand#2 draw A / B / C | 0.9067 / 0.8582 / 0.9064 | 9/13/9 | 3/7/3 | 6/6/6 | 33/27/32 | ~1.04 | ~1.0 / ~3.2 | 103 | 17 |
| WA-JEPA 12 steps | **0.9667** | 3 | **0** | 3 | 26 | 0.966 | 0.63 / 2.23 | **1516** | 104 |
| WA-JEPA 4 steps | 0.9493 | 5 | **0** | 5 | 26 | 0.995 | **0.35** / 2.49 | 520 | 58 |
| WA-JEPA 2 steps | **0.9499** | 5 | **0** | 5 | 27 | 1.003 | 0.42 / 2.51 | **295** | 39 |
| our route follower `f1c` | 0.8926 | 10 | 6 | 4 | 21 | 1.011 | 0.67 / 2.44 | 109 | 18 |

Paired, 4-step vs the three candidate-#2 draws: better 14 / 18 / 14, worse 6 / 6 / 6, Δscore +0.043 / +0.091 / +0.043 — i.e. above the
top of candidate #2's own seed bracket, which nothing of ours has managed. **Zero at-fault collisions in all three arms** is the headline;
collisions are the hard zeros. The **2-step arm dominates the 4-step** (identical score, 295 ms vs 520 ms), so step count buys nothing
beyond 2 here.

**Throughput resolved (09-03, from the 08-31 official record — token expired, not re-pulled).** The run is renderer-bound: 14,850 Drive
calls over 16 replicas in 2265 s = **0.41 calls/s demanded per replica**, against ~10 calls/s capacity at 103 ms. So the right test is
added wall time, not the latency ratio: `added = 14,850 × (L − 103 ms) / 32 concurrent` (upper bound — assumes Drive is fully on the
per-tick critical path).

| arm | ms/call | capacity/replica | headroom vs demand | added wall | of the 220 s margin | verdict |
|---|---|---|---|---|---|---|
| stock B / cand#2 | 103 | 9.7 /s | 24× | — | — | baseline (passed) |
| WA-JEPA 2 steps | 295 | 3.4 /s | 8× | 89 s | 40 % | **passes** |
| WA-JEPA 4 steps | 520 | 1.9 /s | 5× | 194 s | 88 % | tight — would not submit |
| WA-JEPA 12 steps | 1516 | 0.7 /s | 2× | 656 s | 298 % | **fails** |

H100 is faster than our card, so absolute ms shrink officially — the *ratio* to stock B is what transfers. Caveat the other way: the
organizers are moving to a new final scene set, so the limit and scene count may change. Net: **2-step is the only arm with both the
best score and a comfortable throughput story**; my earlier "5× the cost so it likely fails" was reasoning from a raw ratio and was
too pessimistic.

**Remaining reservation, from our own history.** (1) ~~*Throughput may be the binding gate:*~~ *(resolved above.)* our stock-B submission passed with only a
**9.7 % wall-time margin** (2265 s observed vs 2485 s limit) at 103 ms/call; 295 ms is ~3×, 520 ms ~5×, 1516 ms ~15× that per-call cost,
and throughput failure is a hard fail independent of score. Needs the official `throughput_limit` numbers before anything is called
submittable. (2) *n=100 cannot see a 5-collision regression:* our route follower led candidate #2 on every path metric at this scale and
then lost the 400-scene gate on collisions (18 vs 13). The required next step is `navtest_local400` paired against
`confirm400-mup-g100`.

## 6.30 Disk hygiene — two traps worth knowing before anyone frees space  [09-03]

**Trap 1: Docker is not on the disk that fills up.** `DockerRootDir` is `/media/skr/storage/docker` (`nvme1n1p2`, 910 G), not `/`.
Pruning Docker frees the *storage* disk; the one that hits 98 % is `/`, where `/home` lives (686 G: `alpasim-challenge` 243 G —
`nuplan-track` 158 G + `runs/` 56 G — `Downloads` 117 G, `.cache` 71 G, `miniconda3` 54 G). Check `docker info --format '{{.DockerRootDir}}'`
before assuming a prune helps.

**Trap 2: `docker system df` "reclaimable" is not free space, and `prune -a` would cost us the submission.**
The image SIZE column double-counts layers shared between images: 12 dangling `<none>` images each listed at 10.6 GB returned
**1.2 MB** when pruned, because every layer was shared with a tagged image. And the headline "139 GB reclaimable (98 %)" is the
`prune -a` figure — *everything not attached to a **running** container*. That set includes:
- `alpasim-e2e-vavam-driver:submit-mup` = `…team-lucifer:vavam-b-mup-20260831b` — **candidate #2, the staged submission**. The team ECR
  role is **push-only** (no `ecr:GetDownloadUrlForLayer`, Defect 6), so a deleted local copy **can never be pulled back**;
- whatever image another session is mid-experiment with.
**Never run `docker system prune -a` on this box.** The safe subset is `docker container prune` + `docker builder prune -af` +
`docker image prune` (dangling only, no `-a`): that returned 14 GB + 26 GB here, all on the storage disk.

**Done 09-03 12:34: `runs/` moved to the storage disk and symlinked.** `~/alpasim-challenge/alpasim/runs` ->
`/media/skr/storage/alpasim-runs`. Copy-first (rsync), verified before deleting the original: 22,885 files both sides, `rsync
--itemize` dry-run empty, a random `rollout.asl` byte-identical, and the four cited `results-summary.json` parsing to the same scores
(0.8813 / 0.8896 / 0.9499 / 0.9067). Post-swap the tooling's globs still resolve — 38 `aggregate/results-summary.json`, 5,120
`rollout.asl` — so `wizard.log_dir=./runs/<name>` and the eval's `--asl_search_glob` are unaffected. **`/` went 22 G -> 76 G free
(98 % -> 92 %)**; storage disk 141 G free. The destination is `nvme1n1p2`, **ROTA=0, ~3.6 GB/s** — an NVMe SSD, *not* the SeagateHub1
spinning disk — so per-scene wall time is unaffected. Caveat for anyone comparing timings across the move: `DRIVER ms` come from the
telemetry `rpc_duration` counters and are disk-independent, but `% of wall` is a ratio against total wall, so if per-scene wall ever
drifts after the move, rule out I/O before blaming a policy.

**What actually frees `/`:** `runs/` is 56 G and ~97 % of each run is `rollouts/*.asl`. Those ASLs are not disposable — every
post-mortem this week came from them (collision bearings §6.24, route-vs-human-line gap §6.25, all 43 failure/success videos §6.26),
and the eval can re-render video from them offline. Preferred fix is therefore **move `runs/` to the storage disk and symlink**
(zero loss, transparent to `run-eval.sh`), not deletion. If deleting, drop `rollouts/` for superseded runs and keep every
`aggregate/` (1.3 MB each — all cited scores live there).

## 6.31 PRE-REGISTERED criteria for the WA-JEPA 400-scene gate  [written 09-03 13:38, BEFORE the result]

`wajepa-s2-400` (WA-JEPA, 2 flow steps, 4 cameras, `navtest_local400`, `dev_fast2_wajepa`) launched 13:36, ETA ~14:26, paired against
**`confirm400-mup-g100`** (candidate #2). Written down first because today has already produced two contested-number episodes, and
because the route follower's 400-scene failure is the precedent this run exists to test.

**Baseline to beat (official `rollouts[].score`):** score **0.8813** · zeros **46** = 13 at-fault + 33 corridor · progress **1.020** ·
scenes with progress < 0.8: **37** · lateral median **0.90** p90 **3.50** · Drive 103 ms.

**Noise at n = 400:** counts scale as √n, so the ±2/100 numerics floor is ~**±4/400**. A difference of ≤ 4 at-fault is not resolvable.

| verdict | condition (all must hold) |
|---|---|
| **PASS — becomes candidate #3** | at-fault ≤ **8** (i.e. ≥ 5 fewer, the Codex gate) · progress ≥ **0.989** (−3 % of 1.020) · score clearly > 0.8813 · no single city worse than candidate #2 by > 3 at-fault · Drive ≈ 295 ms (throughput arithmetic in §6.29 holds) |
| **INTERESTING, not shippable** | at-fault 9–13 with corridor and lateral clearly better — i.e. it tracks better but does not convert; same shape as the route follower |
| **FAIL** | at-fault ≥ 14, or progress < 0.989, or a city regression, or Drive materially above 295 ms |

**Predictions on record.** If the n=100 result (0 at-fault in 2.58 km) is real rather than a lucky draw, at-fault at 400 should be
**0–4**. If it lands 9–13, the 100-scene zero was noise and the honest read is "no better than candidate #2 on safety".
The one asymmetry to watch: WA-JEPA drove *slower* at n=100 (progress 1.003 vs 1.048), so a progress failure is the more likely way
this dies than a collision failure.

## 6.32 WA-JEPA 400-scene gate — RESULT and the adjudication  [09-03 14:2x, verified independently]

`wajepa-s2-400` (2 flow steps, 4 cameras) vs `confirm400-mup-g100` (candidate #2), 400 paired scenes, VALIDITY 400/400, 0 inference
failures, Drive 290 ms. Both sessions computed this separately from `rollouts[].score` and agree to the digit.

| | cand#2 | WA-JEPA s2 | gate (§6.31) |
|---|---|---|---|
| **scene score** | 0.8813 | **0.9247** (+0.0434) | pass |
| **at-fault** | 13 | **2** (−11) | pass (≤ 8) |
| corridor exits | 33 | 24 (−9) | — |
| zero-scored scenes | 46 | **26** (−20) | — |
| mean progress | 1.0204 | 0.9565 | **FAIL** (≥ 0.989) |
| scenes progress < 0.8 | 37 | **37** | — |
| lateral med / p90 | 0.90 / 3.50 | **0.50 / 2.64** | — |
| per-city at-fault | pitt 6, boston 4, vegas 3, sing 0 | 0, 1, 0, 1 | pass |
| Drive | 103 ms | 290 ms | pass (§6.29: 40 % of margin) |

Per-scene: **59 better / 35 worse / 306 identical**, sign test **p = 0.017**.

**Prediction 1 resolved in favour** (§6.31 said 0–4 at-fault if the n=100 zero was real, 9–13 if noise): **2**. The zero was real.
**Prediction 2 (the mechanism) did not occur.** I expected a slower policy to push scenes under the 0.8 saturation point; the count is
37 vs 37, and it is a genuine exchange — overlap 9, 28 newly below, 28 risen above.

**Adjudication: the gate FAILS as written and was NOT waived.** The peer declined to rule on their own result; I declined to waive my
own criterion after seeing the number, which is exactly what §6.31 exists to prevent. Recorded instead:
- the criterion was **mis-specified**, demonstrable from its own text: §6.31's stated rationale was "a slower policy pushes more scenes
  under 0.8", a claim about the scoring-relevant region that is measurably false here. The scene score is `min(progress/0.8, 1)`, so
  progress above 0.8 earns nothing — and **335 of 400 scenes have both runs above 0.8**, where the mean drop (+0.060) is worth zero.
  A correctly specified gate ("scenes below 0.8 must not increase") passes exactly;
- **but the failure is not cosmetic** — though my first two arguments for that were wrong and are **withdrawn** (peer-corrected, both
  verified against our own files): (a) the SymPhi "+92 PCS from a speed knob" evidence does **not** transfer — §6.16 records that on the
  μP-*correct* model gain ×1.05 made things worse (at-fault 0.94 → 0.58 km, collisions 4 → 7, d2gt 2.71 → 3.02) and attributes SymPhi's
  wins to the μP-*broken* 4× overshoot regime; (b) Spearman(PCS, d2gt) = +0.69 does not mean drifting scores better — the joint **#1
  (NaLa) has the board's LOWEST d2gt at 0.98**, and METRICS.md already says "never optimise d2gt".

  **The risk survives in a stronger form, from evidence neither of us had cited.** Of the 18 board entries with > 3 km between at-fault
  incidents, only **two** clear 1600 (NaLa 1715, 메타몽 1715); the other **16 score 1008–1478 — all below our stock entry's 1592**.
  Of everything under 1.6 m d2gt, only NaLa is above 1600. VF-Team v2 has the board's best safety (12.75 km) and scores **1095**. So
  *"very safe + tracks tightly" is the modal profile of the board's **bottom***, and the discriminator between NaLa (3.36 km / 0.98) at
  1715 and foxhihi c6 (5.69 km / 1.15) at 1447 must be something the board does not display — the organizers named it: *"a policy can get
  a very high distance between at-fault incidents by simply braking hard … this will not result in a very high scene score."*
  **Progress is invisible on the board and is what separates 1715 from 1447 at identical safety.**

  **Why this is a caution and not an alarm:** WA-JEPA does not fit the punished profile. 0.9565 progress is 96 % of the human's distance,
  not braking-hard territory, and `prog<0.8` is tied at 37 with a genuine 28-for-28 exchange — it is not stalling scenes out. Its shape
  resembles NaLa's side of the split, not foxhihi's. But "resembles" is the strongest word the data supports. **Unresolvable locally —
  only a submission answers it.**
- **No noise bracket exists at n = 400** (one cand#2 draw only). At n=100 two same-config draws spanned 0.0485; naive √-scaling
  suggests ~0.024 at n=400, which would put +0.0434 outside — an assumption, not a measurement. A second `confirm400` draw of
  candidate #2 was commissioned to settle it.

**Status: decision deferred to the user**, with candidate #2 remaining the staged submission until then.

**Where WA-JEPA's progress deficit actually falls — CORRECTED (09-03; my first version was wrong by ~6×, peer-caught).**

⚠️ **`progress_clipped_rel` is NOT clipped** despite its name — max 1.469, with 128 of 400 scenes above 1.0. `ground_truth.py` keeps it
"deliberately unclipped so out-running the recording stays visible"; the **scorer** clamps to [0,1] at scoring time. A scene going
1.30 → 1.05 reads as −0.25 raw and is worth exactly **zero**.

| | raw (wrong) | clipped (correct) |
|---|---|---|
| mean Δprogress | −0.0639 | **−0.0377** |
| median | −0.0417 | **−0.0082** |
| slower / faster scenes | 237 / 81 | 198 / 70 |

**And the bigger error was attribution.** My "32 scenes costing 17.0 points" filtered on *progress down AND score down*, which swept in
**14 hard-failure scenes** (collision/corridor) carrying **14.00 of those 17.03 points** — fixing progress recovers nothing there.
Correctly separated:

| measure | scenes | points | on the mean |
|---|---|---|---|
| my original (wrong) | 32 | 17.03 | 0.0426 |
| genuinely progress-driven | 18 | 3.03 | **0.0076** |
| headroom to lift every non-failing scene to progress 0.8 | 23 | 4.12 vs cand#2's 1.48 | **net 0.0066** |

So the deficit costs **~0.007–0.013**, i.e. **15–30 % of the +0.0434 margin — not half**, and "fix the stalls → 0.967" was wrong;
the ceiling is ~**0.932–0.937**. **This strengthens the WA-JEPA result**: the win is more robust than I portrayed, because almost all
of the slowdown sits above the 0.8 threshold where the scorer discards it.

**What survives:** the near-stalls are real (1.00 → 0.09, → 0.13, → 0.17) and worth watching — but the prize is small, and several
stalls are *the safety mechanism working* (three of the worst six score better than candidate #2 did, up to +1.00, by stalling out of a
collision it had). **Fixing stalls naively risks trading back the 13 → 2.** The output-gain knob remains the known-bad fix (§6.16).

## 6.33 RULE: never compute a scoring claim from a raw metric  [09-03 — three violations in one day]

The same class of error occurred **three times today**, once by each session, each time inflating a claim:
1. **`progress_rel` (MIN-aggregated) instead of `progress_clipped_rel`** — a peer's scene-score proxy read 0.035 low (§6.28);
2. **pre-modifier `metrics_unprocessed.parquet` instead of the post-modifier per-scene values** — inflated a tail p90 to 11.7 m
   (true 3.2 m) and a zero count to 14 (true 9);
3. **unclipped progress + hard-failure contamination** — inflated a recoverable deficit 6× (this section).

**Rule: a scoring claim may only be computed from `rollouts[].score` / `score_metrics`, or from a quantity explicitly passed through
the scorer's own transform** (`clip(p,0,1)/0.8`, hard-failure zeroing, post-modifier values). Raw metric columns — `progress_rel`,
`progress_clipped_rel`, the unprocessed parquet — are diagnostics, never scores. Where an attribution is claimed ("X costs Y points"),
**exclude hard-failure scenes explicitly**: a scene scoring 0 from a collision recovers nothing from fixing anything else.

**Strategic framing (peer's, verified):** NaLa `sub1` at 3.36 km *and* 0.98 m d2gt at joint #1 is the existence proof that
safe-and-tight is **necessary-but-not-sufficient**, not punished. The top 5 spans two routes up — `sub1` (safe+tight) and
`vavam-gain1075` (1.75 km / 3.72 m) — and our stock entry (1.62 / 3.05) sits on the gain route. WA-JEPA would move us onto `sub1`'s.
Progress is therefore **the metric to protect, not merely to not-fail**.

## 6.34 Upstream "Maintenance Candidate" landed on `e2e_challenge` (09-02, fetched 09-03) — four things that affect us

`origin/e2e_challenge` moved `f012862 → 54952f4` ("Maintenance Candidate (#173) — Initial candidate version for the final competition
version"), plus #169 (SimScale/NAVSIM sample docs) and #167 (curated NuRec splits). ~5,000 insertions. What matters:

**1. The leaderboard's scoring algorithm is now runnable locally.** New `e2e_challenge/local_evaluation/evaluate.py` (549 lines) fits
*"the same pinned Drive-IRT algorithm used for the challenge leaderboard"* to local `aggregate/results-summary.json` files and emits
`capability_ranking.csv` (policy capability score, avg scene score, **posterior rank interval, rank spread**), `scene_score_matrix.csv`,
and the serialized fit. This is the thing we have repeatedly called "unresolvable locally". Two caveats:
- **the reference bundle `data/` is intentionally empty** until organizers publish it. Without it, `--without-references` compares local
  runs only and is explicitly *"not leaderboard-like"* — no affine scale to real PCS numbers, since the manifest supplies the two anchor
  subjects and their target scores (1000 / 1600);
- **sufficiency guard**: zoib needs ≥ `S + 5N` observations for `S` subjects, `N` scenes, else it silently falls back to arithmetic
  average with no rank spread. At N = 400 that needs **S ≈ 6 runs on the identical scene set**; we have 3 (`confirm400-mup-g100`,
  `f3-follow-cv-400`, `wajepa-s2-400`). More subjects on the same 400 would let us fit it properly.

**2. Submitting now requires accepting competition terms first.** The CLI gained `terms show|status|accept`, and `submit` calls
`require_terms_ready(client)` *before* the image probe — both the acting user **and the team captain** must have accepted the current
terms version. **This is a new precondition on our pending candidate-#2 submission**: when the API reopens, run `terms status` / `terms
accept` before `submit`, or it will refuse. Rejection is API-side and consumes no quota.

**3. New submission lever we did not have: `--controller-gains`.** A modified gain set for the official **nonlinear** MPC can be
submitted *without changing the driver image* (`starter_kit/controller_gains.example.json`: `long_position_weight` 2.0,
`lat_position_weight` 1.0, `heading_weight` 1.0, `acceleration_weight` 0.1, `rel_front_steering_angle_weight` 5.0,
`rel_acceleration_weight` 1.0, `idx_start_penalty` 10). Structure, dynamics and limits stay fixed. Testable locally via
`controller.mpc_implementation=nonlinear controller.gains.*=…`. Note `idx_start_penalty` is the 1.0–2.0 s tracking window we identified
in §6.24 — it is now a *tunable submission parameter*.

**4. Our track's contract is UNCHANGED.** The `4cam_1080 → 6cam_1080` switch is in `e2e_challenge/{dev,ec2}.yaml`, i.e. the **PAI**
track; `e2e_challenge_nuplan*` configs are untouched by the diff. The nuPlan 8-camera contract and everything in §6.29/§6.32 stands.
Also EC2 now runs the renderer with `--no-enable-nrend` ("the public competition evaluates the unharmonized renderer until the
separately announced final reruns").

**Local copy of the updated branch (09-03).** The new commits were fetched into the canonical clone
(`~/alpasim-challenge/alpasim` = `Downloads/alpasim_challenge/workdir/alpasim`, the same directory via symlink), so
`origin/e2e_challenge` = `54952f4` is present locally — **but the working tree is deliberately left pinned at `f012862`.**
Reason: the update touches `src/runtime/.../service_base.py` and `video_model_service.py`, i.e. simulator behaviour. Checking it out
would make every run we have (`confirm400-mup-g100`, `f3-follow-cv-400`, `wajepa-s2-400`, all the 100-scene screens) non-comparable with
anything run afterwards, and our whole comparison ladder depends on those being paired.

Instead: **`git worktree add /media/skr/storage/alpasim-upstream-54952f4 54952f4`** — a second checkout at the new commit sharing the
same object store (282 MB, on the storage disk, no re-clone). It carries the new `local_evaluation/evaluate.py` (Drive-IRT),
the new competitor CLI (terms + `--controller-gains`), and the new configs, while the eval environment stays pinned. Verified:
`e2e_challenge_nuplan_common` is **byte-identical** between the two checkouts, so our scene/camera/route contract is untouched and the
existing runs remain valid.

**When to actually adopt `54952f4` for evaluation:** only alongside a re-baseline — i.e. re-run candidate #2 on `navtest_local400`
under the new commit before comparing anything new against it. Until then, run new arms on `f012862` for comparability, and use the
worktree for tooling only.

## 6.35 What the local Drive-IRT tool can and cannot give us (09-03, code review of `evaluate.py`, nothing run)

**Cannot: a leaderboard-scale PCS (the "1592" kind).** Two ingredients are missing and both live in the reference bundle that is
"intentionally empty":
1. **The affine scale.** `policy_capability_score = offset + scale × raw` where scale/offset come *only* from the manifest's
   `score_scale` block (two anchor subjects → 1000/1600). Without it `score_scale()` returns `applied: False` and the column is
   just the **raw IRT ability**, a latent number (≈1–4 in the unit test) with no relation to 1600.
2. **The reference population.** IRT ability is relative: scene difficulty/discrimination are fitted *jointly* with the subjects in
   the matrix. Three of our arms alone define a different quantity from a fit over the board's ~25 entries. The bundle's precomputed
   runs are what supply that context.
3. **Scene-set lock.** `build_matrix` keeps only runs whose scored scene-ID set is *identical* to the canonical one (others are dropped
   as `scenario_set_mismatch`). The README pairs the nuPlan bundle with **`navtest_full` = 1,485 scenes**; using it means running each
   candidate on those 1,485 (~2 h/arm on dev_fast2, and the full navtest must be mounted from SeagateHub1).

**Can, today: the official algorithm's *relative* ranking with posterior rank intervals among our own arms.** Sufficiency guard is
`S×N ≥ S + 5N` ⇒ **S ≥ 6 subjects at any N** (400: 5.01; 300: 5.02; 100: 5.05). Where we stand:
- 400-scene set: **3** subjects (`confirm400-mup-g100`, `f3-follow-cv-400`, `wajepa-s2-400`) — falls back to arithmetic average.
- 300-scene set: **6** (stock, μP, L-μP, starter, fast, fast2) — exactly enough.
- 100-scene screen set: **21** subjects already — zoib fits *now* with no new runs (disc×4, follower×5, selection×4, gain×3,
  WA-JEPA×3, base, …).
  What that answers: whether the difficulty-weighted IRT ordering agrees with the mean ordering, and whether WA-JEPA's and
  cand#2's rank intervals separate under the *official* statistical lens. It is a check on the metric, not new evidence about the
  board — and the README's "not leaderboard-like" caveat is exactly right.

**Controller gains — local == official, so the lever is real.** `base_config.yaml:11` composes `controller: nonlinear` for
*every* preset, with the same defaults as the example JSON (long 2.0 / lat 1.0 / heading 1.0 / accel 0.1 / steer-rate 5.0 /
accel-rate 1.0 / `idx_start_penalty` 10). Everything we have ever run locally used exactly this gain set; there is no
local/official controller mismatch, and `controller.gains.*=` overrides on the pinned checkout are a faithful test path.
Submission limits: six weights in [0, 10], `idx_start_penalty` integer in [0, 19]. Notes:
- the controller currently weights longitudinal error 2× lateral. 80 % of our lost scenes are lateral (§6.29), but the follower
  work showed the *plan* is off the human line — whether the *tracking* of that plan also contributes is an open, cheap question
  (ASL replay: commanded vs realised path);
- `idx_start_penalty` = the 1.0 s tracking blind-spot from §6.24 — lowering it makes the MPC react to the near part of the plan;
- a gains-only resubmit **consumes a submission slot**, but gains can ride *with* a driver-image submission at zero extra cost,
  so the right use is: screen locally, attach the winner to the candidate — never a separate slot;
- a gain set tuned for one driver's plans need not suit another's (cand#2 vs WA-JEPA screened separately).

## 6.36 What the published anchor scale reveals about the board (09-03; board snapshot 09-01, drive-irt source at the pinned commit)

**The anchors are identified: 1000 = `Host/go_straight`, 1600 = `Host/policy1` ≈ stock VaVAM.** PCS = offset + scale × θ with the
two Host submissions (06-16, pre-launch) pinned exactly. Two teams that submitted the starter kit (AIMM `smoke`, ZGCA
`starter-baseline`) landed at 1000.09/1000.16 with km and d2gt identical to 13 digits → the starter kit *is* go-straight, official
evaluation is deterministic per image, and **fit jitter for identical data is ≈0.1 PCS**. `policy1` has km 1.68 / d2gt 3.07 — the stock
VaVAM signature (ours: 1.62 / 3.05 / 1592). So the whole 600-point span is "doing nothing → the provided baseline".

**Consequences for reading the board.**
- The 1588–1601 cluster (foxhihi b1/b1s, Host, us, Magma v4EMA, SymPhi sample-v2) is one policy: **stock ± ~7 PCS of rollout noise**.
  Our 1592 is 8 below the organizers' own copy — noise, not a deficit.
- Only four entries beat stock beyond noise: NaLa 1715, 메타몽 1715, SymPhi gain1075 1691, gain105 1680. Everyone else is at or below
  the starter after 2.5 months. The competitive band is 1588→1715 = 127 PCS ≈ 21 % of one anchor span.
- `legacy_score` (at-fault km) was the old primary. Under it foxhihi `c4` (4.66 km, d2gt 1.65) would be top-4; under zoib it is 1478,
  below stock — the model charges stalling through the progress channels (see mechanism).

**Pricing local deltas (crude, linear-in-mean; IRT is nonlinear).** Local mean `rollouts[].score`: starter 0.600 (300) / 0.608 (100);
stock 0.826 (300) / 0.840 (100) / 0.906 (base100). ⇒ 600 PCS ≈ 0.22–0.30 mean score ⇒ **≈ 20–27 PCS per +0.01 mean score.**
WA-JEPA's +0.0434 over cand#2 ⇒ **≈ +90–120 PCS ⇒ ~1680–1710** if cand#2 ≈ stock ≈ 1592 (paired 100: μP effect +0.0003 ⇒ cand#2 is
in the stock cluster; the 300-set μP/stock pair is not paired — different presets/seeds — do not price from it).

**The ceiling: #1 and #2 have bit-identical PCS 1715.4967382108227 from different data** (km 3.36 vs 3.09, d2gt 0.98 vs 2.65).
In drive-irt the ability is an unbounded mean-field Normal (`NormalGammaGuide`, no clamp), so a converged fit cannot tie two subjects
exactly. The only mechanism in the pinned code that yields one exact value for different data is the optimizer: per-element gradient
clamp at ±`clip_norm`=10 with lr 0.1·0.975^t over 1000 epochs — a subject whose gradient stays saturated walks an identical path
(Σ lr_t·10 ≈ 40 raw units from init) and lands on the same number. **Inferred, not run** — checkable locally by fitting with a
synthetic all-1.0 subject. If right: (a) ~1715 is the maximum reachable on this fit; (b) #1 vs #2 is decided by the at-fault-km
tiebreak (NaLa 3.36 > 메타몽 3.09), exactly the `ranking_policy` in evaluate.py; (c) at the ceiling nothing but at-fault km matters.
Note 메타몽 reached the ceiling with d2gt 2.65 and SymPhi 1691 with d2gt 3.72 — **tracking tightness is not what the top requires**;
hard-failure avoidance and progress are.

**Rank ≠ PCS.** 24 of 1,891 pairs are inverted; SymPhi `vavam-mup-g120-v1` at 1560 ranks 6th above five entries up to 1601 (us
included). Ranking is by the 97.5 % quantile of posterior rank, so a 41-PCS deficit was overcome by a tighter posterior std. The public
board hides std; **the local tool exposes `policy_capability_score_std`** — the first time we can see this dimension for our own arms.

**Zoib mechanism (beta_irt.py).** Per scene: P(0) = σ(g0 − a·θ), P(1) = σ(a·θ − g1), else Beta with mean σ(a·θ − b). Ability is
pushed by avoiding zeros where others score, hitting 1.0 where others don't, and partial progress. Scenes where everyone is at 1.0
(or 0) carry ~no information — the mechanism behind §6.32's "335 of 400 scenes are free". A zero on a discriminating scene is charged
through its own logistic channel, which is why at-fault dominates and why "safe but stalled" still loses.

**Model-side leakage check of the Maintenance Candidate (09-03): none.** Nothing in `f012862..54952f4` reveals top teams' models or
the final nuPlan scene set (the new curated suites CSVs are NuRec 26.04 = PAI only, 0 nuPlan rows; the renderer-harmonizer note and
the 6-cam/gRPC-64 MiB fix are PAI-only — nuPlan runs `alpasim-mtgs-server`). The NAVSIM sample submissions (LTF, DiffusionDrive,
GTRS-Dense) **pre-exist at f012862**; #169 only adds a doc link. They are already in CHECKPOINT-SURVEY.md with board evidence:
OpenDriveLab's own submissions of all three top out at GTRS-Dense 1354 / LTF 1213 / DiffusionDrive 1207 — 240–590 below stock — so
they are not a hidden stronger baseline. The new CLI endpoints are `/terms/current` and `/terms/status` only; the terms text is
unreadable while the API is closed. **One new, track-relevant disclosure:** the NuPlan/MTGS README section now states *"Traffic on this
track consists of vehicles only; pedestrians and cyclists are not simulated"* — consistent with `capture/collision_actors.py` (every
hit actor was a vehicle), and it bounds any hazard/collision-guard logic to vehicles.

## 6.37 Can `--controller-gains` help WA-JEPA? Mostly no — the corridor losses are model-side (09-03, data-only, nothing run)

**WA-JEPA's remaining loss is now almost purely lateral.** Of its 26 zeros on the 400: **24 `left_corridor_laterally`, 2
`collision_at_fault`** (cand#2: 33 corridor, 13 collision). It tracks tightly in general — median lateral dist-to-GT **0.50 m** vs
cand#2's 0.90 m — but in the 24 failures the median is **4.67 m** (per-tick max 7.9 m). Bimodal: excellent, then catastrophic.

**The corridor sets are largely disjoint, which settles the attribution without new runs.** Both drivers ran the *identical*
controller and *identical* default gains. Yet WA-JEPA **saves 24** of cand#2's 33 corridor scenes and **breaks 15 new ones**
(9 shared). A constant cannot explain a difference: the plan, not the controller, decides which scenes exit the corridor.
Net ledger of the +0.0434: corridor 33→24 (+9 scenes), collisions 13→2 (+11), ≈ +20 scenes ≈ +0.05. **The safety win is real but the
lateral win is only net +9, with 15 fresh regressions hiding inside it** — those 15 are the highest-value diagnostic target, not gains.

**No actuation or stability problem to fix.** In the failures the controller commands 3.4× more steering (max |δ| 0.106 vs 0.031 rad)
and the vehicle *achieves* it: |commanded − achieved| median **0.010 rad** (perfect scenes 0.004), steering sign-flip rate 0.000 in
both. So no saturation, no oscillation, no authority deficit — raising `lat_position_weight` would tighten an error that is not there.

⚠️ **`plan_deviation` is NOT controller tracking error** — `scorers/plan_deviation.py` measures the distance between *consecutive
driver plans* over their common timestamps (decay-weighted), i.e. plan-to-plan churn, the `w_disc` quantity. Failures 0.889 m mean vs
perfect 0.682 m. It does not answer the controller question and must not be read as tracking error. (A clean tracking error needs the
commanded plan and realised path in one frame, i.e. `rollout.asl`.) `x_ref_0/y_ref_0` are also not tracking error: they are the plan
anchor's pose in the *current* rig frame, so they mix heading change with drift.

**The one gain with a real mechanism: `idx_start_penalty`.** At `dt_mpc=0.1`, the default 10 means the MPC **ignores tracking cost for
the first 1.0 s of every plan**, while the 2 Hz driver **replaces the plan every 0.5 s**. The controller therefore only ever acts on
the 1.0–2.0 s segment of a plan it will discard before reaching it. Lowering it (5 → 0.5 s, 2 → 0.2 s) is the only gain change that is
a structural fix rather than a weight-balance guess. Unknown sign: if a plan's near field is good and far field poor it helps, and the
reverse if not.

**Proposed screen (not run; GPU idle, 414 MiB).** 100-scene screen, WA-JEPA image, ~8 min/arm on `dev_fast2`, control already exists
(`wajepa-s2-100` = 0.9499). `run-eval.sh` does **not** pass extra Hydra overrides — add `"$@"` after `wizard.log_dir=...` on line 47
first. Arms: `controller.gains.idx_start_penalty=5`; `=2`; and `controller.gains.lat_position_weight=2.0` as a control that should show
**no** effect if this section is right. **Gate on at-fault, not progress** — WA-JEPA's whole value is the 13→2, and faster/tighter
tracking is exactly what could erode it.

**Submission rule.** Gains ride free with a driver-image submission (no extra slot), but **do not bundle an unvalidated gain set into
WA-JEPA's first submission** — the same rule applied to cand#2 in §6.20. A clean measurement of the driver comes first; a gain set
earns its place only by clearing the ±0.0485 seed band on the 400.

## 6.38 We RAN the official Drive-IRT locally (09-03). It fits — and at n=100 it cannot separate our candidates.

**Setup.** `uv venv` on the storage disk + CPU torch + the pinned `drive-irt` tarball (82ddd5a) + pandas/pyarrow; ran the upstream
`local_evaluation/evaluate.py` from the 54952f4 worktree against our own `runs/`. Env: `/media/skr/storage/irt-venv`, output
`/media/skr/storage/irt-out/screen100`. **20 subjects × 100 scenes** (the main `navtest_local100` set; excluded
`s1b-k5-off-FAILED-cuda-timeout`, an infrastructure failure whose zeros are not capability). `effective_algorithm=zoib`, no warnings,
rank intervals applied — **the real algorithm, not the average fallback.**

| rk | rank_lo | rank_hi | spread | subject | ability | std | mean scene |
|---:|---:|---:|---:|---|---:|---:|---:|
| 1 | 1 | 13 | 12 | `wajepa-s2-100` | 3.022 | 0.451 | 0.9499 |
| 5 | 2 | 15 | 13 | `vavam-base100` | 2.499 | 0.375 | 0.9064 |
| 6 | 2 | 15 | 13 | `screen-mup-g100` (cand#2) | 2.523 | 0.398 | 0.9067 |
| 14 | 3 | 16 | 13 | `wajepa-s12-100` | 2.357 | 0.359 | **0.9667** |
| 17–20 | 16–17 | 20 | **3–4** | the four route-follower arms | 0.76–1.15 | 0.24–0.27 | 0.75–0.87 |

**Headline: WA-JEPA ranks #1 by ability, but the intervals overlap almost completely** — [1,13] vs cand#2's [2,15] out of 20 subjects.
At 100 scenes with 20 highly-correlated subjects the fit **cannot** distinguish the top group. It *can* separate the follower arms
(spread 3–4, `rank_lo` 16+): the IRT confidently agrees they are worse, which independently vindicates parking that branch.

**~~A real IRT-vs-mean inversion~~ — WITHDRAWN, it is a fit artifact (peer-caught, verified).** `wajepa-s12-100` has the best mean
(0.9667) and fewest zeros (3) yet ranks 14th, and I attributed this to the zoib P(1) channel scoring exact-1.0 in its own right.
**That mechanism is wrong.** It could explain s12 vs s2 (90 vs 93 ones) but *not* s12 vs cand#2, where s12 leads on **both** inflation
channels (3 zeros vs 9, 90 ones vs 84). A monotone fit cannot rank a doubly-dominating subject lower; so the ranking, not the model,
is what needs explaining. Two diagnostics settle it:
- **Difficulty-weighting explanation refuted.** If s12's few failures landed on *easy* scenes it would deserve the penalty. They do
  not: field pass-rate on s12's 3 zero-scenes is **0.48**, vs s2's 0.58 and cand#2's 0.43, against an all-scene baseline of **0.83**.
  s12 fails *hard* scenes, which the IRT should forgive — that would push its ability up, not down.
- **The fit is not identified on the item side.** In `fit/item_params.csv`, **90 of 100 scenes have `difficulty_std` >
  |`difficulty`|** (median |difficulty| 0.483 vs median std **1.667**, 3.5× larger). And the 14-subject top group spans just
  **1.9 posterior std** of ability. The point ranks inside that blob are noise.
**Conclusion: no strategy follows.** "Maximise exact-1.0 count rather than mean" would have been a real change of objective built on
an unstable point rank. Scene difficulty needs many *subjects per scene* (the board has 62); 20 correlated local arms cannot deliver it.

⚠️ **Consequence for the 6-subject 400-scene fit now running.** It trades in both directions and the trade is not obviously
favourable: ability precision should *improve* (each ability is estimated from 400 items instead of 100, so posterior std ~0.45 →
~0.22 if it scales as 1/√N — which is what separating WA-JEPA from cand#2 needs), but **item difficulty gets worse, not better**:
6 subjects per scene versus 20. The `S×N ≥ S+5N` guard is a crude sufficiency check, not an identification test. Read the
`difficulty_std`/`|difficulty|` ratio and the top-group-spread-in-std before believing any ordering it produces.

⚠️ **Two runs I mislabelled: `vavam-base100` is NOT stock.** `alpasim-e2e-vavam-driver:local-mup` **bakes
`VAVAM_MUP_SHAPES_DIR`** into the image env, and both `vavam-base100` (09-03) and `screen-mup-g100` (08-31) used that image with
identical extras (`VAVAM_OUTPUT_GAIN=1.00 VAVAM_SEED=1234`) and preset. So they are **two draws of candidate #2**, not stock-vs-μP —
and their gap (0.9064 vs 0.9067, Δ 0.0003, same seed) is pure fp16-batching numerics, a tighter noise bracket than the ±0.0485 seed
band. The main 100-scene set therefore contains **no stock VaVAM and no go-straight run**, so no anchor pair and no PCS scale.

**Path to an anchored, separating number (not run; ~2 h GPU).** Put **6 subjects on the 400-scene set** — we have 3
(`confirm400-mup-g100`, `f3-follow-cv-400`, `wajepa-s2-400`) and all images for the rest: `:local` (stock → the 1600 anchor policy),
`alpasim-e2e-starter-driver:latest` (go-straight → the 1000 anchor), and `:local-mup-k` or `:local-follow`. 6×400 = 2400 ≥ 2006 ✓, and
with both anchor policies present the anchor affine yields **indicative** PCS for WA-JEPA and cand#2 on the board's scale. Still not the
board's number — a 6-subject fit on 400 scenes is not the 62-subject fit on full navtest, and the anchors only pin two points.

## 6.39 How to judge the 400-scene fit — decided BEFORE seeing it (09-03, with peer a5)

**The 6-subject 400 fit is for exactly one thing: the pairwise ability separation of `wajepa-s2-400` vs `confirm400-mup-g100`.**
Not a 6-way ranking — that will stay noise for the same reason the 20-way one was (§6.38). Pre-registering the read so it cannot be
chosen after the fact:
- **Report**: the two subjects' abilities, their posterior stds, and the **gap in units of pooled posterior std**. At n=100 the
  ability gap was 0.50 (3.02 vs 2.52) at std 0.451. If std scales as 1/√N, n=400 gives ~0.225 ⇒ **~2.2 std of separation** for the
  pair. That is the quantity that decides whether WA-JEPA's local win survives the official lens.
- **Report alongside, always**: the fraction of scenes with `difficulty_std` > |`difficulty`| and the top-group spread in std. The
  `S×N ≥ S+5N` guard passed cleanly on a fit whose difficulties were 3.5× noise, so it certifies nothing about identification.
- **Expect difficulties to be WORSE identified, not better** — 6 subjects/scene vs 20. No choice of sixth subject fixes that, so the
  sixth was chosen for **cost, not identification**.

**Sixth subject = WA-JEPA s4, kept deliberately, and it earns its place as a near-replicate.** s4 (5 zeros/92 ones) is almost a
duplicate of s2 (5/93) — which peer a5 correctly called weak for *widening* the fit. But that near-duplication is itself a **built-in
reliability check nobody had proposed**: two configs with near-identical response profiles *should* land at near-identical ability.
**If s2 and s4 come out far apart at n=400, the s2-vs-cand#2 separation cannot be trusted either** — a null-distance control for the
very contrast we care about. s12 would have been the more informative profile (3/90, and would retest the withdrawn inversion) but
runs ~1516 ms/call vs s4's 520 ⇒ ~90+ min instead of ~35; not worth 3× the GPU for a second-order gain.
Cheaper distinct-profile option if ever wanted (peer a5): `VAVAM_OUTPUT_GAIN=1.05` on `:local-mup` reproduces the g105 arm
(0.8683 vs cand#2's 0.9067 on the same 100 — same base model, genuinely different failure subset) at VaVAM speed.

**Correction to my own instinct, recorded because it was wrong:** I proposed picking a sixth subject "far from the others to widen the
spread". That is the wrong objective. A distant *low*-ability subject widens the overall range but carries no information about the
scenes that separate cand#2 from WA-JEPA. Informativeness for a contrast comes from subjects near that contrast failing a *different*
subset, not from range.

**No-GPU robustness check — redesigned after peer a5's replicate caveat, which was correct.** The 100-scene set is a subset of the
400 (peer-verified: 100/100 ids present, and both `wajepa-s2-400` and `confirm400-mup-g100` cover 100/100). My first framing —
"23 now, 26 after tonight" — **overstated the identification**, because a config appearing in both sets is *two draws of one policy*,
not two independent response patterns; counting both inflates the subject count and would tighten difficulty CIs spuriously.
De-duplicated, the arithmetic is quite different and better:
- the **three existing** 400-runs add **zero** new configs (cand#2, wajepa-s2, follower-cv are all already at n=100);
- **tonight adds exactly two**: **stock VaVAM and the go-straight starter** — and those are the two **anchor policies**.
⇒ The n=100 regime becomes **22 distinct configs *including both anchors***, so it can be **anchored too**, not just the 6×400 fit.
That is the real prize of the re-slice: two fits, opposite identification regimes (**22 subjects × 100 items** vs **6 × 400**), *both*
on the board's 1000/1600 scale. Replicate draws (cand#2 ×2, wajepa-s2 ×2, …) are then kept **only** as declared null-distance
controls, never counted toward identification.

**Pre-registered disagreement rule (peer a5's, sharper than mine).** I had said "if they disagree, neither is usable". Correct
reading: **disagreement means the ordering is not resolvable at our sample sizes at all** — itself a reportable result, and it would
mean the **400-scene mean-score margin (+0.0434) remains the better-grounded claim than any ability estimate.** Not a dead end: a
finding about the limit of what we can measure locally.

**Cross-check ownership:** mine, at peer a5's request and for a sound reason — a second drive-irt install risks version skew, which
would make a disagreement between the two fits ambiguous, destroying the very signal the check exists to produce. Both fits come from
`/media/skr/storage/irt-venv`; they critique the output instead of duplicating the tooling.

**Generalisation worth keeping (from the s4 exchange):** *any contrast fit should carry a null-distance pair when one is available
free* — two configs whose response profiles are near-identical must land at near-identical ability, else the contrast of interest is
uninterpretable whatever its size.

### The guard that would have caught all four of today's errors (peer a5's formulation)
> **State the resolution of the measurement before interpreting the difference.**

Today: (1) the score-proxy episode, (2) the progress-deficit overstatement (6×, mine), (3) the P(1) "inversion" mechanism (mine),
(4) the raw-vs-clipped progress deltas. Common shape: **a plausible causal story fitted to a difference the data could not resolve.**
This complements §6.33 (never compute a scoring claim from a raw metric): §6.33 governs *which quantity*, this governs *whether the
quantity is resolved enough to carry an explanation*.

## 6.40 Anchor runs complete (09-03 22:00) — the μP fix measured paired at n=400 for the first time

`stock400-g100` and `starter400` both 400/400, 0 errors. `wajepa-s4-400` started 22:00 (ETA ~22:35).

| run | mean | zeros | ones | at-fault | corridor | at-fault km |
|---|---:|---:|---:|---:|---:|---:|
| `starter400` (go-straight) | 0.6192 | 104 | 218 | 22 | 82 | 0.47 |
| `stock400-g100` (stock VaVAM) | 0.8493 | 60 | 335 | 22 | 38 | 0.578 |
| `confirm400-mup-g100` (cand#2) | 0.8813 | 46 | 329 | 13 | 33 | 0.897 |
| `f3-follow-cv-400` (follower) | 0.8896 | 41 | 323 | 18 | 23 | 0.621 |
| `wajepa-s2-400` (WA-JEPA) | 0.9247 | 26 | 351 | 2 | 24 | 5.4 |

**The μP fix, paired, n=400 — we had never measured this.** Every stock-vs-μP number before came from the unpaired 300-set, and the
"0.9064 vs 0.9067" pair turned out to be two cand#2 draws (§6.38). Paired on identical scenes/seed/preset:
**+0.0320 (sd 0.3388, se 0.0169, 1.89 σ)**, at-fault **22 → 13**, corridor 38 → 33.
**Shape of the win:** cand#2 is *worse* on more scenes than it is better on — **wins 31, loses 40** — but wins **big** (mean magnitude
0.970, i.e. converting hard failures into full scores) and loses **small** (0.432, partial-credit shavings). Net +30.1 vs −17.3 points.
A scene-count comparison would have called this a regression; the magnitude asymmetry is the whole effect.

**Anchor scale, now on identical scenes** (replaces the 20–27 guess built from mismatched sets):
go-straight **0.6192 → 1000**, stock VaVAM **0.8493 → 1600** ⇒ **26.1 PCS per +0.01 mean score**.
*Validation:* our stock submission scored **1592** officially while local stock **is** the 1600 anchor by construction — an 8-point
agreement on the one point we can cross-check. The local scale is not wildly off.

⚠️ **But the linear-in-mean projection fails two sanity checks, so do not quote it.**
| | mean | linear projection |
|---|---:|---:|
| cand#2 | 0.8813 | 1683 |
| follower | 0.8896 | **1705** |
| WA-JEPA | 0.9247 | **1797** |
Both flagged values are implausible: the follower lands *above* cand#2 despite **18 vs 13 at-fault** (and the n=100 IRT put every
follower arm last with tight intervals, §6.38), and WA-JEPA exceeds the **~1715 ceiling** of §6.36. PCS is an IRT ability — difficulty-
weighted, with separate 0/1 channels and an at-fault tiebreak — **not a linear function of the mean**. These numbers are exactly the
artefact the 6-subject fit exists to replace; treat them as an ordering hint at best, and never as a projected score.

## 6.41 First ANCHORED local PCS (09-03) — and it fails its own pre-registered separation test

**Method.** `starter400` and `stock400-g100` re-sliced to the canonical 100 scenes (means 0.6133 / 0.8587), written as a
**local** reference bundle with `score_scale` low→1000, high→1600, and fed to the upstream evaluator via `--reference-manifest`.
The tool applied the affine itself (`score_scale.applied=true`), `effective_algorithm=zoib`, 22 subjects, no warnings.
⚠️ These are **our own runs used as anchors**, not the organizer bundle.

| PCS | ± | subject | mean | | PCS | ± | subject | mean |
|---:|---:|---|---:|---|---:|---:|---|---:|
| **1702** | 116 | `wajepa-s2-100` | 0.9499 | | 1582 | 93 | **`screen-mup-g100` (cand#2)** | 0.9067 |
| 1660 | 115 | `wajepa-s4-100` | 0.9493 | | 1579 | 91 | `vavam-base100` (cand#2 draw C) | 0.9064 |
| 1652 | 97 | `disc-d040` | 0.9062 | | 1551 | 88 | `wajepa-s12-100` | **0.9667** |
| **1600** | 114 | `anchor-high` = stock VaVAM | 0.8587 | | 1377 | 72 | `f1c-follow-cv` | 0.8926 |
| | | | | | **1000** | 20 | `anchor-low` = go-straight | 0.6133 |

**Verdict against §6.39's pre-registered test: NOT SEPARATED.** WA-JEPA − cand#2 = **120 PCS**, but pooled posterior std is
√(116²+93²) = **149** ⇒ **0.81 σ**. Well short of anything decisive. The pre-registration is what makes this reportable rather than
disappointing: the criterion was fixed before the number existed.

**Two internal contradictions confirm the fit is underpowered — do not read the ordering.**
1. **cand#2 (1582) lands *below* the stock anchor (1600)** even though cand#2 beats stock **on these same 100 scenes** by mean
   (0.9067 vs 0.8587) *and* beats it paired at n=400 by **+0.0320 at 1.89 σ** (§6.40). The fit contradicts a direct paired measurement.
2. `wajepa-s12` (1551) still sits below cand#2 (1582) despite the best mean of all — the §6.38 artifact, unchanged.
**Identification:** 80/100 scenes still have `difficulty_std` > |`difficulty`| (was 90/100 with 20 subjects — better, still bad);
the 15-subject top group spans 201 PCS at median std 102 = **2.0 σ**, i.e. one blob, exactly as at n=100 before.

**The null-distance control passes.** The two cand#2 draws land at **1582 and 1579 — 3 PCS apart** against stds of ~92. Replicates
are reproduced tightly, so the fit is deterministic and self-consistent; what it lacks is *resolving power between different policies*,
not stability. That is the distinction the control was built to make.

**Where this leaves the claim.** The 400-scene mean-score margin (+0.0434, and now +0.0320 for μP over stock, paired) remains the
**better-grounded** claim than any local ability estimate — peer a5's pre-registered reading (§6.39), now the operative one. The
6×400 fit is still worth completing for ability precision, but on this evidence expect it to narrow the interval, not to separate.

## 6.42 Why the s4 run completed 0 scenes — and the silent-failure trap it re-exposed (09-03 22:00)

**Cause: my error, one wrong preset argument.** The WA-JEPA driver requires four cameras —
`preprocessing.py:14  CAMERA_IDS = ("CAM_L0","CAM_F0","CAM_R0","CAM_B0")`, enforced at `driver.py:378`. Our `dev_fast2` preset sends
**CAM_F0 only** (the speed optimisation from the fast-eval work: it cuts 7× JPEG encode, gRPC payload and ASL writes; fine for VaVAM,
which is front-camera-only). The peer had built `dev_fast2_wajepa` with all four, and `wajepa-s2-400` used it. I launched s4 on plain
`dev_fast2`, so **every rollout was rejected at the precondition check** before a single tick was driven:
`FAILED_PRECONDITION: missing required cameras: ['CAM_B0','CAM_L0','CAM_R0']`.

**The dangerous part is not the failure — it is the artifact it left behind (Defect 8, confirmed live).** The wizard **exited 0** and
wrote `aggregate/results-summary.json` containing **400 rollouts, all with valid numeric `score: 0.0`**, `scene_score_enabled: true`,
and the gRPC error text stuffed into `failure_reason`. That file is **indistinguishable, to `evaluate.py`, from a legitimate 400-scene
subject that drove every scene and failed all of them**: it passes the score-range check (`0.0 ≤ s ≤ 1`), matches the canonical scene
set exactly, and would have entered the IRT as a real policy sitting at the floor — stretching the ability scale, shifting every
scene-difficulty estimate, and corrupting the anchor affine. Exit code, file presence and rollout count all say "fine".

**What caught it: the VALIDITY gate** added to `run-eval.sh` earlier today (`grep -c "Session COMPLETED"` vs the scene count in the
group YAML) — it printed `VALIDITY wajepa-s4-400: completed 0` and `RUN INVALID`. Without that line the run would have looked
successful in every other respect. Directory set aside as `wajepa-s4-400-FAILED-wrong-preset`; relaunched 22:40 on
`dev_fast2_wajepa`, no camera errors.

**Safety sweep of every run in `runs/` for the same pathology** (mean ≈ 0, or >10 % of rollouts carrying RPC/precondition errors):
exactly **two** hits, both already quarantined by name — `s1b-k5-off-FAILED-cuda-timeout` (98/100 RPC) and this one. **None of the 22
subjects in the anchored fit is contaminated, and neither anchor is.** §6.38/§6.41 stand.

**Rule:** a run is valid only if `completed == expected`; never infer validity from exit code, file presence, or rollout count — the
failure mode writes a full-length, schema-valid, all-zero result. Cross-check any new subject's mean against its driver log before it
enters a fit.

## 6.43 The 6×400 anchored fit (09-04 10:06) — pre-registered test PASSES, but the fit fails an external validity check

`wajepa-s4-400` finished 400/400, VALIDITY clean, 0 inference failures (mean 0.9302, 24 zeros, **1 at-fault**, 23 corridor,
at-fault km 10.68). Six subjects on `navtest_local400`, anchored on our own `starter400`→1000 / `stock400-g100`→1600,
`effective_algorithm=zoib`, `score_scale.applied=true`, no warnings.

| rk | PCS | ± | subject | mean | at-fault km |
|---:|---:|---:|---|---:|---:|
| 1 | 1778 | 47 | `wajepa-s4` | 0.9302 | 10.68 |
| 2 | 1815 | 44 | `wajepa-s2` | 0.9247 | 5.40 |
| 3 | 1600 | 44 | `anchor-high` = stock | 0.8493 | 0.58 |
| 4 | 1529 | 36 | `cand2` | 0.8813 | 0.90 |
| 5 | 1444 | 32 | `follower` | 0.8896 | 0.62 |
| 6 | 1000 | 10 | `anchor-low` = go-straight | 0.6192 | 0.47 |

(s4 outranks s2 despite lower PCS: both have rank_lo 1 / rank_hi 2, and the tiebreak is at-fault km, 10.68 > 5.40 — the tool's
documented `ranking_policy` behaving exactly as specified.)

**§6.39's pre-registered test: PASSES.** `wajepa-s2 − cand2` = **+286 PCS**, pooled std 57 ⇒ **+5.04 σ** (n=100 gave 0.81 σ).
**Null-distance control: PASSES.** s4 − s2 = −37 PCS = **−0.58 σ**, i.e. the near-replicate pair is ~9× closer than the contrast.
**Peer a5's disagreement rule: the two regimes AGREE** on the ordering (WA-JEPA > cand#2 at both n=100 and n=400), so by the
pre-registered criterion the *ordering* is robust to the identification regime.

⚠️ **But the fit is confidently wrong about a contrast we can check directly, and this was NOT pre-registered.** On the *same* 400
scenes cand#2 beats stock on **mean (+0.0320, 1.89 σ paired), at-fault (22→13), corridor (38→33) and zeros (60→46)** — it loses only
6 "ones" (329 vs 335). The IRT nonetheless places cand#2 **71 PCS below** the stock anchor at **−1.24 σ**, and **both** fits (n=100
and n=400) do this. A policy dominating another on four of five channels cannot be 71 PCS worse. So:
- the σ units are **not calibrated** — mean-field variational inference is known to understate posterior variance, and here the
  stds *shrank* (93–116 → 36–47) while identification got *worse*;
- **identification collapsed as predicted**: **370/400 scenes (92.5 %)** have `difficulty_std` > |`difficulty`|, vs 80/100 at 22
  subjects. Fewer subjects per scene ⇒ per-scene difficulty and the g0/g1 channel parameters are fitted from 6 observations each;
- the two fits **agreeing is not validation** when they share a systematic bias — both mis-rank cand#2 vs stock the same way.
- Corroborating implausibility: WA-JEPA's 1778–1815 **exceeds the ~1715 board ceiling** (§6.36), as did the independent
  linear-in-mean projection (1797, §6.40).

**Ruling.** The **ordering** WA-JEPA > cand#2 is now supported three independent ways — raw paired margin (+0.0434), n=100 anchored
fit (+120 PCS), n=400 anchored fit (+286 PCS) — and the null-distance control says it is not replicate noise. **The magnitude and
the σ are not usable**: "+286 PCS" and "5.04 σ" must not be quoted as a projected board gain. The **+0.0434 paired mean-score margin
remains the reportable claim**, exactly as peer a5 pre-registered. What the IRT adds is corroboration of direction, not a number.

**s2 vs s4 at n=400 — indistinguishable in quality; s2 wins on cost alone (09-04).**
Paired on the identical 400: **s4 − s2 = +0.0055 (0.84 σ)** — not significant. Per-metric: s4 has *fewer* zeros (24 vs 26),
*fewer* at-fault (1 vs 2), *fewer* corridor (23 vs 24) and a higher mean; s2 has *more* perfect scores (351 vs 348) and the higher
(uncalibrated) PCS. **No metric separates them beyond noise**, and the IRT itself puts them at **−0.58 σ** — which is precisely why
they served as the null-distance control in §6.43. Note s4 repeats the cand#2-vs-stock pattern: higher mean while losing *more*
scenes (worse on 25, better on 10) — big wins, small losses.
**The decisive axis is cost:** ~**295 ms/call (s2) vs ~520 ms (s4)**, i.e. ~1.75×. With stock B consuming 2265 s of the 2485 s
official budget (9.7 % margin) and 2-step WA-JEPA already ~2.3× stock's driver burden, s4 is the materially riskier arm for the
throughput limit at **zero measurable quality gain**. **s2 remains the ship candidate** — now for a reason measured at n=400 rather
than inferred at n=100.
*Caveat if we ever reach the ~1715 ceiling:* at the ceiling the board's tiebreak is at-fault km, where s4 shows 10.68 vs s2's 5.40 —
but that gap rests on a **1-vs-2 collision count** on 400 scenes and is not a measurable difference; both are far above NaLa's 3.36.

## 6.44 Latency headroom, measured (09-04) — s2 fits with 5.4 % margin, s4 with 1.2 %, s12 fails

**Measured per-`Drive` latency, all five arms on the identical 400 scenes**, from `rpc_duration_seconds_{sum,count}`
`{method="drive",service="driver"}` summed over both workers (4000 calls each — the honest source, not a log estimate):

| arm | mean Drive | added wall | projected | margin | verdict |
|---|---:|---:|---:|---:|---|
| stock | 103.9 ms | 0 s | 2266 s | 220 s (8.8 %) | PASS |
| cand#2 | 102.8 ms | 0 s | 2265 s | 220 s (8.9 %) | PASS |
| follower | 104.6 ms | 1 s | 2266 s | 219 s (8.8 %) | PASS |
| **WA-JEPA s2** | **289.7 ms** | 87 s | 2352 s | **133 s (5.4 %)** | **PASS** |
| **WA-JEPA s4** | **511.2 ms** | 189 s | 2455 s | **31 s (1.2 %)** | **PASS, no room** |
| WA-JEPA s12 | 1516 ms | 656 s | 2921 s | **−436 s** | **FAIL** |

Basis: official 08-31 record `observed_wall_time_s 2265.3` vs `limit_wall_time_s 2485.4` at 103 ms/call;
`added = 14,850 × (L − 103 ms) / 32` (1,485 scenes × 10 calls, 32 concurrent).

**This is an UPPER bound** — it assumes every millisecond of `Drive` sits on the critical path. The official run is renderer-bound
(0.41 calls/s demanded per replica against ~10 calls/s capacity at 103 ms), so the true added wall is **lower**, by an unknown amount.
Conservative basis is the right one for a hard-fail constraint.

**Reading.** s2's 133 s margin survives ordinary run-to-run variance; **s4's 31 s does not** — that is 1.2 %, smaller than the
variation we see between identical local reruns, and throughput failure is a **hard fail independent of score**. Since §6.43 showed
s4 offers **zero measurable quality gain** over s2 (+0.0055, 0.84 σ), s4 costs ~7 points of margin for nothing. **s2 is the only
sensible WA-JEPA arm**, and this is now the second independent reason (cost, and headroom) on top of the quality tie.

⚠️ **Re-verify before submitting.** These are 08-31 numbers for a *different* driver on the *pre-Maintenance-Candidate* stack. The
final competition may change scene count, concurrency or `throughput_limit` (organizers signalled limits may drop 5→3, and #173 is
"the initial candidate version for the final competition version"). Pull the official `limits` from the CLI when the API reopens and
recompute before treating s2's 5.4 % as banked.

## 6.45 Submission prep complete; blocked on MAINTENANCE, not on us (09-04 ~11:00)

**Terms ACCEPTED (on the user's explicit instruction).** Version `placeholder-2026-09-02`
(sha256 `93a4915622242679a2e73a1ac4dbd2c3bbd852303565ccd72756e3fe8052cc64`, body is literally
"this will contain the terms and conditions"). Now `actor_accepted: true`, `captain_accepted: true`,
**`team_ready: true`** — a captain's acceptance satisfies both roles. Requires the **new** CLI from the
`54952f4` worktree; our pinned checkout predates the `terms` subcommand. Acceptance is one-time per version.

**Account trap that cost a round-trip:** the first fresh token authenticated as `sangramrout`
(`sangram.kr.rout@gmail.com`), `registered: false` → every team call 403 "User is not registered", including
`leaderboard`. The registered identity is **`skr3178` / `sangramrout2021@u.northwestern.edu`, captain of
`team-lucifer`, approved**. Two HF accounts exist; only `skr3178` is registered. **Always check
`me → registration.team_id` before assuming a token failure means the API is closed.**

**Quota changed as the organizers signalled:** monthly limit **3** (was 5), **0 used, 3 remaining**.

**Current gate:** `ecr-login` → `403 "Competition is in MAINTENANCE; image uploads are limited to organizer
teams"`. So the push cannot proceed yet; nothing on our side is missing. Competition `status: MAINTENANCE`;
window was announced to ~09-06. `submit` deliberately NOT called — it would consume one of three slots and the
user has the final go on hold.

**Staged and verified, ready to push the moment MAINTENANCE lifts:**
| artifact | tag | verification |
|---|---|---|
| WA-JEPA s2 | `…team-lucifer:wajepa-s2-20260904` | cu124 server base; **resolved `steps=2`** from the policy's own log on CPU, 0 load errors |
| candidate #2 | `…team-lucifer:vavam-b-mup-20260831b` | already in ECR, digest `bbe3a0af…`, muP confirmed in baked env |

**Bug fixed before it could ship (§6.44 follow-up):** neither `Dockerfile` nor `Dockerfile.local` pinned
`WAJEPA_STEPS`, so the image fell through to `wa_jepa_infer.yaml: num_inference_steps: 12` → 1516 ms/call →
**−436 s against the throughput limit, a hard fail**. Every validated run had passed the var через `DRIVER_ENV`,
masking it in all of them including the 400s. `ENV WAJEPA_STEPS=2` now baked in **both** files (peer-confirmed
both were affected). Verification asserts the **resolved** value, not the env var — the muP lesson applied.

## 6.46 The route-command "fix" was WRONG and is reverted (09-05) — the mechanism cannot occur

**Claim I made:** WA-JEPA's `command_from_route` was copied from the GTRS sample (lookahead 5.0, lateral 2.0,
Euclidean `hypot(x,y)`) and diverges from VaVAM (20.0, 3.0, longitudinal `x`); a 5 m *Euclidean* gate fires on a
waypoint merely 5 m to the SIDE, flipping the command mid-straight — suspected cause of the 15 corridor exits
worth 0.0375. I demonstrated it on the synthetic route `[(1,6),(30,0.5)]`: LEFT under the old rule, STRAIGHT
under VaVAM's.

**It is wrong, and peer d0 caught it.** `route_start_offset_m: 40.0` — `e2e_challenge_nuplan_common/base.yaml:121`,
and confirmed present in `runs/wajepa-fix-100/wizard-config.yaml` — means the submitted route **starts ~40 m ahead
of the ego**. So **no waypoint is ever within 5 m**, both gates select the *same* first waypoint at ~40 m, and the
lookahead and the distance metric are **inert on real routes**. Only the lateral threshold (2.0 vs 3.0) can differ
at that point. My synthetic route is not a shape the simulator produces.

**Measured, paired on the 100 (same scenes, same steps=2, same 4-cam preset — only the rule differs):**
| | mean | zeros | corridor | at-fault |
|---|---:|---:|---:|---:|
| pre-fix (5.0/2.0/hypot) | **0.9499** | 5 | 5 | 0 |
| "fix" (20.0/3.0/x) | **0.9399** | 6 | 6 | 0 |
Δ **−0.0100**; 97 unchanged, 1 better, 2 worse; **0 corridor exits repaired, 1 newly broken.** Only 3 scenes moved,
so the delta is inside noise — but there is no repair signal whatsoever, which is what the hypothesis predicted.

**Reverted** to the original defaults (5.0 / 2.0 / Euclidean), keeping the env-overridability, which is useful and
harmless. Consequence: **`cf33b1399a2d` (`…:wajepa-s2-20260904`) is valid again** — it bakes the original logic, so
it reproduces exactly the behaviour measured at n=400 (0.9247). No rebuild needed.

**My error, and the lesson.** I verified the *logic* of the change (in-container, correct outputs) but never checked
that the failure mode could occur in the *input distribution*. A synthetic unit test that exercises a route shape the
simulator never emits proves nothing about the simulator. This is a sibling of §6.39's guard: that one says state the
resolution of the measurement before interpreting a difference; this one says **verify the trigger condition exists in
real inputs before believing a mechanism**. Four of today's five errors are now the same family — a plausible causal
story attached to something the data cannot support.

**The 15 corridor exits remain unexplained** and are still the largest actionable defect (0.0375, ~87 % of the
+0.0434 margin). Peer d0 is screening WA-JEPA's own nav rule (`arc_length` 20 m + lateral 2.5 m AND heading 0.15 rad,
ported from `WA-JEPA/datasets/nav_command_infer.py`) as `WAJEPA_ROUTE_MODE=arc_length`, default unchanged.

## 6.47 WA-JEPA's own nav rule screened (09-05, recorded 09-10): no effect either — the command is not the lever

Arm `wajepa-wjrule-100`: image `alpasim-e2e-wajepa-driver:local-wjrule` (e359f5d6793a, cu128 twin, tree == image verified),
`WAJEPA_STEPS=2 WAJEPA_ROUTE_MODE=arc_length`, navtest_local100 / dev_fast2_wajepa, 746 s wall. Driver log records the
RESOLVED rule: `route_rule=arc_length forward_m=20.0 lateral_m=2.5 heading_rad=0.15 combine=and`. The port was checked
against `WA-JEPA/datasets/nav_command_infer.py` on 3000 random polylines (identical commands) before the build.

| arm (same 100 scenes, steps=2, 4-cam) | rule | mean | ones | corridor zeros |
|---|---|---:|---:|---:|
| wajepa-s2-100 | GTRS 5 m hypot / 2 m | **0.9499** | 93 | 5 |
| wajepa-fix-100 | VaVAM 20 m x / 3 m | 0.9399 | 92 | 6 |
| wajepa-wjrule-100 | WA-JEPA arc 20 m / 2.5 m AND 0.15 rad | **0.9499** | 93 | 5 |

Paired vs wajepa-s2-100: 98 unchanged, 0 better, 2 worse (both < 0.01), Δ −0.0030; 0 corridor exits repaired, 0 new.
**The same 5 corridor-exit scenes are zero under all three rules.** On captured real routes (first waypoint ≈ 42 m ahead,
|y| ≤ 1.5 m over 4.5 s) all three rules emit STRAIGHT on every tick. Conclusion: the route→command rule is not the
lever for the corridor exits on this set; the 15 exits in the 400 need a different mechanism (candidates: the model's
own lateral drift on straights, or the 2 Hz plan cache — untested). Default rule stays GTRS (6.46); `arc_length` mode
remains available via env for any future arm. `submit-s2` (cf33b1399a2d) unaffected.

## 6.47 Upstream moved again: "Candidate Final V2" (09-05, reviewed before submitting)

`origin/e2e_challenge` `54952f4 → cd713e0`: **#177 "Candidate Final V2"** + **#178** (local nuPlan eval docs).
22 files, +435/−45. Reviewed specifically for submission risk.

**Our submission image stays valid.** The only contract change is **additive** to `egodriver.proto` — two new
fields on the ego message, `common.AABB bounding_box = 4` and `common.Pose rig_to_bounding_box = 5` (the ego's
own bounding box and its pose in the rig frame). Protobuf ignores unknown fields, so an image built against the
older generated code simply does not see them. **`scene_score.py` is byte-identical**; nothing under
`e2e_challenge_nuplan*`, `nuplan_scenes`, or `controller` configs changed. So all our measurements still stand and
`cf33b1399a2d` needs no rebuild.
*(New capability, not required: the sim now tells the driver its own vehicle dimensions — previously we had to
assume them.)*

⚠️ **The reference bundle IS published — but PAI only.** `data/pai/` now ships `reference_manifest.json` plus
`alpamayo1`, `vavam-linear`, `vavam-nonlinear` and `alternative_1..5`. **There is no `data/nuplan/`.** So our track
still has no organizer anchors, and §6.41/§6.43's locally-anchored PCS remains the best available — indicative,
not board-comparable. Worth re-checking after each upstream move.

**🔑 NEW LEAD on the 15 corridor exits — organizer-documented, and it beats both of our standing hypotheses.**
The new `e2e_challenge/CONTROLLER_TUNING.md` states: *"we have occasionally observed a failure mode when a
reference trajectory requests extremely harsh, physically unrealistic braking. In this case, the nonlinear
optimization can produce a zig-zagging solution as it tries to reduce longitudinal progress. The resulting
steering response can be harsh, and the vehicle may not recover during the rollout."* It also says explicitly that
the MPC **is not a trajectory validator, repair system, or safety filter**, and that robust recovery from
dynamically infeasible policy output is **out of scope** — i.e. the burden is on the driver.
This fits our corridor evidence better than the drift or plan-cache hypotheses: those scenes show **3.4× the
steering command** of clean scenes while the vehicle *achieves* commanded steering faithfully (|cmd−achieved|
0.010 rad). Harsh steering from a zig-zagging optimizer is exactly that signature. **Testable without a GPU run:**
look for harsh decelerations in the emitted plans and steering reversals in the controller CSV for the 24
corridor scenes. My earlier sign-flip check used a 0.01 rad deadband and found none — too coarse to rule this out.

**Also new:** `CONTROLLER_TUNING.md` explains *why* gains are tunable (closed-loop distribution shift), the
NAVSIM adaptation guide is now linked from the challenge README, and `test_e2e_challenge_nuplan_configs.py` (+68)
adds config tests for our track.

## 6.48 SUBMITTED — and the nuPlan board has been WIPED and re-run (09-10)

**Submission made** on explicit instruction: `submission_id 1340e69a-ac0f-4a1f-96a3-507b315c51aa`, track `nuplan`,
image `…team-lucifer:wajepa-s2-20260904` → resolved digest `sha256:7bcc9e69…`. No `--controller-gains` (unscreened;
bundling would make the result unattributable). Status **RUNNING**. Quota **1 of 3 used this month, 2 remain**.
Terms `official-2026-08` accepted (captain acceptance covers the team). Push took ~3 min — most base layers already
existed in the registry from the cand#2 pushes; only WA-JEPA's layers incl. the 1.58 GB checkpoint uploaded.

**The old leaderboard is GONE.** `leaderboard --track nuplan` now returns **10 entries**, not the 62 in our 09-01
snapshot. **Every previous competitor is absent — NaLa, 메타몽, SymPhi and our own `vavam-stock-20260829` included.**
The organizers' announced "re-run best submissions on a new scene set" has happened, and the board restarted.
`submissions` still lists our Aug-29 entry (`SUCCEEDED`), so submission history survived; only the board was reset.

| rk | PCS | 95 % interval | avg scene | at-fault km | team | tag |
|---:|---:|---|---:|---:|---|---|
| 1 | **1600** | 1519–1681 | 0.9057 | 0.87 | py123d-garage | `007-nuplan-0062-v1` |
| 2 | 1465 | 1400–1530 | 0.8891 | 1.72 | py123d-garage | `014-nuplan-0014-v1` |
| 3 | 1443 | 1380–1506 | 0.8747 | 0.61 | py123d-garage | `017-nuplan-0014-v1` |
| 4–5 | 1381 | 1322–1441 | 0.8194 | 0.37 | Host | `go_straight_with_delay_v2` |
| 6 | 947 | 912–981 | 0.7514 | 0.40 | Host | `policy5` |
| 7–10 | 811 → 600 | | 0.64 → 0.40 | 0.14–0.23 | Host / Alpain | `policy_4`, `mars-v0-2hz-nuplan` |

**Consequences.**
- **§6.36's whole anchor analysis is obsolete.** The 1000 = `go_straight` / 1600 = stock-VaVAM pinning is gone; the
  top entry is now exactly 1600 and go-straight-with-delay sits at 1381. The **~1715 ceiling and the tied-#1
  hypothesis no longer apply** to this board. Do not quote 26.1 PCS per 0.01 against it.
- **The board now publishes what we had to derive**: `average_scene_score`, `policy_capability_score_lo/hi` with a
  95 % interval, `policy_capability_score_spread`, and `rank_lo/hi/spread`. The uncertainty dimension is public.
- **Only 10 entries and one serious competitor** (py123d-garage, 3 of the top 3). Submitting now was the right call
  for a reason we did not anticipate: the field is nearly empty.
- **Encouraging comparison, not a prediction:** the #1 entry has avg scene score **0.9057** and at-fault km **0.87**.
  WA-JEPA scored **0.9247** with **5.40 km** on *our* 400 — different scene set, so not comparable, but the same
  order on score and ~6× on the tiebreak metric.

## 6.49 OFFICIAL RESULT (09-10) — rank 6/11, PCS 986. Local measurements did NOT transfer.

`1340e69a` **SUCCEEDED**. 1000/1000 rollouts valid (rate 1.0), no inference failures, no failure code.

| | official | our local 400 |
|---|---:|---:|
| **average scene score** | **0.7748** | **0.9247** |
| at-fault km | 1.08 | 5.40 |
| dist_to_gt | 1.85 | 0.50 (lateral) |
| **PCS** | **986** (95 % 943–1030), **rank 6 of 11** (rank interval 6–7) | — |

**1. The headline: our local number over-predicted by ~0.15 of mean scene score.** 0.9247 → 0.7748. Every
projection built on the local 400 (§6.40's 26.1 PCS/0.01, §6.41's 1702, §6.43's 1815) was wrong, and wrong in the
same direction. The local 400 is **not** a representative sample of the official set — this is the single most
important fact learned today, and it invalidates the local ladder as an absolute predictor. Paired *comparisons*
on the same local set may still be usable; absolute levels are not.

**2. We rank below `go_straight_with_delay_v2`** (0.8194 avg scene, PCS 1369, rank 4–5). A trivial baseline beats
our model on scene score by 0.045. That means WA-JEPA is *actively doing something worse than driving straight* on
a substantial share of official scenes — a far sharper statement of the corridor problem than anything the local
set showed.

**3. Safety transferred; progress did not.** at-fault km **1.08** is the **2nd best on the board** (leader 0.87,
#2 1.72) and `dist_to_gt` 1.85 beats every Host baseline (2.30–3.94). So the collision-avoidance win is real and
generalises. What does not generalise is scene score, which is what drives PCS.

**4. ⚠️ Throughput was never a constraint — my §6.44 analysis was badly wrong.**
`observed_wall_time_s 1249.3` vs `limit_wall_time_s 3000.0` ⇒ **margin 1750.7 s (58 %)**. I projected 2352 s
against a 2485 s limit (5.4 % margin). Both inputs were stale: the limit is now **3000 s, not 2485 s**, and the
eval is **1000 rollouts**, not the 14,850 Drive calls I extrapolated from. **Consequence: s4 (511 ms) and even
s12 (1516 ms) would have passed comfortably** — and s12 scored *highest* of the three arms locally (0.9667 on the
100). Rejecting s12 on throughput grounds (§6.44) was based on obsolete numbers.

**5. The `score` field in `submissions`/`status` is `dist_to_gt_trajectory`, not PCS and not at-fault km** —
1.8536 here matches the board's `dist_to_gt` 1.85 exactly (and the Aug-29 entry's 3.045 was its d2gt). Do not read
it as a score.

**Standing:** 2 of 3 monthly slots remain. The board has 11 entries; `py123d-garage` holds the top three.

## 6.50 The official nuPlan scene set is PRIVATE and is no longer navtest (09-10) — supersedes part of §6.49

§6.49 attributed the 0.9247 → 0.7748 miss to our local 400 being an unrepresentative sample of navtest. That is
true but it is the *smaller* half of the problem.

**The public suite is unchanged and now test-pinned.** `cd713e0` adds
`src/wizard/tests/test_e2e_challenge_nuplan_configs.py`, which asserts of the `full` preset:
`len(cfg.scenes.scene_ids) == 1485`, no duplicates, `cfg.scenes.test_suite_id is None`, `limit_to_first_n == 0`.
`navtest_full` = **1485**, `navtest_dev` = 9. Those are the only two nuPlan groups upstream ships.

**The official evaluation is not that suite.** Our run reported `rollout_coverage: {expected_rollout_count: 1000,
valid_scored_rollout_count: 1000, rate 1.0}` — **1000, not 1485.**

| | Aug-29 (`6ba9c546`) | Sep-10 (`1340e69a`) |
|---|---|---|
| scenes / rollouts | 1485 (14,850 Drive calls) | **1000 rollouts** |
| wall limit | 2485.438 s (a computed value) | **3000.0 s** (flat cap) |
| `rollout_coverage` | absent from the response | **new field** |
| board presence | **gone** (not re-scored, kept its original numbers) | rank 6 |
| backend | `direct-p5` | `direct-p5` (unchanged) |

The old submission keeping its original metrics *and* disappearing from the board only makes sense if the new set
is not comparable to the old. `test_suite_id is None` on the public preset suggests the official runner sets a
suite id pointing at a **private** suite. `data/nuplan/` in the reference bundle remains empty (PAI got curated
public splits; nuPlan got none), which is consistent with the nuPlan set being held out.

**Undetermined:** whether 1000 rollouts means 1000 scenes × 1, or fewer scenes with repeats. nuPlan
`base.yaml` sets `n_rollouts: 1`, but the organizers demonstrably use `n_rollouts=3` for the PAI references.

**Consequences for how we work.**
1. **No local setup can replicate the official set.** Full navtest is the closest *public* proxy and is worth
   building (1485 ≫ 400, and our 400 covers only 4 of navtest's 9 log-dates — **630 scenes, 42 %, never driven**),
   but it is an approximation by construction, not a replica. Stop expecting any local absolute level to predict.
2. **The transfer is model-dependent, so it must be measured per model.** Stock transferred *upward*
   (0.58 km local → 1.62 official); WA-JEPA transferred *downward* (5.40 → 1.08). One calibration point cannot
   give a transfer function.
3. ⇒ **Submitting cand#2 is now the highest-value use of a slot**: zero prep (already in ECR as
   `…:vavam-b-mup-20260831b`, digest `bbe3a0af…`), and it yields the second point needed to estimate transfer for
   the VaVAM family, whose direction we already know differs from WA-JEPA's.

## 6.51 WHY WA-JEPA under-performed officially — answered by issue #166 + our own data (09-10)

**The organizer's warning (issue #166, `mwatson-nvidia`, COLLABORATOR):**
> *"the dataset used is a **private dataset not published anywhere**, so the results will vary"*
> *"a policy can get a very high 'distance between at-fault incidents' by simply **braking hard** due to the current
> evaluation implementation. This will not result in a very high scene score and **highlights the case where the two
> metrics don't increase together**."*

That is a direct description of the model we selected — and it independently confirms §6.50's private-set inference.

**Our data, paired on the same 400 scenes:**
| run | at-fault km | dist driven /scene | GT dist /scene | progress | scene score |
|---|---:|---:|---:|---:|---:|
| starter (go-straight) | 0.47 | 25.8 | 31.4 | 0.7841 | 0.6192 |
| stock | 0.58 | 31.8 | 31.4 | 1.0553 | 0.8493 |
| cand#2 | 0.90 | 29.2 | 31.4 | 1.0204 | 0.8813 |
| **WA-JEPA s2** | **5.40** | **27.0** | 31.4 | **0.9565** | 0.9247 |

**WA-JEPA drives 7.4 % less distance than cand#2 and travels less far on 287 of 400 scenes (72 %).** It is the most
*cautious* policy we have built. Note the at-fault-km ratio is not itself a braking artifact — 5.40 vs 0.90 comes
from 2 vs 13 incidents, not from distance — but the caution that produces those 2 incidents costs progress
everywhere.

**The mechanism, stated plainly.** WA-JEPA trades **progress for caution**: −7.4 % distance, −0.064 progress,
in exchange for −11 at-fault collisions per 400.
- **On our local 400 that trade pays**: collisions are frequent (13/400 for cand#2), so 11 recovered scenes
  (+0.0275) outweigh the progress loss. Net +0.0434.
- **On the official set it does not**: `go_straight_with_delay_v2` scores **0.8194** there versus **0.6192** for our
  starter locally. A set where driving straight earns 0.82 is a set with **little collision risk to avoid** — so the
  safety premium collapses while the progress penalty is paid in full.

**We optimised for the axis with the least headroom.** Our at-fault distance of 1.08 km is 2nd best on the board;
scene score is 6th. The entire 13→2 selection criterion bought a metric we were already winning, at the cost of the
one that determines PCS.

**Other hints from the issue tracker (all `mwatson-nvidia`):**
- **#170** — *"all team allocations will be reset ... significant changes to the competition (including the
  **evaluation approach and the tests**) so the leaderboard will be wiped clean."* Explains the reset and that the
  test set itself changed, not just the scores.
- **#159** — competition hardware is **H100**; local hardware differs and *"the hardware issue will likely remain an
  open gap."*
- **#155** — the nuPlan track's **500 ms (2 Hz)** step is deliberate and permanent, kept for NAVSIM entrants;
  scenarios are short (~6 s). PAI uses 10 Hz.
- **#152** — nonlinear MPC + harsh braking → *"swerves to artificially shrink the path"*; fixed in PR #153, so this
  is **not** our corridor mechanism (already ruled out empirically in §6.47).
- **#138** — the route is built **once at initialisation from the recorded ~20 s ego path**, lane-matched by
  heuristics; extrapolation only past the recording end. Confirms the route is GT-derived, not a live planner.
- **#166** — rank ordering is by the **upper bound of the posterior rank interval**, then at-fault distance, then
  point-estimate rank. Matches what evaluate.py does.

**Actionable consequence.** The next submission should be selected on **progress/scene score**, not on at-fault
count. cand#2 drives 7.4 % further, has progress 1.0204 vs 0.9565, and is already in ECR — on this analysis it is
the better bet for the official set despite losing to WA-JEPA locally.

## 6.52 The corridor failures are a GRADUAL divergence, not a handover fault (09-10)

Tested the central premise of `ROBUSTNESS-PLAN.md` (a peer session's proposal to sanitise the trajectory and
blend the first 0.5–1.0 s from the current ego state). Median lateral dist-to-GT over time, `wajepa-s2-400`,
policy takes over at **t = 0.5 s** (`force_gt_duration_us: 500_000`):

| group | t=0.5 s | t=1.0 s | t=1.5 s | t=2.5 s | t=4.0 s |
|---|---:|---:|---:|---:|---:|
| corridor-exit (24) | 0.00 | **0.03** | 0.13 | 1.07 | **4.76** |
| clean 1.0 (60) | 0.00 | 0.01 | 0.02 | 0.12 | 0.34 |

**At handover and through the first second, failing scenes are indistinguishable from clean ones** (0.03 vs
0.01 m). Divergence begins around t≈1.5 s and compounds to 4.76 m by t=4 s — roughly a lane and a half.
That is a **slow accumulating separation**, i.e. the model commits to a different path than the human took, and
tracks it faithfully (§6.47: steering commanded−achieved 0.010 rad, no oscillation, no saturation).

**Consequences.**
- The plan's **handover blend targets a window where nothing is wrong**. Sanitising the first 0.5–1.0 s cannot
  touch a divergence that starts at 1.5 s and is driven by plan *content*, not plan *feasibility*.
- Both motivating mechanisms are now empirically refuted on our data: harsh-braking swerve (§6.47 — 0/24 scenes
  below −5 m/s², no zig-zag) and handover discontinuity (this section).
- The plan's own hedge was correct — *"plausible ... not proof without private per-scene traces"*. These local
  traces are the best evidence available and they do not support it.
- What IS supported: the plans are dynamically fine and go somewhere else. A feasibility guard is the wrong
  instrument; this is a path-choice problem (lane selection / turn interpretation), which is why the route-command
  work kept looking relevant even though our specific fix (§6.46) was wrong.

**The plan's SECOND half stands and should be built** — it is methodologically sound and independent of the
mechanism claim: recording-block confidence intervals (our 400 clips come from only 4 source recordings, so
treating them as 400 independent units overstates significance — plausibly why +0.0434 looked solid and did not
transfer), explicit public-suite coverage reporting, and no synthetic local PCS.

## 6.53 py123d_garage — the board leader's code AND checkpoint are public, Apache-2.0 (09-11)

Cloned to `py123d/` (gitignored): `py123d_garage` @ `288d34c` (v0.1.1, 19 MB), `py123d` @ `2a75cb6` (67 MB),
and the HF checkpoint repo (474 MB).

**Who they are.** `kesai-labs` publishes **all three** of: `drive-irt` (the algorithm that computes the
leaderboard PCS), `py123d_garage` (self-described as *"the reference starting point for the Alpasim E2E Challenge
2026"*), and the `ln2697` navhard-leaderboard docs that `mwatson-nvidia` linked in issue #133. They are also
**`py123d-garage`, the team holding ranks 1–3** on the current nuPlan board.

**🔑 The released checkpoint IS (at least) their rank-2/3 board entry.** The file is `model_0014.pth`; their board
tags are `014-nuplan-0014-v1` (rank 2, **PCS 1470**) and `017-nuplan-0014-v1` (rank 3, **PCS 1456**). Rank 1 is
`007-nuplan-0062-v1` — a `model_0062` that is **not** released. So a checkpoint scoring ~1460–1470 is public,
against our **986**.

**What it is** (`checkpoints/resnet34_v0.1.0/README.md`): camera-only **latent TransFuser, ResNet-34**, 248 MB.
Inputs: **3 cameras (L/F/R) stitched to 1024×256, ego velocity, and ONE TARGET POINT 45 m ALONG THE ROUTE**.
Output: 4 s trajectory at 0.5 s, with yaw. Trained on nuPlan + Physical AI AV train+val (nuPlan ~46 % per batch),
2 stages × 15 epochs (perception pretrain with BEV-semantic + CenterNet aux heads, then planning posttrain).

**Why this validates our diagnosis.** A 248 MB ResNet-34 imitation model beats a 1.58 GB world model by ~480 PCS.
Their rank-2 entry has **d2gt 0.81** against our **1.85**, with a *lower* at-fault distance (1.72 vs our 1.08 is
actually higher, but rank 1 sits at 0.87). The board pays for **tight trajectory imitation and progress**, not for
world-modelling or caution — exactly what §6.51 concluded. Their route conditioning is also far more direct than
ours: a continuous 45 m target point versus WA-JEPA's discrete LEFT/STRAIGHT/RIGHT command.

**It ships a complete AlpaSim path**, already wired for our track:
- `src/py123d_garage/evaluation/alpasim/` (driver + `evaluate.py`), `configs/cameras/nuplan_3cam.yaml`
  (CAM_L0/F0/R0 at 1920×1080, 500 ms — the nuPlan contract), `configs/driver/garage_transfuser.yaml`
- `scripts/evaluation/alpasim/latent_transfuser_nuplan.sh` — local nuPlan eval, preset
  `+e2e_challenge_nuplan=dev +cameras=nuplan_3cam`, needs `ALPASIM_NUPLAN_ROOT` (we have 400 scenes of MTGS assets)
- `scripts/alpasim_submission/{login_challenge,build_docker_image,smoke_test_image,submit_image}.sh` — the image
  bakes one checkpoint + one sensor rig; **use `sensor_rig_0.yaml` (nuPlan) and `TRACK=nuplan`**
- `lib/alpasim/tools/submission.Dockerfile`; there is even a `garage_vavam.yaml` driver config

**Licence: Apache-2.0** on all three repos, and the checkpoint card is Apache-2.0. The challenge terms (§5)
require the submission be Apache-2.0 licensable — this satisfies that. The nuPlan track requires publicly
available training data; nuPlan and PhysicalAI-AV are public. So using it is permitted, and the project explicitly
offers *"pretrained baselines to build on."*

**HIGHEST-VALUE NEXT EXPERIMENT (no submission slot, no new data):** run this checkpoint on our own 400 scenes.
We know its official standing (~1470) and ours (986). If our local 400 ALSO ranks it above WA-JEPA, our eval is
sound and we simply selected wrongly; if our local 400 ranks it BELOW, our eval is actively misleading and must be
rebuilt before any further model work. Either result is decisive, and it is the first time we can test our
evaluation against a model with a known official score. Needs a 3-camera preset (we already have the pattern from
`dev_fast2_wajepa`) and their driver container.

## 6.54 py123d-garage's submission volume vs our quota (09-11, factual record)

Counted from the two post-reset board snapshots. **py123d-garage holds 11 entries, all submitted 09-04 → 09-08:**

| track | n | dates |
|---|---:|---|
| nuPlan | 3 | 09-04 14:43, 09-07 00:27, 09-07 21:13 |
| PAI | 8 | 09-04 11:03, 09-04 14:13, 09-06 23:54, 09-07 ×4 (09:09/12:19/15:32/20:41), 09-08 00:23 |

**Our quota is 3 per month, team-wide** (`limits`: "Monthly submission limit: 3 / Submitted this month: 1 /
Remaining this month: 2" — our single nuPlan submission decremented it). Eleven submissions inside one calendar
month is inconsistent with that limit, and 8 on one track alone exceeds it even if the quota were per-track.

**Suggestive but not conclusive on timing:** on **09-04** our `ecr-login` returned
`403 "Competition is in MAINTENANCE; image uploads are limited to organizer teams"` (§6.45, ~05:30 UTC), and
py123d-garage has three submissions timestamped later the same day (11:03, 14:13, 14:43 UTC). Maintenance may
simply have lifted between those times — we did not re-poll — so this is **not** proof they uploaded during a
window closed to us. The quota discrepancy stands on its own regardless.

**Reading.** Combined with §6.53 (they author `drive-irt`, the scoring algorithm, and the challenge's
self-described reference implementation, and co-author the AlpaSim simulator paper with the NVIDIA staff running
the challenge), the most economical explanation is that the platform classifies them as an **organizer team with
elevated or unlimited quota**. Note they nonetheless appear on the board as a *team*, ranked 1–3, not under the
`Host` label NVIDIA uses for its own baselines.

**What follows for us, practically:** their ranks reflect **~11 iterations in 5 days**; ours reflect one. In a
competition where local eval does not predict official score (§6.49–§6.51), submission bandwidth *is* the
optimisation loop, and we have roughly a quarter of theirs per month. That raises the value of (a) every
submission we do spend, and (b) any local proxy we can make trustworthy. It is also the strongest argument yet for
running their public checkpoint through our own eval (§6.53): it is the one way to buy calibration without a slot.

**Not an accusation.** They released the rank-2/3 checkpoint publicly under Apache-2.0, which is the opposite of
hoarding an advantage. If clarification is wanted, the channel is a GitHub issue phrased as a question; the
organizers have answered such questions within hours. **Do not file anything without the user's explicit go.**

## 6.55 ⚠️ OUR LOCAL EVAL IS INVERTED — proved with a known-good reference model (09-11)

Ran **py123d_garage's public `model_0014.pth`** — the checkpoint behind their board ranks 2–3 (**official PCS
~1470**) — through our own harness on the identical 400 scenes. Image `py123d-garage-alpasim:nuplan-0014`
(their Dockerfile, `nvidia/cuda:12.8.1`, Blackwell-compatible), preset `dev_fast2_3cam` (CAM_L0/F0/R0),
VALIDITY 400/400, **0 inference failures**, 1963 s wall (4.4 s/scene — ~1.7× faster than WA-JEPA).

| model | mean | zeros | ones | at-fault | corridor | atf km | **d2gt** | OFFICIAL |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| starter (go-straight) | 0.6192 | 104 | 218 | 22 | 82 | 0.47 | 2.33 | — |
| stock | 0.8493 | 60 | 335 | 22 | 38 | 0.58 | 3.57 | 1592 (old board) |
| cand#2 | 0.8813 | 46 | 329 | 13 | 33 | 0.90 | 2.35 | — |
| **WA-JEPA s2** | **0.9247** | 26 | 351 | 2 | 24 | 5.40 | 1.36 | **986 (rank 6)** |
| **py123d-0014** | **0.8420** | 33 | 292 | 9 | 24 | 1.14 | **1.17** | **~1470 (rank 2)** |

**THE RESULT: our local mean scene score ranks the known-better model BELOW the known-worse one, by
−0.0827 at 4.81 σ.** Not noise — confidently, decisively backwards. Every selection we have made on mean scene
score (including choosing WA-JEPA over cand#2 and spending a submission slot on it) rested on a metric that is
*anti-correlated* with the official result on the one pair where we have ground truth.

**Which local metrics order the pair correctly?** Only one of seven tested:

| metric | py123d | WA-JEPA | verdict |
|---|---:|---:|---|
| mean scene score | 0.8420 | 0.9247 | INVERTED |
| **`dist_to_gt_trajectory`** | **1.167** | **1.356** | ✅ **CORRECT** |
| lateral_dist_to_gt | 0.977 | 0.961 | INVERTED |
| clipped progress | 0.8345 | 0.9096 | INVERTED |
| dist_traveled_m | 25.60 | 27.00 | INVERTED |
| hard-failure rate | 0.0825 | 0.0650 | INVERTED |
| fraction scoring 1.0 | 0.730 | 0.878 | INVERTED |

**`dist_to_gt_trajectory` is the metric that transfers**, and it agrees with the official board's own ordering:
official d2gt is py123d **0.77/0.81/1.18** (ranks 1–3), go-straight 1.18 (4–5), WA-JEPA **1.85** (6), policy5 2.30
(7) — the board is almost perfectly ordered by tracking tightness, and our local d2gt reproduces the direction
(py123d 1.17 < WA-JEPA 1.36). Note **lateral** d2gt does NOT work; it must be the full trajectory distance.

**Local d2gt ranking of every arm we have** (lower = tighter): py123d **1.17** · WA-JEPA 1.36 · follower 2.07 ·
starter 2.33 · **cand#2 2.35** · stock 3.57.

**Consequences.**
1. **Select on `dist_to_gt_trajectory`, not scene score.** This supersedes the open question in §6.49–§6.51.
2. **cand#2 (d2gt 2.35) is NOT the right next submission** — it is barely better than the go-straight starter on
   the only metric that transfers, and worse than WA-JEPA. §6.50/§6.51's recommendation is withdrawn.
3. The route-follower (2.07) beats both our candidates on d2gt — the parked branch was aimed at the right target
   and was killed by the wrong metric (§6.38 ranked it last on scene-score-derived IRT).
4. **py123d's checkpoint is the strongest asset we hold**: Apache-2.0, 62M params, 4.4 s/scene, best d2gt of
   anything we have run, and a known official score. Finetuning it (their docs give the recipe) targets the right
   metric from the best starting point.
