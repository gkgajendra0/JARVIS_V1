# Step 6 — Knowledge, Current Research, and Truthfulness

Date: 2026-09-08

## Status

**RESEARCH COMPLETE — PROVIDER-NEUTRAL ARCHITECTURE OWNER-APPROVED — IMPLEMENTATION IN PROGRESS**

Step 6 covers CAP-014 through CAP-017:

- CAP-014 Knowledge and Source Routing;
- CAP-015 Current Information and Deep Research;
- CAP-016 Trusted Domain Knowledge;
- CAP-017 Fact Checking and Truthfulness.

The product requirement is not to make one vendor the owner of JARVIS knowledge. JARVIS must be able to use the currently selected brain intelligently for research while preserving a provider-neutral evidence/truth boundary so Gemini, OpenAI, or a future provider can be replaced without rewriting canonical conversation, provenance, or truthfulness policy.

Permanent requirements recovered from `PRODUCT.md` remain:

- choose an appropriate source rather than treating model knowledge as universally sufficient;
- current external information must be source-backed;
- specialist/high-stakes requests should prefer authoritative evidence;
- distinguish model knowledge, researched evidence, insufficient evidence, stale/unverified state, and provider failure when relevant;
- capability limitations must be stated plainly;
- adopt mature provider search/research mechanics rather than rebuilding a search engine or second generic brain.

---

## Research-first technology findings

### Gemini Live built-in Google Search — useful but insufficient as the JARVIS evidence boundary

Google supports Grounding with Google Search in the Live API, and the exact JARVIS-pinned LiveKit `1.7.1` Google plugin exposes `google.tools.GoogleSearch()`.

However, Google's Live response schema contains grounding metadata while the pinned LiveKit realtime adapter does not expose that grounding/citation metadata through a stable public JARVIS-facing surface. A current-source check also found no reason to depend on private LiveKit internals for this requirement.

Therefore simply enabling Google Search in Gemini Live would let the model obtain fresh information but would not give JARVIS a dependable provider-independent source/provenance record.

**Decision: REJECT as the sole Step-6 evidence boundary. Do not subclass/patch LiveKit private realtime internals just to capture citations.**

### Gemini Interactions API + Google Search — selected Gemini research adapter

Google's Interactions API is GA in 2026 and supports built-in Google Search. It exposes observable search steps, executed queries, result/source metadata, and URL citations while allowing `store=False` so research calls do not become an uncontrolled server-side canonical history.

JARVIS already pins `google-genai==2.22.0`; no new Python dependency or second provider credential is required when Gemini is the active provider.

**Decision: ADAPT as the Gemini implementation of the JARVIS research contract.**

### OpenAI Responses API + Web Search — selected OpenAI research adapter

OpenAI's Responses API supports built-in web search, can require the web-search tool for an explicit research operation, can return underlying search sources with `include=["web_search_call.action.sources"]`, and supports `store=False`.

JARVIS already pins `openai==2.54.0`. When OpenAI is selected as `JARVIS_AI_PROVIDER`, the same JARVIS research contract can therefore use OpenAI's web research path without changing the voice/memory/truth architecture.

**Decision: ADAPT as the OpenAI implementation of the same JARVIS research contract.**

### Provider-specific Deep Research agents — retain, do not require for first Step 6

Both ecosystems now expose more expensive/longer-running research mechanics. These may eventually improve explicit multi-minute research, but they introduce background lifecycle, progress, cancellation, latency, and cost concerns.

**Decision: DEFER specialized background Deep Research. Normal Step-6 research uses the active provider's mature web-search-capable model first.**

### Brave / Tavily / Exa / other independent search APIs — valid future adapters, not required now

Independent search systems can be useful when deterministic domain filtering or a provider-independent raw index becomes necessary. Adding a new credential/service before the already-installed active-provider search paths are evaluated would add complexity without evidence that it is needed.

**Decision: RETAIN as future evidence-driven adapters. No hard dependency on Google or OpenAI search is created in JARVIS core contracts.**

---

## Owner-approved provider-neutral architecture

### Principle

**The active AI brain is allowed to perform intelligent research orchestration. JARVIS owns the research contract, the canonical user question, normalized evidence/provenance, truth status, and provider selection.**

```text
                           JARVIS
                              |
                  one JARVIS_AI_PROVIDER
                              |
             +----------------+----------------+
             |                                 |
        Gemini brain                      OpenAI brain
             |                                 |
             | model decides research is useful|
             +----------------+----------------+
                              |
                    research_current tool
                              |
               exact canonical latest USER turn
                              |
                    CurrentResearchService
                              |
              +---------------+---------------+
              |                               |
       Gemini adapter                    OpenAI adapter
 Interactions + Google Search       Responses + Web Search
              |                               |
              +---------------+---------------+
                              |
                  provider output normalization
                              |
                EvidenceSource / ResearchResult
                              |
              source domains + URLs + titles
              executed queries + timestamp
              bounded research/truth status
                              |
                              v
                    active brain synthesizes
                              |
                         spoken answer
```

Provider switch example:

```text
JARVIS_AI_PROVIDER=gemini
 -> Gemini realtime brain
 -> Gemini research adapter

JARVIS_AI_PROVIDER=openai
 -> OpenAI realtime brain
 -> OpenAI research adapter
```

There is no silent Gemini-to-OpenAI or OpenAI-to-Gemini research fallback. The selected active provider remains the one production cloud-AI family/account under ADR-015.

### Why the brain is used rather than recreating ChatGPT-like research ourselves

Modern provider research tools already know how to formulate searches, read results, run additional searches when needed, and synthesize findings. Reimplementing that orchestration as a custom keyword/search crawler would be lower quality and violate the research-first rule.

JARVIS therefore lets the active brain/provider do semantic research orchestration while retaining the parts that must remain ours:

- exact original accepted USER request;
- whether a real research tool call occurred;
- provider/model used;
- normalized source URLs/titles/domains;
- returned search queries where available;
- research timestamp;
- bounded evidence sufficiency status;
- fail-closed behavior;
- canonical conversation/memory/authority boundaries.

---

## JARVIS-owned research contract

Provider SDK types must not leak into core state.

Current implementation types:

```text
ResearchMode
  CURRENT
  FACT_CHECK
  AUTHORITATIVE

EvidenceSource
  source_id
  url
  title
  domain
  retrieved_at

EvidenceCitation
  source_id
  start_index / end_index when exposed

ResearchResult
  status
  mode
  answer
  sources[]
  citations[]
  executed_queries[]
  researched_at
  provider
  model
  reason_code
```

Current conservative status vocabulary:

```text
WEB_RESEARCHED
MULTI_SOURCE_RESEARCHED
AUTHORITATIVE_SOURCE_PRESENT
INSUFFICIENT_EVIDENCE
RESEARCH_UNAVAILABLE
```

These names deliberately avoid claiming that a model-generated synthesis is mathematically “verified truth.” A source was observed and used; source quality and claim support remain separate questions.

---

## Research routing

The active brain performs most semantic routing. JARVIS does not need a large handcrafted command classifier.

The agent contract requires research for:

- explicit “search”, “research”, “check online”, “verify”, or “fact-check” requests;
- latest/current/today/recent information whose answer materially changes over time.

The brain may also choose research when external evidence would materially improve an ordinary answer.

Research is normally unnecessary for:

- stable explanations;
- writing/rephrasing/brainstorming;
- reasoning directly from user-supplied content;
- conversational follow-ups with no external freshness requirement.

Minimum deterministic truth guard:

- if research was required/invoked and the research result is insufficient/unavailable, the brain must say fresh verification is insufficient/unavailable;
- it may not silently substitute model-only knowledge and describe it as freshly checked.

---

## Canonical query grounding

The realtime model does not send arbitrary free-form research text.

`research_current` reads the latest accepted canonical USER turn itself. The only semantic control exposed to the brain is the bounded mode:

```text
current
fact_check
authoritative
```

The provider may internally formulate multiple search queries, but JARVIS preserves the user's actual accepted question and records returned executed-query metadata when available.

This prevents a function call from silently changing “research my exact question” into a materially different task.

---

## Truthfulness/source-policy rules

1. A model response without a research tool execution is not “live researched.”
2. No usable sources means no successful source-backed status.
3. Provider citations/search sources are evidence, not canonical personal truth.
4. `fact_check` initially requires evidence from more than one source domain before returning an `ok=true` result.
5. `authoritative` initially fails closed unless a small conservative official/academic/regulatory source policy is observed.
6. The first authoritative policy is deliberately narrow rather than pretending every trustworthy organization can be classified automatically.
7. Current research never mutates personal memory, identity, authority, files, devices, or canonical conversation truth.
8. Provider/search failures become `RESEARCH_UNAVAILABLE`.
9. Normal logs record bounded metadata such as provider/model/status/source/query counts, not raw provider payloads or the complete user question.
10. Source details remain available for “what sources did you use?” while ordinary spoken answers remain concise.

---

## Important implementation roadblocks retained

### LiveKit realtime grounding metadata

Do not implement Step 6 by simply turning on Gemini Live Google Search because JARVIS cannot currently capture the grounding metadata through the accepted public LiveKit surface.

### Accepted provider-native turn detection

Changing the existing voice turn-detection architecture merely to inject pre-response RAG would reopen accepted Step-2 behavior. Step 6 therefore uses a normal function tool within the accepted realtime session.

### Tool mutability

The current Gemini realtime adapter reports immutable tool configuration for the active session. `research_current` is therefore attached as a stable session tool instead of being dynamically injected per turn.

### Long-running research

Normal research runs outside the event loop via a worker thread with an application timeout. Cancelling/timeout cannot forcibly terminate an already-running synchronous provider HTTP thread. This is acceptable for a read-only bounded request but remains a documented limitation. Multi-minute background research needs a separate later lifecycle.

---

## Implementation slices

### 6.1 — Provider-neutral current research foundation — IMPLEMENTING

- `CurrentResearchService` and provider-independent evidence types;
- Gemini Interactions + Google Search adapter;
- OpenAI Responses + Web Search adapter;
- same-provider selection from `JARVIS_AI_PROVIDER`;
- canonical latest-USER grounding;
- stable `research_current` tool;
- evidence/source/query normalization;
- read-only fail-closed behavior;
- unit tests with synthetic Gemini/OpenAI provider shapes.

### 6.2 — Real routing/truthfulness acceptance — NEXT GATE

Owner-machine evaluation must demonstrate:

- stable question does not unnecessarily research;
- explicit current/search request invokes research;
- actual source metadata reaches JARVIS;
- source follow-up names only observed sources;
- fact-check mode does not claim success from one domain;
- unavailable research is stated truthfully;
- English/Hindi/Hinglish remain natural;
- wake/barge-in/conversation/memory behavior remains intact.

### 6.3 — Trusted-domain expansion — EVIDENCE DRIVEN

The initial official-domain policy is intentionally small. Expand only from a frozen acceptance corpus and real cases. If same-provider search cannot satisfy required source constraints, research an independent raw search adapter rather than weakening the truth gate.

### 6.4 — Explicit deep research — DEFERRED UNTIL NEEDED

A dedicated long-running research agent may later use provider-native Deep Research capabilities through the same JARVIS result/evidence boundary. It will need background progress/cancel/result handling and is not part of the initial Step-6 merge.

---

## Acceptance gates

Before protected-main merge:

1. provider-independent unit tests pass;
2. Gemini and OpenAI response shapes are normalized without provider SDK objects becoming JARVIS state;
3. active-provider selection does not silently use the other provider;
4. exact canonical latest USER question is passed to research;
5. provider failure/no evidence returns `ok=false`;
6. no raw provider payload/user-query logging is added;
7. existing full CI remains green;
8. owner machine demonstrates at least the currently active provider's real web-search path and source capture;
9. owner voice test confirms normal stable conversation plus one current researched question and source follow-up;
10. the inactive provider adapter remains covered by contract/unit tests and can receive a separate owner smoke when that provider is intentionally activated.

---

## Primary research sources

Official/primary references consulted during the architecture decision include:

- Google AI — Grounding with Google Search: https://ai.google.dev/gemini-api/docs/google-search
- Google AI — Live API tool use: https://ai.google.dev/gemini-api/docs/live-api/tools
- Google AI — Interactions API overview/reference: https://ai.google.dev/gemini-api/docs/interactions-overview
- Google AI — Deep Research: https://ai.google.dev/gemini-api/docs/deep-research
- Google Gen AI Python SDK documentation/changelog
- OpenAI API — Responses API / Web Search / response source inclusion
- OpenAI model/tool documentation for web-search-capable Responses workflows
- LiveKit — tool definition/use and current Google realtime implementation
- exact JARVIS-pinned `livekit-agents@1.7.1` source
- Brave Search API / other independent search products as future alternatives

## Technology decision

**ADAPT provider-native research, OWN JARVIS evidence/truth authority.**

Use the currently selected brain/provider's mature web research capability rather than rebuilding search orchestration. Gemini and OpenAI are implementations behind one JARVIS-owned research contract. Neither vendor owns canonical conversation, provider selection, evidence normalization, truth status, memory, or authority. A future provider or independent search engine can be added behind the same boundary if evidence shows it is useful.
