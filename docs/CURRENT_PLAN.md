# JARVIS V1 Current Plan

## Active Step

**No implementation step is active. Step 4 is closed with an accepted bounded provider-assisted 4.5D recall fallback. Step 5 remains planned and not started until explicit owner authorization.**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 BOUNDED COMPLETE — 4.5A–4.5C ACCEPTED — PROVIDER-ASSISTED 4.5D RECALL FALLBACK ACCEPTED — STRICT INDEPENDENT 4.5D VERIFIER STILL DEFERRED / UNRESOLVED — 4.5E AUTOMATIC CONTEXT INJECTION DEFERRED — STEP 5 PLANNED / NOT STARTED**

This file is the operational source of truth. Detailed measurements and retired experiments belong in `docs/research/`; accepted architecture belongs in `docs/CURRENT_ARCHITECTURE.md` and ADRs.

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
- `ContextAssembler` remains the sole owner of ordinary provider-context assembly;
- retrieval ranks already-eligible canonical records and never establishes truth;
- canonical lifecycle/security/sensitivity filtering occurs before learned semantic work;
- current runtime/config/repository truth outranks learned self-memory;
- production cloud intelligence remains under one provider switch (`JARVIS_AI_PROVIDER`);
- learned/provider components never create, modify, resurrect, or establish canonical truth;
- Step 4 grants no autonomous repair, deployment, code-modification, or authority expansion.

---

## Accepted Step-4 foundation

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

The accepted derived retrieval foundation remains:

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

### 4.5D bounded provider-assisted recall — ACCEPTED

The original goal of an independent proof-quality multilingual semantic release guard remains unresolved. After the frozen local/generic approaches failed, the owner explicitly authorized a pragmatic fallback.

Accepted flow:

```text
latest accepted USER question
 -> active-provider structured query selection
 -> provider selects one numbered cloud-safe eligible facet
 -> JARVIS reconstructs the exact canonical key
 -> deterministic grounding/query policy
 -> one exact eligible current canonical assertion
 -> second same-provider structured semantic verifier
 -> JARVIS RELEASE only for directly-supported current value/comparison
 -> otherwise ABSTAIN
 -> zero-argument recall_memory tool result to realtime conversation
```

Critical retained boundaries:

- the realtime model cannot supply a memory key to `recall_memory`;
- provider facet selection is only an index into a JARVIS-owned eligible catalog;
- JARVIS reconstructs canonical `subject_scope` / `subject` / `predicate` itself;
- `local_only` and `secret_prohibited` memory never enter the cloud recall path;
- exact lookup must resolve one current canonical assertion;
- provider errors, malformed output, ambiguity, conflicts, semantic-role vetoes, and quota failures all fail closed to ABSTAIN;
- provider output never mutates canonical truth.

Configuration:

- opt-in model setting: `JARVIS_MEMORY_SEMANTIC_RECALL_MODEL`;
- model must belong to the active `JARVIS_AI_PROVIDER` family;
- owner acceptance on Gemini used **`gemini-3.5-flash`**.

Final owner-tested code SHA before documentation-only closure commits:

`bd95734032e2f936945fa02e16bb002ac6b478ea`

Full Code Quality run `34190011723` passed Ruff, full pytest, Windows Hello, and Windows DPAPI.

Owner live acceptance passed on the disposable `test_color = purple` memory:

- `What is my test color?` -> released `purple`;
- `My test color is purple, right?` -> released/confirmed `purple`;
- `Why is my test color purple?` -> abstained and did not invent a reason;
- `Jarvis forget my test color.` -> explicit physical forget committed.

Durable acceptance record:

- `docs/research/STEP_4_PHASE_4_5D_PROVIDER_ASSISTED_FALLBACK.md`

### What remains unresolved/deferred

- **Strict independent 4.5D verifier — DEFERRED / UNRESOLVED.** No tested independent learned/QA/NLI/question-role authority met the frozen safety boundary.
- **4.5E automatic semantic memory injection — DEFERRED.** `ContextAssembler` does not automatically inject ranked semantic memories into normal conversation.
- **4.6–4.8 — DEFERRED / NOT STARTED.** These do not block later roadmap work.

The accepted 4.5D fallback is therefore **bounded useful recall**, not a claim that the original independent semantic authorization problem is solved.

---

## Retired 4.5D evidence remains authoritative

The following failed/exposed methods remain retired and must not be rerun, tuned, trained on, or used as fresh replacement-model scoring data:

1. **V4 composite acceptance — FAIL / RETIRED**
   - `docs/research/STEP_4_PHASE_4_5D_V4_ACCEPTANCE_RESULT.md`
2. **Task-specific guard Method V2 — FAIL / RETIRED**
   - `docs/research/STEP_4_PHASE_4_5D_TASK_SPECIFIC_GUARD_BAKEOFF_V2_RESULT.md`
3. **Custom fine-tune V3 — SUPERSEDED BEFORE EXECUTION**
   - no owner result; executable fine-tune path was not promoted.
4. **Answerability Component Bake-Off V1 — FAIL / RETIRED**
   - `docs/research/STEP_4_PHASE_4_5D_ANSWERABILITY_BAKEOFF_V1_RESULT.md`
5. **Question-Role Bake-Off V1 — FAIL / RETIRED**
   - `docs/research/STEP_4_PHASE_4_5D_QUESTION_ROLE_BAKEOFF_V1_RESULT.md`

Retired corpus identifiers remain:

- Answerability V1: `3e2bd6830df3d08b3ea4ce8e045ee78cf562c228c5b0d2e5e094ffa42b6b44a3`;
- Question-Role V1: `bb09a6a6b7c6f9248c48f35a39e5f4f8002f678a471d4752152c6a6b26cd4c21`.

The original bounded deferral record remains historical evidence:

- `docs/research/STEP_4_PHASE_4_5D_DEFERRED_CLOSURE.md`

The later provider-assisted acceptance does not rewrite or invalidate those failures.

---

## Accepted runtime state after final Step-4 closure

```text
explicit governed memory operations              ENABLED / ACCEPTED
candidate extraction + session quarantine        ENABLED when configured / ACCEPTED
canonical SQLCipher memory                       ACCEPTED
4.5A–4.5C derived retrieval/reranking            ACCEPTED foundation
provider-assisted recall_memory tool             ACCEPTED when explicitly configured
strict independent 4.5D semantic verifier        DEFERRED / UNRESOLVED
4.5E automatic ContextAssembler semantic inject  DEFERRED / DISABLED
remaining unstarted Step-4 extensions            DEFERRED
```

Provider availability is a real residual dependency. The owner observed `gemini-3.8-flash` HTTP 500/429 quota failures; JARVIS correctly abstained with `provider_memory_release_guard_unavailable`. The successful owner acceptance used `gemini-3.5-flash`. Provider failure must continue to degrade to truthful abstention rather than cross-provider fallback or memory release.

---

## Immediate Next Action

**WAIT FOR OWNER AUTHORIZATION TO START STEP 5.**

Do not start Step 5 research, architecture, dependency selection, implementation, or code changes until the owner explicitly says to start Step 5.

When authorized, Step 5 begins from the normal lifecycle:

`requirements recovery -> current web research -> technology decision -> architecture -> owner approval -> implementation`.
