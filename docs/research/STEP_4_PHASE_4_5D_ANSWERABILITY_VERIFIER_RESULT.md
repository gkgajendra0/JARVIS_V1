# Step 4 Phase 4.5D — Answerability Verifier Development Result

Date: 2026-09-06

Status: **REJECTED FOR V3 FREEZE — DEVELOPMENT EVIDENCE ONLY**

## Purpose

This experiment tested whether a task-matched multilingual extractive QA verifier could replace the rejected mMARCO relevance verifier for the Phase 4.5D release/abstain decision.

The V2 corpus was already exposed and retired from acceptance before this experiment. This result is therefore development evidence only and must never be presented as fresh acceptance evidence.

## Frozen retrieval path used in the experiment

- `Qwen/Qwen3-Embedding-0.6B`
- revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`
- normalized 256d embeddings
- eligible-current FTS5 + exact Qwen cosine + equal-weight RRF
- first-stage candidate window widened to 10
- `Qwen/Qwen3-Reranker-0.6B`
- revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`
- frozen JARVIS reranker instruction

The prior retrieval-depth diagnostic had already shown that top-10 completely removed V2 positive candidate starvation.

## Verifier tested

`deepset/xlm-roberta-base-squad2-distilled`

Revision:

`c1bbfe57bc3335c37960a48c5628ba26d7e9e3b7`

The verifier used SQuAD2-style null-vs-best-answer scoring. A larger positive margin meant stronger evidence that the selected memory passage contained an extractive answer to the query.

## Owner result

Artifact:

`.step4-phase45d-v2-answerability-verifier-bakeoff-v1.json`

Terminal status:

`DEVELOPMENT_BAKEOFF_COMPLETE`

### Ranking

Top-10 Qwen retrieval/reranking was perfect on all V2 positive cases:

- overall: `900/900 = 1.000000` Top-1
- calibration: `600/600 = 1.000000` Top-1
- validation: `300/300 = 1.000000` Top-1

This confirms again that the 256d Qwen embedding contract is sufficient once the candidate window is widened to 10.

### Calibration-selected QA threshold

Threshold selected using V2 calibration only:

`7.436666965484619`

Calibration result:

- TP `577`
- FP `30`
- released `607`
- precision `0.950577`
- positive release recall `0.961667`

The calibration wording therefore made the QA verifier look extremely strong.

### Unchanged threshold on differently worded V2 validation

Validation result:

- TP `140`
- FP `12`
- released `152`
- precision `0.921053`
- positive release recall `0.466667`

The overall recall floor was cleared, but the frozen 0.95 precision requirement was not.

The per-language release-recall requirement also failed.

### False-release pattern

The 12 validation false releases were:

- 9 `relation_mismatch`
- 1 `ambiguous`
- 2 `historical`

The two security-boundary false releases were:

- `v2_val_a0191` — Hindi, `historical`
- `v2_val_a0194` — Hindi, `historical`

Therefore `validation_zero_security_boundary_releases` failed.

## Interpretation

This is a genuine architecture result, not an infrastructure or harness failure.

The QA verifier solved a different problem better than mMARCO: it was very effective at detecting whether some answer-like span existed in the memory passage. It did **not** reliably enforce JARVIS's stricter requirement that the memory answer the exact requested relation and temporal scope.

The large calibration-to-validation precision drop also shows wording/template sensitivity. A high calibration margin was not a stable release guarantee under paraphrase shift.

The dominant validation errors remained relation mismatch, and the hard failures were temporal/historical Hindi cases. That is exactly the semantic distinction the final Phase 4.5D gate must protect.

## Decision

Reject the SQuAD2 answerability verifier for V3 freeze.

Do not:

- lower the 0.95 precision target;
- tune the QA threshold on V2 validation;
- rerun the same QA architecture and call it acceptance;
- change Qwen embedding dimensions;
- replace Qwen retrieval/reranking based on this result;
- begin Phase 4.5E.

## Research-first next direction

Current external research now justifies a direct semantic-classification bake-off rather than another generic relevance or extractive-answer model.

Two mature challengers should be compared on the same exposed V2 top-10 pairs:

1. `knowledgator/gliclass-multilang-mini`
   - approximately 288M parameters;
   - Apache-2.0;
   - natively multilingual including Hindi;
   - explicitly supports hallucination detection, NLI, rule-following verification and zero-shot classification;
   - current immutable development revision to pin: `c09fb5ca4cb7957044168e6bf8bcefa2e14b8dfb`.

2. `gemini-3.5-flash-lite`
   - GA Gemini model;
   - existing JARVIS production provider family;
   - structured JSON outputs supported;
   - designed for low-cost high-volume subagent/classification work;
   - no new cloud provider is introduced.

The bake-off must classify only query + selected memory document. Ground-truth label, category, expected memory ID and validation metadata must never be supplied to either semantic judge.

Any V2-based selection remains development-only. A materially selected architecture still requires a completely fresh V3 calibration/validation corpus before Phase 4.5D can close.
