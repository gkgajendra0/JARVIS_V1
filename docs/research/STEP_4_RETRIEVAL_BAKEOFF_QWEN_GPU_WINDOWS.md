# Step 4 — Qwen GPU Retrieval Bake-off on JARVIS Windows Machine

## Status

**MEASURED RESEARCH EVIDENCE — NOT A FINAL EMBEDDING OR ARCHITECTURE APPROVAL.**

Date: 2026-09-04
Machine: actual JARVIS Windows machine
GPU: NVIDIA GeForce RTX 5060 Ti (8 GB)
Driver: 596.49
CUDA reported by driver: 13.2
PyTorch: 2.14.0+cu130
Model: `Qwen/Qwen3-Embedding-0.6B`
Harness: `tools/research/step4_memory_retrieval_bakeoff.py`
Corpus: 14 research memories
Queries: 20 total, 17 positive + 3 absent-answer cases

## Result summary

The GPU run completed with `status = PASS` and `device = cuda:0`.

### Retrieval quality

Quality was effectively identical to the prior CPU run, as expected:

| Method | Recall@1 | Recall@3 | MRR |
|---|---:|---:|---:|
| SQLite FTS5 | 0.6471 | 0.7647 | 0.7275 |
| Qwen3-Embedding-0.6B | 0.7647 | 1.0000 | 0.8824 |

This confirms the semantic-retrieval gain is not an artifact of the CPU run.

### GPU performance

Measured values:

- model load: **9.5494 s**
- corpus encoding: **0.6483 s**
- query encode p50: **61.0165 ms**
- query encode p95: **64.8851 ms**
- maximum measured query encode latency: **64.8851 ms**
- PyTorch peak CUDA allocation: **1,292,429,824 bytes (~1.20 GiB / 1.29 GB)**
- embedding dimension: **1024**
- parameters: **595,776,512**

Compared with the prior CPU run (~955 ms p50 / ~1,942 ms p95), the CUDA path reduces normal single-query embedding latency by roughly an order of magnitude and makes Qwen a viable candidate for further runtime evaluation.

### Important interpretation

Qwen is now fast enough to remain a serious Step-4 semantic-retrieval candidate, but this does not mean every conversational turn should pay ~61–65 ms for embedding.

Current research direction remains a bounded hybrid path:

1. deterministic structured/temporal lookup first where the query can be resolved directly;
2. FTS5 as the cheap lexical path;
3. semantic retrieval as a fallback or parallel candidate source when paraphrase/weak lexical overlap makes it useful;
4. deterministic temporal, source-authority, sensitivity and lifecycle filters remain mandatory after retrieval;
5. nearest-vector rank is never treated as canonical truth.

### Remaining rank-1 misses

The GPU run retained the same important Qwen rank-1 misses as the CPU run:

- Hinglish bike query: `jimny` ranked above `bike`;
- Hinglish research-rule query: `echo_incident` ranked above `research_rule`;
- Hinglish memory-database query: `provider_boundary` ranked above `memory_store`;
- memory-poisoning query: `provider_boundary` ranked above `memory_security`.

Recall@3 remained 1.0, reinforcing the candidate-retrieval + reranking/filtering design.

### Absent-answer evidence

The three absent-answer probes still produced nearest neighbours with top scores around 0.260–0.327. No similarity threshold is approved. A larger calibration corpus is required before any abstention threshold is selected.

## Current Qwen disposition

**KEEP QWEN3-EMBEDDING-0.6B AS A LEADING SEMANTIC-RETRIEVAL CANDIDATE. DO NOT APPROVE IT YET.**

Reasons to keep:

- material multilingual/paraphrase retrieval improvement over FTS5;
- Recall@3 = 1.0 on the first research corpus;
- GPU query encoding around 61–65 ms on the actual JARVIS RTX 5060 Ti;
- ~1.3 GB measured PyTorch CUDA allocation is feasible on the 8 GB GPU if scheduling/resource contention is managed;
- Qwen supports multilingual retrieval, long context, instruction-aware queries and Matryoshka output dimensions.

Remaining requirements before selection:

- run BGE-M3 under the same hardware/harness;
- compare retrieval quality, p50/p95 latency, model load, VRAM and footprint;
- evaluate whether Qwen task instructions improve JARVIS-specific retrieval;
- later evaluate reduced Qwen output dimensions only if Qwen remains selected, because dimension reduction can reduce stored-vector/search cost without proving the full 1024-dimension vector is necessary;
- expand the corpus before calibrating abstention thresholds.

No vector database is justified by this result alone.
