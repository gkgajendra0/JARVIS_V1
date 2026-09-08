# Step 4 — Phase 4.5 Embedding Selection

Date: 2026-09-05

## Status

**MODEL SELECTION COMPLETE — QWEN3-EMBEDDING-0.6B @ 256D SELECTED.**

This record closes the Phase-4.5 incumbent-versus-challenger embedding bake-off on the actual JARVIS Windows machine. It supplements the earlier retrieval technology decision with the 2026 EmbeddingGemma challenger measurement.

## Fixed comparison contract

Both candidates were evaluated against the same research contract:

- 14 fixed canonical-style memory records;
- 20 fixed queries;
- 17 positive queries + 3 absent-answer queries;
- English, Hindi and Hinglish coverage;
- 256-dimensional embeddings;
- identical deterministic eligibility/scoping;
- identical SQLite FTS5 lexical path;
- equal-weight RRF with `k=60`;
- FTS window `10`;
- exact local cosine ranking;
- NVIDIA GeForce RTX 5060 Ti;
- PyTorch `2.14.0+cu130`, CUDA 13.0;
- Sentence Transformers `6.0.1`;
- Transformers `5.16.1`.

The two uploaded result artifacts were:

- `.step4-phase45-embedding-bakeoff.json` — valid Qwen result; the initial Gemma entry was access-gated before execution;
- `.step4-phase45-embeddinggemma-only.json` — valid authenticated EmbeddingGemma result.

Qwen was not rerun merely to recover the previously gated challenger result.

## Measured result

| Metric | Qwen3-Embedding-0.6B | EmbeddingGemma 300M | Decision signal |
|---|---:|---:|---|
| Dense Recall@1 | 0.8824 | 0.8824 | tie |
| Dense Recall@3 | 1.0000 | 1.0000 | tie |
| Dense MRR | 0.9412 | 0.9314 | Qwen |
| RRF Recall@1 | **0.9412** | 0.7647 | **Qwen** |
| RRF Recall@3 | 1.0000 | 1.0000 | tie |
| RRF MRR | **0.9608** | 0.8824 | **Qwen** |
| Hybrid p50 | **63.2179 ms** | 84.0370 ms | **Qwen** |
| Hybrid p95 | **68.7911 ms** | 96.7016 ms | **Qwen** |
| Peak CUDA allocated | **1,292,429,824 B** | 1,312,609,280 B | Qwen |
| Peak process RSS delta | **1,397,387,264 B** | 1,630,117,888 B | Qwen |
| Parameters | 595,776,512 | **307,581,696** | Gemma only on nominal parameter count |
| Runtime dtype | BF16 | FP32 | explains why smaller Gemma did not win measured memory |

EmbeddingGemma's first-load `284.2642 s` included its first gated-model download/cache path and is not used as a warm-load comparison against the already-cached Qwen load.

### Relative owner-machine cost

Compared with Qwen, EmbeddingGemma measured approximately:

- **32.9% slower** hybrid p50;
- **40.6% slower** hybrid p95;
- **1.6% more** peak CUDA allocation;
- **16.7% more** process RSS delta.

Therefore the smaller nominal parameter count did not produce a real JARVIS resource advantage under the tested native inference paths.

## Multilingual evidence

### Qwen dense

- English Recall@1: 0.8889;
- Hindi Recall@1: **1.0000**;
- Hinglish Recall@1: 0.8571.

### EmbeddingGemma dense

- English Recall@1: **1.0000**;
- Hindi Recall@1: **0.0000** on the one fixed Hindi case;
- Hinglish Recall@1: 0.8571.

### Qwen RRF hybrid

- English Recall@1: **1.0000**;
- Hindi Recall@1: **1.0000**;
- Hinglish Recall@1: **0.8571**.

### EmbeddingGemma RRF hybrid

- English Recall@1: 0.8889;
- Hindi Recall@1: 0.0000;
- Hinglish Recall@1: 0.7143.

For JARVIS, Hindi/Hinglish performance is a first-class requirement. The challenger therefore does not meet the required multilingual quality bar for the leading production path.

## Case-level ordering failures

Qwen RRF had one top-1 miss among the 17 positive cases:

- `rule_hi_mix`.

EmbeddingGemma RRF had four:

- `rule_hi_mix`;
- `rule_hi`;
- `memory_db_mix`;
- `self_model_en`.

Gemma's dense model did improve `poison_en` relative to Qwen dense, but Qwen's RRF lexical rescue already returned the correct memory at rank 1 for that case. The net production hybrid result therefore still strongly favors Qwen.

## Absent-query observation

EmbeddingGemma produced lower absolute cosine scores on the three absent queries, but this does **not** imply a safer threshold.

Measured dense score separation on this fixed corpus:

- Qwen weakest correct positive: ~0.483868;
- Qwen strongest absent top score: ~0.421085;
- Qwen observed gap: **~0.062783**;
- EmbeddingGemma weakest correct positive: ~0.303378;
- EmbeddingGemma strongest absent top score: ~0.287295;
- EmbeddingGemma observed gap: **~0.016083**.

The Gemma gap is materially narrower because the Hindi positive scored poorly. No production cosine cutoff is approved from either model.

## Final embedding decision

**SELECT:** `Qwen/Qwen3-Embedding-0.6B`

Production target contract:

- 256-dimensional Matryoshka output;
- normalized embeddings;
- JARVIS memory retrieval instruction for query encoding;
- model-native BF16 where supported by the runtime/GPU;
- exact local cosine over derived vectors initially;
- no vector extension until scale measurements require one.

**DO NOT SELECT:** `google/embeddinggemma-300m` for the Phase-4.5 production retrieval path.

Reason: it did not materially reduce owner-machine resources and it materially regressed the actual hybrid multilingual retrieval path.

## Reranker disposition

The embedding selection does not reopen the already-measured reranker decision.

The Qwen first-stage hybrid still has one ordering miss while preserving 100% positive Recall@3. Earlier owner-machine measurements showed `Qwen/Qwen3-Reranker-0.6B` over the top 3 fused candidates reaches:

- Recall@1 = 1.0000;
- Recall@3 = 1.0000;
- MRR = 1.0000;
- no repeat/order instability in the BF16 precision follow-up;
- deterministic exact-score tie handling by preserving first-stage RRF rank, then stable memory ID.

Therefore the leading production design keeps the **top-3 Qwen reranker at model-default BF16**, subject to the still-open abstention calibration gate.

## Permanent boundaries

- retrieval ranks evidence and never creates truth;
- only eligible canonical memory may enter lexical/dense/rerank stages;
- exact deterministic lookup remains preferred when a canonical key is known;
- embeddings/reranker scores are derived and rebuildable;
- physical forget must remove every stored derived representation for the forgotten assertion;
- no provider history/cache becomes memory;
- no second cloud-AI provider is introduced;
- no ANN/vector extension is approved yet;
- no absolute embedding or reranker threshold is approved from this small corpus.

## Next implementation gate

Proceed with Phase-4.5 production implementation in this order:

1. define encrypted derived-vector schema + rebuild/version semantics;
2. guarantee physical forget removes derived vectors;
3. implement eligible-current FTS5 + exact dense cosine + equal RRF;
4. implement top-3 Qwen reranking with deterministic ties;
5. expand the abstention corpus and calibrate release/abstention from measured data;
6. release accepted retrieval evidence only through `ContextAssembler`;
7. run automated and owner-PC production acceptance.
