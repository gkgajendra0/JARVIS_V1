# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 ARCHITECTURE APPROVED — PHASE 4.0A COMPLETE — PHASE 4.1 COMPLETE — PHASE 4.2 COMPLETE — PHASE 4.3 OWNER ACCEPTANCE PASS / FINAL CI CLOSURE PENDING**

This file is the operational source of truth for current work. Detailed measured evidence belongs in `docs/research/`; significant accepted architecture decisions belong in `docs/decisions/`; `docs/CURRENT_ARCHITECTURE.md` continues to describe only architecture that actually exists and has passed the normal acceptance lifecycle.

Owner architecture approval was recorded on 2026-09-05 in `docs/research/STEP_4_ARCHITECTURE_APPROVAL.md`.

---

## Step 3 — DONE

Step 3 is complete on protected `main` through PR #15 / merge commit `360a72c58402fbe357fa409437a4ce181921d837`.

Accepted authority boundary remains unchanged:

```text
face identity            = accepted evidence
face liveness            = accepted evidence
CAM++ speaker similarity = shadow evidence only
LR-ASD active speaker    = shadow evidence only
T2 CORROBORATED_OWNER    = disabled
Windows Hello            = strong verification path
```

Step 4 does not promote any shadow biometric threshold and does not expand execution authority.

Closure evidence: `docs/research/STEP_3_CLOSURE_ACCEPTANCE.md`.

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

It also lays the machine-readable self-knowledge foundation required by later diagnostics/self-improvement work without implementing autonomous repair or self-modification now.

---

## Permanent Step-4 constraints

- not every sentence becomes durable memory;
- explicit current user input outranks passive inference, old memory, or stale preference;
- durable memory carries provenance + time/freshness/verification metadata;
- correction, historical change, retraction, and forgetting are distinct operations;
- session context is separate from durable memory;
- provider history/caches are not canonical JARVIS memory;
- transient emotional interpretations stay transient by default;
- secrets are never normal model context or normal durable memory;
- models do not write persistent memory directly;
- `MemoryService` is the sole durable mutation facade;
- `ContextAssembler` is the sole Step-4 model-context release owner;
- retrieval ranks only already-eligible canonical records and never establishes truth;
- raw full transcripts/provider payloads are not archived merely because available;
- current runtime/config/repository truth outranks stale learned self-memory;
- Step 4 grants no autonomous repair, code modification, deployment, or authority expansion.

---

## Technology disposition — COMPLETE

### Canonical storage

- SQLCipher 4.17.0 Community / SQLite relational canonical store;
- SQLite baseline 3.53.3 in the accepted Windows build;
- FTS5 derived lexical index;
- JARVIS-owned bitemporal-style valid/system-time lifecycle;
- no graph/vector/database service as canonical truth owner.

### Encryption / key protection

- pinned reproducible JARVIS Windows SQLCipher build;
- random 32-byte database key;
- Windows DPAPI user scope + purpose binding;
- no plaintext key file;
- same-user/same-machine recovery for first design;
- portable disaster recovery separately deferred.

### Extraction

- provider-native structured output;
- explicit Pydantic contract when Phase 4.4 begins;
- replaceable OpenAI/Gemini extractor adapters;
- model proposes candidate; deterministic JARVIS policy owns admission;
- current provider quality result remains a provisional tie on shared evidence.

### Retrieval

```text
structured / temporal / authority / sensitivity eligibility
 -> exact deterministic lookup when possible
 -> SQLite FTS5 + Qwen3-Embedding-0.6B (256d)
 -> equal RRF (research k=60)
 -> top 3
 -> Qwen3-Reranker-0.6B BF16
 -> exact tie preserves RRF rank -> stable memory ID
 -> ContextAssembler
```

No vector database is selected. Embeddings are derived/rebuildable. Broad automatic semantic injection remains calibration-gated.

### Self-knowledge

- current runtime/config = current dynamic truth;
- accepted repo/architecture/ADRs/policies/code/tests = declared truth;
- JARVIS Capability Registry = product capability semantics;
- CycloneDX 1.7 = generated dependency inventory;
- verified incident/episode memory = historical evidence;
- learned observations never silently override declared/current truth.

---

## Approved ownership model

```text
ConversationSession
    = canonical accepted conversation truth

LiveContext
    = current session/working context only

MemoryService
    = sole durable memory mutation/truth facade

MemoryPolicy
    = deterministic admission + lifecycle authority

MemoryRetriever
    = ranking only; never truth authority

ContextAssembler
    = sole Step-4 model-context release owner

SelfKnowledgeProvider
    = authority-aware aggregation of current/declared/historical self-knowledge
```

---

## Phase 4.0A — COMPLETE

Delivered stable JARVIS `session_id`, `turn_id`, aware UTC `accepted_at`, provider IDs as external metadata only, and the neutral `jarvis.security` DPAPI boundary while preserving identity behavior.

Validation: `docs/research/STEP_4_PHASE_4_0A_VALIDATION.md`.
Final CI run `33947865564`: Ruff / pytest / Windows Hello / Windows DPAPI all PASS.

---

## Phase 4.1 — COMPLETE

Delivered the deterministic encrypted canonical semantic-memory kernel:

- memory domain/provenance contracts;
- SQLCipher 4.17 connection and DPAPI key lifecycle;
- crash-safe key/database state handling;
- one serialized writer + dedicated reader worker;
- ordered checksum-validated SQL migrations;
- canonical relational schema and safe current view;
- temporal create/change/correct/retract/verify/expire lifecycle;
- FTS5 synchronization/rebuild + core/FTS secure-delete controls;
- physical forget with zero canonical + FTS hits;
- deterministic exact current queries;
- privacy-aware content-free forget operation metadata.

Real Windows SQLCipher/DPAPI adapter validation passed on the crash-recovery implementation. Closure record: `docs/research/STEP_4_PHASE_4_1_IMPLEMENTATION_RESULT.md`.

No model-driven memory write or semantic auto-injection was introduced.

---

## Phase 4.2 — COMPLETE

Delivered JARVIS-owned transient context:

- bounded accepted-turn tail;
- monotonic TTL;
- active goal/topic/entities/unresolved work/interaction state;
- session disposal with no durable dump;
- deterministic `ContextAssembler` precedence;
- strict local context budget;
- sensitivity release filtering;
- immutable context packets with JARVIS provenance;
- LiveKit ordinary-message translation boundary;
- accepted turn enters LiveContext only after canonical conversation acceptance;
- provider-native VAD/turn detection remains unchanged.

Provider sync research refresh found that the current LiveKit Gemini 3.1 realtime adapter does not support mid-session `update_chat_ctx()` forwarding. Therefore automatic mid-session provider-history synchronization remains disabled/fail-closed for Gemini 3.1. OpenAI realtime has a supported update path, but no automatic provider mutation is enabled by Phase 4.2.

Canonical Phase-4.2 closure is not blocked by an optional provider-sync bake-off because the risky feature remains disabled. A provider/model-specific real-voice bake-off is required before it can ever be enabled.

Validation:

- LiveContext/assembler/bridge/translation baseline run `33952348876`: PASS;
- provider capability guard commit `0bf39e7775689d930b92f3e0276edb451ded0a01`, run `33957508425`: Ruff / pytest / Windows Hello / Windows DPAPI PASS.

Closure record: `docs/research/STEP_4_PHASE_4_2_IMPLEMENTATION_RESULT.md`.

---

## Phase 4.3 — OWNER ACCEPTANCE PASS / FINAL CI CLOSURE PENDING

Goal: deliver the first safe useful cross-session memory behavior through **explicit remember / correct / forget / inspect** operations.

Implementation contract: `docs/research/STEP_4_PHASE_4_3_IMPLEMENTATION_DECISIONS.md`.

Delivered:

- `MemoryService` as the sole voice-facing durable mutation facade;
- exact structured personal memory keys (`personal / owner / predicate`);
- explicit TEXT remember/correct;
- exact inspect and exact physical forget;
- fail-closed zero/ambiguous targets;
- latest canonical USER-turn authorization for each operation;
- deterministic English/Hindi/Hinglish intent guard;
- conservative credential/secret rejection;
- predicate/value grounding against the latest canonical user utterance;
- provenance from JARVIS session/turn IDs with no copied raw command text;
- LiveKit function tools following the existing JARVIS tool pattern;
- non-interruptible durable mutations;
- spoken-number canonical predicate normalization using pinned `number-parser==0.3.2`;
- no fuzzy semantic target selection;
- no implicit auto-admission;
- no provider-history mutation requirement;
- no change to stabilized turn detection.

Persistent memory remains rollout-gated. OFF exposes no memory tools/database. ON requires the approved SQLCipher runtime with no plaintext fallback.

Automated validation: **PASS**.

Real owner-PC acceptance: **PASS**, including remember -> cross-process recall -> correct -> corrected cross-process recall -> physical forget -> cross-process absence, implicit statement rejection with durable absence, synthetic credential-memory rejection, and normal wake/Pocket3/provider behavior.

Owner evidence: `docs/research/STEP_4_PHASE_4_3_OWNER_PC_ACCEPTANCE.md`.

Implementation result draft: `docs/research/STEP_4_PHASE_4_3_IMPLEMENTATION_RESULT.md`.

**Phase 4.4 remains blocked until the post-acceptance closure commit passes pytest, Ruff, Windows DPAPI, and Windows Hello.**

---

## Remaining approved implementation order

1. Phase 4.0A — provenance + neutral security — **COMPLETE**.
2. Phase 4.1 — canonical memory kernel — **COMPLETE**.
3. Phase 4.2 — LiveContext + ContextAssembler — **COMPLETE**.
4. Phase 4.3 — explicit remember/correct/forget/inspect — **OWNER ACCEPTANCE PASS; FINAL CI PENDING**.
5. Phase 4.4 — structured extraction/candidate quarantine; implicit admission remains OFF until measured acceptance.
6. Phase 4.5 — Qwen semantic retrieval + FTS/RRF/top-3 reranker + abstention/irrelevant-injection calibration.
7. Phase 4.6 — episodic/reflection learning for meaningful outcomes/decisions/incidents, not raw transcripts.
8. Phase 4.7 — production self-knowledge foundation: Capability Registry + CycloneDX + authoritative aggregation, no autonomous repair.
9. Phase 4.8 — final hardening, multilingual/adversarial/privacy/security/backup tests, real use, reconciliation, ADR, protected-main merge.

---

## Key Step-4 documents

- `docs/research/STEP_4_FINAL_TECHNOLOGY_DECISION.md`;
- `docs/research/STEP_4_ARCHITECTURE_PROPOSAL.md`;
- `docs/research/STEP_4_ARCHITECTURE_APPROVAL.md`;
- `docs/research/STEP_4_PHASE_4_0A_VALIDATION.md`;
- `docs/research/STEP_4_PHASE_4_1_IMPLEMENTATION_RESULT.md`;
- `docs/research/STEP_4_PHASE_4_2_IMPLEMENTATION_DECISIONS.md`;
- `docs/research/STEP_4_PHASE_4_2_IMPLEMENTATION_RESULT.md`;
- `docs/research/STEP_4_PHASE_4_3_IMPLEMENTATION_DECISIONS.md`;
- `docs/research/STEP_4_PHASE_4_3_AUTOMATED_VALIDATION.md`;
- `docs/research/STEP_4_PHASE_4_3_OWNER_PC_ACCEPTANCE.md`;
- `docs/research/STEP_4_PHASE_4_3_OWNER_ACCEPTANCE_FAILURE_1.md`;
- `docs/research/STEP_4_PHASE_4_3_IMPLEMENTATION_RESULT.md`;
- `docs/research/STEP_4_RETRIEVAL_TECHNOLOGY_DECISION.md`;
- `docs/research/STEP_4_MEMORY_EXTRACTION_PROVISIONAL_TIE.md`;
- `docs/research/STEP_4_SQLCIPHER_417_WINDOWS_RESULT.md`;
- `docs/research/STEP_4_SELF_KNOWLEDGE_SBOM_WINDOWS_RESULT.md`.

---

## Non-blocking deferred decisions

- portable disaster recovery/export;
- final extraction provider winner;
- implicit durable auto-admission threshold;
- semantic abstention threshold;
- dedicated ANN/vector derivative if future measured scale needs it;
- persisted crash-resume LiveContext;
- relationship/graph memory if later use cases justify it;
- automatic provider chat-history synchronization;
- autonomous diagnosis/repair/self-improvement.

---

## Immediate Next Action

**RUN PHASE 4.3 POST-ACCEPTANCE CLOSURE CI.**

The owner-PC acceptance sequence is complete. Do not begin Phase 4.4 until the closure commit passes pytest, Ruff format/lint, Windows DPAPI, and Windows Hello. After that, mark Phase 4.3 COMPLETE and begin Phase 4.4 research-first structured extraction/candidate quarantine.