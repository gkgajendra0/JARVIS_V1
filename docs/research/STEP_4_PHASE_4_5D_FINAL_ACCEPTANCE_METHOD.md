# Step 4 — Phase 4.5D Final Acceptance Method

Date: 2026-09-06

## Status

**PRE-REGISTERED — OWNER RTX FINAL ACCEPTANCE RUN PENDING.**

This document freezes the final Phase 4.5D calibration/validation protocol before the fresh acceptance corpus is scored.

No threshold, acceptance floor, model instruction, query wording, or candidate grid may be changed after the owner run merely to make the final held-out result pass.

## Why V1 is not reused

The first 64-query Phase 4.5D corpus produced a valid development measurement but an unusably conservative release policy:

- zero observed held-out false releases;
- positive release recall `0.1875`;
- Hindi positive release recall `0.0`.

Those labels and case-level results are now exposed. The entire V1 corpus is therefore permanently development-only and cannot be used again as final acceptance evidence.

Record:

- `docs/research/STEP_4_PHASE_4_5D_OWNER_MEASUREMENT_V1.md`.

## Frozen reranker instruction

A development-only comparison on the retired V1 corpus selected the JARVIS-specific Qwen3-Reranker instruction without any measured English/Hindi/Hinglish ranking regression.

Selected instruction:

```text
Judge whether the memory Document directly and sufficiently answers the JARVIS memory Query using only facts stated in the Document. Answer yes only when the Document supports the specific fact or relation requested; answer no when it is merely related, missing the requested detail, contradictory, negated, or otherwise does not answer the Query.
```

Measured development changes versus the generic Qwen default:

- positive top-1 accuracy: `0.90625 -> 0.90625`;
- score AUROC safe-vs-unsafe: `0.918719 -> 0.936453`;
- margin AUROC: `0.768966 -> 0.795074`;
- AURC: `0.267634 -> 0.242616`;
- zero-error positive-release recall: `0.03125 -> 0.1875`;
- no English/Hindi/Hinglish top-1 regression;
- no material latency penalty.

The production `Qwen3RetrievalReranker` now defaults to this instruction. `instruction=None` exists only as an explicit research/reproduction override.

Selection record:

- `docs/research/STEP_4_PHASE_4_5D_RERANKER_INSTRUCTION_SELECTION.md`.

## Research-first risk-control technology

Final calibration uses:

- MAPIE `1.5.0`;
- `mapie.risk_control.BinaryClassificationController`;
- Learn-Then-Test binary precision control;
- multidimensional prediction parameters;
- Holm-Bonferroni family-wise error-rate control.

Research dependency:

- `tools/research/requirements-step4-risk-control.txt`.

MAPIE is research/calibration-only. Production inference will not depend on MAPIE; only a frozen versioned score/margin rule may enter production if this acceptance passes.

Authoritative references reviewed before implementation:

- MAPIE risk-control API: https://mapie.readthedocs.io/en/stable/api/risk-control/
- BinaryClassificationController API: https://mapie.readthedocs.io/en/stable/generated/mapie.risk_control.BinaryClassificationController.html
- multi-parameter binary risk-control example: https://mapie.readthedocs.io/en/v1.4.x/examples_risk_control/2-advanced-analysis/plot_risk_control_multi_parameter_binary_classification.html
- LLM-as-a-judge abstention example: https://mapie.readthedocs.io/en/latest/generated/risk_control/2-advanced-analysis/plot_risk_control_llm_as_a_judge/

## Important statistical limitation

MAPIE's formal distributional guarantees require assumptions such as exchangeability between calibration and future data.

The JARVIS acceptance corpus is deliberately synthetic and fixed. It cannot establish that future owner traffic is exchangeable with this benchmark.

Therefore:

- MAPIE is used here for disciplined finite-sample acceptance calibration and multiple-testing control;
- the repository does **not** claim a real-world 95% traffic guarantee from this synthetic benchmark;
- post-deployment shadow-labelled observations, drift checks, and later operational risk review remain necessary.

This limitation is explicit rather than hidden behind a statistical-looking threshold.

## Fresh fixed acceptance corpus

Generator:

- `tools/research/step4_phase45d_final_cases.py`.

The payload is generated deterministically before model execution and its SHA-256 is emitted into the result artifact.

Total queries: **320**.

### Calibration

- 192 cases;
- 96 `release`;
- 96 `abstain`.

### Held-out validation

- 128 cases;
- 64 `release`;
- 64 `abstain`.

### Languages

Both splits contain:

- English;
- Hindi;
- Hinglish.

### Canonical/security boundaries

The fresh benchmark exercises:

- current canonical facts;
- historical-transition records and current replacements;
- physically forgotten records;
- `LOCAL_ONLY` evidence;
- secret-prohibited markers that never become canonical memory;
- untrusted-source evidence;
- near-miss / missing-detail queries;
- relation mismatch;
- high lexical-overlap unsupported questions.

All content is synthetic/project-style. It does not read the owner's production memory database.

Automated tests assert that no query string is reused from the retired V1 corpus.

## Production retrieval path under test

The final harness uses the real implementation path:

```text
fresh query
 -> Qwen3-Embedding-0.6B query vector
 -> canonical current/authority/sensitivity eligibility
 -> SQLite FTS5 lexical rank
 -> exact stored dense cosine rank
 -> equal-weight RRF
 -> top 3 eligible candidates
 -> Qwen3-Reranker-0.6B BF16
 -> frozen JARVIS memory reranker instruction
 -> score + top1/top2 margin
 -> MAPIE-selected release rule
```

The harness uses a temporary migrated SQLite database and the production lifecycle/storage/retrieval classes. It does not touch owner production memory.

## Pre-registered release-rule family

Features:

1. Qwen reranker top-1 raw score;
2. top-1 minus top-2 reranker-score margin.

Release rule:

```text
release = top_score >= score_threshold
          AND top1_minus_top2 >= margin_threshold
```

No dense-score threshold is added in this final experiment because the instruction bake-off materially improved reranker confidence ordering and keeping the final rule two-dimensional limits multiple-testing cost and production complexity.

## Pre-registered candidate grid

The fresh corpus cannot change this grid.

Score thresholds:

```text
-2, 0, 2, 4, 6, 8
```

Margin thresholds:

```text
0, 4, 8, 12, 16
```

Cartesian product:

- 30 candidate policies.

The grid was chosen before fresh-corpus scoring using only retired V1 development evidence and engineering simplicity.

## MAPIE calibration contract

Frozen values:

- controlled metric: precision;
- target precision: `0.95`;
- confidence level: `0.95`;
- secondary objective among valid policies: recall;
- FWER method: `bonferroni_holm`;
- candidates: the fixed 30 score/margin pairs above.

If MAPIE finds no valid parameter pair, that is a legitimate fail-closed outcome.

## Held-out acceptance gates

MAPIE validity is necessary but not sufficient.

The frozen policy must additionally satisfy all of these on the untouched 128-case validation split:

1. MAPIE produced a valid score/margin policy;
2. positive top-1 retrieval accuracy >= `0.85`;
3. positive Recall@3 >= `0.90`;
4. observed false releases = `0`;
5. positive release recall >= `0.40`;
6. positive release recall for **each** language >= `0.25`.

A release-labeled query whose top-1 memory is wrong is labelled unsafe for release and counts as a false release if the policy releases it.

This prevents high model confidence from hiding a retrieval-ranking error.

## Result artifact

Default output:

- `.step4-phase45d-final-acceptance.json`.

The artifact records:

- fixed corpus SHA-256;
- corpus/split/language counts;
- calibration and validation ranking quality;
- all 30 tested MAPIE parameters;
- MAPIE-valid parameters;
- selected parameter pair or no-policy result;
- calibration and validation policy metrics;
- per-language and per-category breakdowns;
- all case-level top IDs/scores/margins/dense/rank evidence;
- query/retrieval/reranker timing;
- CUDA peak allocation;
- each acceptance gate.

The JSON is evidence even when the process exits non-zero because acceptance failed.

## One-run rule

Once the fresh final owner run produces a valid result JSON:

- do not rerun it to chase a pass;
- do not change thresholds, language floors, the candidate grid, or query labels based on held-out failures;
- treat a failure as architecture/retrieval evidence and research the underlying cause before defining any genuinely new evaluation protocol.

## Next gate

Run the final harness once on the accepted owner RTX 5060 Ti environment after repository CI is green on the exact owner-run SHA.

Phase 4.5E remains blocked until this fresh Phase 4.5D acceptance passes.
