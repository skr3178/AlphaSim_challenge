# Selected pretrained GTRS-Dense checkpoint

- Variant: OpenDriveLab/SimScale GTRS-Dense, ResNet34, reward, NAVHARD.
- File: `gtrs_dense_resnet_sim_reward_navhard.ckpt`.
- Source: https://huggingface.co/datasets/OpenDriveLab/SimScale/resolve/main/SimScale_ckpts/GTRS_Dense/gtrs_dense_resnet_sim_reward_navhard.ckpt
- Verified size: 269,095,388 bytes.
- Verified SHA-256: `8dad0395332ccd844785cbfc7c9e24cb3f8d8dbf5cb9ca7f8f8dc75478fcf409`.
- Expected identity comes from the local challenge sample's `scripts/prepare_assets.sh`.

Download and integrity verification complete. No inference, training, evaluation,
container build or submission was run as part of this download. This is not the
original VoV GTRS checkpoint or the complete competition-winning ensemble.

## Authorized local smoke evaluation — 2026-09-21

Checkpoint staged using the supplied asset-preparation script. The supplied
trajectory vocabulary was a Git LFS pointer, so the actual `navsim_16384.npy`
was downloaded from
https://media.githubusercontent.com/media/NVlabs/alpasim/e2e_challenge/e2e_challenge/sample_submission_simscale_navsim_gtrs_dense/assets/gtrs_dense/navsim_16384.npy
and verified: 7,864,448 bytes, SHA-256
`e8c29cfc25add59ae8b64769a4554c6518878726178c0bd889fc8518ebe1261d`.

Results: [validated artifact](artifacts/20260921T091436Z/validation.json).

| Check | Result |
| --- | --- |
| Supplied protocol probe | Passed, two concurrent sessions |
| Closed-loop scenes | One development scene |
| Neural calls | 10/10, finite 41-pose trajectories |
| Inference errors / straight fallbacks / cached plans / dynamic-state fallbacks | 0 / 0 / 0 / 0 |
| Local scene score | 0, lateral corridor exit |
| Distance to reference trajectory | 4.4474 m |
| Relative progress (`progress_rel`) | 60.99% |
| Clipped relative progress (`progress_clipped_rel`) | 42.82% |
| Collision / offroad | Neither reported |

Requested maximum 20 steps; runtime clipped to 10 because of available scene
duration. All ten calls and controller returns were recorded. No ground-truth
service requests were recorded. Scoring failure is distinct from service failure.

This used the unchanged supplied policy and default progress-enhanced scorer
(`nc_dac_ep`, exponent 3, speed top-k 64, speed weight 3), running as a host GPU
process with the existing local Docker simulator. It is not a hardened submission
container test, official-scorer parity claim, throughput certification, or a
representative performance benchmark. No full-400 run or submission was made.
The first failed probe (LFS pointer) remains in `artifacts/20260921T091347Z`.

Next: inspect route conditioning, selected trajectories and controller tracking
on this failure before a larger, paired diagnostic evaluation. No cause has yet
been established from the score alone.
