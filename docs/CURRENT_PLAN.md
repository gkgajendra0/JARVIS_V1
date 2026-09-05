# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 ARCHITECTURE APPROVED — PHASE 4.0A COMPLETE — PHASE 4.1 CANONICAL MEMORY KERNEL ACTIVE**

This file is the operational source of truth for current work. Detailed evidence belongs in `docs/research/`; significant accepted architecture decisions belong in `docs/decisions/`; `docs/CURRENT_ARCHITECTURE.md` continues to describe only architecture that actually exists and has passed acceptance.

Owner architecture approval was recorded on 2026-09-05 in `docs/research/STEP_4_ARCHITECTURE_APPROVAL.md`.

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

Deferred identity hardening remains tracked separately and must not automatically interrupt Step 4.

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

Step 4 also lays the machine-readable self-knowledge foundation required by later diagnostics/self-improvement work, without implementing autonomous repair or self-modification now.

---

## Permanent Step-4 product constraints

- not every sentence becomes durable memory;
- explicit current user input outranks passive inference, old memory, or stale preference;
- durable memory carries provenance and enough timing/confidence metadata for correction/supersession;
- correction, historical change, retraction, and forgetting are distinct operations;
- session context is separate from durable memory;
- provider history/caches are not canonical JARVIS memory;
- transient emotional interpretations stay transient by default;
- secrets are never normal model context;
- models do not write directly to persistent memory;
- conversation/context/memory must not have duplicate authoritative owners;
- providers/storage/retrieval components remain replaceable;
- raw full transcripts/provider payloads must not be durably retained merely because they are available;
- current runtime/config/repository truth outranks stale learned self-memory;
- Step 4 grants no autonomous repair, code modification, deployment, or authority expansion.

---

## Step-4 research disposition — COMPLETE

The research-first technology gates are answered and the resulting architecture has owner approval.

### Canonical storage

Selected direction:

- SQLCipher 4.17.0 Community / SQLite relational canonical store;
- FTS5 derived lexical index;
- JARVIS-owned bitemporal-style valid/system-time lifecycle;
- no graph/vector/database service as canonical truth owner.

### Encryption / key protection

Selected direction:

- pinned reproducible JARVIS Windows build of SQLCipher 4.17.0 behind the maintained `sqlcipher3` DB-API binding;
- random 32-byte database key;
- Windows DPAPI user-scope + purpose binding;
- no plaintext key file;
- same-user/same-machine recovery accepted for the first design;
- portable disaster recovery explicitly deferred unless separately approved.

### Structured candidate extraction

Selected architecture:

- provider-native structured output;
- explicit Pydantic contract;
- `MemoryCandidateExtractor` protocol;
- JARVIS `MemoryPolicy` retains all durable-write authority.

Provider result remains a **provisional quality tie on shared evidence** between OpenAI Terra and Gemini 3.8 Flash. Provider selection remains replaceable/configurable.

### Retrieval

Selected local pipeline:

```text
structured / temporal / authority / sensitivity eligibility
 -> exact deterministic lookup when possible
 -> SQLite FTS5 + Qwen3-Embedding-0.6B (JARVIS instruction, 256d)
 -> equal RRF (research k=60)
 -> top 3
 -> Qwen3-Reranker-0.6B BF16
 -> exact tie preserves RRF rank -> stable memory ID
 -> JARVIS ContextAssembler
```

No vector database is selected. Embeddings remain derived/rebuildable. Broad automatic semantic context injection remains calibration-gated.

### Self-knowledge

Selected direction:

- current runtime/configuration = current dynamic truth;
- accepted repository/architecture/ADRs/policies/code/tests = declared truth;
- small JARVIS Capability Registry = product capability semantics;
- CycloneDX 1.7 + `cyclonedx-bom` = generated dependency inventory;
- verified incident/episode memory = historical learned evidence;
- learned observations never silently override declared/current truth.

### Async DB boundary

Normal `aiosqlite.connect()` is not selected because it opens the standard-library `sqlite3` driver rather than the selected SQLCipher DB-API. The approved architecture uses a small thread-affinity async adapter over the proven `sqlcipher3` connection: one serialized writer worker and initially one read worker, with short transactions and WAL.

---

## Approved ownership model

```text
ConversationSession
    = canonical accepted conversation truth

LiveContext
    = current session/working context only

MemoryService
    = sole durable memory mutation/truth owner

MemoryPolicy
    = deterministic admission + lifecycle authority

MemoryRetriever
    = ranking only; never truth authority

ContextAssembler
    = sole Step-4 model-context release owner

SelfKnowledgeProvider
    = authority-aware aggregation of current/declared/historical self-knowledge
```

Approval record: `docs/research/STEP_4_ARCHITECTURE_APPROVAL.md`.

---

## Phase 4.0A — COMPLETE

Delivered:

- stable JARVIS-owned `session_id`;
- stable JARVIS-owned `turn_id`;
- timezone-aware UTC `accepted_at`;
- LiveKit/provider item IDs retained only as `external_item_id` provenance;
- neutral shared `jarvis.security` DPAPI boundary;
- existing `jarvis.identity` compatibility preserved;
- SQLCipher research probe moved to the neutral security primitive;
- focused provenance and DPAPI compatibility tests.

Validation record:

`docs/research/STEP_4_PHASE_4_0A_VALIDATION.md`

Final validation run `33947865564`:

- Ruff: PASS;
- pytest: PASS;
- Windows Hello helper: PASS;
- Windows DPAPI: PASS.

Final diff reconciliation found only the approved provenance/security/test/documentation surface. No canonical memory database or LLM memory write was introduced.

---

## Phase 4.1 — ACTIVE

Goal: build the deterministic encrypted canonical memory kernel before any model is allowed to propose or write memory.

Approved implementation scope:

- memory domain enums/value objects and provenance contracts;
- `MemoryStore` protocol;
- SQLCipher connection/key lifecycle;
- thin thread-affinity database worker boundary;
- ordered, auditable schema migrations;
- relational canonical schema and safe current-state query/view;
- bitemporal-style valid/system-time lifecycle fields;
- deterministic semantic assertion creation/change/correction/retraction/verification/expiration;
- FTS5 derived index with tested synchronization and secure-delete behavior;
- explicit physical forget across canonical + derived representations;
- deterministic exact current/history queries;
- privacy-aware operation metadata without forgotten plaintext.

Phase 4.1 implementation decisions being applied from current research:

- SQLCipher key is set before the first database read, then validated with a real schema read;
- one serialized writer follows SQLite's one-writer concurrency model; WAL permits concurrent readers;
- application schema versioning uses ordered SQL migrations with JARVIS-owned version state rather than an ORM migration framework;
- FTS5 is a derived external-content-style index synchronized by deterministic database triggers/rebuild logic;
- FTS5 `secure-delete=1` and core SQLite/SQLCipher `PRAGMA secure_delete=ON` are both required for the forget path;
- production code must not silently fall back from SQLCipher to plaintext SQLite;
- the unverified research PyPI wheel is not promoted as the production packaging decision; the selected production target remains the pinned reproducible SQLCipher 4.17 Windows artifact.

Not in Phase 4.1:

- LLM extraction;
- candidate auto-admission;
- semantic embedding/reranking;
- provider context injection;
- autonomous repair.

---

## Remaining approved implementation order

1. **Phase 4.0A — provenance + neutral security boundary** — COMPLETE.
2. **Phase 4.1 — canonical memory kernel** — ACTIVE.
3. **Phase 4.2 — LiveContext + ContextAssembler**
   - session state, sensitivity/context-release policy, turn-scoped provider integration.
4. **Phase 4.3 — explicit remember/correct/forget/inspect**
   - first useful safe cross-session memory behavior; real human acceptance.
5. **Phase 4.4 — structured extraction/candidate quarantine**
   - OpenAI/Gemini adapters, Pydantic contracts, source-trust policy;
   - implicit auto-admission remains OFF until measured precision acceptance.
6. **Phase 4.5 — semantic retrieval**
   - Qwen 256d derived embeddings, process-local exact NumPy index, FTS/RRF/top-3 reranker;
   - realistic scale + abstention/irrelevant-injection calibration before broad automatic injection.
7. **Phase 4.6 — episodic/reflection learning**
   - meaningful outcomes/decisions/incidents, not raw transcript archive.
8. **Phase 4.7 — self-knowledge foundation**
   - production Capability Registry, CycloneDX adapter, authoritative-source aggregation, drift fingerprints;
   - no autonomous repair.
9. **Phase 4.8 — hardening + real acceptance**
   - exact 4.17 owner-PC package check, backup/restore, privacy/security, multilingual/adversarial tests, real use, reconciliation, ADR, protected-main merge.

---

## Key Step-4 documents

- `docs/research/STEP_4_FINAL_TECHNOLOGY_DECISION.md`;
- `docs/research/STEP_4_ARCHITECTURE_PROPOSAL.md`;
- `docs/research/STEP_4_ARCHITECTURE_APPROVAL.md`;
- `docs/research/STEP_4_PHASE_4_0A_VALIDATION.md`;
- `docs/research/STEP_4_RETRIEVAL_TECHNOLOGY_DECISION.md`;
- `docs/research/STEP_4_MEMORY_EXTRACTION_PROVISIONAL_TIE.md`;
- `docs/research/STEP_4_SQLCIPHER_417_WINDOWS_RESULT.md`;
- `docs/research/STEP_4_SELF_KNOWLEDGE_SBOM_WINDOWS_RESULT.md`;
- `docs/research/STEP_4_TEMPORAL_FRESHNESS_PROVENANCE_REQUIREMENTS.md`;
- `docs/research/STEP_4_SELF_KNOWLEDGE_CONTINUOUS_LEARNING_REQUIREMENTS.md`.

---

## Non-blocking deferred decisions

These do not reopen the selected architecture:

- portable disaster recovery/export;
- final extraction provider winner;
- implicit durable auto-admission threshold;
- semantic abstention threshold;
- dedicated vector/ANN database if future scale proves it necessary;
- persisted crash-resume LiveContext;
- relationship/graph memory if a later use case proves measurable value;
- autonomous diagnosis/repair/self-improvement.

---

## Immediate Next Action

**IMPLEMENT PHASE 4.1 CANONICAL MEMORY KERNEL TEST-FIRST.**

Start with domain/provenance contracts, migration/schema definition, and the fail-closed SQLCipher connection boundary. Do not add LLM memory writes, implicit durable admission, or semantic provider injection in this phase.
