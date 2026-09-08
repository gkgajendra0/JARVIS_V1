# Step 4 Phase 4.5D — Provider-Independent Core Acceptance Method

## Status

**FROZEN BEFORE RESULT — PROVIDER-INDEPENDENT CORE ACCEPTANCE**

The earlier final-composite owner execution was interrupted by Gemini free-tier request quota before a complete artifact existed. Per the already-frozen final-composite method, that was transport/quota failure rather than model-quality evidence.

The interruption exposed a test-boundary problem: Phase 4.5D is the JARVIS-owned memory evidence/release gate, but the attempted final acceptance made its completion depend on hundreds of calls to one replaceable conversational-provider adapter. That is inconsistent with the selected provider-independent architecture and with the one-provider-switch contract.

Current external guidance supports separating these concerns:

- structured model output can be syntactically valid while semantically wrong, so application code must validate it before use;
- tool/server boundaries must validate model-proposed inputs and enforce authorization outside the model.

Therefore this method accepts **JARVIS memory authority** independently from any Gemini/OpenAI quota. Provider natural-language planning quality becomes a separate provider-conformance concern and does not establish canonical truth or release authority.

## Architecture under test

```text
raw user query
→ frozen local multilingual answer-type veto
→ hostile deterministic MemoryQueryProposal fixture
→ deterministic JARVIS grounding
→ deterministic query policy
→ deterministic lifecycle / authority / sensitivity eligibility
→ unique exact current-facet lookup
→ TrustedMemoryEvidence or ABSTAIN
```

The deterministic interpreter in this harness is **test-only**. It is not a production brain, not another provider selector, and not a replacement for Gemini/OpenAI. Its purpose is to apply fixed structured proposals so the JARVIS-owned release boundary can be tested without provider transport or quota.

## Frozen corpus

Reuse the already-frozen V4 corpus unchanged:

- 255 queries;
- 90 release targets;
- 165 abstain targets;
- English / Hindi / Hinglish;
- 55 synthetic documents;
- corpus SHA-256:

`69666a37d436828b1d65827852f9e43d524253608209275205c41a36f8accadf`

The 31 partial console observations from the quota-interrupted provider run are non-evidentiary and must not be used to tune this local architecture, labels, thresholds, prompts or corpus.

## Frozen proposal strategy

The test interpreter is deliberately adversarial rather than optimistic.

### Release targets

For each direct current-value or current-value-comparison target, provide the exact expected current canonical facet with grounded subject/relation references.

### Ordinary semantic abstain targets

For `absent`, `near_miss`, `ambiguous`, `adversarial_lexical`, `negation`, and `unsupported_source`, provide an `EXACT_FACT / CURRENT` proposal for the tempting current canonical facet that is explicitly mentioned in the query.

This is intentionally hostile: if the local answer-type veto fails, the deterministic core is allowed to see a plausible existing facet. The composite must still produce zero false releases.

### Security/lifecycle targets

Provide the corresponding structured subject/predicate request:

- historical → `EXACT_FACT / HISTORICAL`;
- forgotten → exact current request for the forgotten facet;
- local-only → exact current request for the local-only facet;
- secret → exact current request for the secret facet;
- untrusted → exact current request for the untrusted facet.

In addition to the guarded end-to-end run, every security/lifecycle case is run once through the deterministic coordinator **without the local semantic guard**. Every such authority-only decision must still abstain. This prevents a local semantic veto from masking a lifecycle/security-policy regression.

## What this acceptance does and does not prove

It **does prove**:

- the local semantic veto plus JARVIS deterministic gate can safely consume hostile structured proposals;
- canonical lifecycle/security policy works without relying on the local classifier;
- exact current-fact lookup releases only the expected canonical assertion;
- the release owner does not depend on Gemini/OpenAI quota or model choice;
- Qwen embedding/reranking is not needed on the exact-fact path.

It **does not prove** that every conversational provider will always map arbitrary natural language to the best `MemoryQueryProposal`. That belongs to provider-adapter conformance/live integration. A provider adapter remains untrusted and replaceable; switching `JARVIS_AI_PROVIDER` does not change the memory authority implementation.

## Frozen gates

All gates must pass simultaneously:

1. zero false releases across all 165 abstain targets;
2. zero wrong-target releases among 90 release targets;
3. zero security-boundary releases in the guarded path;
4. zero security/lifecycle releases in the authority-only precheck;
5. every release equals the exact expected canonical memory ID;
6. overall release recall >= `0.75`;
7. direct current-value recall >= `0.75`;
8. current-value comparison recall >= `0.60`;
9. English release recall >= `0.65`;
10. Hindi release recall >= `0.65`;
11. Hinglish release recall >= `0.65`;
12. exact one-sided 95% Clopper-Pearson lower confidence bound for released precision >= `0.95`;
13. zero cloud/provider calls;
14. zero Qwen embedding/reranker calls;
15. local answer-type guard remains veto-only;
16. the deterministic interpreter has a frozen proposal for every one of the 255 corpus queries.

No probability threshold is fitted.

## Decision

- all gates pass → `PASS_CORE_ACCEPTANCE`; Phase 4.5D JARVIS-owned memory authority may be closed after durable result recording and a green closure SHA;
- any gate fails → `FAIL_CORE_ACCEPTANCE`; diagnose the JARVIS-owned gate without changing the corpus and without hiding the failure behind a different cloud provider;
- provider adapter conformance remains separate from canonical memory authority and can be exercised with a small bounded suite during provider/live integration rather than hundreds of acceptance calls.

Phase 4.5E remains blocked until this provider-independent core acceptance is complete, durably recorded, and the closure SHA is green.
