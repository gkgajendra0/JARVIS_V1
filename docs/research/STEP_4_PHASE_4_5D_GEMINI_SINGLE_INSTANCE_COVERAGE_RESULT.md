# Step 4 Phase 4.5D — Gemini Single-Instance Coverage Result

Status: **DEVELOPMENT DIAGNOSTIC COMPLETE — GEMINI SELECTED FOR FRESH V3 DESIGN**

This result is development-only architecture-selection evidence. It is **not** final Phase 4.5D acceptance evidence and does **not** authorize Phase 4.5E.

## Owner run

Owner-run branch:

`implementation/step-4-memory-context`

Owner-run exact SHA:

`a3f6fc66647b03a2441f96d0fd8c703d86fb6dda`

Command:

```powershell
python tools\research\step4_phase45d_gemini_single_instance_coverage_diagnostic.py `
    --device cuda `
    --gemini-rpm 12
```

Output artifact:

`.step4-phase45d-v2-gemini-single-instance-coverage-diagnostic-v1.json`

The artifact is based on the already-exposed V2 corpus and therefore can never become fresh acceptance evidence.

## Frozen purpose

The preceding 15-case boundary diagnostic proved that the earlier 120-cases-per-request Gemini evaluation was materially confounded by request shape: all 15 targeted boundary cases flipped from batch-120 `RELEASE` to production-shaped single-instance `ABSTAIN`.

The coverage diagnostic was preregistered to answer the remaining question: does the single-instance request shape preserve cases that the batch-120 run had already judged correctly?

It added exactly 24 already-exposed V2 validation cases and did not rerun the 15 boundary calls:

- 3 positive cases: one English, one Hindi and one Hinglish;
- 21 ordinary semantic abstentions:
  - `absent`;
  - `near_miss`;
  - `ambiguous`;
  - `adversarial_lexical`;
  - `negation`;
  - `relation_mismatch`;
  - `unsupported_source`;
- every ordinary abstain family appeared once in English, Hindi and Hinglish.

The only semantic-judge request shape allowed was one query/document pair per Gemini request.

## Exact owner result

```text
STATUS: DEVELOPMENT_GEMINI_SINGLE_INSTANCE_COVERAGE_DIAGNOSTIC_COMPLETE
SUMMARY: {"cases": 24, "positive_cases": 3, "ordinary_abstain_cases": 21, "preserved_correct_decisions": 24, "regressions": 0, "all_coverage_cells_correct_single_instance": true, "by_language": {"en": {"cases": 8, "preserved": 8, "regressions": 0}, "hi": {"cases": 8, "preserved": 8, "regressions": 0}, "hinglish": {"cases": 8, "preserved": 8, "regressions": 0}}, "by_family": {"positive": {"cases": 3, "preserved": 3, "regressions": 0}, "absent": {"cases": 3, "preserved": 3, "regressions": 0}, "near_miss": {"cases": 3, "preserved": 3, "regressions": 0}, "ambiguous": {"cases": 3, "preserved": 3, "regressions": 0}, "adversarial_lexical": {"cases": 3, "preserved": 3, "regressions": 0}, "negation": {"cases": 3, "preserved": 3, "regressions": 0}, "relation_mismatch": {"cases": 3, "preserved": 3, "regressions": 0}, "unsupported_source": {"cases": 3, "preserved": 3, "regressions": 0}}}
DECISION: {"boundary_cells_correct": 15, "coverage_cells_correct": 24, "combined_production_shape_cells": 39, "combined_all_cells_correct": true, "gemini_selected_for_v3_design": true, "v3_is_acceptance_complete": false, "phase45e_authorized": false}
```

## Interpretation

The preregistered selection rule passed exactly:

- coverage cells preserved: **24/24**;
- coverage regressions: **0**;
- English: **8/8**;
- Hindi: **8/8**;
- Hinglish: **8/8**;
- positive: **3/3**;
- all seven ordinary semantic abstain families: **3/3 each**.

Combined with the completed boundary diagnostic:

- boundary cells correct: **15/15**;
- additional coverage cells correct: **24/24**;
- combined production-shaped development cells: **39/39**;
- combined regressions: **0**.

This is sufficient to select **Gemini 3.5 Flash-Lite, one query/document pair per Interactions API request**, as the semantic judge architecture to take into a completely fresh V3 acceptance design.

It does **not** establish a 95% precision guarantee, does not make the exposed V2 corpus fresh again, and does not prove exchangeability with future owner traffic.

## Development architecture selected for V3 design

The selected development pipeline is:

```text
canonical eligibility / security authority
→ eligible-current SQLite FTS5 + Qwen3-Embedding-0.6B 256d exact cosine
→ equal-weight RRF
→ candidate window 10
→ Qwen3-Reranker-0.6B with frozen JARVIS instruction
→ selected Top-1 eligible memory
→ Gemini 3.5 Flash-Lite semantic sufficiency judge
→ exactly one query/document pair per Interactions API request
→ structured RELEASE / ABSTAIN
```

The semantic judge has no mutation authority and cannot create, modify, resurrect or override canonical memory truth.

## Research alignment

The production-shape decision is consistent with the external research already used to motivate the diagnostic:

- Google documents `gemini-3.5-flash-lite` as a stable GA model and a cost-efficient high-throughput model: https://ai.google.dev/gemini-api/docs/models
- Google structured-output guidance supports classification but explicitly requires application validation of semantic values: https://ai.google.dev/gemini-api/docs/structured-output
- MAPIE 2026 documents risk control for LLM-as-a-judge with abstention, but that example assumes model probability scores that can be thresholded: https://mapie.readthedocs.io/en/latest/generated/risk_control/2-advanced-analysis/plot_risk_control_llm_as_a_judge/

The JARVIS Gemini judge currently exposes a fixed hard `RELEASE` / `ABSTAIN` decision rather than a validated calibrated probability score. Therefore final V3 precision control must not fabricate a confidence score merely to reuse a threshold-search method.

## Decision

**Gemini single-instance is selected for fresh V3 design.**

Next:

1. freeze the complete V3 method before generating or exposing V3 validation results;
2. create a completely fresh corpus with new facts, profiles and query wording;
3. keep calibration and validation separated before owner execution;
4. statistically certify the fixed release policy using fresh calibration;
5. expose fresh validation once;
6. keep Phase 4.5E blocked until V3 passes every frozen acceptance gate.
