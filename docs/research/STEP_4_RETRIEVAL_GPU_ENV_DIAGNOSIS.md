# Step 4 — Retrieval GPU Environment Diagnosis

## Status

**MEASURED RESEARCH EVIDENCE — NOT A FINAL EMBEDDING OR ARCHITECTURE APPROVAL.**

Date: 2026-09-04
Machine: actual JARVIS Windows machine
GPU: NVIDIA GeForce RTX 5060 Ti (Blackwell, compute capability 12.0 per NVIDIA)
Research environment: `.step4-retrieval-venv`

## Observed Torch environment

The owner ran:

```text
torch= 2.14.0+cpu
torch_cuda= None
cuda_available= False
device= NONE
```

This confirms the first Qwen3-Embedding-0.6B retrieval run was a CPU-only PyTorch run. Its ~955 ms p50 / ~1.94 s p95 query-encoding latency must therefore **not** be interpreted as RTX 5060 Ti performance.

## Current upstream compatibility finding

NVIDIA lists GeForce RTX 5060 Ti as Blackwell compute capability 12.0.

Current PyTorch guidance says newer Blackwell GPUs should use CUDA 13.0+ wheels. PyTorch 2.14.0 reached general availability on 2026-09-02, and official CUDA builds are distributed through `download.pytorch.org`.

Before replacing the CPU wheel, verify the installed NVIDIA driver with `nvidia-smi`. Current PyTorch guidance for CUDA 13.x / Blackwell requires a recent driver; PyTorch's 2.12 release guidance states Windows driver 580.88 or newer for CUDA 13.0+ Blackwell use.

Research sources:

- https://developer.nvidia.com/cuda/gpus
- https://pytorch.org/get-started/locally/
- https://dev-discuss.pytorch.org/t/pytorch-2-14-0-general-availability/3431
- https://pytorch.org/blog/pytorch-2-12-release-blog/

## Next research action

1. Run `nvidia-smi` and record the driver version.
2. If the driver is compatible, replace only the research venv's CPU Torch wheel with the official PyTorch 2.14.0 CUDA 13.0 wheel.
3. Verify `torch.cuda.is_available()` and confirm the detected device is the RTX 5060 Ti.
4. Rerun the exact Qwen retrieval bake-off with `--device cuda`.
5. Compare retrieval quality, warm model load, query latency, and peak CUDA memory against the CPU-only run.

Production JARVIS dependencies remain unchanged.
