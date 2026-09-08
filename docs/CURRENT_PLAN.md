# JARVIS V1 Current Plan

## Active Step

**Step 4 Phase 4.5D bounded provider-assisted semantic recall fallback is active. Step 5 remains not started.**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 FOUNDATION THROUGH 4.5C ACCEPTED — STRICT INDEPENDENT 4.5D GUARD REMAINS DEFERRED / UNRESOLVED — OWNER-AUTHORIZED PROVIDER-ASSISTED 4.5D FALLBACK ACTIVE — STEP 5 PLANNED / NOT STARTED**

This file is the operational source of truth. Detailed measurements and retired experiments belong in `docs/research/`; only accepted architecture belongs in `docs/CURRENT_ARCHITECTURE.md` and ADRs.

---

## Permanent Step-4 constraints retained

- not every sentence becomes durable memory;
- explicit current owner input outranks passive inference, old memory, or stale preference;
- durable memory carries provenance + freshness/verification metadata;
- correction, historical change, retraction, and forgetting are distinct;
- session context is separate from durable memory;
- provider history/caches are not canonical memory;
- secrets are never normal durable memory/model context;
- models do not write persistent memory directly;
- `MemoryService` is the sole durable mutation facade;
- `ContextAssembler` is the sole Step-4 provider-context release owner;
- retrieval ranks already-eligible canonical records and never establishes truth;
- canonical lifecycle/security/sensitivity filtering occurs before learned ranking/judging;
- current runtime/config/repository truth outranks learned self-memory;
- production cloud intelligence remains under one provider switch (`JARVIS_AI_PROVIDER`);
- learned components never create, modify, resurrect, or establish canonical truth;
- Step 4 grants no autonomous repair, deployment, code-modification, or authority expansion.

---

## Accepted Step-4 bounded foundation

### 4.0A–4.4

Accepted behavior includes:

- stable conversation provenance;
- bounded `LiveContext` and deterministic `ContextAssembler`;
- SQLCipher canonical memory with JARVIS-owned temporal lifecycle;
- Windows DPAPI protected database key;
- governed explicit `remember`, `inspect`, `correct`, and `forget`;
- structured memory-candidate extraction through the active provider;
- session-local candidate quarantine;
- no implicit durable candidate admission;
- physical quarantine disposal on session close.

Selected Phase-4.4 provider model: **`gemini-3.5-flash-lite`**.

### 4.5A–4.5C

The derived retrieval foundation remains accepted:

**Embedding:** `Qwen/Qwen3-Embedding-0.6B`

- revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- normalized 256d contract;
- exact local cosine.

**First stage:**

- eligible-current SQLite FTS5 lexical rank;
- exact Qwen dense rank;
- equal-weight RRF, `k=60`;
- development candidate depth `10` where applicable.

**Reranker:** `Qwen/Qwen3-Reranker-0.6B`

- revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- BF16 owner path;
- deterministic tie handling.

Accepted owner environment:

- Torch `2.13.0+cu132`;
- Torchvision `0.28.0+cu132`;
- Transformers `5.16.1`;
- SentenceTransformers `6.0.1`;
- NVIDIA GeForce RTX 5060 Ti 8 GB.

The structured exact-facet/query-policy scaffolding is retained because it preserves deterministic lifecycle/security boundaries. It is **not** promoted as an automatic conversational semantic-release authority.

---

## Phase status at bounded closure

- **4.0A — COMPLETE**
- **4.1 — COMPLETE**
- **4.2 — COMPLETE**
- **4.3 — COMPLETE**
- **4.4 — COMPLETE**
- **4.5A — COMPLETE**
- **4.5B — COMPLETE**
- **4.5C — COMPLETE**
- **4.5D — DEFERRED / UNRESOLVED:** no tested semantic release/answerability authority met the frozen safety boundary.
- **4.5E — DEFERRED:** automatic semantic memory injection into normal conversation remains disabled.
- **4.6–4.8 — DEFERRED / NOT STARTED:** excluded from the bounded Step-4 closure rather than blocking later roadmap work.

Closure record:

- `docs/research/STEP_4_PHASE_4_5D_DEFERRED_CLOSURE.md`

---

## Why 4.5D is deferred

The blocker is semantic sufficiency/answer-role safety, not canonical storage or basic retrieval.

Multiple research-backed frozen methods failed:

1. **V4 composite acceptance — FAIL / RETIRED**
   - `docs/research/STEP_4_PHASE_4_5D_V4_ACCEPTANCE_RESULT.md`
2. **Task-specific guard Method V2 — FAIL / RETIRED**
   - `docs/research/STEP_4_PHASE_4_5D_TASK_SPECIFIC_GUARD_BAKEOFF_V2_RESULT.md`
   - every frozen-embedding classifier produced unsafe false allows.
3. **Custom fine-tune V3 — SUPERSEDED BEFORE EXECUTION**
   - no owner result; executable fine-tune path was not promoted.
4. **Answerability Component Bake-Off V1 — FAIL / RETIRED**
   - `docs/research/STEP_4_PHASE_4_5D_ANSWERABILITY_BAKEOFF_V1_RESULT.md`
   - XLM-R SQuAD2: 45 unauthorized releases + 2 wrong evidence spans;
   - mDeBERTa SQuAD2: 39 unauthorized releases + 8 wrong evidence spans;
   - native NLI forced all 24 neutral/unknown comparisons into YES/NO.
5. **Question-Role Bake-Off V1 — FAIL / RETIRED**
   - `docs/research/STEP_4_PHASE_4_5D_QUESTION_ROLE_BAKEOFF_V1_RESULT.md`
   - Mini and Ultra collapsed to one veto class across all 480 cases;
   - allow recall was 0.0 in EN / HI / Hinglish.

No failed model is promoted and no gate is weakened.

---

## Safe runtime state after closure

```text
explicit governed memory operations            ENABLED / ACCEPTED
candidate extraction + session quarantine      ENABLED when configured / ACCEPTED
canonical SQLCipher memory                     ACCEPTED
4.5A–4.5C derived retrieval/reranking          ACCEPTED foundation
automatic semantic release to Gemini chat      DISABLED / NOT ACCEPTED
4.5D semantic release authority                DEFERRED
4.5E normal semantic conversational injection  DEFERRED
```

`ContextAssembler` must not silently start releasing derived semantic retrieval results merely because the retrieval infrastructure exists.

---

## Retired-corpus rule

Do not rerun, tune, train on, or use as fresh replacement-model scoring data:

- retired V4 query text/results;
- Method V2 train/holdout text/results;
- Answerability V1 corpus/results (`3e2bd6830df3d08b3ea4ce8e045ee78cf562c228c5b0d2e5e094ffa42b6b44a3`);
- Question-Role V1 corpus/results (`bb09a6a6b7c6f9248c48f35a39e5f4f8002f678a471d4752152c6a6b26cd4c21`).

If 4.5D is reopened later, use a fresh never-exposed corpus and a materially new architecture/technology reason.

---

## Cleanup decision

At closure:

- durable research/result Markdown is preserved;
- accepted production Step-4 code/tests are preserved;
- latest retired Answerability V1 and Question-Role V1 executable harnesses/tests are removed from the working tree;
- the unexecuted GLiClass runtime-sanity harness/test is removed;
- experiment-only optional dependency groups used only by those removed latest harnesses are removed;
- Git history remains the archive for exact retired executable source.

---

## Reopened bounded 4.5D fallback

The owner authorized a pragmatic provider-assisted recall path on 2026-09-08. The strict independent semantic guard remains unresolved; this does not rewrite the failed research evidence. The bounded fallback uses the active `JARVIS_AI_PROVIDER` for both structured query interpretation and a second structured semantic `ALLOW/ABSTAIN` verification around JARVIS-owned exact canonical lookup. It is opt-in through `JARVIS_MEMORY_SEMANTIC_RECALL_MODEL`, fail-closed on all provider/validation errors, and never releases `local_only` or secret-prohibited memory to the cloud provider. See `docs/research/STEP_4_PHASE_4_5D_PROVIDER_ASSISTED_FALLBACK.md`.

Step 5 remains explicitly not started until this fallback is integrated and the owner separately authorizes Step 5.

---

## Immediate Next Action

**WAIT FOR OWNER AUTHORIZATION.**

Do not start Step 5 research, architecture, implementation, dependency selection, or code changes until the owner explicitly says to start Step 5.

When authorized, Step 5 begins from its normal lifecycle: requirements recovery → current web research → technology decision → architecture → approval → implementation.
