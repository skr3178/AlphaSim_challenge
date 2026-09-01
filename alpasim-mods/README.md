# alpasim-mods/ — our changes to NVlabs/alpasim (nuPlan track submission code)

Source of truth is the working clone `~/alpasim-challenge/alpasim` (branch `e2e_challenge`, base commit in `alpasim-mods/BASE_COMMIT`).
`tools/snapshot.sh` re-exports it here at every commit, so `git log -- alpasim-mods/` is the history of our driver code.

- `tree/` — every file we modified or added, at its path inside the clone (driver, policy, selection + tests, Dockerfiles, presets, scene lists, μP shape files)
- `tracked-changes.patch` — the diff of upstream-tracked files (driver.py, vavam_policy.py, controller pyproject casadi pin)
- `files.txt` — the list

Reproduce the working tree:
```bash
git clone -b e2e_challenge https://github.com/NVlabs/alpasim.git && cd alpasim && git checkout "$(cat ../alpasim-mods/BASE_COMMIT)"
git apply ../alpasim-mods/tracked-changes.patch && cp -r ../alpasim-mods/tree/. .
# then put the VaVAM weights in e2e_challenge/sample_submission_vavam/assets/vavam/ (see VAVAM-CHECKPOINTS.md)
```
Excluded on purpose: checkpoints (`assets/vavam*`, 1.8–6.5 GB), `runs/`, logs.
