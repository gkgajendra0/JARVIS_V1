# Step 4 — Phase 4.5 CUDA Research Environment Fix

Date: 2026-09-05

## Status

**ROOT CAUSE IDENTIFIED. CUDA RETRIEVAL BAKE-OFF NOT YET RUN.**

## Owner-PC observation

The isolated `.step4-retrieval-venv` installed `torch 2.14.0+cpu` through the generic PyPI dependency path. The GPU probe therefore reported:

```text
CUDA: False
GPU: NONE
Torch: 2.14.0+cpu
```

The Phase-4.5 research harness then correctly failed closed because `--device cuda` was requested while `torch.cuda.is_available()` was false. No Qwen or EmbeddingGemma benchmark result was produced and no output JSON existed.

## Research-first diagnosis

Current official PyTorch package listings provide a stable Windows x86-64 CPython 3.11 CUDA 13.0 wheel for PyTorch 2.14.0:

- `torch-2.14.0+cu130-cp311-cp311-win_amd64.whl`

PyTorch installation guidance requires selecting a CUDA build for CUDA-capable systems rather than relying on the default no-CUDA package path.

NVIDIA documents CUDA 13.x minor-version compatibility with NVIDIA driver branch 580 or newer. PyTorch wheels carry their CUDA runtime dependencies; a separate local CUDA Toolkit installation is not required for ordinary wheel-based inference, but a compatible NVIDIA display/compute driver remains required.

References:

- https://pytorch.org/get-started/locally/
- https://download.pytorch.org/whl/cu130/torch/
- https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html

## Repository fix

Added:

- `tools/research/requirements-step4-retrieval-windows-cuda.txt`

The Windows owner-machine overlay pins:

```text
--extra-index-url https://download.pytorch.org/whl/cu130
-r requirements-step4-retrieval.txt
torch==2.14.0+cu130
```

This exact local-version pin prevents pip from silently satisfying the retrieval environment with the CPU-only `torch 2.14.0` wheel.

A CI contract test now protects the CUDA research-environment pin.

## Next measured step

1. inspect the installed NVIDIA driver with `nvidia-smi`;
2. require driver branch 580 or newer for the selected CUDA 13.0 wheel;
3. replace only the research venv's CPU torch build with `torch==2.14.0+cu130`;
4. prove `torch.cuda.is_available() == True` and the RTX GPU name is visible;
5. only then run the fixed Qwen-versus-EmbeddingGemma retrieval bake-off.

Do not interpret the failed CUDA guard as retrieval-model evidence. No model was executed.
