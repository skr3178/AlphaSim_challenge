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
- 🟢 **Fast eval preset validated 2026-08-31** — `dev_fast` (CAM_F0 only + no eval video): 7.4 s/scene vs ~13 s, identical benchmark (stock B on the same 300: 26 vs 27 at-fault incidents, 291/300 identical per-scene outcomes). Standard for all local evals; `strategy.md` has the tier ladder
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
So VaVAM is the template. Checkpoint links: `VAVAM-CHECKPOINTS.md`.

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

> **The forward plan now lives in `strategy.md` §8** (fixes needed to compete locally, policy work in
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
   [`RANKING.md` §10](RANKING.md). Summary: it is the only sample that matches the driver
   API with no adapter; it is **pinhole-native and 2 Hz-native**, both of which are free wins
   on the nuPlan track specifically (the 546-line `rectification.py` and the plan-cache
   staleness are PAI-only concerns); its video pretraining survives MTGS novel viewpoints
   where open-loop NAVSIM models do not (`opendrivelab-org`'s 17-model sweep peaked at 1377
   vs VaVAM's 1587-1731); and the tuning surface is ~162 lines. **CarPlanner does not fit** —
   the driver API supplies no map and no agent tracks, so a privileged vector planner would
   need a full perception stack built in front of it (`RANKING.md` §10.7).

   What to optimise once it runs is [`RANKING.md` §3 and §9](RANKING.md): progress saturates
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

**Exploration for the next round** (recorded in `ROUTE-SELECTION-PLAN.md`), three facts that change the design:
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
| Fix 3 (per-scene official metrics) | **Blocked** — artifacts in a private S3 bucket; tracked as C4 in `strategy.md` §8 |
| Fast eval loop findings + exact YAML | `EVAL-RUNBOOK.md` §2-3 |
| Policy work (P-series) | `strategy.md` §8 (as A/B/C/D + N + X rows) |
| Submission strategy | `strategy.md` §6 |
| Housekeeping | `strategy.md` §8 D-rows; practices in `EVAL-RUNBOOK.md` §4 |
| Next round after candidate #2 | `ROUTE-SELECTION-PLAN.md` |

**Doc set after consolidation** — one file per question:

| File | Question it answers |
|---|---|
| `CURRENT-BEST.md` | What are we submitting, and against what baseline? |
| `strategy.md` | What do we do next, and how do we decide? |
| `EVAL-RUNBOOK.md` | How do I run a local evaluation? |
| `RANKING.md` | Why does the score behave this way? |
| `METRICS.md` | What does this term/metric mean? |
| `ROUTE-SELECTION-PLAN.md` | How is the in-flight B1/B2/B4 change designed? (retire on ship) |
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
