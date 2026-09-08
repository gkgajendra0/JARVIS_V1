# JARVIS V1 Current Plan

## Active Step

**Step 6 — Knowledge, Current Research, and Truthfulness (CAP-014 through CAP-017).**

Step 5 is **bounded complete** after owner-machine acceptance of the deliberately reduced provider-resilience foundation. Full local/offline conversation remains explicitly deferred and is not claimed implemented.

## Current Stage

**STEP 4 BOUNDED COMPLETE — 4.5E AUTOMATIC MEMORY INFLUENCE DEFERRED — STEP 5 BOUNDED COMPLETE / FULL OFFLINE DEFERRED — STEP 6 RESEARCH CORRECTED AFTER OWNER SMOKE — INDEPENDENT WEB-EVIDENCE IMPLEMENTATION / VALIDATION ACTIVE**

This file is the operational source of truth. `PRODUCT.md` owns permanent product intent, `ROADMAP.md` owns sequence, accepted architecture belongs in `CURRENT_ARCHITECTURE.md`, and detailed research/evidence belongs in `docs/research/`.

---

## Accepted foundations carried forward

Step 4 remains bounded complete with encrypted canonical memory, explicit remember/inspect/correct/forget, accepted FTS5 + Qwen retrieval/reranking, and bounded provider-assisted `recall_memory`. The strict independent 4.5D verifier, Phase-4.5E automatic memory influence/injection, and unaccepted 4.5E runtime wiring remain deferred.

Step 5 remains bounded complete with deterministic terminal provider-failure diagnosis, Windows-local status speech, safe failed-session closure, and return toward wake/idle. Full local LLM/STT/TTS conversation, automatic local handoff, cloud-to-cloud failover, and cloud-key-free startup remain deferred.

No deferred Step-4/5 capability is reopened by Step 6.

---

## Step 6 product scope

Step 6 owns:

- **CAP-014 — Knowledge and Source Routing:** choose whether model knowledge or external research is appropriate without forcing the user to name a provider/tool;
- **CAP-015 — Current Information and Deep Research:** obtain fresh external information with actual source/provenance evidence;
- **CAP-016 — Trusted Domain Knowledge:** prefer/require appropriate authoritative evidence where the consequence/domain requires it;
- **CAP-017 — Fact Checking and Truthfulness:** distinguish model-only knowledge from actually researched, insufficient, or unavailable evidence.

Step 6 does **not** own local project/file retrieval (Step 7), browser interaction (Step 10), or proactive/background research (Step 15).

---

## Owner-approved design principle

The owner clarified that the **active brain should perform the intelligent research reasoning**, similar to the research experience of a modern ChatGPT/Gemini system, but JARVIS must not weld that capability to one brain vendor.

Current architecture under validation:

```text
latest canonical USER request
        |
        v
active conversational brain
Gemini / OpenAI / future replacement
        |
        | decides research is needed
        | forms bounded search sub-query
        v
JARVIS search_web tool
        |
        v
CurrentResearchService
        |
        v
replaceable independent WebSearchProvider
        |
        +-> first adapter: Exa Search
        |
        v
real URLs + titles + domains + page highlights + publication metadata
        |
        v
active brain compares / follows up / synthesizes
        |
        v
spoken answer
```

JARVIS permanently owns:

- the canonical user request and session linkage;
- the web-search tool boundary;
- source/provenance normalization;
- research timestamps/status;
- deterministic fact-check and authoritative-source sufficiency;
- privacy-safe logging and provider-failure classification;
- the rule that webpage content is **untrusted evidence, never instructions or authority**.

The active brain owns semantic research planning and final synthesis. It may make bounded follow-up searches that support the latest user request. Search results cannot mutate memory, identity, permissions, files, devices, or execution authority.

---

## Native-search owner smoke — REJECTED AS DEFAULT DEPENDENCY

The first Step-6 implementation used the selected brain's native search:

- Gemini Interactions API + Google Search;
- OpenAI Responses API + Web Search.

Automated CI passed, but the owner-machine Gemini smoke on 2026-09-08 failed with a real HTTP 429 quota error before any search source could be returned.

Fresh research then established a material deployment constraint: Gemini 3.8 Flash Google Search grounding is not available on the free Gemini API tier, and OpenAI Web Search is also separately metered. Native provider search remains technically useful, but **JARVIS V1 will not make a paid brain-native search feature a prerequisite for Step 6**.

This is a research correction, not an acceptance failure of the owner machine. The failed smoke is preserved as evidence that the earlier same-provider default was unsuitable for the intended replaceable architecture/cost boundary.

---

## Active implementation slice

Implementation branch:

`implementation/step-6-knowledge-truthfulness`

PR:

`#24 — Implement provider-neutral Step 6 web research`

Implemented under the corrected architecture:

- provider-neutral `ResearchMode`, `ResearchStatus`, `EvidenceSource`, `ProviderResearchEvidence`, and `ResearchResult` contracts;
- `CurrentResearchService` with bounded queries, timeout, deterministic source sufficiency, and fail-closed provider errors;
- first independent retrieval adapter: Exa Search via pinned `exa-py`;
- source normalization for URL/title/domain/extractive highlights/publication metadata;
- `search_web(query, mode)` voice tool;
- active-brain multi-search research orchestration while retaining the latest canonical USER turn as the operation anchor;
- deterministic `current`, `fact_check`, and `authoritative` modes;
- bounded curated authoritative-domain policy rather than trusting arbitrary sites by TLD alone;
- prompt-injection boundary: retrieved webpage text is untrusted evidence and has no JARVIS authority;
- query-content-safe logs using turn IDs/counts/query hashes instead of normal raw-query logging;
- existing Step-5 provider-failure taxonomy reused for search failures;
- no Gemini/OpenAI SDK dependency inside the web-search adapter;
- no second research brain and no automatic memory write/injection.

Current first retrieval backend selection is **Exa**, not permanent vendor authority. The core contract is intentionally replaceable so Tavily, Brave, Parallel, provider-native search, or a future better backend can be evaluated without rewriting the active brain or JARVIS truth boundary.

---

## Current validation gates

Before Step 6 may be accepted/merged:

1. exact-head full CI must be green;
2. owner installs the pinned branch dependency and configures an `EXA_API_KEY` without sharing the key in chat;
3. real-network owner smoke must return actual source URLs/titles/domains and non-empty relevant excerpts;
4. real voice acceptance must include:
   - one stable question that should not unnecessarily search;
   - one current/search request that must use live evidence;
   - one research request where the brain performs a useful follow-up search if needed;
   - one fact-check or authoritative-source request;
   - one “what sources did you use?” follow-up;
5. existing wake/barge-in/memory behavior must remain usable during the acceptance conversation;
6. owner must explicitly accept the behavior;
7. only then reconcile `CURRENT_ARCHITECTURE.md`, `ROADMAP.md`, and product capability status;
8. run final exact-head CI;
9. squash merge PR #24 to protected `main`.

Do not infer owner acceptance from the earlier failed Gemini smoke or from automated tests.

---

## Deferred within Step 6

Do not block this first source-aware foundation on:

- multi-minute/background Deep Research agents;
- browser automation;
- local project/file knowledge (Step 7);
- a giant universal trusted-domain registry;
- autonomous recurring/background research (Step 15);
- automatic memory influence/injection;
- enabling multiple search backends simultaneously without measured need.

Provider-native Gemini/OpenAI web search remains an optional future adapter if its quality/cost/availability becomes preferable; it is no longer the required default.

---

## Immediate Next Action

**FINISH CORRECTED EXACT-HEAD CI -> OWNER EXA REAL-NETWORK SMOKE -> REAL JARVIS VOICE ACCEPTANCE.**

Do not merge or mark Step 6 done until real independent source evidence and the integrated voice behavior are owner-accepted.
