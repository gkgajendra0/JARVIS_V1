# Step 4 — Phase 4.5D Reranker Instruction Selection

Date: 2026-09-05

## Status

**SELECTED FOR PRODUCTION RETRIEVAL: JARVIS-SPECIFIC QWEN3 RERANKER INSTRUCTION.**

This is a development-model-selection result, not final Phase 4.5D release-policy acceptance.
The 64-query V1 corpus is permanently retired from final acceptance after this comparison.

## Compared configurations

Both configurations used the same:

- `Qwen/Qwen3-Reranker-0.6B`;
- immutable revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- top-3 first-stage candidates;
- Qwen3-Embedding-0.6B / FTS5 / RRF first stage;
- RTX 5060 Ti owner environment;
- Torch `2.13.0+cu132`, CUDA runtime `13.2`.

Only the reranker instruction changed.

### Baseline

Sentence Transformers / Qwen generic default reranking instruction.

### Challenger

```text
Judge whether the memory Document directly and sufficiently answers the JARVIS memory Query using only facts stated in the Document. Answer yes only when the Document supports the specific fact or relation requested; answer no when it is merely related, missing the requested detail, contradictory, negated, or otherwise does not answer the Query.
```

## Owner-machine result

Artifact:

- `.step4-phase45d-reranker-instruction-bakeoff.json`

Harness status:

- `PASS`;
- `final_acceptance_eligible=false` by design.

### Ranking quality

Both configurations were identical on positive ranking:

| Metric | Generic default | JARVIS instruction |
|---|---:|---:|
| Positive top-1 accuracy | 0.90625 | 0.90625 |
| Positive Recall@3 | 0.90625 | 0.90625 |
| English positive top-1 | 0.933333 | 0.933333 |
| Hindi positive top-1 | 1.000000 | 1.000000 |
| Hinglish positive top-1 | 0.833333 | 0.833333 |

The custom instruction therefore caused no measured ranking or language regression.

### Confidence separation / selective retrieval

| Metric | Generic default | JARVIS instruction | Direction |
|---|---:|---:|---|
| score AUROC safe vs unsafe | 0.918719 | **0.936453** | higher better |
| margin AUROC safe vs unsafe | 0.768966 | **0.795074** | higher better |
| AURC | 0.267634 | **0.242616** | lower better |
| zero-error prefix cases | 1 | **6** | higher better |
| zero-error coverage | 0.015625 | **0.093750** | higher better |
| zero-error positive-release recall | 0.031250 | **0.187500** | higher better |

The JARVIS instruction materially improved confidence ordering while preserving ranking accuracy.

### Latency / GPU

| Metric | Generic default | JARVIS instruction |
|---|---:|---:|
| rerank p50 | 74.5163 ms | **74.3643 ms** |
| rerank p95 | 87.2734 ms | **80.9301 ms** |
| maximum | 3711.8255 ms | 3656.0725 ms |

Combined bake-off peak CUDA allocation:

- `2,504,516,096` bytes.

There is no material runtime penalty from the selected instruction.

## Decision

Freeze `JARVIS_MEMORY_RERANK_INSTRUCTION` as the default production instruction for `Qwen3RetrievalReranker`.

Keep `instruction=None` only as an explicit research override for reproducing generic Qwen behavior.

This change does **not** alter:

- model ID;
- model revision;
- Torch/CUDA dependencies;
- candidate window;
- embedding contract;
- canonical memory authority;
- Step-3 audio/vision architecture.

## Important limitation

The instruction improves confidence separation but does not fix the three positive retrieval misses in the retired V1 development corpus. The final Phase 4.5D acceptance must therefore continue to report first-stage/top-3 ranking quality separately from release-policy calibration.

No threshold from the V1 corpus is eligible for production.

## Next research decision

Use a fresh, untouched multilingual acceptance corpus and a mature Learn-Then-Test risk-control implementation rather than another ad-hoc threshold search.

Selected research library:

- MAPIE `1.5.0`;
- research/calibration dependency only;
- `BinaryClassificationController` precision control / Learn-Then-Test;
- fail closed if no valid prediction parameter exists.

The final acceptance corpus must be frozen before model execution and must not reuse the retired V1 queries.
