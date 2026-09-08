# JARVIS V1 Current Plan

## Active Step

**Step 6 — Knowledge, Current Research, and Truthfulness (CAP-014 through CAP-017).**

Step 5 is **bounded complete** after owner-machine acceptance of the deliberately reduced provider-resilience foundation. Full local/offline conversation remains explicitly deferred and is not claimed implemented.

## Current Stage

**STEP 4 BOUNDED COMPLETE — 4.5E AUTOMATIC MEMORY INFLUENCE DEFERRED — STEP 5 BOUNDED COMPLETE / FULL OFFLINE DEFERRED — STEP 6 RESEARCH COMPLETE — PROVIDER-NEUTRAL ARCHITECTURE OWNER-APPROVED — IMPLEMENTATION / VALIDATION ACTIVE**

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

## Owner-approved Step-6 architecture

Research record:

- `docs/research/STEP_6_KNOWLEDGE_TRUTHFULNESS_RESEARCH_AND_ARCHITECTURE.md`

The active AI provider may perform intelligent research orchestration, but JARVIS owns the provider-neutral research/evidence boundary.

```text
one JARVIS_AI_PROVIDER
        |
        +-> realtime conversational brain
        |
        +-> same-provider research adapter
                |
                +-> Gemini: Interactions API + Google Search
                |
                +-> OpenAI: Responses API + Web Search
        |
        v
JARVIS EvidenceSource / ResearchResult
        |
        v
active brain synthesizes the spoken answer
```

Permanent boundaries:

- Gemini and OpenAI are replaceable implementations, not JARVIS knowledge authority;
- no silent cross-provider research fallback;
- the latest accepted canonical USER turn is the authoritative research question;
- the brain can choose research for semantic need, but cannot provide an arbitrary rewritten research question to the tool;
- real tool execution is required before JARVIS may claim live web research occurred;
- provider sources are evidence, not automatic proof or canonical personal memory;
- research has no memory-write, identity, permission, execution, file, or device authority;
- provider-specific SDK objects do not become core JARVIS state;
- raw provider payloads/full user questions are not normal research logs;
- Phase-4.5E automatic memory injection remains disabled.

---

## Active implementation slice — Step 6.1

Implementation branch:

`implementation/step-6-knowledge-truthfulness`

Implemented so far:

- provider-neutral `ResearchMode`, `ResearchStatus`, `EvidenceSource`, `EvidenceCitation`, and `ResearchResult` contracts;
- `CurrentResearchService` with timeout/error fail-closed behavior;
- provider-output normalization so Gemini/OpenAI SDK objects do not leak into JARVIS core state;
- Gemini same-provider research adapter using Interactions API + Google Search with `store=False`;
- OpenAI same-provider research adapter using Responses API + Web Search, required search, source inclusion, and `store=False`;
- lazy provider clients so normal composition does not make a research request or require a second provider;
- one stable `research_current` voice tool grounded to the exact latest canonical USER turn;
- bounded modes: `current`, `fact_check`, `authoritative`;
- agent rules requiring real research for explicit online/search/fact-check requests and materially current/latest information;
- fail-closed source sufficiency rules;
- synthetic Gemini/OpenAI evidence-normalization and research-contract tests.

No new search framework, API provider, API key, Python dependency, local model, or second conversation brain has been added.

---

## Current validation gates

Before Step 6 may be accepted/merged:

1. open a protected-main PR and run exact-head full CI;
2. fix any lint/unit/Windows regressions;
3. run a real-network owner-machine research diagnostic against the currently active provider;
4. prove JARVIS captures actual source metadata rather than merely hearing the model say it searched;
5. run real voice acceptance with at least:
   - one stable question that should not unnecessarily research;
   - one explicit current/search question that must research;
   - one “what sources did you use?” follow-up;
   - one fact-check or authoritative-source request;
6. confirm English/Hindi/Hinglish and existing wake/barge-in/memory behavior remain usable;
7. document owner result;
8. reconcile `CURRENT_ARCHITECTURE.md` / `ROADMAP.md` only after human acceptance;
9. final exact-head CI;
10. squash merge to protected `main`.

The currently inactive cloud provider does not need to be made active merely to close the first Step-6 slice if the owner is not using it. Its adapter/contract must remain tested and provider-neutral; a live smoke is required when that provider is intentionally activated in production.

---

## Deferred within Step 6

Do not block the initial source-aware foundation on:

- multi-minute background Deep Research agents;
- independent Brave/Tavily/Exa search credentials;
- a giant universal trusted-domain registry;
- local project/file knowledge (Step 7);
- autonomous recurring/background research (Step 15).

A separate search adapter or specialized Deep Research path should be added only if measured evidence shows the current same-provider research boundary cannot meet a real product requirement.

---

## Immediate Next Action

**OPEN PR FOR THE CURRENT STEP-6 IMPLEMENTATION -> FULL CI -> OWNER-MACHINE REAL RESEARCH + VOICE ACCEPTANCE.**

Do not merge or mark Step 6 done until the owner-machine research path has demonstrated real sources and the owner accepts the voice behavior.
