# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 ARCHITECTURE APPROVED — PHASES 4.0A, 4.1, 4.2, 4.3 AND 4.4 COMPLETE — PHASE 4.5 ACTIVE / RESEARCH REFRESH NEXT**

This file is the operational source of truth for current work. Detailed measured evidence belongs in `docs/research/`; significant accepted architecture decisions belong in `docs/decisions/`; `docs/CURRENT_ARCHITECTURE.md` describes architecture that actually exists and has passed acceptance.

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
- one active cloud-AI provider/account owns production cloud intelligence at a time;
- different model IDs inside the active provider are allowed when capability/efficiency requires them;
- local ML/model artifacts are not cloud-provider subscriptions;
- Step 4 grants no autonomous repair, code modification, deployment, or authority expansion.

---

## Technology disposition already accepted

### Canonical memory

- SQLCipher 4.17.0 Community / SQLite canonical relational store;
- accepted SQLite baseline 3.53.3;
- FTS5 derived lexical index;
- JARVIS-owned temporal lifecycle;
- no graph/vector service as canonical truth owner.

### Encryption/key protection

- pinned reproducible Windows SQLCipher build;
- random 32-byte database key;
- Windows DPAPI user scope + purpose binding;
- no plaintext key file.

### Cloud-AI provider boundary

ADR-015 establishes one canonical production provider through `JARVIS_AI_PROVIDER` / `JarvisConfig.ai_provider`.

Current active provider: **Gemini**.

Voice, scripted cloud TTS, memory extraction and future cloud-reasoning/tool workloads remain inside the selected provider family/account.

### Phase 4.4 selected extraction model

**`gemini-3.5-flash-lite`**

Accepted measured evidence:

- 14/14 provider-eligible cases schema-valid;
- 100% intent/type/durable core exact accuracy;
- zero false durable proposals;
- zero missed durable candidates;
- English 10/10, Hindi 1/1, Hinglish 3/3;
- p50 ~1.636 s, p95/max ~2.415 s;
- 6,748 input + 1,293 output tokens across the full 14-call run;
- owner-PC production path accepted with no cross-session durable resurrection.

`gemini-3.8-flash` was not run because the staged escalation condition was not met.

---

## Phase status

### Phase 4.0A — COMPLETE

Stable conversation provenance and neutral DPAPI security boundary accepted.

### Phase 4.1 — COMPLETE

Encrypted canonical memory kernel, temporal lifecycle, FTS5 synchronization/rebuild, secure physical forget and exact current queries accepted.

### Phase 4.2 — COMPLETE

Bounded LiveContext + deterministic ContextAssembler accepted. Provider history remains non-canonical.

### Phase 4.3 — COMPLETE

Governed explicit `remember / inspect / correct / forget` accepted through the normal production voice path.

Owner-PC acceptance proved remember -> cross-process recall -> correction -> corrected cross-process recall -> physical forget -> absence, plus implicit-write and credential rejection.

### Phase 4.4 — COMPLETE

Structured extraction + session-local candidate quarantine accepted.

Permanent accepted behavior:

```text
accepted canonical USER turn
 -> deterministic source / explicit-control / secret gates
 -> active-provider structured extraction
 -> typed proposal
 -> deterministic JARVIS policy
 -> session-local quarantine
 -> physical disposal on session close
 X  no MemoryService durable mutation
 X  no SQLCipher/FTS/embedding write
 X  no automatic durable admission
```

Owner-PC acceptance proved:

- ordinary fact -> Flash-Lite proposal -> `outcome=quarantined`;
- `durable_admission=False`;
- no explicit remember tool call for ordinary facts after routing hardening;
- ordinary implicit memory handling remains invisible to conversation;
- session close -> `disposed_candidates=1`, `quarantine_disposed=True`;
- fresh explicit memory query -> Phase-4.3 exact lookup miss;
- no durable resurrection of the synthetic value;
- wake/Pocket3/Gemini/vision/return-to-wake stable;
- CAM++/LR-ASD/prototype/authority behavior unchanged.

Closure records:

- `docs/research/STEP_4_PHASE_4_4_GEMINI_MODEL_SELECTION.md`;
- `docs/research/STEP_4_PHASE_4_4_OWNER_PC_ACCEPTANCE.md`;
- `docs/research/STEP_4_PHASE_4_4_IMPLEMENTATION_RESULT.md`.

---

## Phase 4.5 — ACTIVE

### Goal

Add semantic retrieval over **eligible canonical memory** without letting retrieval establish, modify, resurrect, or override truth.

The previously researched target architecture is:

```text
structured / temporal / authority / sensitivity eligibility
 -> exact lookup when possible
 -> SQLite FTS5 + local dense embeddings
 -> rank fusion
 -> small candidate set
 -> local reranker
 -> abstention / release policy
 -> ContextAssembler
```

The prior research candidate stack was:

```text
FTS5
 + Qwen3-Embedding-0.6B
 + reciprocal-rank fusion
 + Qwen3-Reranker-0.6B
```

**Do not implement this stack blindly.** Per the project research-first rule, Phase 4.5 begins with a fresh web verification of current model/library/runtime options and Windows/RTX suitability before code changes.

### Phase 4.5 mandatory invariants

- only canonical eligible memory may be retrieved;
- current/valid records outrank expired/superseded history;
- sensitivity/release eligibility is applied before provider context release;
- retrieval ranks evidence only and never establishes truth;
- embeddings/reranker outputs are derived/rebuildable artifacts;
- physical forget must remove or make unretrievable every derived representation;
- no vector service becomes canonical truth owner;
- exact lookup remains preferred when a deterministic exact key exists;
- no provider history/cache becomes memory;
- no cloud-AI second provider may be introduced for retrieval;
- local retrieval must not alter Step-3 audio/vision/authority behavior;
- abstention thresholds must be measured, not guessed.

### Phase 4.5 planned evidence sequence

1. research-refresh current embedding/reranker/runtime options;
2. select the smallest sufficient local retrieval stack;
3. define derived embedding storage/rebuild/forget semantics;
4. implement lexical + dense retrieval behind an explicit interface;
5. implement deterministic rank fusion;
6. implement local reranking only if measured benefit justifies it;
7. build a fixed semantic retrieval corpus including exact, paraphrase, stale, corrected, forgotten, sensitive and no-answer cases;
8. calibrate abstention from measured data rather than an arbitrary score;
9. integrate only through `ContextAssembler`;
10. run automated + owner-PC acceptance;
11. write Phase-4.5 closure before Phase 4.6 begins.

---

## Remaining approved implementation order

1. Phase 4.0A — provenance + neutral security — **COMPLETE**.
2. Phase 4.1 — canonical memory kernel — **COMPLETE**.
3. Phase 4.2 — LiveContext + ContextAssembler — **COMPLETE**.
4. Phase 4.3 — explicit remember/correct/forget/inspect — **COMPLETE**.
5. Phase 4.4 — structured extraction/candidate quarantine — **COMPLETE**.
6. Phase 4.5 — semantic retrieval + abstention calibration — **ACTIVE**.
7. Phase 4.6 — episodic/reflection learning for meaningful outcomes/decisions/incidents, not raw transcripts.
8. Phase 4.7 — Capability Registry + CycloneDX + authoritative self-knowledge aggregation, no autonomous repair.
9. Phase 4.8 — final hardening, multilingual/adversarial/privacy/security/backup tests, real use, reconciliation, ADR, protected-main merge.

---

## Non-blocking deferred decisions

- portable disaster recovery/export;
- implicit durable auto-admission threshold;
- deterministic canonical subject/predicate normalization for future implicit admission;
- dedicated ANN/vector derivative if memory scale later requires it;
- persisted crash-resume LiveContext;
- relationship/graph memory;
- automatic provider chat-history synchronization;
- autonomous diagnosis/repair/self-improvement.

---

## Immediate Next Action

**BEGIN PHASE-4.5 RESEARCH REFRESH BEFORE IMPLEMENTATION.**

Re-verify current local embedding, reranking, SQLite/FTS/vector-adjacent tooling, model licensing, Windows/CUDA support, memory footprint, multilingual quality and deployment maturity. Prefer mature existing solutions over custom retrieval infrastructure. Do not write Phase-4.5 production code until that comparison is documented and the retrieval architecture is reconfirmed.
