# Step 4 — Bake-off Results

## Status

**EVIDENCE IN PROGRESS — THESE RESULTS DO NOT APPROVE THE FINAL STEP-4 ARCHITECTURE.**

This document records measured evidence for the Step-4 technology decision. Results distinguish between reference-environment measurements and measurements from the real JARVIS Windows machine.

Research harnesses deliberately live under `tools/research`; no runtime memory under `src/jarvis` is implemented by these bake-offs.

## 1. SQLite temporal + FTS bake-off — COMPLETE

### Purpose

Test whether plain SQLite can satisfy the important canonical-memory mechanics before adding a temporal database server, graph database, or vector database:

- current fact lookup;
- valid-time history;
- system/learned-time history;
- historical change versus correction;
- FTS5 English/Hindi/Hinglish lexical retrieval;
- explicit-forget deletion from canonical + derived FTS representations;
- low-latency local lookup at a scale much larger than the expected early personal-memory corpus.

### Reference-environment result

Initial research execution used Python's built-in SQLite 3.46.1 with 30,000 synthetic fact records.

Temporal semantics passed all tested assertions:

1. old system-time queries recover what JARVIS believed then;
2. genuine preference changes preserve the old value for its historical valid-time interval while a new value becomes current;
3. later corrections can change the current best-known historical truth while old system-time queries still recover the earlier mistaken belief.

Reference latency was approximately:

| Query | p50 | p95 |
|---|---:|---:|
| Exact structured current-fact lookup | 0.008 ms | 0.009 ms |
| FTS5 English | 3.25 ms | 4.84 ms |
| FTS5 Hindi | 3.45 ms | 5.12 ms |
| FTS5 Hinglish | 2.89 ms | 3.20 ms |

These reference numbers were not acceptance thresholds.

### Real JARVIS Windows-machine result — PASS

The owner reran the same harness on the actual JARVIS Windows/Python 3.11 environment on 2026-09-04.

Environment/result highlights:

- SQLite: `3.45.1`;
- seed records: `30,000`;
- temporal semantics: all tested assertions passed;
- FTS5 `secure-delete`: supported;
- explicit forget: zero canonical rows and zero normal FTS hits after deletion;
- database size: `16,928,768` bytes (~16.9 MB decimal).

Measured latency:

| Query | p50 | p95 | Maximum observed |
|---|---:|---:|---:|
| Exact current-fact lookup | 0.0165 ms | 0.0186 ms | 0.2087 ms |
| FTS5 English | 4.0938 ms | 4.6056 ms | 6.1346 ms |
| FTS5 Hindi | 4.3506 ms | 4.6950 ms | 6.0042 ms |
| FTS5 Hinglish | 3.7851 ms | 3.9048 ms | 4.1437 ms |

### SQLite disposition

**KEEP SQLITE + FTS5 AS THE LEADING CANONICAL/LEXICAL FOUNDATION. DO NOT ADD XTDB/QDRANT/GRAPHITI/LANCEDB TO THE RUNTIME WITHOUT MEASURED NEED.**

Reason:

- the required bitemporal semantics were demonstrated on the real machine;
- lookup/FTS latency is comfortably low at the tested scale;
- secure-delete is available;
- the tested forget path removed both canonical and FTS representations;
- WAL matches the expected same-host, low-write-concurrency workload;
- a heavier database would add operational, security, synchronization and self-diagnostic surface without demonstrated benefit.

Relevant detailed harness/result:

- `tools/research/step4_memory_sqlite_bakeoff.py`

## 2. Multilingual retrieval-quality bake-off — TECHNOLOGY SELECTION COMPLETE

Detailed consolidated decision:

- `docs/research/STEP_4_RETRIEVAL_TECHNOLOGY_DECISION.md`

### Why semantic retrieval was tested

FTS5 was fast but missed low-overlap semantic paraphrases, including cases equivalent to:

- “Which device gives Jarvis eyes?” versus the stored camera fact;
- “Meri bike kaunsi hai?” versus the stored motorcycle fact;
- Hindi/Hinglish research-first-rule paraphrases.

Therefore semantic retrieval addresses a measured lexical-recall gap rather than being added by convention.

### Model comparison on the actual RTX 5060 Ti

#### Qwen3-Embedding-0.6B — default 1024

- Recall@1: `0.7647`;
- Recall@3: `1.0000`;
- MRR: `0.8824`;
- GPU query p50: ~61 ms;
- peak CUDA allocation: ~1.29 GB decimal.

#### BGE-M3

- Recall@1: `0.8824`;
- Recall@3: `0.9412`;
- MRR: `0.9265`;
- GPU query p50: ~23.4 ms;
- peak CUDA allocation: ~2.33 GB decimal.

BGE was faster and stronger at rank 1, but Qwen used roughly 1 GB less GPU memory and retained all positive memories within the top 3.

### Qwen JARVIS-specific optimization

Qwen supports instruction-aware retrieval and Matryoshka dimensions. A JARVIS-memory-specific query instruction plus 256-dimensional output measured:

- Recall@1: `0.8824`;
- Recall@3: `1.0000`;
- MRR: `0.9412`;
- query p50: ~63 ms;
- 256-dimensional vectors (4x smaller than 1024-d for derived vector storage/search).

This configuration became the leading semantic retriever.

### First-stage hybrid fusion

Equal-weight Reciprocal Rank Fusion (RRF) over FTS5 + Qwen-256 measured:

- Recall@1: `0.9412`;
- Recall@3: `1.0000`;
- MRR: `0.9608`;
- end-to-end p50: ~61.6 ms;
- p95: ~67.0 ms.

A semantic-weight sweep (`1.0, 1.25, 1.5, 1.75, 2.0`) demonstrated that no single global static weight safely resolved every disagreement:

- `1.0–1.75` retained one Hinglish research-rule rank-1 miss;
- `2.0` fixed that case but lost two lexical rescues.

Disposition: do not overfit a global fusion weight to the small corpus.

### Second-stage reranking

A mature retrieve/fuse/rerank pattern was then tested using `Qwen/Qwen3-Reranker-0.6B` over only the top fused candidates.

Top-3 reranking measured:

- candidate recall: `1.0000`;
- Recall@1: `1.0000`;
- Recall@3: `1.0000`;
- MRR: `1.0000`;
- rerank p50: ~68.8 ms in the initial top-3 harness;
- end-to-end p50: ~130.9 ms;
- end-to-end p95: ~150.0 ms;
- combined embedder + reranker peak CUDA allocation: roughly 2.35 GiB in the initial reranker harness.

Top-5 reranking regressed Recall@1 to `0.9412`, so the selected candidate window is **3**.

### BF16 versus FP32 reranker precision

A focused stability harness repeated each query in first-stage and reversed candidate order three times.

| Precision | Recall@1 | Recall@3 | MRR | p50 | p95 | Peak CUDA | Exact top-score ties | Order/repeat instability |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Default BF16 | 1.0000 | 1.0000 | 1.0000 | 68.33 ms | 76.00 ms | ~2.31 GiB | 2 | 0 |
| Forced FP32 | 1.0000 | 1.0000 | 1.0000 | 62.40 ms | 67.88 ms | ~3.48 GiB | 0 | 0 |

FP32 removed the two exact BF16 ties but cost about 1.17 GiB additional peak CUDA allocation. BF16 remained fully deterministic across repeats and reversed candidate order.

Disposition:

- keep the reranker at model-default BF16;
- exact reranker-score ties preserve the first-stage RRF rank, then stable memory ID;
- do not spend ~1.17 GiB additional GPU memory merely to remove deterministic numerical ties.

### Selected retrieval technology

```text
structured / temporal / authority / sensitivity filtering
        |
        +---- exact deterministic lookup when possible
        |
        v
SQLite FTS5 lexical rank
        +
Qwen3-Embedding-0.6B semantic rank
(JARVIS memory instruction, 256-d)
        |
        v
Equal-weight RRF (research k=60)
        |
        v
Top 3 eligible candidates
        |
        v
Qwen3-Reranker-0.6B CrossEncoder
(default BF16)
        |
        v
exact-score tie -> RRF rank -> stable ID
        |
        v
JARVIS policy/context assembler
```

### Retrieval boundaries / non-decisions

**No dedicated vector database yet.** The research harness intentionally used exact cosine similarity to isolate model quality. Qdrant/LanceDB/sqlite-vec/another vector engine is added only if later corpus-scale measurements demonstrate need.

**No production reranker-score/abstention threshold yet.** The corpus has only three absent-answer probes, and valid positives can also produce negative reranker logits. `score > 0` is therefore not a valid rule. Confidence/abstention must be calibrated on a larger acceptance corpus with absent, ambiguous, stale, adversarial and multilingual cases.

**Retrieval never establishes truth.** FTS, embeddings, RRF and the reranker only order already-eligible candidates and cannot override JARVIS source authority, correction/forget operations, temporal validity, sensitivity or admission policy.

Detailed result records include:

- `docs/research/STEP_4_RETRIEVAL_BAKEOFF_QWEN_WINDOWS.md`
- `docs/research/STEP_4_RETRIEVAL_BAKEOFF_QWEN_GPU_WINDOWS.md`
- `docs/research/STEP_4_RETRIEVAL_BAKEOFF_BGE_GPU_WINDOWS.md`
- `docs/research/STEP_4_RETRIEVAL_QWEN_OPTIMIZATION_WINDOWS.md`
- `docs/research/STEP_4_RETRIEVAL_HYBRID_RRF_WINDOWS.md`
- `docs/research/STEP_4_RETRIEVAL_WEIGHTED_RRF_WINDOWS.md`
- `docs/research/STEP_4_RETRIEVAL_QWEN_RERANKER_WINDOWS.md`
- `docs/research/STEP_4_RETRIEVAL_RERANKER_PRECISION_WINDOWS.md`

## 3. Structured memory-candidate extraction — pending

Current research supports using provider-native structured outputs behind JARVIS-owned typed contracts rather than building an ad-hoc parser.

The next bake-off must compare OpenAI and Gemini on semantic correctness, not merely schema-valid JSON:

- correct candidate classification;
- false durable-memory candidate rate;
- missed explicit remember/correct/forget commands;
- temporal meaning;
- preservation of uncertainty;
- refusal to treat assistant/external content as user truth;
- English/Hindi/Hinglish behaviour;
- latency and token/cost characteristics.

Current design direction remains:

```text
accepted text
 -> MemoryCandidateExtractor protocol
   -> OpenAI native structured-output adapter
   -> Gemini native structured-output adapter
 -> Pydantic-validated candidate
 -> JARVIS MemoryPolicy
```

Schema validity never implies factual truth.

## 4. Encryption / Windows packaging — pending owner-machine spike

SQLCipher remains the leading whole-database encryption family, but the Python/Windows packaging decision is not approved.

The Windows spike must compare a vetted/official build path, dependency provenance, DPAPI-wrapped random DB key handling, backup/recovery, wrong-key/corruption behaviour, FTS/vector leakage and reliable forgetting before any real personal memory is stored.

## 5. Self-knowledge / SBOM — pending spike

Use maintained `cyclonedx-bom` tooling rather than a deprecated GitHub Action for generated dependency inventory.

A JARVIS-specific capability registry is still necessary because an SBOM cannot express product semantics such as capabilities, authority boundaries, diagnostics, known limitations or runtime health.

The spike must verify generated CycloneDX inventory + capability-registry ownership and how declared architecture differs from learned operational observations.

## 6. Remaining evidence required before “research complete”

Research is complete only after all of the following are measured or explicitly dispositioned:

- [x] requirements and lifecycle research;
- [x] memory-framework landscape research;
- [x] first SQLite bitemporal correctness spike;
- [x] first SQLite/FTS reference latency spike;
- [x] rerun SQLite/FTS spike on the actual JARVIS Windows environment;
- [x] multilingual retrieval-quality/model/fusion/reranker technology selection;
- [ ] larger abstention/confidence calibration (acceptance/hardening gate; not blocking retrieval technology selection);
- [ ] OpenAI/Gemini memory-candidate extraction bake-off;
- [ ] SQLCipher/DPAPI Windows encryption/package spike;
- [ ] CycloneDX SBOM + JARVIS capability-registry self-knowledge spike;
- [ ] consolidate all measured results into the final Step-4 technology decision;
- [ ] prepare final architecture proposal for human approval.

No production Step-4 memory implementation begins before the final technology decision and architecture approval.
