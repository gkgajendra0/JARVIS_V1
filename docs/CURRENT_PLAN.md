# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 ARCHITECTURE APPROVED — PHASES 4.0A–4.5C COMPLETE — PHASE 4.5D ACTIVE / OWNER RTX ABSTENTION CALIBRATION NEXT**

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

**Embedding:** `Qwen/Qwen3-Embedding-0.6B`

- immutable revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- exact JARVIS memory retrieval instruction;
- normalized 256-dimensional Matryoshka output;
- local exact cosine initially.

**First stage:**

- eligible-current SQLite FTS5 lexical rank;
- exact Qwen dense rank;
- equal-weight RRF, `k=60`, lexical window `10`;
- no ANN/vector extension until scale evidence requires one.

**Reranker:** `Qwen/Qwen3-Reranker-0.6B`

- immutable revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- top 3 candidates;
- model-default BF16 path;
- exact reranker-score tie -> first-stage fused rank -> stable assertion ID.

Owner-machine model-selection evidence:

- Qwen hybrid Recall@1 `0.9412`, Recall@3 `1.0000`, MRR `0.9608`;
- hybrid p50 `63.2179 ms`, p95 `68.7911 ms`;
- earlier reranker follow-up reached Recall@1/Recall@3/MRR `1.0000` on the fixed selection corpus;
- EmbeddingGemma was rejected because the actual multilingual hybrid path regressed and measured latency/RAM/VRAM did not improve.

Selection record:

- `docs/research/STEP_4_PHASE_4_5_EMBEDDING_SELECTION.md`.

### Phase 4.5C accepted production GPU compatibility

Owner-machine acceptance preserved the existing Step-3 stack exactly:

- Torch `2.13.0+cu132` before and after retrieval dependency install;
- Torchvision `0.28.0+cu132` before and after;
- Sentence Transformers `6.0.1`;
- Transformers `5.16.1`;
- `pip check` clean;
- `torchvision`, `rfdetr`, `trackers`, `mediapipe`, and `cv2` all import in the same process;
- real Qwen embedding + reranker both run together on the RTX 5060 Ti;
- camera memory ranks top-1 through dense and reranker checks;
- combined Qwen peak CUDA allocation `2,462,774,784` bytes.

No compatibility rerun is required unless model/dependency/Torch revisions change.

Result record:

- `docs/research/STEP_4_PHASE_4_5C_IMPLEMENTATION_STATUS.md`.

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

#### Phase 4.5A — encrypted derived-vector lifecycle — COMPLETE

Implemented and validated:

- SQLCipher schema v2 derived semantic vectors;
- canonical assertion FK with `ON DELETE CASCADE`;
- model/revision/dimension/dtype/byte-order/content-fingerprint lineage;
- little-endian float32 vector BLOB representation;
- deterministic stale-vector detection;
- canonical physical forget -> zero derived vector rows.

Result:

- `docs/research/STEP_4_PHASE_4_5A_IMPLEMENTATION_RESULT.md`.

#### Phase 4.5B — lexical + dense + RRF retrieval core — COMPLETE

Implemented and validated:

- current eligible assertion selection before ranking;
- assertion + provenance authority/sensitivity filtering;
- safe FTS5 MATCH construction;
- exact dense cosine over encrypted/rebuildable vectors;
- stale vector exclusion;
- equal-weight RRF (`k=60`, lexical window `10`);
- deterministic first-stage ordering;
- no ANN dependency.

GitHub Actions run `33983727641` passed Ruff, full pytest, Windows DPAPI, and Windows Hello.

Result:

- `docs/research/STEP_4_PHASE_4_5B_IMPLEMENTATION_RESULT.md`.

#### Phase 4.5C — Qwen local model adapters — COMPLETE

Implemented and owner-accepted:

- lazy revision-pinned Qwen embedder and reranker adapters;
- 256d normalized query/document encoding;
- exact measured JARVIS query instruction;
- top-3 reranker;
- deterministic ties;
- `trust_remote_code=False`;
- no model import/load in ordinary unit-test/startup paths;
- isolated optional `retrieval` dependency extra;
- retrieval extra does not own/change Torch;
- owner RTX compatibility PASS with the accepted Step-3 vision environment.

Result:

- `docs/research/STEP_4_PHASE_4_5C_IMPLEMENTATION_STATUS.md`.

#### Phase 4.5D — abstention calibration — ACTIVE

Research and implementation are ready for measured owner-machine calibration.

Research decision:

- Qwen reranker scores are decision/logit scores, not universal probabilities;
- do not guess an absolute score/cosine cutoff;
- use fixed labeled calibration and held-out validation splits;
- derive threshold candidates only from calibration observations/midpoints;
- minimize false releases first, then maximize correct release recall, then prefer simpler policy;
- freeze policy before validation;
- any validation false release is blocking and must not be tuned away using validation labels.

Fixed corpus:

- 64 queries total;
- calibration: 16 release + 16 abstain;
- validation: 16 release + 16 abstain;
- English/Hindi/Hinglish;
- absent, near-miss, ambiguous, historical, forgotten, local-only, secret, untrusted, adversarial lexical, negation, and relation-mismatch boundaries.

Harness:

- `tools/research/step4_phase45d_abstention_calibration.py`;
- uses the real production lifecycle, embedding store, eligibility, FTS5+dense+RRF retrieval service, Qwen embedder, and Qwen reranker against a temporary synthetic/project-style database;
- does not read owner production memory;
- does not auto-write a production threshold.

Research/status records:

- `docs/research/STEP_4_PHASE_4_5D_ABSTENTION_RESEARCH.md`;
- `docs/research/STEP_4_PHASE_4_5D_IMPLEMENTATION_STATUS.md`.

#### Phase 4.5E — ContextAssembler integration + owner acceptance — BLOCKED ON 4.5D

After an abstention/release policy is measured and accepted:

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
6. Phase 4.5A — derived-vector lifecycle — **COMPLETE**.
7. Phase 4.5B — lexical+dense+RRF core — **COMPLETE**.
8. Phase 4.5C — local Qwen adapters + GPU compatibility — **COMPLETE**.
9. Phase 4.5D — abstention calibration — **ACTIVE**.
10. Phase 4.5E — ContextAssembler integration + owner acceptance — **BLOCKED ON 4.5D**.
11. Phase 4.6 — episodic/reflection learning for meaningful outcomes/decisions/incidents, not raw transcripts.
12. Phase 4.7 — Capability Registry + CycloneDX + authoritative self-knowledge aggregation, no autonomous repair.
13. Phase 4.8 — final hardening, multilingual/adversarial/privacy/security/backup tests, real use, reconciliation, ADR, protected-main merge.

---

## Non-blocking deferred decisions

- portable disaster recovery/export;
- implicit durable auto-admission threshold;
- deterministic canonical subject/predicate normalization for future implicit admission;
- dedicated ANN/vector derivative if memory scale later requires it;
- persisted crash-resume LiveContext;
- relationship/graph memory;
- automatic provider chat-history synchronization;
- learned probability calibrator for semantic release, until enough independent real labeled data exists;
- autonomous diagnosis/repair/self-improvement.

---

## Immediate Next Action

**RUN THE FIXED PHASE 4.5D OWNER RTX ABSTENTION CALIBRATION ONCE.**

Use the accepted Windows `.venv` and existing cached Qwen models. Generate `.step4-phase45d-abstention-calibration.json`, then review calibration + held-out validation evidence before accepting any production release/abstain policy.

Do not rerun Phase 4.5C. Do not tune a policy against held-out validation merely to make the result pass. Do not begin Phase 4.5E until Phase 4.5D is formally accepted.
