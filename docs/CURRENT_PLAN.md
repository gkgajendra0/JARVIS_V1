# JARVIS V1 Current Plan

## Active Step

**Step 4 is deliberately reopened for the bounded Phase 4.5E context-injection investigation. Phase 4.5E.1 shadow semantic retrieval is active. Step 5 remains planned and must not start while this slice is active.**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 BOUNDED FOUNDATION ACCEPTED — 4.5A–4.5C ACCEPTED — PROVIDER-ASSISTED 4.5D RECALL ACCEPTED — 4.5E.1 SHADOW RETRIEVAL IMPLEMENTED ON BRANCH / AUTOMATED + OWNER-MACHINE ACCEPTANCE IN PROGRESS — AUTOMATIC MEMORY INJECTION STILL DISABLED — STEP 5 NOT STARTED**

This file is the operational source of truth. Detailed measurements and experiment evidence belong in `docs/research/`; only accepted architecture belongs in `docs/CURRENT_ARCHITECTURE.md` and ADRs.

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
- `MemoryService` remains the sole canonical durable-memory mutation facade;
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

Accepted behavior remains:

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

Accepted local derived retrieval foundation:

- `Qwen/Qwen3-Embedding-0.6B`, revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- normalized 256-dimensional vectors;
- eligible-current SQLite FTS5 lexical retrieval;
- exact local cosine dense retrieval;
- equal-weight RRF with `k=60`;
- `Qwen/Qwen3-Reranker-0.6B`, revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- top-3 reranking, BF16 owner path, deterministic tie handling.

Accepted owner GPU environment remains Torch `2.13.0+cu132`, Torchvision `0.28.0+cu132`, Transformers `5.16.1`, SentenceTransformers `6.0.1`, and RTX 5060 Ti 8 GB.

### 4.5D bounded provider-assisted recall

The accepted explicit `recall_memory` tool remains unchanged. It uses the active provider only for bounded structured facet selection and a second semantic release check, with JARVIS retaining canonical key reconstruction, exact lookup, lifecycle/security policy, and release authority.

Historical acceptance evidence:

- `docs/research/STEP_4_PHASE_4_5D_PROVIDER_ASSISTED_FALLBACK.md`

The strict independent 4.5D semantic verifier remains deferred/unresolved. Retired 4.5D corpora and failed approaches must not be reused as fresh 4.5E training/evaluation data.

---

## Phase 4.5E technology decision

**ADAPT the accepted JARVIS memory stack. Do not adopt a second memory framework.**

Current research found that Mem0, LangGraph/LangMem, Zep/Graphiti, LlamaIndex-style memory/RAG stacks and similar products overlap with storage/retrieval/reranking mechanics JARVIS already owns or has accepted. They do not solve JARVIS's actual 4.5E authority question: whether a true retrieved memory should influence this specific answer.

Security guidance also treats persistent/retrieved memory as an injection/poisoning surface. Therefore semantic similarity or reranker score may nominate evidence but must never by itself authorize provider-context injection.

---

## Phase 4.5E.1 — active bounded slice

### Goal

Measure what the accepted local retrieval stack proposes for ordinary accepted USER turns **without allowing those proposals to affect the answer**.

### Implemented branch flow

```text
accepted canonical USER turn
 -> session-local MemoryContextShadowRuntime
 -> RetrievalEligibility.cloud_context()
 -> refresh missing/stale rebuildable derived embeddings only
 -> Qwen query embedding
 -> existing FTS5 + dense + RRF first stage
 -> existing Qwen top-3 reranker
 -> session-local diagnostic observation
 -> metrics/logging

NO ContextAssembler mutation
NO provider-context insertion
NO provider relevance call
NO canonical memory mutation
NO automatic memory influence
```

### Runtime boundaries

- feature flag: `JARVIS_MEMORY_CONTEXT_SHADOW_ENABLED=false` by default;
- enabling it requires `JARVIS_MEMORY_ENABLED=true`;
- only already-accepted canonical USER turns are observed;
- work is scheduled asynchronously through the existing accepted-turn observer boundary;
- encoder/reranker adapters are process-scoped and lazy-loaded once, then shared across sessions;
- shadow observations are session-local and disposed on session close;
- model/shadow failures cannot fail canonical conversation or change provider context;
- normal production logs contain turn IDs, assertion IDs, counts, and latency, not raw remembered values;
- `RetrievalEligibility.cloud_context()` applies before any learned ranking;
- `local_only` / `secret_prohibited` values therefore cannot enter this cloud-context candidate path;
- missing/stale vector rows may be rebuilt because they are encrypted derived artifacts, not canonical truth.

### Important implementation discovery

Existing durable assertions are not guaranteed to already possess Qwen embedding rows because 4.5A established vector storage, 4.5B established retrieval, 4.5C established model adapters, and the accepted 4.5D provider fallback did not need those local models.

Phase 4.5E.1 therefore refreshes only missing/stale derived embeddings before measuring the dense path. Without this, a supposedly semantic shadow run could silently degrade to lexical-only retrieval and produce misleading evidence.

---

## Phase 4.5E.1 acceptance gates

### Automated

Must pass on the exact branch head:

- Ruff formatting;
- Ruff lint;
- full pytest;
- Windows DPAPI smoke;
- Windows Hello helper build/probe;
- tests proving USER-only shadow observation;
- tests proving cloud-context eligibility;
- tests proving derived-vector refresh and reuse;
- tests proving model failure isolation;
- tests proving session evidence disposal;
- composition test proving process-shared model adapters plus session-local shadow runtimes.

### Owner-machine

After automated gates are green, run the exact branch on the owner Windows/RTX 5060 Ti machine with 4.5E shadow enabled and verify:

1. normal wake/conversation behavior remains usable;
2. local Qwen models load and execute on the accepted GPU stack;
3. the first eligible-memory pass may rebuild missing derived vectors, then later turns reuse them;
4. ordinary USER turns produce top-3 shadow observations without changing spoken answers;
5. raw memory values are not emitted in normal logs;
6. conversation continues truthfully if shadow retrieval/model work fails;
7. GPU/resource impact is acceptable alongside the existing voice/vision/identity runtime.

Do **not** call 4.5E.1 accepted until this owner-machine run is complete.

---

## Phase 4.5E.2 — blocked on 4.5E.1 evidence

Only after 4.5E.1 acceptance, create a new frozen 4.5E-specific evaluation corpus. Do not reuse the retired 4.5D corpora for model selection.

The next decision separates deterministic vetoes from semantic usefulness:

Deterministic vetoes:

- ineligible;
- sensitive beyond cloud-context policy;
- stale where freshness policy forbids use;
- conflicting/ambiguous canonical state;
- instruction-like or authority-seeking memory content.

Semantic utility candidates:

- `ESSENTIAL`;
- `HELPFUL`;
- `UNNECESSARY`;
- `STEERING_RISK`.

The first technology to bake off is a second task-specific prompt over the already-loaded Qwen reranker. No numeric threshold is accepted in advance; any release rule must come from measured false-influence/precision evidence.

---

## Phase 4.5E.3 — not authorized

Actual ordinary-conversation injection remains disabled.

If 4.5E.2 later passes, the first proposed activation remains deliberately narrow:

- at most one memory;
- `ESSENTIAL` only initially;
- current exact canonical assertion only;
- cloud-context eligible;
- deterministic vetoes passed;
- bounded token budget;
- rendered as explicitly non-authoritative factual data;
- routed only through `ContextAssembler`;
- current user text always outranks memory;
- uncertain means do not inject.

No code for this activation should be written before 4.5E.2 evidence and explicit owner approval.

---

## Immediate Next Action

**Finish Phase 4.5E.1 automated validation, then run owner-machine shadow acceptance.**

Step 5 remains not started. Automatic provider-context memory injection remains disabled.
