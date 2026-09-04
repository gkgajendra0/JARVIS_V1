# Step 4 — Qwen Reranker Bake-off on JARVIS Windows Machine

## Status

**MEASURED RESEARCH EVIDENCE — NOT FINAL PRODUCTION APPROVAL.**

Date: 2026-09-04  
Machine: actual JARVIS Windows machine  
GPU: NVIDIA GeForce RTX 5060 Ti 8 GB  
First stage: SQLite FTS5 + Qwen3-Embedding-0.6B, JARVIS memory prompt, 256-d, equal RRF k=60  
Second stage: Qwen3-Reranker-0.6B via Sentence Transformers CrossEncoder

## Measured result

First-stage equal-RRF retrieval remained:

- Recall@1: 0.9412
- Recall@3: 1.0000
- MRR: 0.9608
- p50: 61.8951 ms
- p95: 69.7420 ms

### Rerank top 3

- candidate recall: 1.0000
- Recall@1: 1.0000
- Recall@3: 1.0000
- MRR: 1.0000
- rerank p50: 68.7779 ms
- rerank p95: 80.2188 ms
- end-to-end p50: 130.8817 ms
- end-to-end p95: 149.9608 ms

### Rerank top 5

- candidate recall: 1.0000
- Recall@1: 0.9412
- Recall@3: 1.0000
- MRR: 0.9706
- rerank p50: 70.3791 ms
- rerank p95: 79.7002 ms
- end-to-end p50: 132.0173 ms
- end-to-end p95: 141.6515 ms

Top-5 reranking regressed `bike_hi_mix`: `current_tyre` scored -5.125 while `bike` scored -5.1875.

Combined peak CUDA allocation with embedder + reranker loaded: 2,523,767,296 bytes (~2.35 GiB).

The first reranker load took 268.3333 s because it included the first model download/cache path; this is not a warm-start production load measurement.

## Important precision/tie finding

The apparent 100% top-3 Recall@1 must **not** yet be treated as robust perfection.

Two top-3 cases had exact reported score ties:

- `bike_hi_mix`: `bike` = -5.1875 and `current_tyre` = -5.1875
- `memory_db_mix`: `memory_store` = 5.625 and `provider_boundary` = 5.625

The expected candidate happened to remain first because it was earlier in the first-stage candidate ordering. The harness currently uses `np.argsort(-scores)` and does not explicitly define a semantic tie policy.

A second stability signal is that `current_tyre` changed from -5.1875 in the top-3 batch to -5.125 in the top-5 batch for `bike_hi_mix`, despite the query/document pair being the same.

The Qwen3-Reranker-0.6B model config declares `torch_dtype = bfloat16`. The observed score quantization is consistent with reduced-precision inference being a plausible contributor. This is a hypothesis to test, not yet a conclusion.

## Current disposition

1. Qwen3-Reranker-0.6B is a **strong candidate** because top-3 reranking corrected every first-stage ordering error on the measured corpus.
2. Prefer reranking only a very small candidate set; top 3 was both better and slightly cheaper than top 5 on this corpus.
3. Do not claim 100% robust accuracy until BF16-vs-FP32 score stability/tie behavior is measured.
4. Do not invent more RRF weights or custom relevance heuristics. The remaining question is numerical/stability behavior of the mature reranker component.
5. Abstention is still unresolved: the three absent queries produced strongly negative reranker top scores (-9.5625 to -6.5 for top-3), which is promising, but three negatives are far too few to choose a production threshold.

## Next research gate

Run a precision/stability bake-off comparing the model default BF16 path against explicit FP32 on the same top-3 candidates, including candidate-order perturbation, repeated scoring, latency, VRAM, exact ties and final ranking stability.
