# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 ACTIVE — REQUIREMENTS RECOVERY + CURRENT-TECHNOLOGY RESEARCH NEXT**

This file is the operational source of truth for current work. Detailed evidence belongs in `docs/research/`; significant architecture decisions belong in `docs/decisions/`.

---

## Step 3 — DONE

Step 3 is complete on protected `main` through PR #15 / merge commit `360a72c58402fbe357fa409437a4ce181921d837`.

Accepted foundation:

- deterministic T0–T3 graduated trust;
- deterministic R0–R5 risk floors;
- immutable proposal fingerprints and proposal-bound approvals;
- fail-closed policy boundary and final execution revalidation;
- privacy-aware audit/observability state;
- Windows-session invalidation;
- Windows Hello strong verification for consequential authority;
- encrypted local OWNER profile;
- accepted Pocket3 face identity + active/passive liveness evidence;
- one production Pocket3 microphone owner through LiveKit MediaDevices/WebRTC AEC+NS+HPF+AGC;
- LR-ASD active-speaker diagnostics on canonical user PCM + Vision timelines;
- encrypted CAM++ OWNER voice enrollment;
- asynchronous per-turn CAM++ speaker-shadow scoring that does not block normal conversation.

Final Step-3 authority boundary:

```text
face identity            = accepted evidence
face liveness            = accepted evidence
CAM++ speaker similarity = shadow evidence only
LR-ASD active speaker    = shadow evidence only
T2 CORROBORATED_OWNER    = disabled
Windows Hello            = strong verification path
```

No speaker threshold or LR-ASD threshold is promoted. Identity/perception evidence does not directly grant consequential execution permission.

Closure evidence: `docs/research/STEP_3_CLOSURE_ACCEPTANCE.md`.

Deferred identity hardening is tracked in GitHub Issue #14 and must not automatically interrupt Step 4:

- overlap / concurrent-speaker and speaker-change detection;
- replay/synthetic/cloned-voice countermeasures;
- direct non-OWNER CAM++ distributions and any future threshold;
- E/F with a real second visible person;
- short-turn same-speaker continuity;
- fixed monitor-relative attention/gaze;
- any future T2 composition or biometric authority promotion.

---

## Step 4 goal

Build **one JARVIS-owned personal-context and memory system** that makes JARVIS meaningfully continuous across conversations without turning every utterance into permanent memory.

Step 4 owns:

- CAP-008 Live Session Context;
- CAP-009 Long-Term Personal Memory;
- CAP-010 Episodic Memory;
- CAP-011 Semantic Memory;
- CAP-012 Reflection and Session Learning;
- CAP-013 Emotional Interaction Context.

No memory database/provider/framework has been selected yet. Research comes before implementation.

---

## Product behavior Step 4 must deliver

### Live context

JARVIS should understand the current working situation without forcing every turn into durable storage:

- current goal/task;
- active project/topic;
- recent relevant decisions/results;
- unresolved issues/pending next steps;
- current-session corrections and constraints.

Live context may expire with the session/task unless deliberately promoted to durable memory.

### Durable semantic memory

JARVIS should retain genuinely useful long-lived facts such as approved preferences, personal/project facts, stable rules, and explicit corrections.

Durable facts require enough metadata to support:

- provenance;
- time/freshness;
- confidence/verification state;
- correction;
- supersession;
- deletion/forgetting.

### Episodic memory

JARVIS may retain meaningful events/milestones/outcomes where later recall is useful, without logging every conversation as an episode.

Examples of the category include completed project milestones, meaningful failures/fixes, significant decisions, and explicit user-requested memories.

### Reflection / memory candidates

Models may help identify candidate memories after conversations or important events, but model output is a **proposal**, not durable-memory authority.

JARVIS-owned policy decides whether a candidate is stored, ignored, merged, superseded, or requires explicit confirmation.

### Emotional interaction context

Transient signals may help JARVIS respond naturally during the current interaction, but inferred mood/emotion must not become a permanent identity label by default.

---

## Hard requirements inherited from PRODUCT.md

- not every sentence becomes durable memory;
- explicit current user input outranks passive inference, old memory, or stale preference;
- durable memory carries provenance and enough timing/confidence metadata for correction/supersession;
- correction and forgetting are first-class;
- session context is separate from durable memory;
- provider history/caches are not automatically canonical JARVIS memory;
- transient emotional interpretations stay transient by default;
- secrets are never normal model context;
- models do not write directly to persistent memory;
- conversation/context/memory must not have duplicate authoritative owners;
- providers/storage/retrieval components remain replaceable;
- raw full transcripts/provider payloads must not be durably retained merely because they are available.

---

## Step 4 research questions

Before selecting architecture or code, answer these with current 2026 evidence:

1. What mature memory/context frameworks or patterns are actually suitable for a local-first personal assistant in 2026?
2. Which responsibilities should JARVIS own directly versus delegate to commodity storage/retrieval infrastructure?
3. What is the best boundary between live working context, semantic memory, episodic memory, and reflection?
4. What storage model best supports provenance, temporal validity, correction, supersession, and deletion?
5. Where are embeddings useful, and where would exact structured lookup be safer/better?
6. How should retrieval avoid flooding the realtime model with irrelevant memory?
7. How should memory candidates be extracted without allowing the LLM to self-author durable truth?
8. How should explicit user corrections immediately supersede older facts?
9. Which memory data should remain strictly local, and what—if anything—may be sent to cloud models for reasoning?
10. How do we migrate/learn from old JARVIS memory work without recreating its duplicate context/memory owners?
11. What current tools/frameworks materially outperform custom implementation for extraction, retrieval, graph/temporal memory, or lifecycle management?
12. How do we test memory quality: precision of recall, false memories, stale recall, correction, deletion, privacy, latency, and token cost?

---

## Immediate Step-4 work order

1. Read the Step-4 capability requirements in `PRODUCT.md`.
2. Inspect relevant mappings/lessons in `LEGACY_REQUIREMENTS_MAP.md` and only the necessary old-JARVIS memory/context implementation evidence.
3. Research current 2026 memory/context technology and serious alternatives.
4. Produce a requirements + technology comparison document.
5. Select the smallest suitable architecture with one authoritative JARVIS memory owner and replaceable provider boundaries.
6. Define privacy/data-lifecycle rules and acceptance tests.
7. Present the architecture for human approval.
8. Only then implement Step 4.

## Immediate Next Action

**Begin Step-4 requirements recovery and current-technology research. Do not implement a memory provider/database until the research and architecture decision are complete.**
