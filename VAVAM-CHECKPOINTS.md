# VaViM / VaVAM checkpoints — valeoai/VideoActionModel v1.0.0

Source (authoritative): https://github.com/valeoai/VideoActionModel/releases/tag/v1.0.0
Model table: https://github.com/valeoai/VideoActionModel/blob/main/MODELS.md
Paper: arXiv 2502.15672 · License: research-only RAIL. Sizes from the GitHub API, 2026-08-29.

Naming: `width_768` = S · `width_1024` = B · `width_2048` = L.
`VAM_*` = **VaVAM** (video + action, drives). Plain `width_*` = **VaViM** (video-only world model, no action head).
`pretrained_<N>k` = video pretraining steps · `_total_<M>k` = additionally fine-tuned (nuPlan+nuScenes high-quality).

## ⭐ What the AlpaSim sample submission needs (2 files, 1.87 GB)
| File | Size | URL |
|---|---|---|
| VaVAM-B, 139k | 1.75 GB | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VAM_width_1024_pretrained_139k.pt |
| VQ tokenizer **encoder** (LlamaGen ds16, 16384 codes) | 0.12 GB | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VQ_ds16_16384_llamagen_encoder.jit |

Optional: VQ **decoder** (only to visualise generated video, not needed to drive): https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VQ_ds16_16384_llamagen_decoder.jit (0.17 GB)

## VaVAM (video-action) — all variants
| Model | Params (video + action) | Steps | Size | URL |
|---|---|---|---|---|
| VaVAM-S | 185M + 21M | 38k | 1.01 GB | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VAM_width_768_pretrained_38k.pt |
| VaVAM-S | | 77k | 1.01 GB | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VAM_width_768_pretrained_77k.pt |
| VaVAM-S | | 116k | 1.01 GB | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VAM_width_768_pretrained_116k.pt |
| VaVAM-S | | 139k | 1.01 GB | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VAM_width_768_pretrained_139k.pt |
| VaVAM-B | 318M + 38M | 38k | 1.75 GB | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VAM_width_1024_pretrained_38k.pt |
| VaVAM-B | | 77k | 1.75 GB | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VAM_width_1024_pretrained_77k.pt |
| VaVAM-B | | 116k | 1.75 GB | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VAM_width_1024_pretrained_116k.pt |
| **VaVAM-B** | | **139k** | 1.75 GB | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VAM_width_1024_pretrained_139k.pt |
| VaVAM-L | 1.2B + 150M | 139k | 6.3 GB (4 parts) | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VAM_width_2048_pretrained_139k_chunked.tar.gz.part_aa · part_ab · part_ac · part_ad |

Reassemble L: `cat VAM_width_2048_pretrained_139k_chunked.tar.gz.part_* > x.tar.gz && tar -xzf x.tar.gz`

## VaViM (video-only world model) — all variants
| Model | Params | Steps | Pre-trained | Fine-tuned (+nuPlan/nuScenes) |
|---|---|---|---|---|
| VaViM-S | 185M | 38k | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_768_pretrained_38k.pt | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_768_pretrained_38k_total_54k.pt |
| VaViM-S | | 77k | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_768_pretrained_77k.pt | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_768_pretrained_77k_total_93k.pt |
| VaViM-S | | 116k | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_768_pretrained_116k.pt | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_768_pretrained_116k_total_132k.pt |
| VaViM-S | | 139k | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_768_pretrained_139k.pt | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_768_pretrained_139k_total_155k.pt |
| VaViM-B | 318M | 38k | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_1024_pretrained_38k.pt | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_1024_pretrained_38k_total_54k.pt |
| VaViM-B | | 77k | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_1024_pretrained_77k.pt | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_1024_pretrained_77k_total_93k.pt |
| VaViM-B | | 116k | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_1024_pretrained_116k.pt | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_1024_pretrained_116k_total_132k.pt |
| VaViM-B | | 139k | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_1024_pretrained_139k.pt | https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/width_1024_pretrained_139k_total_155k.pt |
| VaViM-L | 1.2B | 139k | `width_2048_pretrained_139k_chunked.tar.gz.part_{aa,ab,ac}` (4.6 GB) | `width_2048_pretrained_139k_total_155k_chunked.tar.gz.part_{aa,ab,ac}` (4.6 GB) |

S/B single files: 0.73 GB (S) · 1.28 GB (B).

## Also in the release
- `nuscenes_vavam.tar.gz` (0.25 GB), `opendv_vavam.tar.gz` — dataset-specific VaVAM artefacts/splits.

## Download the two sample-submission files
```bash
mkdir -p ~/alpasim-challenge/vavam-weights && cd ~/alpasim-challenge/vavam-weights
curl -LO https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VAM_width_1024_pretrained_139k.pt
curl -LO https://github.com/valeoai/VideoActionModel/releases/download/v1.0.0/VQ_ds16_16384_llamagen_encoder.jit
bash ~/alpasim-challenge/alpasim/e2e_challenge/sample_submission_vavam/scripts/prepare_assets.sh ~/alpasim-challenge/vavam-weights
```
