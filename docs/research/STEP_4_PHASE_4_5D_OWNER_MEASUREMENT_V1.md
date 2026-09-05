# Step 4 — Phase 4.5D Owner Measurement V1

Date: 2026-09-06

## Status

**MEASUREMENT COMPLETE — PRODUCTION RELEASE POLICY NOT ACCEPTED.**

This record preserves the first successful owner-RTX abstention measurement. The harness completed on the accepted owner environment and emitted a result artifact, but the selected policy is too conservative for useful production memory recall.

The 64-case corpus is now **retired from final acceptance use**. It may be used only as a development/diagnostic set for improving the confidence mechanism. Future production acceptance must use a fresh, pre-registered calibration/validation corpus.

## Owner environment / harness result

Owner branch head:

- `c2c43b33e5927e6e152b27e4c3a592a0f4ce6a54`

Harness artifact:

- `.step4-phase45d-abstention-calibration.json`

Harness status string:

- `PASS`

Important interpretation:

- `PASS` meant only that the frozen policy produced zero observed validation false releases;
- it did **not** mean Phase 4.5D was production-accepted;
- the implementation-status document explicitly required positive release recall and multilingual/category review before acceptance.

## Security-boundary proof

The corrected fixture respected the canonical secret prohibition:

- corpus document markers: `23`;
- canonical seed documents: `22`;
- secret fixture excluded before canonical creation: `secret_placeholder`.

The harness therefore tested a secret-query abstention boundary without manufacturing impossible `SECRET_PROHIBITED` semantic memory.

## Selected V1 policy

Calibration-only selection produced:

- family: `score_margin`;
- reranker score threshold: `8.96875`;
- top-1/top-2 margin threshold: `9.15625`;
- dense threshold: none.

## Calibration metrics

- observed false releases: `0`;
- correct releases: `4`;
- missed correct releases: `11`;
- reported precision: `1.0`;
- positive release recall: `0.25`.

This is already too conservative for a useful memory retrieval experience.

## Held-out validation metrics

- observed false releases: `0`;
- correct releases: `3`;
- missed correct releases: `11`;
- reported precision: `1.0`;
- positive release recall: `0.1875`;
- released cases: `val_p09`, `val_p10`, `val_p12`.

Language breakdown:

- English positive release recall: `0.166667`;
- Hindi positive release recall: `0.0`;
- Hinglish positive release recall: `0.333333`.

Category examples:

- cross-lingual release recall: `0.0`;
- low-lexical-overlap release recall: `0.25`;
- semantic release recall: `0.142857`;
- current-state release recall: `1.0`.

All measured abstention-only categories shown in the owner output had zero observed false releases, including absent, adversarial lexical, ambiguous, forgotten, historical-excluded, local-only, near-miss, negation, relation-mismatch, secret, and untrusted cases.

## Runtime measurements

- fixture population + document embedding: `13.2594 s`;
- query embedding p50 / p95: `85.5243 / 97.1626 ms`;
- first-stage retrieval p50 / p95: `1.8417 / 2.3153 ms`;
- reranker p50 / p95: `76.2037 / 89.0013 ms`;
- reranker max included first-load/warmup outlier: `3526.6771 ms`;
- peak CUDA allocation: `2,477,882,880` bytes.

## Why V1 is not accepted

### 1. Utility is insufficient

Zero observed false releases came at only `18.75%` held-out positive release recall. JARVIS would abstain on most correct memory queries, including every held-out Hindi cross-lingual positive.

### 2. Raw reranker scores are not calibrated probabilities

Qwen/Sentence Transformers generative rerankers expose a true-vs-false logit-difference relevance score. A monotone sigmoid can remap the number but does not create a statistical production guarantee by itself.

### 3. The validation sample is too small for a strong precision claim

Only three held-out cases were actually released. `3/3` observed correctness is useful evidence but is not a strong finite-sample guarantee of field precision.

### 4. The confidence mechanism itself should be improved before scaling threshold search

The selected Qwen reranker is instruction-aware. The current production adapter still uses the model's generic default web-search instruction. Qwen recommends task-specific English instructions for downstream use and reports typical improvements from instruction tailoring.

## Research-first next decision

The V1 64-case corpus is retired from final acceptance and becomes a development-only diagnostic set.

Next experiment:

1. keep the selected Qwen3 embedding and reranker models unchanged;
2. compare the current default reranker instruction against exactly one pre-registered JARVIS-memory-specific English instruction on the retired V1 corpus;
3. compare ranking quality, Hindi/Hinglish quality, score separability, and selective risk/coverage behavior;
4. freeze the better instruction before creating any fresh final corpus;
5. replace the custom final threshold-selection logic with a mature Learn-Then-Test risk-control implementation (MAPIE) for pre-registered precision control;
6. evaluate the frozen method on a new corpus whose validation labels are never used for tuning.

No Phase 4.5E integration is allowed yet.
