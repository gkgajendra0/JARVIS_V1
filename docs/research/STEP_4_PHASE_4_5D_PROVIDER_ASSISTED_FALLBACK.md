# Step 4 Phase 4.5D — Provider-Assisted Semantic Recall Fallback

## Status

**OWNER-ACCEPTED BOUNDED COMPROMISE — IMPLEMENTED / FULL CI GREEN / OWNER LIVE SMOKE PASSED**

Date: 2026-09-08

This work does not reverse the research conclusion that the strict independent 4.5D semantic release boundary remains unresolved. The owner explicitly chose a pragmatic fallback: use the already-selected production cloud provider (Gemini or OpenAI) for structured semantic planning and a second structured semantic verification step because a probabilistic guarded recall path is more useful than having no semantic recall at all.

Step 5 remains not started. It still requires separate explicit owner authorization.

## Research basis

Current official APIs support the required structured classification surface:

- Gemini Interactions structured outputs accept JSON Schema and are documented for structured classification and agentic workflows.
- OpenAI Structured Outputs / Responses structured parsing can enforce a supplied schema.
- Schema conformance does not make semantic classification deterministic. This fallback therefore remains probabilistic by design.

The implementation deliberately does not hard-code a provider-specific semantic-recall model. `JARVIS_MEMORY_SEMANTIC_RECALL_MODEL` is an explicit same-provider model setting. Owner acceptance on Gemini used **`gemini-3.5-flash`**. An earlier `gemini-3.8-flash` owner attempt reached the final release-verifier stage but then failed closed on provider HTTP 500/429 responses and a free-tier quota limit; that run is provider-availability evidence, not a semantic failure.

## Accepted bounded architecture

```text
latest accepted USER utterance
        |
        v
same-provider structured query selection
        |
        v
provider selects one numbered eligible facet
        |
        v
JARVIS reconstructs canonical subject_scope / subject / predicate
        |
        v
JARVIS deterministic grounding + query policy
        |
        v
cloud-safe eligibility + exact current facet lookup
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

The indexed-facet contract replaced the earlier requirement that the provider reproduce three internal canonical strings. The provider now selects one numbered eligible facet, while JARVIS reconstructs the exact canonical key itself. This preserves deterministic canonical-key ownership and removed the live `incomplete_exact_fact_query` failure seen in the first owner smoke.

## Authority rules retained

- `JARVIS_AI_PROVIDER` remains the one production cloud-provider switch.
- The semantic-recall model must belong to that active provider family.
- The realtime model never supplies a memory predicate/key to semantic recall.
- The tool reads the latest canonical accepted USER utterance from `ConversationSession`.
- `RetrievalEligibility.cloud_context()` excludes `local_only` and `secret_prohibited` memory before any candidate value is sent to the provider.
- Provider semantic planning is untrusted input.
- Provider facet selection is only an index into a JARVIS-owned eligible catalog; JARVIS reconstructs the canonical key.
- JARVIS grounding/policy must validate the resulting existing eligible canonical facet.
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

## Automated validation

Final owner-tested code SHA before documentation-only closure commits:

`bd95734032e2f936945fa02e16bb002ac6b478ea`

Full repository Code Quality run on that exact SHA: `34190011723`.

All normal gates passed:

- Ruff formatting: PASS;
- Ruff lint: PASS;
- full pytest: PASS;
- Windows Hello helper build + JSON contract probe: PASS;
- Windows DPAPI smoke: PASS.

No accepted 4.5A–4.5C implementation was changed by the final indexed-facet correction; the surgical correction was confined to the provider query-interpreter adapter and its tests.

## Owner live acceptance

Owner PC acceptance used:

- branch: `implementation/step-4-provider-memory-release`;
- exact code SHA: `bd95734032e2f936945fa02e16bb002ac6b478ea`;
- active provider: `gemini`;
- semantic-recall model: `gemini-3.5-flash`;
- persistent memory: enabled;
- bounded provider-assisted semantic recall: enabled.

Disposable canonical memory:

`test_color = purple`

Observed behavior:

1. **Current-value recall — PASS**
   - USER: `What is my test color?`
   - runtime: `Semantic memory recall released ... predicate=test_color ... reason=provider_verified_unique_eligible_current_exact_fact`
   - assistant: `Purple is the colour you mentioned.`
2. **Current-value comparison — PASS**
   - USER: `My test color is purple, right?`
   - runtime: semantic memory recall released for `test_color` with the same provider-verified release reason.
   - assistant: `Indeed, sir, your stored test colour is purple.`
3. **Related-but-different reason request — PASS / SAFE ABSTAIN**
   - USER: `Why is my test color purple?`
   - runtime: `Semantic memory recall abstained ... reason=unsupported_query`
   - assistant explicitly stated that memory contained no reason, only the fact itself; no reason was invented.
4. **Physical forget cleanup — PASS**
   - USER: `Jarvis forget my test color.`
   - runtime: `Explicit memory forget committed | predicate=test_color`
   - assistant confirmed the test memory was forgotten.

The owner smoke therefore proves the intended bounded flow for one real current-value query, one comparison, one unsafe semantic-role request, and cleanup on the target Windows/RTX/Pocket3 runtime.

## Provider-availability behavior observed

Before the successful `gemini-3.5-flash` smoke, `gemini-3.8-flash` reached the final provider verifier but encountered HTTP 500 followed by HTTP 429 quota exhaustion. JARVIS converted that failure to:

`provider_memory_release_guard_unavailable`

and abstained rather than releasing the memory. This is accepted fail-closed behavior. It also establishes a real provider-resilience concern for later roadmap work; it does not authorize Step 5 by itself.

## Explicit trade-off and residual risk

This fallback is intentionally weaker than the originally desired independent deterministic/learned safety boundary. The same provider family participates in semantic planning and final semantic verification, so correlated model mistakes remain possible. Structured output constrains shape, not semantic truth.

The product therefore treats this as **bounded useful recall**, not a proof-quality semantic authorization mechanism. The strict independent 4.5D verifier remains deferred/unresolved. If a future mature multilingual verifier meets the original strict acceptance boundary, it may replace the provider verifier without redesigning canonical storage, lifecycle, query policy, or the recall tool surface.

Automatic Phase-4.5E semantic memory injection through `ContextAssembler` remains deferred. The accepted fallback is a governed explicit `recall_memory` tool path only.

## Acceptance decision

**ACCEPT the provider-assisted 4.5D recall fallback as bounded production behavior.**

This acceptance does not promote any retired V4/Method-V2/Answerability/Question-Role model, does not weaken canonical security/lifecycle rules, and does not claim the original independent semantic release problem is solved.

Step 5 remains **PLANNED / NOT STARTED / AWAITING OWNER AUTHORIZATION**.
