# Submission image (cu124, matches the sample submissions base).
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    XDG_CACHE_HOME=/tmp/.cache \
    TORCH_HOME=/tmp/torch \
    HF_HOME=/tmp/huggingface \
    MPLCONFIGDIR=/tmp/matplotlib \
    CUDA_CACHE_PATH=/tmp/nv \
    NUMBA_CACHE_DIR=/tmp/numba \
    ALPASIM_DRIVER_LOG_DIR=/run/alpasim-driver \
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
    TOKENIZERS_PARALLELISM=false TORCH_NUM_THREADS=1 TORCH_NUM_INTEROP_THREADS=1 \
    ALPASIM_DRIVER_HOST=0.0.0.0 ALPASIM_DRIVER_PORT=6789 ALPASIM_DRIVER_GRPC_WORKERS=4 \
    WAJEPA_CONFIG=/app/assets/wajepa/wa_jepa_infer.yaml \
    WAJEPA_CKPT=/app/assets/wajepa/model_state_dict.pt \
    WAJEPA_SOURCE_ROOT=/app/wajepa_src \
    WAJEPA_STEPS=2

WORKDIR /app
COPY src/grpc /tmp/alpasim_grpc
RUN pip install /tmp/alpasim_grpc && rm -rf /tmp/alpasim_grpc
COPY e2e_challenge/sample_submission_wajepa/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm -f /tmp/requirements.txt
COPY e2e_challenge/sample_submission_wajepa/wajepa_src /app/wajepa_src
COPY e2e_challenge/sample_submission_wajepa/assets/wajepa /app/assets/wajepa
COPY e2e_challenge/sample_submission_wajepa/wajepa_challenge /app/wajepa_challenge
EXPOSE 6789
STOPSIGNAL SIGTERM
CMD ["python", "-m", "wajepa_challenge.driver"]
