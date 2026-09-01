# Superseded — see [SETUP-NOTES.md](SETUP-NOTES.md)

This file was created in error during an assistant session on 2026-08-29, before
`SETUP-NOTES.md` was discovered. Everything it contained has been merged there, which is
the canonical record — it is more complete (challenge constraints, dates, track decision,
container topology) and better sourced.

Two claims that briefly lived here were **wrong** and are corrected in `SETUP-NOTES.md`:

- *"`uv sync` never completed."* It did — at ~11:00, log at `~/alpasim-challenge/logs/sync.log`.
  The venv has torch 2.8.0+cu128 and a working wizard. What it is missing is `alpasim_mtgs`
  and `gsplat`, because the sync that ran was a bare `--extra all` (§3 Defect 2).
- *"Sync lean, the host doesn't need the plugin extras."* The host **does** need
  `--extra mtgs` for Hydra config discovery (§4.5). The setup script has been corrected.
