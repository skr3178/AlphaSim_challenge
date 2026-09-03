# sample_submission_wajepa — WA-JEPA driver (local addition, team lucifer)

Not an upstream sample. AlpaSim driver for AFARI-Research/WA-JEPA
(arXiv 2608.20974, Apache-2.0): V-JEPA 2.1 ViT-L + joint flow predictor,
4 cameras (CAM_L0/F0/R0/B0) x 4 history frames @ 2 Hz -> 8 waypoints @ 2 Hz.

- `wajepa_challenge/` — driver (structure follows the GTRS sample: cached 4 s
  plan at 10 Hz, inference only on new synchronized camera sets = 2 Hz).
- `wajepa_src/` — vendored upstream inference code (models/, third_party/vjepa2,
  minimal utils/training), commit in `UPSTREAM_COMMIT`, license in `LICENSE`.
- `assets/wajepa/` — checkpoint (1.58 GB, not in git; run
  `scripts/prepare_assets.sh`) + inference config.
  sha256 model_state_dict.pt = e1d3be013de7dbaa5a6c30925a0d2f91e6ce1a6b17a75ca73fe01a1abe6d6408

Build (local, Blackwell): from the repo root
  docker build -f e2e_challenge/sample_submission_wajepa/Dockerfile.local -t alpasim-e2e-wajepa-driver:local .
Run local eval: needs the 4-camera preset
  run-eval.sh alpasim-e2e-wajepa-driver:local NAME GROUP dev_fast2_wajepa

Env knobs: WAJEPA_STEPS (flow sampling steps; empty = config default 12;
paper: 5 recovers most quality in the SimWAM analog, WA-JEPA untested below 12),
WAJEPA_MAX_BATCH_SIZE (2), WAJEPA_BATCH_WINDOW_MS (2), WAJEPA_DEVICE.
Measured on RTX PRO 4000: 974 ms/inference @ 12 steps, 364 @ 4, 215 @ 2, 140 @ 1
(2 Hz cadence -> per-Drive-call cost is 1/5 of that on average).
