# Ten-observation full-checkpoint feature probe

Follow-up: the user subsequently confirmed local head-only scope and the
[ten-sample learning test](LOCAL-HEAD10-RESULT.md) completed 100 updates. That is
a separate experiment; the inference-only measurements below remain unchanged.

Completed 2026-09-19. **Inference only: zero optimizer steps, no trained weights,
no training feature cache, no simulator evaluation or submission.**

The user requested a small sample training test. While clarifying local-only
training scope and head-only versus backbone adaptation, the non-fitting
prerequisite was run on ten real, previously observed development images.
This result does **not** establish that Cosmos can be fine-tuned successfully.

## Measured result

| Check | Result |
| --- | --- |
| Successful feature calls | 10/10 |
| Feature shape per image | 32 spatial tokens × 2,048 channels |
| Finite outputs | 10/10 |
| Missing, unexpected or mismatched parameter keys | None for transformer or VAE |
| Trainable backbone/VAE parameters | 0 |
| Parameter versions unchanged; gradients absent | Passed |
| Local checkpoint load | 56.75 seconds |
| First feature call | 555 ms |
| Mean of subsequent nine calls | 41.28 ms |
| Mean including first call | 92.70 ms |
| Sampled peak process VRAM | 8.113 GiB |
| Total probe time, including load | 58.90 seconds |
| Optimizer steps | **0** |

Raw results, source/image hashes, actual loading diagnostics and feature recipe:
[results.json](artifacts/20260919T060507Z_features10_no_training/results.json).

The full 3,369,657,024-parameter generator transformer and 704,688,668-parameter
VAE were loaded from the existing local snapshot. The separate reasoner/vision
tower was not substituted. Model work used a fixed prompt and one causally
observed image per request, letterboxed to 256×448. No expert future trajectory
was supplied to the model.

Loading emitted warnings for ignored configuration attributes (`backbone_type`,
`temporal_compression_factor`, `clip_output`) and a dtype-argument deprecation.
Parameter loading diagnostics were clean. This is a tested prototype feature
path, not certification of every released configuration or a validated driving
representation.

The memory number is sampled process VRAM, not merely torch allocations; 185
samples were collected over the run. Timing includes preprocessing, tokenization,
VAE and transformer feature computation with CUDA synchronization, but excludes
ASL reading/JPEG decoding, which happened before the calls. It excludes a driving
head, multi-frame history, gRPC and concurrent sessions. Do not equate these
figures with complete driver latency or competition throughput.

## Data selection and non-fitting checks

The original eight development scenes were retained. Two additional scenes were
chosen deterministically, without model scores, from two distinct source logs
already represented by that pilot:

- Pittsburgh: `2021.09.16.15.47.30_veh-45_01199_01391-0481cf2b75f1532f`
- Singapore: `2021.10.06.07.26.10_veh-52_01245_02064-115d3d7bdadf52f8`

The ten observations therefore stay within the same four development source logs;
the protected validation/holdout lists were neither changed nor evaluated. They
are distinct scene examples, not duplicates used to pad an eight-sample batch.
The original eight-scene conditional training manifest remains unchanged. These
extra two observations have not been added to an authorized training manifest.

Read-only diagnostics found that all ten initial requests occur at 17,000 us,
inside the 500,000-us expert-controlled window. Observed/actual/reference poses
pass the alignment check and all forty future reference targets interpolate to
finite values. JPEG observations were decoded successfully for the probe. No
training dataset export was performed; full exporter validation still remains.

## Next step and limits

Clarify whether the requested learning test is:

1. **Frozen Cosmos plus waypoint-head fitting**, the agreed first adaptation
   stage. This can test finite loss/gradients and tiny-set overfitting, but does
   not test updating Cosmos backbone weights.
2. A separately implemented small backbone adapter, which would test actual
   backbone adaptation and needs additional backward-pass/resource validation.

Competition training-data eligibility remains unverified. A local-only fitted
test needs its scope recorded separately, without fabricating a competition
permission record or treating its checkpoint as a submission candidate. The
questions about that scope were sent to the user; no answer had arrived at the
time this probe completed. No conditional training gate was removed or bypassed.

Implementation: [probe_features10.py](probe_features10.py). Re-running it repeats
only the ten-image frozen feature probe, not training:

```bash
PYTHONPATH=/home/skr/alpasim-challenge/alpasim/src/grpc \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 timeout 660 \
  /media/skr/storage/cosmos3-edge-feasibility-20260918/venv/bin/python \
  -u -m cosmos3.probe_features10
```
