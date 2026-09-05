# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 TECHNOLOGY RESEARCH COMPLETE — FINAL ARCHITECTURE PROPOSAL READY — HUMAN APPROVAL REQUIRED BEFORE IMPLEMENTATION**

This file is the operational source of truth for current work. Detailed evidence belongs in `docs/research/`; significant accepted architecture decisions belong in `docs/decisions/`; `docs/CURRENT_ARCHITECTURE.md` continues to describe only architecture that actually exists and has been accepted.

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

## Step-4 research disposition — COMPLETE FOR ARCHITECTURE APPROVAL

The research-first technology gates are sufficiently answered.

### Canonical storage

Selected direction:

- SQLCipher 4.17.0 Community / SQLite relational canonical store;
- FTS5 derived lexical index;
- JARVIS-owned bitemporal-style valid/system-time lifecycle;
- no graph/vector/database service as canonical truth owner.

Real-machine SQLite/FTS testing demonstrated the required temporal behavior, multilingual lexical lookup, secure-delete availability, and explicit-forget cleanup at 30,000 synthetic records.

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

Provider result remains a **provisional quality tie on shared evidence** between OpenAI Terra and Gemini 3.8 Flash. Provider selection therefore remains replaceable/configurable and does not block architecture approval.

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

No vector database is selected. Embeddings remain derived/rebuildable. Broad automatic semantic context injection remains calibration-gated because no production abstention threshold has been invented.

### Self-knowledge

Selected direction:

- current runtime/configuration = current dynamic truth;
- accepted repository/architecture/ADRs/policies/code/tests = declared truth;
- small JARVIS Capability Registry = product capability semantics;
- CycloneDX 1.7 + `cyclonedx-bom` = generated dependency inventory;
- verified incident/episode memory = historical learned evidence;
- learned observations never silently override declared/current truth.

The Windows self-knowledge spike passed with 92 SBOM components, 8 research capability declarations, 45 authoritative source fingerprints, and zero failed validation checks.

### Async DB boundary

Normal `aiosqlite.connect()` is not selected because it opens the standard-library `sqlite3` driver rather than the selected SQLCipher DB-API. The proposal uses a small thread-affinity async adapter over the proven `sqlcipher3` connection: one serialized writer worker and initially one read worker, with short transactions and WAL.

---

## Human-review documents

Final research technology decision:

- `docs/research/STEP_4_FINAL_TECHNOLOGY_DECISION.md`

Final architecture proposal:

- `docs/research/STEP_4_ARCHITECTURE_PROPOSAL.md`

Important supporting evidence:

- `docs/research/STEP_4_RETRIEVAL_TECHNOLOGY_DECISION.md`;
- `docs/research/STEP_4_MEMORY_EXTRACTION_PROVISIONAL_TIE.md`;
- `docs/research/STEP_4_SQLCIPHER_417_WINDOWS_RESULT.md`;
- `docs/research/STEP_4_SELF_KNOWLEDGE_SBOM_WINDOWS_RESULT.md`;
- `docs/research/STEP_4_TEMPORAL_FRESHNESS_PROVENANCE_REQUIREMENTS.md`;
- `docs/research/STEP_4_SELF_KNOWLEDGE_CONTINUOUS_LEARNING_REQUIREMENTS.md`.

---

## Proposed ownership model awaiting approval

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

---

## Proposed implementation order after approval

1. **Phase 4.0A — provenance + neutral security boundary**
   - stable JARVIS `session_id`, `turn_id`, `accepted_at`;
   - move/generalize proven DPAPI primitive behind `jarvis.security` without identity regression.
2. **Phase 4.1 — canonical memory kernel**
   - SQLCipher store, migrations, temporal schema, provenance, lifecycle, FTS, explicit forget;
   - no LLM auto-write.
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

**HUMAN REVIEW / APPROVAL OF `STEP_4_ARCHITECTURE_PROPOSAL.md`.**

No production Step-4 memory implementation begins until the owner explicitly approves the architecture. On approval, start Phase 4.0A on a dedicated implementation branch with provenance IDs and the neutral security boundary—not automatic LLM memory writing.