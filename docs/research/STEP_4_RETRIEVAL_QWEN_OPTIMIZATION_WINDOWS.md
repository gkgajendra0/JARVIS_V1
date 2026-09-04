# Step 4 — Optimized Qwen Retrieval Result on JARVIS Windows

## Status

**MEASURED RESEARCH EVIDENCE — EMBEDDING MODEL DIRECTION SELECTED, FINAL RETRIEVAL STACK STILL AWAITS HYBRID-FUSION CHECK.**

Date: 2026-09-04
Machine: actual JARVIS Windows machine
GPU: NVIDIA GeForce RTX 5060 Ti 8 GB
Model: `Qwen/Qwen3-Embedding-0.6B`
Harness: `tools/research/step4_qwen_memory_optimization_bakeoff.py`
Corpus: 14 research memories
Queries: 20 total, 17 positive + 3 absent-answer cases

## Why this spike existed

The initial Qwen run used the model's generic built-in retrieval prompt and 1024-dimensional output. Qwen3-Embedding is instruction-aware and supports Matryoshka output dimensions from 32 through 1024, so the research question was whether a JARVIS-specific retrieval instruction and a smaller output vector would improve quality or efficiency without changing models.

JARVIS-specific query instruction tested:

```text
Instruct: Given a JARVIS memory retrieval query, retrieve the most relevant trustworthy personal, episodic, project, or self-knowledge memory needed to answer the query
Query:
```

## Results

| Configuration | Recall@1 | Recall@3 | MRR | GPU query p50 | GPU query p95 |
|---|---:|---:|---:|---:|---:|
| Qwen default 1024 | 0.7647 | 1.0000 | 0.8824 | 61.86 ms | 75.27 ms |
| Qwen default 512 | 0.8235 | 1.0000 | 0.9020 | 61.72 ms | 70.06 ms |
| Qwen default 256 | 0.7647 | 1.0000 | 0.8824 | 60.59 ms | 63.73 ms |
| Qwen JARVIS 1024 | 0.8824 | 1.0000 | 0.9314 | 62.58 ms | 70.68 ms |
| Qwen JARVIS 512 | 0.8824 | 1.0000 | 0.9314 | 61.30 ms | 64.78 ms |
| **Qwen JARVIS 256** | **0.8824** | **1.0000** | **0.9412** | **63.08 ms** | **67.49 ms** |

Peak CUDA allocation remained about **1.292 GB** because Matryoshka truncation reduces output-vector size, not the neural-network model itself.

## Comparison with BGE-M3 on the same machine and corpus

| Measure | Qwen JARVIS 256 | BGE-M3 dense |
|---|---:|---:|
| Recall@1 | **0.8824** | **0.8824** |
| Recall@3 | **1.0000** | 0.9412 |
| MRR | **0.9412** | 0.9265 |
| Query p50 | 63.08 ms | **23.38 ms** |
| Query p95 | 67.49 ms | **31.70 ms** |
| Peak CUDA allocation | **~1.29 GB** | ~2.33 GB |
| Dense vector dimension | **256** | 1024 |

## Interpretation

The tailored JARVIS instruction changed the Qwen result materially:

- Recall@1 rose from 0.7647 to 0.8824.
- Recall@3 remained perfect at 1.0000.
- MRR rose from 0.8824 to 0.9412.
- The 256-dimensional configuration produced the best MRR of the tested Qwen variants.
- It matched BGE-M3 at rank 1, exceeded BGE-M3 at top-3 recall and MRR, and used roughly 1.0 GB less peak CUDA allocation.
- BGE-M3 remains substantially faster per query and is retained as a strong fallback/benchmark candidate.

The 256-dimensional output does **not** make Qwen inference materially faster or reduce model VRAM. Its value is downstream: four times fewer float components than 1024-dimensional vectors, therefore lower persistent vector storage, lower memory bandwidth and lower similarity-search/index cost.

## Remaining Qwen misses

The optimized Qwen JARVIS-256 configuration missed only two positive cases at rank 1:

1. the Hinglish memory-database query ranked `provider_boundary` above `memory_store`;
2. the webpage/memory-poisoning query ranked `provider_boundary` above `memory_security`.

In both cases the correct result was still in Qwen's top 3. Importantly, SQLite FTS5 ranked the correct memory first for these cases. This is evidence that the two retrieval methods are complementary rather than evidence for replacing one with the other.

## Absent-answer caution

On the three absent-answer cases, Qwen JARVIS-256 still returned nearest neighbours with top similarity scores from roughly 0.291 to 0.421. The minimum expected-memory score in the positive cases was roughly 0.484, leaving a gap in this tiny corpus, but **no production threshold is approved from only three negatives**. Threshold/abstention calibration belongs in the larger acceptance corpus.

## Embedding-model disposition

**SELECT `Qwen/Qwen3-Embedding-0.6B` WITH THE JARVIS-SPECIFIC ENGLISH QUERY INSTRUCTION AND 256-DIMENSION MATRYOSHKA OUTPUT AS THE LEADING STEP-4 SEMANTIC-RETRIEVAL MODEL.**

BGE-M3 is retained as the fallback/reference model because it is faster but costs materially more VRAM and did not match Qwen's top-3 reliability in this JARVIS-specific bake-off.

This selection does not approve unconditional semantic lookup on every turn, does not select a vector database, and does not make similarity rank authoritative truth.

## Next retrieval-stack check

Run lexical FTS5 and optimized Qwen in parallel and fuse the ranked candidate lists using standard Reciprocal Rank Fusion (RRF). This is a mature hybrid-retrieval pattern used to combine lexical and vector systems without pretending their raw relevance scores are directly comparable.

If the hybrid check preserves semantic-paraphrase wins while correcting the two remaining rank-1 misses, Step-4 retrieval research can close with:

```text
structured / temporal / authority filtering
        -> SQLite FTS5 lexical retrieval
        +  Qwen3-Embedding-0.6B semantic retrieval (JARVIS instruction, 256d)
        -> RRF candidate fusion
        -> later abstention / policy / context assembly
```

No vector database is justified by the current corpus. Exact cosine similarity is sufficient for model-quality research; physical vector-index technology should be revisited only when measured corpus size or latency requires it.
