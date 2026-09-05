# Step 4 — Phase 4.5D Abstention Calibration Implementation Status

Date: 2026-09-05

## Status

**IMPLEMENTED — OWNER RTX CALIBRATION RUN PENDING.**

Phase 4.5D now has a research-backed, research-only calibration harness. It does not set or write a production threshold automatically.

## Research basis

The current Qwen reranker emits raw decision/logit-difference scores rather than calibrated probabilities. A monotonic sigmoid can change the numeric range but does not justify an arbitrary universal cutoff.

The accepted method is therefore:

1. label queries as `release` or `abstain`;
2. split them into calibration and held-out validation sets before model execution;
3. generate candidate thresholds only from observed calibration scores/midpoints;
4. compare transparent score/margin/dense rule families;
5. choose lexicographically by minimum false releases, then maximum correct releases, then simpler rule;
6. freeze the selected rule;
7. evaluate it unchanged on held-out validation;
8. treat any validation false release as blocking rather than tuning on validation.

Research record:

- `docs/research/STEP_4_PHASE_4_5D_ABSTENTION_RESEARCH.md`.

## Fixed corpus

Added:

- `tools/research/step4_phase45d_abstention_cases.json`.

The corpus contains 64 fixed queries:

- calibration: 16 release + 16 abstain;
- validation: 16 release + 16 abstain.

Languages:

- English;
- Hindi;
- Hinglish.

Abstention boundaries include:

- absent facts;
- near misses;
- ambiguous questions;
- historical/current-state boundaries;
- forgotten facts;
- `LOCAL_ONLY` evidence;
- `SECRET_PROHIBITED` evidence;
- untrusted/poison-style evidence;
- adversarial lexical overlap;
- negation;
- relation mismatch.

The fixtures are synthetic/project-style and contain no real secret values.

## Calibration harness

Added:

- `tools/research/step4_phase45d_abstention_calibration.py`.

It uses the actual production retrieval path against a temporary migrated SQLite database:

- `MemoryLifecycleService`;
- `SemanticEmbeddingStore`;
- `SemanticRetrievalService`;
- `RetrievalEligibility.cloud_context()`;
- revision-pinned `Qwen3EmbeddingEncoder`;
- revision-pinned top-3 `Qwen3RetrievalReranker`.

Fixture setup deliberately exercises:

- current records;
- historical transition/replacement;
- physical forget after derived embedding creation;
- local-only filtering;
- secret-prohibited filtering;
- untrusted-source filtering.

The owner's production memory database is not read or modified.

## Candidate release-policy families

The harness compares:

1. reranker top-1 score only;
2. reranker score + top-1/top-2 margin;
3. reranker score + winning dense score;
4. reranker score + margin + dense score.

Threshold candidates come only from calibration-set observed values and their midpoints.

No learned Platt/isotonic/temperature calibrator has been added because the current hand-curated dataset is too small to justify another learned component.

## Required output

Default artifact:

- `.step4-phase45d-abstention-calibration.json`.

It records:

- corpus counts;
- positive top-1 and top-3 retrieval quality;
- calibration frontier;
- selected calibration-only policy;
- held-out validation confusion counts;
- validation false-release IDs;
- positive release recall;
- language/category breakdowns;
- per-case reranker score, margin and dense score;
- first-stage rank metadata;
- timing;
- CUDA peak memory.

Harness status is `PASS` only when the frozen policy produces zero validation false releases. A `PASS` is necessary but not by itself sufficient for production acceptance; positive release recall and multilingual/category failures must also be reviewed before freezing a runtime policy.

## Automated guards

Added:

- `tests/test_phase45d_abstention_calibration.py`.

The tests prove:

- 64 fixed cases and 16/16 release/abstain balance per split;
- English/Hindi/Hinglish coverage;
- required safety fixture modes/categories;
- candidate thresholds are derived from observed boundaries rather than magic constants;
- policy selection prioritizes zero false release, then recall;
- a high-scoring but wrong top-1 positive is counted as unsafe false release rather than hidden as a ranking success.

A dynamic test-loader defect was found in CI and corrected using Python's documented manual-import sequence: register the module in `sys.modules` before `exec_module()`.

After that correction, full pytest passed. Ruff cleanup then removed only style/lint issues; no calibration logic was changed.

## Authority/security boundaries

Phase 4.5D:

- does not create production canonical memory;
- does not mutate production truth;
- does not auto-write a threshold;
- does not use a cloud provider;
- does not introduce another cloud subscription;
- does not bypass retrieval eligibility;
- does not enable implicit durable admission;
- does not grant self-repair/code-modification authority.

## Next gate

Run the fixed harness once on the accepted owner RTX 5060 Ti environment.

Then review the emitted calibration and held-out validation evidence. Do not rerun or tune against validation merely to improve the result.
