# Pinned upstream pose decoder

`pose_utils.py` is an unmodified copy from NVIDIA/cosmos-framework commit
`cc96ae8a34a6925efa523671a4c6220678b1fbe1`, downloaded 2026-09-18.

Source: https://github.com/NVIDIA/cosmos-framework/blob/cc96ae8a34a6925efa523671a4c6220678b1fbe1/cosmos_framework/data/generator/action/utils/pose_utils.py

Its original copyright and OpenMDW-1.1 SPDX license header are retained.
Only `pose_rel_to_abs(..., rotation_format="rot6d",
pose_convention="backward_framewise", translation_scale=1.35)` is used.
The 1.35 AV scale and camera-frame interpretation follow NVIDIA's
[AV notebook](https://github.com/NVIDIA/cosmos/blob/b0e54e88c322695dab188e6ed160c4d6d071c39d/cookbooks/cosmos3/generator/action/run_id_with_diffusers.ipynb).
No robotics quantile normalizer is applied to the AV branch.
