# Step 4 Phase 4.5D — Gemini 3.8 Calibration Diagnostic Method

Status: **FROZEN DEVELOPMENT METHOD**

This diagnostic is authorized only because fresh V3 acceptance failed calibration. It uses only the already exposed V3 calibration split. It is not acceptance evidence and must never access V3 validation.

## Question

Does the current GA `gemini-3.8-flash` model materially improve the failed V3 semantic release gate when every other production-shaped variable is held fixed?

## Why this model is the next candidate

Google released Gemini 3.8 Flash on September 2, 2026 and describes it as its most intelligent Flash model, designed for complex enterprise workflows with higher factual rigor. It is stable/GA, supports the Interactions API, structured outputs and thinking levels, and is currently offered at introductory pricing through December 31, 2026.

Official references:

- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- https://ai.google.dev/gemini-api/docs/latest-model
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/thought-signatures

The existing V3 judge used `gemini-3.5-flash-lite`, which Google positions as the fastest/cost-efficient model for high-volume automation and simple processing. The V3 failure is therefore sufficient evidence to test the materially stronger current Flash model before building custom semantic logic.

## Frozen one-variable comparison

Keep unchanged:

- V3 payload SHA-256 `baac40840bc260a01f4fc630570e4578dbdf8dc9f36c8b3192c6bb6471191195`;
- calibration split only: `360` cases;
- canonical lifecycle and security eligibility;
- Qwen3-Embedding-0.6B revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- normalized 256-dimensional query/document embeddings;
- eligible FTS5 + exact cosine + equal-weight RRF, `k=60`;
- candidate window `10`;
- Qwen3-Reranker-0.6B revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- frozen JARVIS reranker instruction;
- exactly one query/document pair per Gemini request;
- Interactions API;
- same semantic sufficiency system instruction;
- same RELEASE/ABSTAIN + failure-mode structured schema;
- `store=False`;
- no temperature/top-p/top-k tuning;
- no threshold fitting;
- no validation data.

Change only:

- semantic judge model: `gemini-3.8-flash`;
- thinking level: `medium` (Google's default balanced quality setting for 3.8 Flash).

## Source evidence requirement

The diagnostic requires the original owner-local V3 artifact:

`.step4-phase45d-final-v3-acceptance.json`

It must prove:

- `status == FAIL_CALIBRATION`;
- `validation_executed == false`;
- V3 corpus SHA matches the frozen value;
- owner-run SHA is `783a5b49cdf31a957c403066f1ea421c007354a4`;
- exactly `360` public cases exist and all are calibration cases;
- the recorded V3 calibration failure set is preserved.

The harness reruns the deterministic V3 calibration retrieval and must reproduce the artifact's Top-1 memory ID, Recall@10 flag and Top-1-correct flag for every case before any Gemini 3.8 call is accepted as comparable evidence.

## Statistical reporting

The diagnostic reuses the frozen V3 policy metrics and exact one-sided Clopper-Pearson calculation:

- target precision `0.95`;
- confidence `0.95`;
- minimum releases `59`.

These statistics are development evidence here because the V3 calibration set is already exposed.

It must also report:

- empirical precision;
- positive release recall;
- EN/HI/Hinglish positive release recall;
- false-release IDs and categories;
- security-boundary releases;
- corrections of prior V3 false releases;
- new false releases relative to V3;
- safe-release regressions relative to V3;
- per-request timing and token usage.

## Frozen development selection rule

`gemini-3.8-flash` is selected for **fresh V4 design** only if all are true on the exposed calibration diagnostic:

1. exact V3 retrieval reproduction succeeds for all 360 calibration cases;
2. exact one-sided 95% lower precision bound is at least `0.95`;
3. positive release recall is at least `0.40`;
4. EN/HI/Hinglish positive release recall each is at least `0.25`;
5. zero historical/forgotten/local-only/secret/untrusted releases;
6. no API/schema execution failure.

The result remains development-only even if every check passes.

## Interpretation

### If selected

Freeze a candidate V4 architecture with the same Qwen Top-10 retrieval/reranker and Gemini 3.8 Flash medium single-instance semantic judge. Then design a completely fresh V4 corpus before any acceptance run.

Do not use the untouched V3 validation split as V4 acceptance data.

### If rejected

Do not cycle through more generic relevance models or prompt tweaks.

Research and prototype the structure-aware architecture already supported by mature retrieval practice:

1. parse the user's memory query into structured subject / relation / temporal-scope / source-scope constraints;
2. apply those constraints deterministically against canonical assertion metadata before semantic release;
3. use semantic ranking only inside the eligible structured candidate set;
4. if an additional verifier is still required, evaluate multilingual NLI/entailment as a secondary task-matched guard rather than another relevance score.

This direction follows the same architecture used by mature self-query/auto-retrieval systems, where an LLM infers metadata filters and deterministic retrieval executes those filters.
