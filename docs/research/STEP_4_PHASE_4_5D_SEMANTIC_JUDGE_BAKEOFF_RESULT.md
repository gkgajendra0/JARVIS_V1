# Step 4 Phase 4.5D — Semantic Judge Bake-off Result

## Status

**DEVELOPMENT RESULT — COMPLETED — NO V3 FREEZE AUTHORIZED**

This result uses the fully exposed and retired V2 corpus for development architecture selection only. It is **not final acceptance evidence** and does not authorize Phase 4.5E.

## Owner run

Owner-run repository SHA:

`cdbc89a51728c8134e5182980b6885f2d2ccfa91`

Owner output:

`.step4-phase45d-v2-semantic-judge-bakeoff-v1.json`

Harness:

`tools/research/step4_phase45d_semantic_judge_bakeoff.py`

Gemini request settings used for the completed run:

- model: `gemini-3.5-flash-lite`
- cases per Gemini request: `120`
- concurrency: `4`
- request-start cap: `12 RPM`
- structured JSON output
- same frozen semantic-sufficiency system instruction used throughout the bake-off

The larger batch was introduced only to remain within the observed free-tier request-rate boundary after an earlier batch-8 run terminated with HTTP 429. No semantic labels, corpus rows, model revisions, prompts, thresholds, or acceptance targets were changed for the completed run.

## Retrieval result

The already-selected Qwen retrieval/rerank path reproduced the post-V2 depth result exactly:

| Split | Positive Top-1 | Accuracy |
|---|---:|---:|
| Overall | 900 / 900 | 1.000000 |
| Calibration | 600 / 600 | 1.000000 |
| Validation | 300 / 300 | 1.000000 |

This further confirms that, with candidate depth 10 on the exposed V2 corpus, the remaining 4.5D problem is semantic release/abstention rather than positive retrieval ranking.

## GLiClass result

Local model:

`knowledgator/gliclass-multilang-mini`

Revision:

`c09fb5ca4cb7957044168e6bf8bcefa2e14b8dfb`

The frozen empirical calibration procedure found **no GLiClass margin threshold** reaching the required development precision target.

Result:

- selected threshold: `null`
- validation releases: `0`
- validation positive release recall: `0.0`
- development candidate: **NO**

GLiClass is therefore rejected for the current Phase 4.5D semantic-sufficiency role. Do not lower the precision floor or tune on V2 validation to rescue it.

## Gemini batch-120 result

Validation:

- TP: `300`
- FP: `125`
- released: `425`
- precision: `300 / 425 = 0.705882`
- positive release recall: `1.000000`
- language recall floor: passed in the completed harness
- zero-security-boundary-release gate: failed

All `300` validation positives were released.

The `125` validation false releases were distributed **exactly** as:

| Category | False releases |
|---|---:|
| historical | 25 |
| forgotten | 25 |
| local_only | 25 |
| secret | 25 |
| untrusted | 25 |
| **Total** | **125** |

The V2 validation abstain partition contains `25` cases for each of 12 categories. Therefore the completed result also implies that Gemini produced **zero false releases across all 175 ordinary semantic abstain cases** in these seven categories:

- absent
- near_miss
- ambiguous
- adversarial_lexical
- negation
- relation_mismatch
- unsupported_source

This does **not** make the 125 boundary false releases irrelevant. Canonical eligibility correctly excludes forbidden/forgotten/non-current/non-cloud-eligible target memory before ranking, but the semantic verifier must still reject an eligible fallback document when that fallback does not answer the query.

## Why the batch-120 Gemini result is not yet production-shape evidence

The completed result has an unusually structured failure pattern: every ordinary semantic validation abstain was handled correctly, every positive was released, and every validation case from the five deterministic boundary groups was released.

The production semantic verifier, however, will judge **one live retrieval query/document pair at a time**. The completed development run packed 120 independent classifications into one model request to satisfy the free-tier request-rate constraint.

Current external research provides a concrete reason to treat that request shape as a possible confound before rejecting Gemini:

1. Chen, Pilehvar, and Camacho-Collados, ACL 2026, *Understanding LLM Performance Degradation in Multi-Instance Processing: The Roles of Instance Count and Context Length* reports slight degradation at roughly 20–100 instances followed by larger degradation/collapse at higher instance counts, with instance count exerting a stronger effect than context length in their evaluation.
   - https://aclanthology.org/2026.acl-long.1470/
2. Google Gemini structured-output documentation supports structured classification and schema-constrained output, but explicitly notes that schema validity does not guarantee semantically correct values and applications must validate model outputs.
   - https://ai.google.dev/gemini-api/docs/structured-output

These sources do not prove that Gemini's 125 misses were caused by batching. They do establish enough external-validity risk that the 120-instance result should not be assumed equivalent to the single-instance production role.

## Decision

### Frozen conclusions from this run

- Top-10 Qwen retrieval/reranking remains the development retrieval path.
- GLiClass is not a viable current release verifier under the frozen precision requirement.
- The completed batch-120 Gemini policy fails the original development gates and cannot be frozen for V3.
- Do not retune V2 or lower precision/recall/security floors.
- Do not generate V3 yet.
- Do not start Phase 4.5E.

### Required next diagnostic

Run a **small production-shape Gemini single-instance boundary diagnostic** using only already-exposed V2 development cases:

- 15 cases total;
- 5 boundary categories × 3 languages;
- exactly one deterministic validation case per category/language cell;
- every selected case must have been RELEASE under the batch-120 source artifact;
- reproduce the same eligible Qwen top-10 + reranked Top-1 document;
- call Gemini with exactly **one query/document case per request**;
- same Gemini model and frozen semantic-sufficiency instruction;
- no GLiClass;
- no threshold fitting;
- no fresh acceptance data;
- no V3 claim.

Diagnostic implementation:

`tools/research/step4_phase45d_gemini_single_instance_boundary_diagnostic.py`

Expected output:

`.step4-phase45d-v2-gemini-single-instance-boundary-diagnostic-v1.json`

Interpretation:

- Any RELEASE→ABSTAIN flips demonstrate that the 120-instance request shape affected behavior and therefore cannot be treated as production-equivalent evidence.
- Zero single-instance releases across all 15 targeted boundary cells would support continuing Gemini as a **development candidate**, but still would not constitute V3 acceptance.
- Any remaining single-instance RELEASE is a genuine targeted boundary miss under the production-shaped diagnostic and requires architecture review before V3; multilingual NLI/grounding remains the next research-first fallback if needed.

## Security / authority reminder

The verifier remains a derived release gate only. It must never establish canonical truth, resurrect forgotten memory, override lifecycle state, expose secret/local-only memory to cloud context, or elevate untrusted provenance. Deterministic eligibility remains authoritative before semantic scoring.
