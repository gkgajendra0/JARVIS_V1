# Step 4 — Retrieval Technology Decision

## Status

**RESEARCH TECHNOLOGY DECISION — NOT FINAL STEP-4 ARCHITECTURE APPROVAL AND NOT AUTHORIZATION TO IMPLEMENT PRODUCTION MEMORY.**

This document consolidates the measured retrieval research completed for Step 4 on the actual JARVIS Windows machine.

The purpose is to stop technology hopping and establish the leading retrieval stack before the remaining Step-4 research gates (structured extraction, encryption/package path, self-knowledge/SBOM, final architecture approval).

## Decision summary

Use a **tiered local retrieval stack**:

1. **Deterministic structured/temporal lookup first** for exact current facts, explicit keys, authority, status, sensitivity, valid-time and system-time constraints.
2. **SQLite FTS5** for cheap lexical/BM25 retrieval.
3. **Qwen3-Embedding-0.6B** for semantic retrieval when lexical overlap is insufficient.
   - JARVIS memory-specific query instruction.
   - 256-dimensional Matryoshka output.
4. **Equal-weight Reciprocal Rank Fusion (RRF)** to combine lexical and semantic candidate ranks.
   - rank constant `k=60` in the research harness;
   - lexical window `10` in the research harness.
5. **Qwen3-Reranker-0.6B** as a second-stage CrossEncoder over only the **top 3 fused candidates**.
   - keep model-default BF16 precision;
   - if reranker scores tie exactly, preserve first-stage fused rank, then stable memory ID.
6. Return only candidates that remain allowed by JARVIS source/authority/time/sensitivity policy. The retrieval models never decide canonical truth.

No dedicated vector database is approved at this stage. Add Qdrant/LanceDB/another vector engine only if a later scale benchmark demonstrates that exact/embedded local candidate search is no longer adequate.

## Why this stack was selected

### 1. SQLite + FTS5 is sufficient as the canonical/lexical foundation

On the real JARVIS Windows machine, the 30,000-record SQLite research harness passed:

- bitemporal/current-vs-history semantics;
- correction versus historical-change semantics;
- FTS5 secure-delete availability;
- explicit forget with zero canonical rows and zero FTS hits afterward.

Measured p95 latency was approximately:

- exact current-fact lookup: `0.0186 ms`;
- English FTS: `4.61 ms`;
- Hindi FTS: `4.70 ms`;
- Hinglish FTS: `3.90 ms`.

There is no measured reason to introduce a heavier canonical database.

### 2. Semantic retrieval is necessary

FTS5 alone missed low-overlap paraphrases such as:

- “Which device gives Jarvis eyes?” -> camera memory;
- “Meri bike kaunsi hai?” -> BMW motorcycle memory;
- Hindi/Hinglish research-rule paraphrases.

Therefore embeddings solve a measured problem rather than being added by convention.

### 3. Qwen3-Embedding-0.6B beat the alternative on the JARVIS trade-off

BGE-M3 was faster and initially stronger at rank 1, but Qwen offered better GPU economy and top-3 coverage. After applying the model-supported JARVIS-specific instruction and Matryoshka truncation, Qwen became the better overall JARVIS fit.

Best Qwen configuration measured:

- model: `Qwen/Qwen3-Embedding-0.6B`;
- instruction: `Given a JARVIS memory retrieval query, retrieve the most relevant trustworthy personal, episodic, project, or self-knowledge memory needed to answer the query`;
- dimension: `256`;
- Recall@1: `0.8824`;
- Recall@3: `1.0000`;
- MRR: `0.9412`;
- query encode p50: about `63 ms`;
- peak CUDA allocation: about `1.29 GB` (decimal, research measurement).

BGE-M3 measured:

- Recall@1: `0.8824`;
- Recall@3: `0.9412`;
- MRR: `0.9265`;
- query encode p50: about `23 ms`;
- peak CUDA allocation: about `2.33 GB` (decimal, research measurement).

For an 8 GB RTX 5060 Ti that must share GPU capacity with vision and identity workloads, Qwen’s roughly 1 GB lower GPU allocation and 100% top-3 positive recall outweighed BGE’s faster standalone embedding latency.

### 4. RRF improved first-stage ordering without score-scale tuning

Equal-weight RRF over FTS5 + Qwen-256 improved the first stage to:

- Recall@1: `0.9412`;
- Recall@3: `1.0000`;
- MRR: `0.9608`;
- hybrid end-to-end p50: about `61.6 ms`;
- p95: about `67.0 ms`.

A weighted-RRF sweep from semantic weights `1.0` to `2.0` demonstrated that no single global static weight safely removed all ranking disagreements:

- weights `1.0–1.75` retained the Hinglish research-rule miss;
- weight `2.0` fixed that case but lost the lexical rescues for the memory-database and poisoning queries.

Therefore JARVIS should not overfit a static fusion weight to this small corpus.

### 5. A dedicated reranker solved the ordering problem

`Qwen/Qwen3-Reranker-0.6B` over the top 3 RRF candidates measured:

- candidate recall: `1.0000`;
- Recall@1: `1.0000`;
- Recall@3: `1.0000`;
- MRR: `1.0000`;
- rerank p50: about `68.8 ms` in the initial top-3 harness;
- end-to-end p50: about `130.9 ms`;
- end-to-end p95: about `150.0 ms`;
- combined embedder + reranker peak CUDA allocation: roughly `2.35 GiB` in the initial rerank harness.

Top-5 reranking was worse (Recall@1 `0.9412`) and adds no benefit while top-3 candidate recall is already 100% on the fixed corpus. The selected candidate window is therefore **3**, not 5.

### 6. BF16 is the selected reranker precision

The precision stability bake-off compared default BF16 with forced FP32 using repeated and reversed candidate order.

Both achieved:

- Recall@1: `1.0000`;
- Recall@3: `1.0000`;
- MRR: `1.0000`;
- zero repeat/order unstable cases.

BF16 had two exact top-score ties, while FP32 removed them. However:

- BF16 rankings were fully deterministic;
- FP32 increased measured peak CUDA allocation from about `2.31 GiB` to `3.48 GiB`, about `1.17 GiB` more;
- Qwen’s model config declares BF16 as its native/default dtype.

Decision: **keep BF16**, and use the first-stage RRF rank as the explicit deterministic tie-break for exact reranker-score ties.

## Selected retrieval pipeline

```text
query / context need
        |
        v
structured + authority + time + sensitivity filters
        |
        +---- exact deterministic lookup when possible
        |
        v
SQLite FTS5 lexical rank
        +
Qwen3-Embedding-0.6B semantic rank
(JARVIS instruction, 256-d)
        |
        v
Equal-weight RRF candidate fusion
(k=60 research default)
        |
        v
Top 3 eligible candidates
        |
        v
Qwen3-Reranker-0.6B CrossEncoder
(default BF16)
        |
        v
exact-score tie -> preserve RRF rank -> stable ID
        |
        v
JARVIS policy/context assembler
```

## Explicit non-decisions / boundaries

### No vector database yet

The research corpus used exact cosine similarity to isolate embedding quality. This technology decision does **not** approve Qdrant, LanceDB, sqlite-vec or another vector engine.

A dedicated vector index is added only after a corpus-scale latency/storage benchmark demonstrates a real need. Derived embeddings/indexes remain rebuildable and never become canonical truth.

### No reranker score threshold yet

Do not use `score > 0` or any other arbitrary fixed cutoff.

The small corpus showed correct positive memories can receive negative reranker logits, while the three absent-answer probes also receive negative logits. The current sample is too small for a safe production abstention threshold.

Abstention/confidence calibration is deferred to a larger acceptance corpus containing many more:

- absent-answer queries;
- ambiguous questions;
- near-miss distractors;
- stale/superseded memories;
- adversarial or poisoned content;
- English/Hindi/Hinglish paraphrases.

### Retrieval never establishes truth

Embedding similarity, FTS BM25, RRF and the reranker only order already-eligible candidates.

They may not override:

- explicit owner correction/forget instructions;
- source authority;
- valid/system-time semantics;
- sensitivity filtering;
- supersession/retraction/deletion state;
- JARVIS memory admission policy.

## External references

- SQLite FTS5: https://www.sqlite.org/fts5.html
- Qwen3-Embedding-0.6B: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- Qwen3-Reranker-0.6B: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- Qwen reranker config (BF16): https://huggingface.co/Qwen/Qwen3-Reranker-0.6B/blob/main/config.json
- Sentence Transformers CrossEncoder: https://www.sbert.net/docs/package_reference/cross_encoder/model.html
- Sentence Transformers retrieve/rerank pattern: https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html

## Research disposition

**MULTILINGUAL RETRIEVAL TECHNOLOGY SELECTION: COMPLETE.**

Leading Step-4 retrieval stack:

- SQLite bitemporal canonical store + FTS5;
- Qwen3-Embedding-0.6B, JARVIS instruction, 256 dimensions;
- equal-weight RRF candidate fusion;
- top-3 Qwen3-Reranker-0.6B, default BF16;
- deterministic first-stage tie-break;
- no dedicated vector database unless later scale evidence requires one;
- no confidence threshold until larger abstention calibration.

The next Step-4 research gate is **OpenAI versus Gemini structured memory-candidate extraction**.
