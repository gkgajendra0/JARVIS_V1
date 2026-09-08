# Step 4 — Qwen Reranker Precision/Stability Results (Windows)

## Status

**RESEARCH EVIDENCE — NOT FINAL STEP-4 ARCHITECTURE APPROVAL.**

This document records the precision/stability follow-up for the Step-4 retrieve/fuse/rerank stack on the actual JARVIS Windows machine.

The purpose was narrow: determine whether the perfect top-3 reranker result depended on BF16 score ties or unstable candidate ordering, and whether FP32 materially improves robustness enough to justify its GPU cost.

## Environment/result

Date: 2026-09-04

Harness:

- `tools/research/step4_qwen_reranker_precision_bakeoff.py`

Fixed retrieval stack before reranking:

- SQLite FTS5 lexical retrieval;
- `Qwen/Qwen3-Embedding-0.6B` semantic retrieval;
- JARVIS memory-specific query instruction;
- 256-dimensional Matryoshka embeddings;
- equal-weight RRF, rank constant 60;
- top-3 fused candidates.

Reranker:

- `Qwen/Qwen3-Reranker-0.6B` via Sentence Transformers `CrossEncoder`.

The harness repeated scoring three times in both first-stage and reversed candidate order.

## Measured comparison

| Configuration | Effective dtype | Recall@1 | Recall@3 | MRR | p50 rerank | p95 rerank | Peak CUDA allocation | Exact top-score ties | Repeat/order instability |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen default | `torch.bfloat16` | 1.0000 | 1.0000 | 1.0000 | 68.33 ms | 76.00 ms | ~2.31 GiB | 2 cases | 0 cases |
| Forced FP32 | `torch.float32` | 1.0000 | 1.0000 | 1.0000 | 62.40 ms | 67.88 ms | ~3.48 GiB | 0 cases | 0 cases |

FP32 removed the two exact BF16 top-score ties:

- `bike_hi_mix`: BF16 tied `bike` and `current_tyre` at `-5.1875`; FP32 separated them to approximately `-5.1186` and `-5.1260`, retaining `bike` first.
- `memory_db_mix`: BF16 tied `memory_store` and `provider_boundary` at `5.625`; FP32 separated them to approximately `5.5781` and `5.4591`, retaining `memory_store` first.

However, BF16 was fully deterministic in this test:

- score range was zero across repeated runs for every candidate;
- reversing candidate input order did not change the observed final ranking;
- no query had repeat/order ranking instability;
- all 17 positive cases remained correct at rank 1.

## Precision decision

**KEEP THE RERANKER AT ITS MODEL-DEFAULT BF16 PRECISION FOR THE LEADING STEP-4 DESIGN.**

Reason:

1. BF16 and FP32 produced identical measured retrieval quality: 100% Recall@1, 100% Recall@3, MRR 1.0 on the fixed corpus.
2. BF16 showed no repeat or candidate-order instability.
3. FP32 removed exact score ties but increased measured peak CUDA allocation by about **1.17 GiB** (~2.31 GiB to ~3.48 GiB in this harness).
4. JARVIS has an 8 GB RTX 5060 Ti and must share GPU capacity with vision/identity and future workloads; preserving ~1.17 GiB is materially valuable.
5. The Qwen model config itself declares `torch_dtype: bfloat16`; BF16 is therefore the model-native/default path rather than an ad-hoc reduced-precision conversion.
6. Sentence Transformers supports overriding CrossEncoder dtype, which made FP32 a valid research comparison, but the measured evidence does not justify paying its memory cost as the default.

### Deterministic tie policy

When reranker scores are exactly equal, use the **existing first-stage fused rank** as the deterministic secondary ordering signal, followed only by a stable memory identifier if a tie still remains.

This is not a learned truth rule and does not allow the reranker to override JARVIS temporal/source/authority policy. It only orders already-eligible retrieval candidates whose reranker score is numerically identical.

## Important non-decision: abstention threshold

Do **not** infer a production confidence threshold from this small corpus.

The three absent-answer probes produced strongly negative top logits, but some valid positive matches also produced negative logits. For example, the Hinglish bike and Hindi research-rule positives can score below zero while still being the correct top candidate.

Therefore:

- `score > 0` is invalid as a generic relevance rule;
- no absolute reranker cutoff is approved here;
- abstention/confidence calibration must use a larger acceptance corpus with many more absent/ambiguous/adversarial cases.

## External references

- Qwen3-Reranker-0.6B model/config: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- Qwen config declares BF16: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B/blob/main/config.json
- Sentence Transformers CrossEncoder supports `model_kwargs` / `torch_dtype`: https://www.sbert.net/docs/package_reference/cross_encoder/model.html

## Disposition

The precision question is **closed for technology selection**:

- default BF16 reranker: **KEEP**;
- FP32 reranker: **DO NOT USE BY DEFAULT**;
- deterministic exact-score tie-break: **FIRST-STAGE RRF RANK, THEN STABLE ID**;
- confidence/abstention cutoff: **DEFER TO LARGER ACCEPTANCE CALIBRATION**.
