# JARVIS Cost Call Inventory

Status: **C0 BASELINE COMPLETE / C1 FOUNDATION IMPLEMENTED**

Date: 2026-09-29

Purpose: map every current external intelligence/search/voice call path that can create API cost, classify its optimization role, and record current telemetry coverage before routing changes.

## Baseline telemetry contract

For routed model work, the cost foundation records or derives:

- work/mission ID;
- routing request and decision lineage;
- subsystem/stage;
- provider and exact model snapshot;
- target ID;
- primary versus fallback attempt;
- input tokens;
- output tokens;
- cached-input tokens when reported;
- reasoning/thought tokens when reported;
- tool-use tokens when reported;
- whether provider usage was actually observed;
- latency;
- failure/retry state;
- estimated USD cost when a dated target CostProfile exists;
- explicit unpriced/unknown state when pricing or usage is unavailable.

Unknown usage or price is never converted to zero.

Current provider normalization follows the SDK/API usage shapes exposed by:

- OpenAI Responses: input/output/total tokens plus cached-input and reasoning-token details;
- Gemini Interactions: total input/output/cached/thought/tool-use token usage.

Pricing itself remains separately versioned and effective-dated through `CostProfile`; C7 owns production price-profile population.

## Current call inventory

| Subsystem | Current call site | External provider/path | Classification | C1 coverage now | Next optimization |
| --- | --- | --- | --- | --- | --- |
| Background Work / capability acquisition | `src/jarvis/work/reasoner.py` through `src/jarvis/model_routing/` | Gemini/OpenAI structured reasoning | local-candidate / cheap-cloud-candidate / strong-cloud-candidate | **Durable provider/model/usage/latency/retry/cost provenance implemented** | C3/C5/C7 |
| Hands semantic route + planner | `src/jarvis/hands/planner.py` + `provider_adapters.py` | Gemini Interactions / OpenAI Responses | local-candidate / cheap-cloud-candidate | Shared provider adapter now exposes normalized usage telemetry; direct Hands persistence not yet adopted | C5/C8 |
| Realtime conversation brain | `src/jarvis/voice/livekit_session.py::_create_realtime_model` | Gemini/OpenAI realtime through LiveKit | voice-specific | Direct realtime session is outside routed durable C1 telemetry | C2 then late C8 |
| Scripted TTS | `src/jarvis/voice/scripted_speech.py::build_scripted_speech` | Gemini TTS / OpenAI TTS through LiveKit | voice-specific | Separate from routed model telemetry | C2 |
| Memory candidate extraction | `src/jarvis/memory/extractors.py` | Gemini Interactions / OpenAI Responses | local-candidate | Direct provider adapter; inventoried, not yet routed/persisted | C5/C8 |
| Memory query interpretation | `src/jarvis/memory/query_interpreters.py` | Gemini Interactions / OpenAI Responses | local-candidate / cheap-cloud-candidate | Direct provider adapter; inventoried, not yet routed/persisted | C5/C8 |
| Memory release verification | `src/jarvis/memory/release_guard.py` | Gemini Interactions / OpenAI Responses | local-candidate / cheap-cloud-candidate | Direct provider adapter; inventoried, not yet routed/persisted | C5/C8 |
| Live web research retrieval | `src/jarvis/knowledge/research_providers.py::ExaWebResearchProvider` | Exa search | research-provider cost | Source retrieval is provider-decoupled but not token-priced through ModelRouting | C6/C8 |
| Visual desktop computer use | `src/jarvis/computer/providers.py` and `latency_provider.py` | Gemini Interactions computer-use / OpenAI Responses computer tool | strong-cloud-candidate; multi-round screenshot risk | Direct provider loop; inventoried, not yet routed/persisted | C5/C8 |
| Deterministic capability execution | capability runtime, native Hands, Git/Docker/tests/local operations | local execution | deterministic-avoidable | No model cost by design | C3 prefers this before model invocation |
| Local retrieval / EngineeringKnowledge | existing local retrieval paths | local execution | deterministic/local | No cloud-model cost by design | C6 expands reuse |

## C0 conclusions

1. The immediate paid-experiment cost center is background Work reasoning because capability acquisition repeatedly invokes the Work reasoner across research, development, debugging and verification steps.
2. The existing Phase-4 router is therefore the correct first telemetry boundary.
3. Realtime voice and scripted TTS must not be mixed into the paid-brain experiment budget.
4. Hands and memory contain several bounded classification/verification calls that are strong local-model candidates later.
5. Visual computer use can become expensive because one user goal can generate multiple screenshot/model round trips; it should remain an escalation path, not a default.
6. Exa/search cost must eventually be measured as provider-call cost rather than forced into token-only model accounting.

## C1 implementation boundary

C1 deliberately establishes the reusable foundation without prematurely rewriting every subsystem:

- `StructuredOutputTelemetry` normalizes provider-returned usage at the shared Gemini/OpenAI structured-output boundary.
- `ModelInvoker.invoke_structured_with_telemetry()` adds telemetry without breaking existing callers that expect only a parsed Pydantic result.
- routed Work attempts persist exact provider/model/stage snapshots and explicit usage-observed state;
- token cost estimation uses versioned `CostProfile` data only when both required usage and price information exist;
- `CostTelemetryReader` aggregates all attempts for a WorkItem or EngineeringChange without the old 20-decision status-view limit;
- reports expose known cost separately from complete estimated total and count missing-usage/unpriced attempts.

This is sufficient for the planned capability-acquisition experiment path. C8 will adopt the same telemetry/routing substrate for Hands, memory, research, and finally broader voice rather than creating parallel accounting systems.
