# Step 4 Phase 4.5D — Provider-Assisted Semantic Recall Fallback

## Status

**OWNER-AUTHORIZED BOUNDED COMPROMISE — IMPLEMENTATION ACTIVE**

Date: 2026-09-08

This work does not reverse the research conclusion that the strict independent 4.5D semantic release boundary remains unresolved. The owner explicitly chose a pragmatic fallback: use the already-selected production cloud provider (Gemini or OpenAI) for a structured semantic verification step because a probabilistic guarded recall path is more useful than having no semantic recall at all.

Step 5 remains not started while this bounded Step-4 fallback is integrated.

## Research basis

Current official APIs support the required structured classification surface:

- Gemini Interactions structured outputs accept JSON Schema and are documented for structured classification and agentic workflows.
- OpenAI Structured Outputs / Responses structured parsing can enforce a supplied schema.
- Schema conformance does not make semantic classification deterministic. This fallback therefore remains probabilistic by design.

For Gemini, `gemini-3.8-flash` is the current stable GA Flash model as of September 2026 and supports structured outputs. The implementation deliberately does not hard-code a provider-specific model; `JARVIS_MEMORY_SEMANTIC_RECALL_MODEL` is an explicit same-provider model setting.

## Bounded architecture

```text
latest accepted USER utterance
        |
        v
same-provider structured MemoryQueryProposal
        |
        v
JARVIS deterministic grounding + query policy
        |
        v
cloud-safe eligible facet catalog + exact current facet lookup
        |
        v
exactly one canonical current assertion
        |
        v
same-provider structured semantic release verifier
        |
        +-- current value / current comparison + directly supported --> RELEASE
        |
        `-- why/who/history/replacement/related/external/broad/advice/uncertain --> ABSTAIN
        |
        v
zero-argument `recall_memory` tool result to realtime model
```

## Authority rules retained

- `JARVIS_AI_PROVIDER` remains the one production cloud-provider switch.
- The semantic-recall model must belong to that active provider family.
- The realtime model never supplies a memory predicate/key to semantic recall.
- The tool reads the latest canonical accepted USER utterance from `ConversationSession`.
- `RetrievalEligibility.cloud_context()` excludes `local_only` and `secret_prohibited` memory before any candidate value is sent to the provider.
- Provider query interpretation is untrusted input.
- JARVIS grounding/policy must select an existing eligible canonical facet.
- Exact lookup must return one and only one current assertion.
- The second provider judgement is also untrusted; JARVIS derives release only from the frozen allow shapes.
- Any provider exception, malformed structured result, ambiguity, conflict, stale exact facet, or semantic veto becomes ABSTAIN.
- No model may create, correct, supersede, forget, resurrect, or otherwise establish canonical memory truth through this path.

## Frozen allowed semantic shapes

The second verifier may permit release only when it classifies the question as:

1. `current_value` and the exact fact directly contains the requested answer; or
2. `current_value_comparison` and the exact fact directly contains the value needed for the comparison.

All other answer types veto release:

- reason/explanation;
- provenance/actor;
- replacement/successor;
- related record;
- historical value;
- external source;
- broad recall;
- advice/other.

## Explicit trade-off

This fallback is intentionally weaker than the originally desired independent deterministic/learned safety boundary. The same provider family participates in both semantic planning and final semantic verification, so correlated model mistakes remain possible. Structured output constrains shape, not semantic truth.

The product therefore treats this as **bounded useful recall**, not a proof-quality semantic authorization mechanism. If a future mature multilingual verifier meets the original strict acceptance boundary, it may replace the provider verifier without redesigning canonical storage, lifecycle, query policy, or the recall tool surface.
