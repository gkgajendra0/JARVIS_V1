# Step 4 Phase 4.5D — Gemini Single-Instance Boundary Diagnostic Result

## Status

**DEVELOPMENT RESULT COMPLETE — BATCHING CONFOUND CONFIRMED — GEMINI REMAINS A DEVELOPMENT CANDIDATE — V3 NOT YET AUTHORIZED**

This result is development-only. The V2 corpus is exposed and retired from acceptance. Nothing in this diagnostic is fresh acceptance evidence and it does not authorize Phase 4.5E.

## Owner run

Owner-run exact SHA:

`e645fe8ab469d962bc2bcc23f11db8da650d9279`

Output artifact:

`.step4-phase45d-v2-gemini-single-instance-boundary-diagnostic-v1.json`

Status:

`DEVELOPMENT_GEMINI_SINGLE_INSTANCE_BOUNDARY_DIAGNOSTIC_COMPLETE`

## Frozen diagnostic

The prior semantic-judge bake-off evaluated Gemini 3.5 Flash-Lite by packing 120 independent query/document classifications into each request. That run produced 125 validation false releases, all in the five deterministic boundary categories.

The follow-up diagnostic selected exactly 15 already-exposed validation cases:

- historical × EN / HI / Hinglish;
- forgotten × EN / HI / Hinglish;
- local-only × EN / HI / Hinglish;
- secret × EN / HI / Hinglish;
- untrusted × EN / HI / Hinglish.

Every selected source case had been `RELEASE` under the prior batch-120 request shape.

The retrieval side was held fixed:

- canonical lifecycle and eligibility filtering;
- `RetrievalEligibility.cloud_context()`;
- Qwen3-Embedding-0.6B, frozen 256d contract;
- first-stage top-10 candidate window;
- frozen Qwen3-Reranker-0.6B instruction;
- same selected Top-1 memory as the source artifact.

Only the Gemini request shape changed: **one query/document pair per request**.

## Exact result

Summary:

```text
cases: 15
prior_batch_release: 15
single_instance_release: 0
single_instance_abstain: 15
release_to_abstain_flips: 15
batching_confound_observed: true
all_target_boundaries_abstained_single_instance: true
```

By category:

| Category | Cases | Single-instance RELEASE | Single-instance ABSTAIN |
|---|---:|---:|---:|
| historical | 3 | 0 | 3 |
| forgotten | 3 | 0 | 3 |
| local_only | 3 | 0 | 3 |
| secret | 3 | 0 | 3 |
| untrusted | 3 | 0 | 3 |

By language:

| Language | Cases | Single-instance RELEASE | Single-instance ABSTAIN |
|---|---:|---:|---:|
| EN | 5 | 0 | 5 |
| HI | 5 | 0 | 5 |
| Hinglish | 5 | 0 | 5 |

## Decision

The preregistered interpretation is satisfied in the strongest possible way:

- all 15 prior batch-120 `RELEASE` decisions flipped to `ABSTAIN`;
- the effect appears in every targeted boundary category;
- the effect appears in every targeted language;
- therefore request shape materially changes Gemini semantic-judge behavior on this task.

The prior batch-120 false-release pattern **must not be treated as production-equivalent evidence**. Production JARVIS will judge one live query/document pair at a time.

This result does **not** prove that single-instance Gemini is ready for final acceptance. Because request shape demonstrably matters, the batch-120 successes on positive and ordinary semantic-abstain cases also cannot be blindly assumed to transfer unchanged.

## Research alignment

The observed result is consistent with current external evidence:

- ACL 2026 reports that multi-instance LLM processing begins to degrade at roughly 20–100 instances and can collapse at larger instance counts: https://aclanthology.org/2026.acl-long.1470/
- Google documents that structured output guarantees syntax, not semantic correctness, and application-level validation remains required: https://ai.google.dev/gemini-api/docs/structured-output
- MAPIE now provides an explicit LLM-as-a-judge-with-abstention risk-control example, supporting held-out statistical control rather than empirical threshold tuning: https://mapie.readthedocs.io/en/latest/generated/risk_control/2-advanced-analysis/plot_risk_control_llm_as_a_judge/

## Next development step

Do **not** rerun the 1,800-case Gemini bake-off.

Run one bounded production-shape coverage diagnostic on the already-exposed V2 validation set:

- one positive case per language = 3 cases;
- seven ordinary semantic abstain categories × three languages = 21 cases;
- total = 24 new single-instance Gemini calls;
- combine those results with the already-completed 15 boundary cells.

If all 24 preserve the previously correct batch decisions, the combined development evidence covers all 13 semantic/category families across EN/HI/Hinglish in production-shaped single-instance mode and Gemini may be selected for **fresh V3 design**.

Any single-instance regression blocks V3 and triggers architecture review before moving to multilingual NLI/grounding.

Phase 4.5E remains blocked.