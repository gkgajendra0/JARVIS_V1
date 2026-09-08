# Step 4 — Retrieval CUDA Environment Validation

## Status

**MEASURED RESEARCH EVIDENCE — ENVIRONMENT VALIDATION ONLY.**

Date: 2026-09-04
Machine: actual JARVIS Windows machine
GPU: NVIDIA GeForce RTX 5060 Ti, 8151 MiB reported VRAM
NVIDIA driver: 596.49
NVIDIA-SMI reported CUDA capability/runtime compatibility: 13.2

## Initial research environment

The first Qwen3-Embedding-0.6B retrieval run used a CPU-only PyTorch wheel:

```text
torch = 2.14.0+cpu
torch_cuda = None
cuda_available = False
device = NONE
```

Therefore the first measured query latency (~955 ms p50, ~1.94 s p95) was a CPU-only result and must not be used to judge GPU suitability.

## CUDA research environment correction

Only the isolated `.step4-retrieval-venv` research environment was modified. Production JARVIS dependencies were not changed.

The CPU-only wheel was removed and the official PyTorch CUDA 13.0 wheel was installed from the PyTorch wheel index:

```text
torch = 2.14.0+cu130
torch.version.cuda = 13.0
torch.cuda.is_available() = True
device = NVIDIA GeForce RTX 5060 Ti
```

The installed NVIDIA driver (596.49) is newer than the minimum required by the CUDA 13.x/Blackwell guidance researched for this spike, and the driver reports CUDA 13.2 compatibility.

## Decision consequence

The research environment is now valid for a GPU rerun of the exact same Qwen retrieval bake-off. No model-quality conclusion changes from the CPU run; only the performance/resource measurement must be repeated on CUDA.

Next evidence required:

1. rerun Qwen3-Embedding-0.6B with `--device cuda`;
2. record warm model-load time, corpus encode time, query p50/p95, and peak CUDA allocation;
3. run BGE-M3 under the same CUDA environment;
4. compare quality, latency, VRAM, and model footprint before selecting an embedding model.
