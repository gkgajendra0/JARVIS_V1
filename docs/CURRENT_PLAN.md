# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 ARCHITECTURE APPROVED — PHASES 4.0A–4.4 COMPLETE — PHASE 4.5 ACTIVE / RETRIEVAL STACK SELECTED / PRODUCTION IMPLEMENTATION ACTIVE**

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

## Accepted Step-4 technology

### Canonical memory + security

- SQLCipher 4.17.0 Community / SQLite 3.53.3 canonical relational store;
- FTS5 derived lexical index with secure-delete behavior;
- JARVIS-owned bitemporal/current lifecycle;
- random 32-byte SQLCipher key protected by Windows DPAPI user scope + purpose binding;
- no graph/vector service as canonical truth owner.

### Active cloud-AI provider

ADR-015 establishes one canonical production provider through `JARVIS_AI_PROVIDER` / `JarvisConfig.ai_provider`.

Current active provider: **Gemini**.

Voice, scripted cloud TTS, structured memory extraction and future cloud-reasoning/tool workloads remain inside the selected provider family/account.

### Phase 4.4 structured extraction

Selected model: **`gemini-3.5-flash-lite`**.

Owner-PC production acceptance proved session-local candidate quarantine, physical disposal on session close, no implicit durable write, no cross-session resurrection, and stable Step-3 audio/vision behavior.

### Phase 4.5 local retrieval stack — SELECTED

The 2026 incumbent/challenger bake-off is complete on the actual JARVIS RTX 5060 Ti.

**Selected embedding:** `Qwen/Qwen3-Embedding-0.6B`

Production retrieval contract:

- JARVIS memory-specific query instruction;
- normalized embeddings;
- 256-dimensional Matryoshka output;
- model-native BF16 path where supported;
- exact local cosine initially;
- SQLite FTS5 lexical rank;
- equal-weight RRF, measured contract `k=60`, lexical window `10`;
- top-3 `Qwen/Qwen3-Reranker-0.6B` at model-default BF16;
- exact reranker-score tie -> preserve first-stage fused rank -> stable memory ID;
- no dedicated ANN/vector extension until scale evidence requires one;
- no absolute embedding/reranker threshold until a larger abstention corpus is measured.

Measured Qwen owner-machine evidence:

- dense Recall@1 `0.8824`, Recall@3 `1.0000`, MRR `0.9412`;
- FTS5 + Qwen RRF Recall@1 `0.9412`, Recall@3 `1.0000`, MRR `0.9608`;
- hybrid p50 `63.2179 ms`, p95 `68.7911 ms`;
- peak CUDA allocation `1,292,429,824` bytes;
- top-3 Qwen reranker previously measured Recall@1/Recall@3/MRR `1.0000` on the same fixed retrieval corpus;
- BF16 reranker precision follow-up showed zero repeat/order instability.

Rejected challenger: **`google/embeddinggemma-300m`**.

Reason:

- dense overall Recall@1 tied Qwen at `0.8824`;
- actual hybrid Recall@1 regressed to `0.7647`;
- Hindi fixed case failed at rank 1 and Hinglish hybrid Recall@1 fell to `0.7143`;
- hybrid p50/p95 were slower (`84.0370 / 96.7016 ms`);
- measured peak CUDA and process RSS were higher despite the smaller parameter count.

Selection record:

- `docs/research/STEP_4_PHASE_4_5_EMBEDDING_SELECTION.md`.

---

## Phase status

### Phase 4.0A — COMPLETE

Stable conversation provenance and neutral DPAPI security boundary accepted.

### Phase 4.1 — COMPLETE

Encrypted canonical memory kernel, temporal lifecycle, FTS5 synchronization/rebuild, secure physical forget and exact current queries accepted.

### Phase 4.2 — COMPLETE

Bounded `LiveContext` + deterministic `ContextAssembler` accepted. Provider history remains non-canonical.

### Phase 4.3 — COMPLETE

Governed explicit `remember / inspect / correct / forget` accepted through the normal production voice path.

### Phase 4.4 — COMPLETE

Structured extraction + session-local candidate quarantine accepted. Implicit auto-admission remains disabled.

### Phase 4.5 — ACTIVE

Goal: production semantic retrieval over **eligible canonical memory**, without giving retrieval any truth or mutation authority.

Target pipeline:

```text
query/context need
 -> deterministic exact current lookup when possible
 -> canonical eligibility (state/time/authority/sensitivity)
 -> FTS5 lexical rank + Qwen3-Embedding-0.6B dense rank
 -> equal-weight RRF
 -> top 3 eligible candidates
 -> Qwen3-Reranker-0.6B BF16
 -> measured abstention/release policy
 -> ContextAssembler
 -> active Gemini session
```

#### Phase 4.5A — encrypted derived-vector lifecycle — ACTIVE

Implement:

- SQLCipher migration for derived semantic vectors;
- canonical assertion FK with `ON DELETE CASCADE`;
- explicit model ID + immutable revision + dimension + dtype/byte-order + content fingerprint metadata;
- little-endian float32 vector BLOB representation;
- deterministic stale-vector detection/rebuild semantics;
- tests proving physical forget atomically removes derived vectors.

#### Phase 4.5B — lexical + dense + RRF retrieval core — NEXT

Implement:

- current eligible assertion selection before ranking;
- safe FTS5 lexical retrieval;
- exact dense cosine over encrypted/rebuildable stored vectors;
- equal-weight RRF (`k=60`, lexical window `10`);
- deterministic first-stage ordering;
- no ANN dependency.

#### Phase 4.5C — Qwen local model adapters — NEXT

Implement lazy local adapters behind narrow protocols:

- `Qwen/Qwen3-Embedding-0.6B`, 256d, normalized query/document encoding;
- immutable model-revision pin;
- `Qwen/Qwen3-Reranker-0.6B`, top 3, BF16;
- deterministic exact-score tie handling;
- no model import/load in ordinary unit-test paths unless explicitly requested.

Do **not** silently change the accepted Step-3 Torch/CUDA production dependency set. Reconcile the local retrieval dependency path with existing vision/identity GPU constraints through measured owner-machine compatibility before final production enablement.

#### Phase 4.5D — abstention calibration — BLOCKED ON 4.5A–C

Expand the acceptance corpus with many more:

- absent-answer queries;
- ambiguous/near-miss queries;
- stale/superseded/history cases;
- corrected and forgotten memories;
- sensitivity boundaries;
- adversarial/poisoned content;
- English/Hindi/Hinglish paraphrases.

No absolute embedding/reranker cutoff is approved before this measurement.

#### Phase 4.5E — ContextAssembler integration + owner acceptance — BLOCKED ON 4.5D

- release only accepted retrieval evidence through `ContextAssembler`;
- preserve bounded context budgets and evidence metadata;
- never release `LOCAL_ONLY` or `SECRET_PROHIBITED` content to cloud context;
- run automated + owner-PC GPU/voice acceptance;
- record closure before starting Phase 4.6.

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

**IMPLEMENT PHASE 4.5A — ENCRYPTED DERIVED-VECTOR LIFECYCLE.**

Add the migration/store contract first, with physical-forget cascade and rebuild/version tests. Do not wire semantic retrieval into production conversation until the derived-vector lifecycle is correct and CI-clean. Then proceed to 4.5B lexical+dense+RRF core.
