# Step 4 — Phase 4.5 CUDA Research Environment Fix

Date: 2026-09-05

## Status

**CUDA ENVIRONMENT FIXED. QWEN MEASURED. EMBEDDINGGEMMA ACCESS PENDING.**

## Initial owner-PC observation

The isolated `.step4-retrieval-venv` initially installed `torch 2.14.0+cpu` through the generic PyPI dependency path. The first GPU probe therefore reported:

```text
CUDA: False
GPU: NONE
Torch: 2.14.0+cpu
```

The Phase-4.5 research harness correctly failed closed because `--device cuda` was requested while `torch.cuda.is_available()` was false. No model was executed during that first attempt.

## Research-first diagnosis

Official PyTorch package listings provide a stable Windows x86-64 CPython 3.11 CUDA 13.0 wheel for PyTorch 2.14.0:

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

A CI contract test protects the CUDA research-environment pin.

## Owner-PC CUDA acceptance

The corrected research environment was measured on:

```text
GPU: NVIDIA GeForce RTX 5060 Ti
NVIDIA driver: 596.49
Torch: 2.14.0+cu130
Torch CUDA runtime: 13.0
CUDA available: True
```

Therefore the original CPU-wheel blocker is closed.

A PowerShell/Python quoting error occurred in an auxiliary verification snippet (`python -c` with a PowerShell here-string). This did not represent a CUDA failure. The actual Phase-4.5 harness subsequently reported `cuda_available=True`, CUDA 13.0, and the RTX 5060 Ti while successfully executing Qwen on CUDA. Future owner commands should avoid that quoting form and use a normal quoted `python -c` expression or pipe a here-string to Python stdin.

## First valid retrieval evidence

The fixed harness produced a valid Qwen result on CUDA:

```text
model: Qwen/Qwen3-Embedding-0.6B
benchmark dimension: 256

dense:
  Recall@1: 0.8824
  Recall@3: 1.0000
  MRR:      0.9412

FTS5 + Qwen RRF hybrid:
  Recall@1: 0.9412
  Recall@3: 1.0000
  MRR:      0.9608

latency:
  dense query p50:       62.4852 ms
  dense query p95:       68.0436 ms
  hybrid end-to-end p50: 63.2179 ms
  hybrid end-to-end p95: 68.7911 ms

memory:
  peak CUDA allocated: 1,292,429,824 bytes
  peak RSS delta:       1,397,387,264 bytes
```

This is valid model evidence and must not be rerun merely because the challenger failed to load.

## EmbeddingGemma blocker

`google/embeddinggemma-300m` returned `GatedRepoError` / HTTP 401 before model execution. The Hugging Face model repository requires the individual user to review and accept Google's Gemma usage license and then authenticate the local Hugging Face client.

This is an access-control blocker, not model-quality evidence.

## Next measured step

1. the owner accepts EmbeddingGemma's usage terms in the Hugging Face browser UI;
2. authenticate the existing `.step4-retrieval-venv` with `hf auth login`;
3. run **only** the missing `embeddinggemma` profile into a separate JSON result;
4. preserve the already-valid Qwen JSON unchanged;
5. compare case-level quality, multilingual performance, latency, RSS, and CUDA memory before selecting the production embedding model.

Do not rerun Qwen unless the fixed corpus, benchmark contract, or machine environment materially changes.
