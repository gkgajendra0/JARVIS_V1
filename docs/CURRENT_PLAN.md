# JARVIS V1 Current Plan

## Active Step

**Step 5 — Local/Offline Survival and Provider Resilience (CAP-048, CAP-049).**

Owner authorization to move forward was given on 2026-09-08 after deliberately deferring unresolved Phase-4.5E automatic memory influence rather than allowing it to block the roadmap.

## Current Stage

**STEP 4 BOUNDED COMPLETE — PHASE 4.5E AUTOMATIC MEMORY INFLUENCE DEFERRED / NOT ACCEPTED — STEP 5 REQUIREMENTS + CURRENT RESEARCH COMPLETE — ARCHITECTURE PROPOSED — OWNER APPROVAL REQUIRED BEFORE 5.1 IMPLEMENTATION**

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

- Gemini provider calls can fail with HTTP 500 / 429 and quota exhaustion; accepted 4.5D semantic recall already fails closed on such errors.
- Voice conversation currently depends on a configured realtime cloud provider for full intelligence.
- Missing active cloud credentials currently fail startup preflight even though local wake/vision/etc. could otherwise operate.
- The outer `VoiceRuntimeController` already owns wake/active/recovering lifecycle and returns to local wake after a failed activation.
- `LiveKitConversationBridge` already converts provider events into one canonical JARVIS `ConversationSession`.
- The owner machine has an NVIDIA RTX 5060 Ti 8 GB and already runs local wake, vision/tracking, identity diagnostics, and Qwen memory retrieval components.

---

## Step 5 research decision

Detailed record:

- `docs/research/STEP_5_RESILIENCE_RESEARCH_AND_ARCHITECTURE_PROPOSAL.md`

Selected direction:

```text
cloud-native Gemini/OpenAI realtime primary
        |
        | deterministic JARVIS resilience policy
        v
public LiveKit AgentSession handoff
        |
        v
validated local pipeline fallback
  STT -> local LLM -> TTS
        |
        v
same JARVIS canonical conversation/context/memory/authority owners
```

Technology decisions:

- keep the existing JARVIS single-provider/config authority;
- keep native realtime as the primary experience;
- adapt public LiveKit `AgentSession.update_agent()` for controlled realtime-to-fallback handoff;
- use LiveKit STT/LLM/TTS fallback adapters inside pipeline mode where their mechanics fit, not as the top-level JARVIS authority;
- first local LLM runtime candidate: Ollama through LiveKit's official `openai.LLM.with_ollama` integration;
- first owner-machine model bake-off: Qwen3.5 4B Q4_K_M vs Gemma 4 E2B QAT, sequentially;
- full-offline STT/TTS selection remains later in Step 5; researched first candidates are Qwen3-ASR-0.6B and local Kokoro-FastAPI respectively;
- do not build a new generic provider router or depend on private/young realtime-fallback internals.

No local model/runtime is selected for production before owner-machine evidence.

---

## Proposed Step-5 slices

### 5.1 — Resilience contracts + simulated handoff

First implementation slice after owner approval. No local model installation required.

Implement only:

- deterministic resilience/runtime-mode state;
- provider/session failure observations and transitions;
- partial-output/retry semantics;
- provider-independent agent-factory/handoff seam around the existing LiveKit boundary;
- canonical bounded handoff-context construction;
- capability-aware degraded-mode description;
- fake/local test doubles for outage simulation;
- preflight resilience seam without falsely declaring offline fallback healthy;
- privacy-safe state-transition observability/tests.

### 5.2 — Owner-machine local LLM bake-off + bounded local brain

- install/evaluate Ollama separately from the JARVIS Python dependency set;
- freeze multilingual/persona/tool/latency/resource gates before scoring;
- benchmark Qwen3.5 4B Q4_K_M and Gemma 4 E2B QAT sequentially;
- integrate only the evidence-backed winner through LiveKit's Ollama boundary;
- validate controlled cloud-realtime -> local-pipeline handoff.

### 5.3 — Full network-offline spoken conversation

- benchmark/select local STT and TTS;
- first researched candidates: Qwen3-ASR-0.6B and Kokoro-FastAPI;
- preserve English/Hindi/Hinglish voice interaction, interruption, truthfulness, and canonical-state continuity;
- only after this is accepted may preflight treat a proven healthy local stack as sufficient when cloud credentials/network are unavailable.

### 5.4 — Cloud-to-cloud failover, only if still valuable

Any later Gemini/OpenAI failover must reuse the same resilience policy/handoff contract. It must not create a second provider router.

---

## Non-goals before 5.1 approval

Do not yet:

- install Ollama or a local LLM;
- install local STT/TTS;
- modify production provider routing;
- add cross-provider automatic failover;
- change accepted Torch/CUDA dependencies;
- rewrite the LiveKit voice path;
- start Step 6 knowledge/source routing;
- revive Phase 4.5E memory injection;
- build a generic agent framework.

---

## Immediate Next Action

**OWNER APPROVAL OF THE PROPOSED STEP 5 ARCHITECTURE / 5.1 BOUNDARY.**

After approval, create a fresh implementation branch from the reconciled protected-main planning state and implement **5.1 only**. Do not install a local model until the 5.1 contracts and simulated outage behavior are accepted.

Required lifecycle from this point:

`owner architecture approval -> 5.1 implementation -> automated validation -> simulated outage acceptance -> documentation/merge -> 5.2 benchmark design`.
