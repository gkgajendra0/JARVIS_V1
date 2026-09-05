# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 ARCHITECTURE APPROVED — PHASE 4.0A COMPLETE — PHASE 4.1 COMPLETE — PHASE 4.2 COMPLETE — PHASE 4.3 COMPLETE — PHASE 4.4 NEXT**

This file is the operational source of truth for current work. Detailed measured evidence belongs in `docs/research/`; significant accepted architecture decisions belong in `docs/decisions/`; `docs/CURRENT_ARCHITECTURE.md` describes architecture that actually exists and has passed acceptance.

Owner Step-4 architecture approval was recorded on 2026-09-05 in `docs/research/STEP_4_ARCHITECTURE_APPROVAL.md`.

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

---

## Step 4 goal

Build one JARVIS-owned personal-context and memory system that makes JARVIS meaningfully continuous across conversations without turning every utterance into permanent memory.

Step 4 owns CAP-008 through CAP-013: live context, long-term personal memory, episodic memory, semantic memory, reflection/session learning, and emotional interaction context. It also lays the machine-readable self-knowledge foundation for later diagnostics without implementing autonomous repair or self-modification.

---

## Permanent Step-4 constraints

- not every sentence becomes durable memory;
- explicit current owner input outranks passive inference, old memory, or stale preference;
- durable memory carries provenance + time/freshness/verification metadata;
- correction, historical change, retraction, and forgetting are distinct;
- session context is separate from durable memory;
- provider history/caches are not canonical memory;
- transient emotional interpretations stay transient by default;
- secrets are never normal durable memory/model context;
- models do not write persistent memory directly;
- `MemoryService` is the sole durable mutation facade;
- `ContextAssembler` is the sole Step-4 model-context release owner;
- retrieval ranks eligible canonical records and never establishes truth;
- raw full transcripts/provider payloads are not archived merely because available;
- current runtime/config/repository truth outranks learned self-memory;
- Step 4 grants no autonomous repair, code modification, deployment, or authority expansion.

---

## Technology disposition — COMPLETE

### Canonical storage

- SQLCipher 4.17.0 Community / SQLite canonical relational store;
- accepted SQLite baseline 3.53.3;
- FTS5 derived lexical index;
- JARVIS-owned temporal lifecycle;
- no graph/vector service as canonical truth owner.

### Encryption / key protection

- pinned reproducible Windows SQLCipher build;
- random 32-byte database key;
- Windows DPAPI user scope + purpose binding;
- no plaintext key file;
- portable disaster recovery deferred.

### Extraction target for Phase 4.4

- provider-native structured output;
- explicit Pydantic candidate contract;
- replaceable OpenAI/Gemini extractor adapters;
- model proposes candidate only;
- deterministic JARVIS policy owns admission;
- implicit admission remains OFF until measured acceptance.

### Retrieval target for Phase 4.5

```text
structured / temporal / authority / sensitivity eligibility
 -> exact lookup when possible
 -> SQLite FTS5 + Qwen3-Embedding-0.6B (256d)
 -> equal RRF (research k=60)
 -> top 3
 -> Qwen3-Reranker-0.6B BF16
 -> exact tie preserves RRF rank -> stable memory ID
 -> ContextAssembler
```

No vector database is selected. Embeddings remain derived/rebuildable.

### Self-knowledge target

- runtime/config = current dynamic truth;
- accepted repo/architecture/ADRs/policies/code/tests = declared truth;
- Capability Registry = product capability semantics;
- CycloneDX 1.7 = generated dependency inventory;
- verified incidents/episodes = historical evidence;
- learned observations never override declared/current truth silently.

---

## Approved ownership model

```text
ConversationSession = canonical accepted conversation truth
LiveContext         = session/working context only
MemoryService       = sole durable mutation/truth facade
MemoryPolicy        = deterministic admission/lifecycle authority
MemoryRetriever     = ranking only
ContextAssembler    = sole model-context release owner
SelfKnowledgeProvider = authority-aware current/declared/historical aggregation
```

---

## Phase 4.0A — COMPLETE

Stable `session_id`, `turn_id`, aware UTC `accepted_at`, provider IDs as external metadata only, and neutral `jarvis.security` DPAPI boundary delivered and validated.

Final CI run `33947865564`: PASS.

---

## Phase 4.1 — COMPLETE

Delivered encrypted canonical memory kernel, provenance/domain contracts, SQLCipher + DPAPI lifecycle, crash-safe key/database handling, serialized writer + reader, migrations, temporal lifecycle, FTS5 synchronization/rebuild, secure delete, physical forget, and exact current queries.

Closure: `docs/research/STEP_4_PHASE_4_1_IMPLEMENTATION_RESULT.md`.

---

## Phase 4.2 — COMPLETE

Delivered bounded `LiveContext`, monotonic TTL, session working state, deterministic `ContextAssembler`, sensitivity release filtering, immutable context packets, LiveKit translation boundary, and accepted-turn-only context admission.

Gemini 3.1 realtime mid-session `update_chat_ctx()` remains unsupported/fail-closed; no automatic provider-history mutation was enabled.

Closure: `docs/research/STEP_4_PHASE_4_2_IMPLEMENTATION_RESULT.md`.

---

## Phase 4.3 — COMPLETE

Delivered governed explicit `remember / inspect / correct / forget` behavior through the normal production voice path.

Accepted properties include:

- `MemoryService` sole durable facade;
- exact `personal / owner / predicate` targeting;
- latest canonical USER-turn authorization;
- deterministic English/Hindi/Hinglish intent guard;
- predicate/value grounding;
- conservative credential/secret rejection;
- owner-explicit provenance/authority enforcement;
- sensitivity agreement and local-only release blocking;
- bounded non-value-echoing mutation metadata;
- non-interruptible durable mutations;
- spoken-number normalization via `number-parser==0.3.2`;
- no fuzzy/semantic target selection;
- no implicit auto-admission;
- no provider-history-as-memory;
- no change to provider-native turn detection.

Real owner-PC acceptance proved remember -> cross-process recall -> correct -> corrected cross-process recall -> physical forget -> cross-process absence, implicit-statement rejection with durable absence, synthetic credential-memory rejection, and stable wake/Pocket3/provider behavior.

Closure CI commit `69f909d5287d640fa23b7c9206bfef1c0964e70e`, Code Quality run `33962138222`: pytest / Ruff / Windows DPAPI / Windows Hello all PASS.

Records:

- `docs/research/STEP_4_PHASE_4_3_AUTOMATED_VALIDATION.md`;
- `docs/research/STEP_4_PHASE_4_3_OWNER_PC_ACCEPTANCE.md`;
- `docs/research/STEP_4_PHASE_4_3_OWNER_ACCEPTANCE_FAILURE_1.md`;
- `docs/research/STEP_4_PHASE_4_3_IMPLEMENTATION_RESULT.md`.

---

## Remaining approved implementation order

1. Phase 4.0A — provenance + neutral security — **COMPLETE**.
2. Phase 4.1 — canonical memory kernel — **COMPLETE**.
3. Phase 4.2 — LiveContext + ContextAssembler — **COMPLETE**.
4. Phase 4.3 — explicit remember/correct/forget/inspect — **COMPLETE**.
5. Phase 4.4 — structured extraction/candidate quarantine — **NEXT**; implicit admission remains OFF until measured acceptance.
6. Phase 4.5 — Qwen semantic retrieval + FTS/RRF/top-3 reranker + abstention calibration.
7. Phase 4.6 — episodic/reflection learning for meaningful outcomes/decisions/incidents, not raw transcripts.
8. Phase 4.7 — Capability Registry + CycloneDX + authoritative self-knowledge aggregation, no autonomous repair.
9. Phase 4.8 — final hardening, multilingual/adversarial/privacy/security/backup tests, real use, reconciliation, ADR, protected-main merge.

---

## Key Step-4 documents

- `docs/research/STEP_4_FINAL_TECHNOLOGY_DECISION.md`;
- `docs/research/STEP_4_ARCHITECTURE_PROPOSAL.md`;
- `docs/research/STEP_4_ARCHITECTURE_APPROVAL.md`;
- `docs/research/STEP_4_PHASE_4_1_IMPLEMENTATION_RESULT.md`;
- `docs/research/STEP_4_PHASE_4_2_IMPLEMENTATION_RESULT.md`;
- `docs/research/STEP_4_PHASE_4_3_IMPLEMENTATION_DECISIONS.md`;
- `docs/research/STEP_4_PHASE_4_3_AUTOMATED_VALIDATION.md`;
- `docs/research/STEP_4_PHASE_4_3_OWNER_PC_ACCEPTANCE.md`;
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
- dedicated ANN/vector derivative if scale needs it;
- persisted crash-resume LiveContext;
- relationship/graph memory;
- automatic provider chat-history synchronization;
- autonomous diagnosis/repair/self-improvement.

---

## Immediate Next Action

**BEGIN PHASE 4.4 RESEARCH-FIRST STRUCTURED EXTRACTION / CANDIDATE QUARANTINE.**

Before implementation, refresh current structured-output/extraction technology and proven memory-candidate admission patterns on the web. Preserve the approved boundary: models may propose typed candidates, but implicit durable admission remains OFF and only deterministic JARVIS policy may later admit canonical memory.