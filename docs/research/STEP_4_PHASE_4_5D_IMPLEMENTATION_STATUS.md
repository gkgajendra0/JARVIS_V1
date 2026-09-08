# Step 4 — Phase 4.5D Abstention Calibration Implementation Status

Date: 2026-09-06

## Status

**ACTIVE — V1 POLICY REJECTED / JARVIS RERANKER INSTRUCTION SELECTED / FRESH FINAL ACCEPTANCE IMPLEMENTED / OWNER RTX RUN NEXT.**

Phase 4.5D has completed the development/model-selection work required before final release-policy acceptance.

The final acceptance protocol is now frozen before fresh-corpus model execution.

## V1 owner measurement — complete / rejected

The first successful 64-query owner measurement completed on the accepted RTX environment.

Selected V1 policy:

- family `score_margin`;
- score threshold `8.96875`;
- margin threshold `9.15625`.

Held-out V1 result:

- `tp=3`;
- `fp=0`;
- observed precision `1.0`;
- positive release recall `0.1875`;
- English release recall `0.166667`;
- Hindi release recall `0.0`;
- Hinglish release recall `0.333333`.

The policy is too conservative for production and is permanently rejected.

The V1 corpus is now development-only because its former held-out labels/results have been exposed.

Owner record:

- `docs/research/STEP_4_PHASE_4_5D_OWNER_MEASUREMENT_V1.md`.

## Secret-boundary fixture correction — complete

The first V1 attempt failed before measurement because the fixture tried to create `SECRET_PROHIBITED` canonical semantic memory.

That production constructor invariant was correct and remains unchanged.

Research fixtures now:

- preserve secret entries only as non-canonical corpus markers;
- exclude them before semantic-memory creation;
- forbid release-labelled cases from targeting them;
- record their exclusion in output evidence.

No secret-prohibited canonical-memory path was introduced.

## Reranker instruction selection — complete

Qwen3-Reranker is instruction-aware, so Phase 4.5D compared the generic model default with exactly one pre-registered JARVIS-memory instruction using the retired V1 corpus as a development set.

Selected instruction:

```text
Judge whether the memory Document directly and sufficiently answers the JARVIS memory Query using only facts stated in the Document. Answer yes only when the Document supports the specific fact or relation requested; answer no when it is merely related, missing the requested detail, contradictory, negated, or otherwise does not answer the Query.
```

Owner development result:

| Metric | Generic default | JARVIS instruction |
|---|---:|---:|
| positive top-1 accuracy | 0.90625 | 0.90625 |
| positive Recall@3 | 0.90625 | 0.90625 |
| score AUROC safe-vs-unsafe | 0.918719 | **0.936453** |
| margin AUROC | 0.768966 | **0.795074** |
| AURC | 0.267634 | **0.242616** |
| zero-error positive-release recall | 0.03125 | **0.1875** |

Language top-1 accuracy was unchanged:

- English `0.933333`;
- Hindi `1.0`;
- Hinglish `0.833333`.

There was no material latency penalty.

Decision:

- `Qwen3RetrievalReranker` now uses the JARVIS instruction by default;
- generic Qwen instruction behavior remains only through explicit `instruction=None` for research/reproduction.

Record:

- `docs/research/STEP_4_PHASE_4_5D_RERANKER_INSTRUCTION_SELECTION.md`.

## Final risk-control technology — frozen

Research selected MAPIE `1.5.0` and `BinaryClassificationController` Learn-Then-Test precision control instead of another custom threshold sweep.

MAPIE is a research/calibration dependency only:

- `tools/research/requirements-step4-risk-control.txt`.

Production inference will not depend on MAPIE. If acceptance passes, production receives only the frozen versioned release rule.

Final calibration controls:

- metric: precision;
- target precision `0.95`;
- confidence level `0.95`;
- secondary objective: recall;
- FWER procedure: Holm-Bonferroni;
- pre-registered two-dimensional score/margin grid.

MAPIE may legitimately return no valid policy; that is a fail-closed outcome.

## Statistical limitation — explicit

MAPIE's formal distributional guarantees require assumptions such as exchangeability.

The final JARVIS corpus is synthetic and cannot prove exchangeability with future owner conversations.

Therefore this work claims only disciplined finite-sample benchmark acceptance, not a real-world 95% traffic guarantee.

Post-deployment shadow-labelled observations and drift/risk review remain required.

## Fresh final corpus — implemented/frozen

Generator:

- `tools/research/step4_phase45d_final_cases.py`.

Total: **320 new queries**.

Calibration:

- 192 cases;
- 96 release;
- 96 abstain.

Held-out validation:

- 128 cases;
- 64 release;
- 64 abstain.

Both splits contain:

- English;
- Hindi;
- Hinglish.

The benchmark includes:

- current facts;
- historical transitions;
- forgotten facts;
- `LOCAL_ONLY` facts;
- non-canonical secret markers;
- untrusted evidence;
- near-miss / missing-detail questions;
- relation mismatch;
- adversarial high-lexical-overlap unsupported questions.

Automated guards prove the final query set has no exact query-string reuse from the retired V1 corpus.

The payload SHA-256 is emitted by the owner result artifact.

## Final release-rule family — frozen

Features:

1. reranker top-1 raw score;
2. reranker top-1 minus top-2 score margin.

Rule:

```text
release = score >= score_threshold
          AND margin >= margin_threshold
```

Pre-registered score values:

- `-2, 0, 2, 4, 6, 8`.

Pre-registered margin values:

- `0, 4, 8, 12, 16`.

Total candidate policies:

- `30`.

The fresh corpus cannot alter this grid.

## Final held-out acceptance gates — frozen

The selected calibration-only policy must satisfy all of these on untouched validation:

1. MAPIE finds a valid policy;
2. positive top-1 retrieval accuracy >= `0.85`;
3. positive Recall@3 >= `0.90`;
4. observed false releases = `0`;
5. positive release recall >= `0.40`;
6. positive release recall for every language >= `0.25`.

A release-labelled query with the wrong top-1 memory is unsafe and counts as a false release if the policy releases it.

## Final harness — implemented

Harness:

- `tools/research/step4_phase45d_final_acceptance.py`.

It uses the actual production path against a temporary migrated database:

- `MemoryLifecycleService`;
- `SemanticEmbeddingStore`;
- `SemanticRetrievalService`;
- `RetrievalEligibility.cloud_context()`;
- revision-pinned `Qwen3EmbeddingEncoder`;
- revision-pinned top-3 `Qwen3RetrievalReranker`;
- frozen JARVIS reranker instruction.

It does not read or mutate owner production memory.

Result artifact:

- `.step4-phase45d-final-acceptance.json`.

The artifact is valid evidence even when acceptance fails and the harness exits non-zero.

## Automated guards

Final acceptance tests cover:

- exact `320` query count;
- `96/96` calibration balance;
- `64/64` validation balance;
- English/Hindi/Hinglish in both splits;
- required lifecycle/security boundary modes;
- deterministic corpus SHA;
- retired-V1 query disjointness;
- exact 30-point pre-registered policy grid;
- score+margin release semantics;
- wrong top-1 release counted as false release;
- fail-closed false-release and language-starvation gates.

## Authority/security boundaries

Phase 4.5D continues to enforce:

- no production canonical-memory mutation from research harnesses;
- no `SECRET_PROHIBITED` canonical memory;
- no cloud provider for local retrieval calibration;
- no second cloud subscription;
- no retrieval eligibility bypass;
- no implicit durable admission;
- no self-repair/code-modification authority;
- no post-hoc tuning against final held-out labels.

## Final method record

- `docs/research/STEP_4_PHASE_4_5D_FINAL_ACCEPTANCE_METHOD.md`.

## Next gate

Run the fresh final Phase 4.5D harness **once** on the accepted owner RTX 5060 Ti environment after the exact repository head passes Ruff, full pytest, Windows DPAPI, and Windows Hello.

Once a result JSON exists:

- do not rerun it to chase a pass;
- do not change thresholds or acceptance floors from held-out failures;
- analyze any failure as system/retrieval evidence.

Phase 4.5E remains blocked until this fresh final acceptance passes.
