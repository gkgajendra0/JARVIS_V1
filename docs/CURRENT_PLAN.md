# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 ARCHITECTURE APPROVED — PHASES 4.0A–4.4 COMPLETE — PHASE 4.5 ACTIVE / RESEARCH REFRESH COMPLETE / LOCAL EMBEDDING BAKE-OFF NEXT**

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

The accepted direction remains:

```text
structured / temporal / authority / sensitivity eligibility
 -> exact lookup when possible
 -> SQLite FTS5 + local dense embeddings
 -> rank fusion
 -> small candidate set
 -> local reranker only if measured benefit remains
 -> abstention / release policy
 -> ContextAssembler
```

### Research refresh result

Current 2026 research has been refreshed before implementation.

Measured incumbent:

- `Qwen/Qwen3-Embedding-0.6B`;
- 256d Matryoshka;
- JARVIS retrieval instruction;
- existing owner-machine Recall@3 = 1.0000;
- existing RRF Recall@1 = 0.9412;
- existing top-3 Qwen reranker result = 1.0000 Recall@1/MRR.

Only new challenger worth a fresh bake-off:

- `google/embeddinggemma-300m`;
- ~308M parameters;
- 100+ languages;
- on-device/private design;
- Matryoshka embeddings;
- materially smaller model than the incumbent;
- official Sentence Transformers path.

Current mature inference boundary:

- Sentence Transformers 6.0.x family;
- native Qwen embedding integration;
- native current CrossEncoder support for Qwen3 rerankers.

Vector extension decision:

- `sqlite-vec` remains pre-v1 -> not selected;
- `sqliteai/sqlite-vector` reached 1.0 and is the preferred future extension candidate if scale proves a need;
- initial Phase-4.5 base path remains exact local cosine over derived embeddings because no current JARVIS measurement requires ANN/native vector indexing.

Research record:

- `docs/research/STEP_4_PHASE_4_5_RESEARCH_REFRESH.md`.

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

### Phase 4.5 evidence sequence

1. build a **research-only** fixed-corpus local bake-off using current stable Sentence Transformers;
2. compare exactly two embedding candidates: Qwen3-Embedding-0.6B incumbent vs EmbeddingGemma 300M challenger;
3. keep deterministic eligibility, FTS5 and RRF identical between candidates;
4. measure Recall@1, Recall@3, MRR, multilingual breakdown, no-answer behavior, encode p50/p95, model-load time, GPU/process memory and hybrid latency;
5. select EmbeddingGemma only if it materially reduces resources while meeting the required JARVIS retrieval quality; otherwise keep Qwen;
6. add Qwen3-Reranker-0.6B only if first-stage ordering errors remain and the reranker materially fixes them;
7. benchmark exact-vector scan at realistic memory scale before considering `sqlite-vector`;
8. define derived embedding storage/rebuild/physical-forget semantics;
9. implement production retrieval only after the bake-off selection is documented;
10. expand corpus for no-answer/stale/corrected/forgotten/sensitive/adversarial cases and calibrate abstention from data;
11. integrate retrieval only through `ContextAssembler`;
12. run automated + owner-PC acceptance and write Phase-4.5 closure.

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

**BUILD THE PHASE-4.5 RESEARCH-ONLY LOCAL EMBEDDING BAKE-OFF HARNESS.**

Do not modify production retrieval yet. Reuse the existing fixed JARVIS multilingual corpus and deterministic eligibility/FTS/RRF logic. Compare only Qwen3-Embedding-0.6B against EmbeddingGemma 300M under the current stable Sentence Transformers runtime, then select from measured owner-machine quality/resource data. Reranker and vector-extension decisions remain conditional on measured need.
