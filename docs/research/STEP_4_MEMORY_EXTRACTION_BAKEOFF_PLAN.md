# Step 4 — Structured Memory-Candidate Extraction Bake-off Plan

## Status

**ACTIVE PHASE-4.4 RESEARCH PLAN — NOT AUTHORIZATION TO WRITE PRODUCTION MEMORY.**

Date refreshed: 2026-09-05

This plan validates the Phase-4.4 `MemoryCandidateExtractor` against the production contract while obeying ADR-015: JARVIS has one active cloud-AI provider/account at a time. The active provider is currently Gemini, so this phase does not require or compare an OpenAI account.

Implicit durable admission remains OFF. The model may only propose a temporary candidate for JARVIS-owned quarantine.

## Current Gemini research refresh

### Primary candidate — Gemini 3.5 Flash-Lite

Google documents `gemini-3.5-flash-lite` as a stable GA, low-latency and cost-effective model optimized for high-throughput work, subagent tasks, document parsing and simple data extraction. Structured outputs are supported.

This is the closest fit to Phase 4.4 because the job is narrow schema-constrained classification/extraction, not long-horizon reasoning.

Current pricing snapshot:

- Free Tier: free of charge within applicable quota;
- paid input: $0.30 / 1M tokens;
- paid output, including thinking tokens: $2.50 / 1M tokens.

Google's deprecation page lists no shutdown date for `gemini-3.5-flash-lite`.

Primary references:

- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/deprecations
- https://ai.google.dev/gemini-api/docs/changelog

**Disposition: TEST FIRST.**

### Escalation candidate — Gemini 3.8 Flash

Google documents `gemini-3.8-flash` as its most intelligent stable Flash model, aimed at long-horizon software engineering, autonomous agents and complex enterprise workflows. Structured outputs are supported.

That makes it a useful quality ceiling, but it is broader than the normal Phase-4.4 extraction requirement. It should consume quota only if Flash-Lite fails the fixed safety/correctness gate.

Primary references:

- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- https://ai.google.dev/gemini-api/docs/latest-model
- https://ai.google.dev/gemini-api/docs/pricing

**Disposition: ESCALATION ONLY.**

### Models not selected for this new commitment

`gemini-3.1-flash-lite` is not selected because Google has announced a May 7, 2027 earliest shutdown date and explicitly recommends `gemini-3.5-flash-lite` as its replacement.

`gemini-3.5-flash` is not the preferred escalation path for this narrow job. It is more expensive than Flash-Lite, while the newer 3.8 Flash provides the stronger quality ceiling if escalation becomes necessary.

## Why the experiment is staged rather than broad

The goal is not to find the globally strongest model. The goal is to find the cheapest, fastest model inside the already selected provider account that safely satisfies JARVIS's exact extraction contract.

Therefore:

1. test `gemini-3.5-flash-lite` first;
2. stop if it satisfies the fixed safety/correctness gate;
3. run `gemini-3.8-flash` only if Lite produces a material semantic/safety failure;
4. do not add another cloud provider merely to improve this subsystem.

This reduces API spend, avoids a subscription/provider zoo and keeps production debugging under one provider boundary.

## Shared production contract

The harness imports the production Pydantic schema:

- `jarvis.memory.candidates.MemoryExtractionProposal`

and the production instruction:

- `jarvis.memory.extractors.MEMORY_EXTRACTION_SYSTEM_PROMPT`

Core semantic output fields are:

- `intent`;
- `candidate_type`;
- `durable_candidate`;
- `subject`;
- `predicate`;
- `value`;
- `temporal_hint`;
- `sensitivity`;
- `confidence`.

The provider cannot write memory and cannot author JARVIS provenance or authority.

## Production-aligned pre-provider gates

The benchmark mirrors the same ordering as production:

1. only canonical accepted USER turns are eligible;
2. explicit Phase-4.3 remember/correct/forget controls are handled by the governed explicit-memory path and do not reach the extractor;
3. locally recognizable credentials/secrets are rejected before a provider call;
4. only remaining direct-user utterances reach Gemini.

Assistant output, web content, email content and file/document content are tested as deterministic source-boundary rejections rather than asking the LLM to decide source authority.

## Fixed corpus

Reuse without provider-specific edits:

- `tools/research/step4_memory_extraction_cases.json`

The corpus covers English, Hindi and Hinglish plus facts, preferences, transient state, uncertainty, historical change, corrections/retractions, meaningful decisions/incidents, explicit memory controls, external-source poisoning and credentials/secrets.

Do not rewrite the corpus merely because a model performs poorly.

## Measured evidence

The production-aligned harness records:

- schema-valid count/failures;
- intent accuracy;
- candidate-type accuracy;
- durable-flag accuracy;
- strict core exact accuracy (`intent + type + durable`);
- false durable proposals among expected non-durable cases;
- missed durable candidates;
- English/Hindi/Hinglish breakdown;
- p50/p95/max provider latency;
- input/output token usage when exposed by the API;
- per-case outputs for human inspection.

## Acceptance priority

Safety and semantic correctness outrank average score, latency and price.

Before selecting Flash-Lite, require at minimum:

- zero provider/schema failures on the fixed provider-eligible corpus;
- zero false durable proposals on expected non-durable provider-eligible cases;
- no secret or explicit-memory-control bypass of the deterministic pre-provider gates;
- no source-authority bypass;
- human review of every core classification mismatch, especially correction/retraction/uncertainty cases;
- acceptable English, Hindi and Hinglish behavior.

A missed low-confidence candidate is less harmful than a false durable proposal. No implicit candidate is admitted to canonical memory in Phase 4.4 regardless of model score.

No arbitrary latency threshold is selected before measurement. Latency is evidence because extraction runs off the response path.

## Research isolation

Harness:

- `tools/research/step4_memory_extraction_bakeoff.py`

Windows-safe output runner:

- `tools/research/step4_extraction_utf8_runner.py`

Dependencies:

- `tools/research/requirements-step4-extraction.txt`

The harness uses `store=False`, enables no search/web/file tools and never calls `MemoryService`.

## Staged run sequence

1. verify the documented branch is green in normal CI;
2. create/reuse the isolated extraction venv on the owner PC;
3. run a 2-case Gemini 3.5 Flash-Lite smoke test to validate model/API/schema availability under the owner's existing Google API project;
4. if smoke succeeds, run the full production-eligible fixed corpus on Flash-Lite;
5. inspect safety first, then semantic accuracy, language behavior, latency and token use;
6. if Flash-Lite satisfies the gate, select it and do not spend quota on 3.8;
7. only if Flash-Lite materially fails, run the identical corpus on Gemini 3.8 Flash and compare;
8. after a defensible model choice, run narrow owner-PC production-path acceptance with candidate extraction enabled;
9. verify quarantine only and no canonical SQLCipher write;
10. write Phase-4.4 closure before starting Phase 4.5.

## Historical provider comparison

Earlier OpenAI-versus-Gemini extraction results remain useful historical technology evidence, but they predate the final production contract and the single-active-provider architecture. They do not require JARVIS to maintain both providers and do not control the Phase-4.4 production choice.
