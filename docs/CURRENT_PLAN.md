# JARVIS V1 Current Plan

## Active Step

**Step 5 — Local/Offline Survival and Provider Resilience (CAP-048, CAP-049).**

Owner authorization to move forward was given on 2026-09-08 after deliberately deferring unresolved Phase-4.5E automatic memory influence rather than allowing it to block the roadmap.

## Current Stage

**STEP 4 BOUNDED COMPLETE — PHASE 4.5E AUTOMATIC MEMORY INFLUENCE DEFERRED / NOT ACCEPTED — STEP 5 ACTIVE AT REQUIREMENTS / RESEARCH — NO STEP-5 IMPLEMENTATION AUTHORIZED YET**

This file is the operational source of truth. `PRODUCT.md` owns permanent product intent, `ROADMAP.md` owns sequence, accepted architecture belongs in `CURRENT_ARCHITECTURE.md`, and detailed research/evidence belongs in `docs/research/`.

---

## Step-4 closure carried forward

Accepted production behavior remains:

- bounded live session context and deterministic `ContextAssembler`;
- encrypted canonical memory with provenance/lifecycle/correction/supersession/physical forget;
- explicit governed `remember`, `inspect`, `correct`, and `forget`;
- structured candidate quarantine with no implicit durable admission;
- accepted Qwen3 Embedding + FTS5/dense/RRF retrieval foundation;
- accepted Qwen3 Reranker over already-eligible canonical records;
- accepted opt-in provider-assisted explicit `recall_memory` fallback;
- deterministic lifecycle/security/sensitivity authority ahead of learned components.

Deferred / disabled:

- strict independent 4.5D semantic release verifier;
- Phase-4.5E automatic semantic memory influence/injection;
- unaccepted 4.5E shadow-runtime production wiring;
- remaining unstarted Step-4 extensions.

The stacked experimental Phase-4.5E branches are research evidence only and are not part of accepted protected-main architecture.

Durable closure evidence:

- `docs/research/STEP_4_PHASE_4_5D_PROVIDER_ASSISTED_FALLBACK.md`
- `docs/research/STEP_4_PHASE_4_5E_DEFERRED_CLOSURE.md`

Automatic memory injection remains disabled. No failed 4.5D/4.5E learned component is promoted.

---

## Step 5 product requirements recovered from authoritative docs

### CAP-048 — Local and Offline Survival

Product purpose:

> Preserve useful functionality during cloud/network/provider failure where practical.

Permanent behavioral requirements:

1. A cloud/network/provider failure must not corrupt canonical conversation, memory, identity, or authority state.
2. JARVIS must never claim a cloud-dependent operation succeeded when it did not execute.
3. A fallback must preserve the user's question/intention rather than silently answering a different question.
4. Degradation must be explicit and truthful: capabilities may become reduced, unavailable, or local-only.
5. Local/offline fallback is added where it materially improves resilience, privacy, latency, cost, or availability; Step 5 does not require cloning every cloud capability locally.
6. Existing wake/audio/vision/identity/memory foundations must remain usable to the greatest practical extent during provider/network degradation.
7. Recovery must not duplicate or fork canonical state ownership.

### CAP-049 — Provider and Model Replaceability

Product purpose:

> Keep speech/model/search/memory/browser providers replaceable.

Step-5 implications:

1. Provider SDK/mechanics stay behind JARVIS-owned contracts/adapters where practical.
2. Core domain/conversation/memory/authority state must not depend on provider-specific SDK types.
3. Provider failure/fallback policy belongs to JARVIS, not to an LLM prompt.
4. Replacing or failing over a provider must not create a second conversation/context authority.
5. Runtime health must distinguish provider unavailable, network unavailable, local fallback active, degraded capability, and recovered state.
6. Step 5 should establish the resilience/provider boundary needed by later Step-6+ capabilities without building future knowledge/action architecture early.

---

## Known evidence entering Step 5

Step 5 begins with real failures already observed rather than hypothetical requirements:

- Gemini provider calls can fail with HTTP 500 / 429 and quota exhaustion; accepted 4.5D semantic recall already fails closed on such errors.
- Voice conversation currently depends on a configured realtime cloud provider for full intelligence.
- The owner machine has an NVIDIA RTX 5060 Ti 8 GB and already runs local wake, vision/tracking, identity diagnostics, and Qwen memory retrieval components.
- Local Qwen memory models are useful supporting components but are not a general offline conversational brain by themselves.
- Existing provider-selection/config code must be inspected before introducing any failover abstraction; no duplicate provider router should be created.

---

## Step 5 research questions

Before implementation, answer these with current web research and repository inspection:

1. What minimum useful JARVIS experience must survive complete internet/provider loss?
2. Which existing local components already survive with no cloud and which currently terminate/degrade?
3. Can the current LiveKit/realtime architecture switch or reconnect providers without corrupting the canonical `ConversationSession`?
4. What mature local inference runtime best fits Windows + RTX 5060 Ti 8 GB for a bounded offline conversational fallback?
5. What mature local STT/TTS path, if any, is necessary for true network-offline voice survival versus retaining existing local audio capture/wake with reduced functionality?
6. Which provider-resilience mechanics should be deterministic JARVIS infrastructure: timeout, retry/backoff, circuit breaker, health state, reconnect, session handoff, and explicit degraded modes?
7. Should Step 5 provide provider failover between cloud providers, local fallback, or both, and under which authority/consistency constraints?
8. How will JARVIS truthfully represent capability differences when the fallback model cannot use the same provider-native tools/features?
9. How will resource arbitration prevent a local fallback model from starving accepted vision/identity/Qwen workloads on the 8 GB GPU?
10. What exact owner-machine outage scenarios will define acceptance before implementation starts?

---

## Non-goals for the current stage

Do not yet:

- install a local LLM runtime;
- choose a local model from popularity alone;
- modify production provider routing;
- add cross-provider automatic failover;
- add local STT/TTS merely because they exist;
- rewrite the accepted LiveKit voice path;
- start Step 6 knowledge/source routing;
- revive Phase 4.5E memory injection;
- build a generic agent framework.

---

## Immediate Next Action

**Complete Step-5 repository inspection + fresh technology research, then freeze the smallest useful resilience architecture for owner approval.**

Required lifecycle:

`requirements -> research -> technology decision -> architecture -> owner approval -> implementation -> automated validation -> owner outage acceptance -> protected-main merge`.
