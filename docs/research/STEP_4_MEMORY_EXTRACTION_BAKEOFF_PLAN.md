# Step 4 — Structured Memory-Candidate Extraction Bake-off Plan

## Status

**RESEARCH PLAN — NOT FINAL STEP-4 ARCHITECTURE APPROVAL AND NOT AUTHORIZATION TO WRITE PRODUCTION MEMORY.**

This plan follows the completed retrieval technology selection and compares mature provider-native structured-output APIs before implementing any runtime `MemoryCandidateExtractor`.

## Current provider research (2026-09-04)

### OpenAI

Current OpenAI API documentation recommends JSON-Schema Structured Outputs over legacy JSON mode. The official Python SDK supports Pydantic parsing through `client.responses.parse(..., text_format=...)`.

Quality-first initial model:

- `gpt-5.6-terra`
- positioned by OpenAI as the balance of intelligence and cost;
- pricing snapshot: $2 / 1M input tokens and $12 / 1M output tokens.

A later cost-down comparison may test `gpt-5.6-luna` ($0.20 / 1M input, $1.20 / 1M output) only if the quality-first run demonstrates that the task can safely be down-tiered.

References:

- https://platform.openai.com/docs/models
- https://github.com/openai/openai-python/blob/main/examples/responses/structured_outputs.py

### Gemini

Google's current Gemini API Structured Outputs support JSON Schema and Pydantic-generated schemas. The current Interactions API accepts `system_instruction`, `response_format`, `store=False`, and returns token usage.

Google released `gemini-3.8-flash` as GA in September 2026; it supports Structured Outputs and is the current most intelligent stable Flash model.

Quality-first initial model:

- `gemini-3.8-flash`
- introductory pricing through 2026-12-31: $0.75 / 1M input tokens and $3.75 / 1M output tokens.

A later cost-down comparison may test `gemini-3.5-flash-lite` ($0.30 / 1M input, $2.50 / 1M output) only if quality evidence supports doing so.

References:

- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/text-generation

## Why quality-first models are tested first

Memory admission errors have asymmetric cost:

- a missed low-confidence candidate is recoverable later;
- a false durable write can poison long-term personal context, persist across sessions, and bias future answers.

Therefore the first bake-off uses stable quality-oriented models. Cost-down variants are evaluated only after the semantic/safety bar is demonstrated.

## Shared provider-independent contract

Both providers receive the same Pydantic `MemoryExtraction` schema and the same policy instruction.

Core output fields include:

- `intent`;
- `candidate_type`;
- `durable_candidate`;
- `subject`;
- `predicate`;
- `value`;
- `temporal_hint`;
- `sensitivity`;
- `confidence`;
- short `rationale`.

The model never writes memory. It only proposes/classifies a candidate for later JARVIS policy.

## Existing fixed corpus

Reuse:

- `tools/research/step4_memory_extraction_cases.json`

The 24 cases already cover:

- explicit remember in English/Hindi/Hinglish;
- stable direct facts;
- weak preferences;
- transient task/style context;
- temporary mood;
- historical change;
- correction and retraction;
- explicit forget;
- assistant-output poisoning;
- web/email/file poisoning;
- quoted/hypothetical remember text;
- uncertain future facts;
- episode decisions;
- incident/self-observation candidates;
- secret/password handling.

Do not replace this corpus merely because a provider performs poorly.

## Measured metrics

The harness records:

- schema-valid count/failures;
- intent accuracy;
- candidate-type accuracy;
- durable-flag accuracy;
- strict core exact accuracy (`intent + type + durable`);
- false durable writes among expected non-durable cases;
- missed durable candidates;
- explicit remember/correct/forget/retract recall;
- untrusted-source handling and false durable writes;
- secret-policy accuracy;
- English/Hindi/Hinglish breakdown;
- p50/p95/max latency;
- input/output token usage;
- same-day estimated token cost where pricing is known;
- per-case outputs for human inspection.

### Safety weighting

No overall model winner is chosen from raw average accuracy alone.

Highest-severity failures are:

1. untrusted external/assistant content becoming durable;
2. secret/password content becoming normal durable memory;
3. explicit forget/correction/retraction being misclassified;
4. transient/quoted/uncertain content becoming durable.

A provider with a higher average score but a false durable poisoning failure is not automatically preferred.

## Research isolation

Dependencies are isolated in:

- `tools/research/requirements-step4-extraction.txt`

Harness:

- `tools/research/step4_memory_extraction_bakeoff.py`

No dependency is added to production `pyproject.toml` by this research.

Both provider calls use `store=False`; no search, web, files, or tools are enabled.

## Initial run sequence

1. create `.step4-extraction-venv`;
2. install the pinned research-only dependencies;
3. run a 2-case smoke test for each provider;
4. if schema/API calls work, run the full 24-case OpenAI quality-first corpus;
5. run the full 24-case Gemini quality-first corpus;
6. compare semantic/safety correctness first, then latency/cost;
7. only then decide whether a cheaper-model cost-down run is justified.

No production extractor/provider decision is made before the measured results are recorded.
