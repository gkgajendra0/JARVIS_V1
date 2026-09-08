# JARVIS V1 Current Plan

## Active Step

**Step 4 remains deliberately reopened for the bounded Phase 4.5E context-injection investigation. Phase 4.5E.1 functional owner-machine shadow evidence passed, its CPU/GPU resource-profile gate is explicitly deferred by the owner, and Phase 4.5E.2 research/bake-off is now active on a stacked branch. Step 5 remains planned and must not start while this work is active.**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 BOUNDED FOUNDATION ACCEPTED — 4.5A–4.5C ACCEPTED — PROVIDER-ASSISTED 4.5D RECALL ACCEPTED — 4.5E.1 FUNCTIONAL OWNER SHADOW PASS / RESOURCE PROFILE DEFERRED — 4.5E.2 RESEARCH-ONLY UTILITY/STEERING BAKE-OFF ACTIVE — AUTOMATIC MEMORY INJECTION STILL DISABLED — STEP 5 NOT STARTED**

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

Research found that Mem0, LangGraph/LangMem, Zep/Graphiti, LlamaIndex-style memory/RAG stacks and similar products overlap with storage/retrieval/reranking mechanics JARVIS already owns or has accepted. They do not solve JARVIS's actual 4.5E authority question: whether a true retrieved memory should influence this specific answer.

Current 2026 memory-security guidance also treats persistent/retrieved memory as an injection/poisoning surface. Therefore semantic similarity or reranker score may nominate evidence but must never by itself authorize provider-context injection.

---

## Phase 4.5E.1 — functional owner pass; resource profile deferred

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

### Automated evidence

Exact E.1 head:

`62b9fc082438b153d770ba65d6bcf45018840aa7`

GitHub Actions `Code Quality` run `34195010898` passed on that exact SHA:

- Ruff formatting: PASS;
- Ruff lint: PASS;
- full pytest: PASS;
- Windows DPAPI smoke: PASS;
- Windows Hello helper build/probe: PASS.

### Owner-machine evidence

Functional owner-machine testing on the Windows/RTX 5060 Ti/Pocket3 runtime established:

1. normal wake/conversation remained usable;
2. both accepted Qwen models loaded and executed;
3. previously created derived vectors were reused (`indexed_embeddings=0`);
4. direct personal queries ranked the correct test memory first for test color, vehicle, and city;
5. unrelated/advice turns still returned top-3 candidates, proving retrieval alone cannot authorize influence;
6. normal 4.5E logs emitted opaque assertion IDs rather than raw remembered values;
7. `context_injection=False` remained true;
8. 4.5D semantic recall continued to release supported exact personal facts and abstain on unsupported queries;
9. warm 4.5E shadow latency settled around the ~0.6–0.75 second range in the observed run.

The remaining acceptance item is the explicit CPU/GPU resource-profile gate. The owner chose to defer this measurement while development continues. It is **not waived**.

**Do not record Phase 4.5E.1 as fully accepted until the deferred resource-profile gate is completed.**

---

## Phase 4.5E.2 — research / bake-off active on stacked branch

Branch:

`implementation/step-4-phase45e2-utility-gate`

This branch is stacked on the exact E.1 head rather than merging an incompletely accepted slice.

Fresh research is documented in:

- `docs/research/STEP_4_PHASE_4_5E2_UTILITY_GATE_RESEARCH.md`

The key question is:

> Should this already-eligible current memory influence this answer at all?

### First technology candidate

Reuse the already-loaded revision-pinned `Qwen/Qwen3-Reranker-0.6B` with task-specific CrossEncoder prompts. Do not load a second utility model for the first bake-off.

The first research harness measures three semantic scores over the same query/memory pair:

- essential;
- helpful;
- steering risk.

Evaluation labels remain:

- `ESSENTIAL`;
- `HELPFUL`;
- `UNNECESSARY`;
- `STEERING_RISK`.

### Fresh evaluation corpus

Research-only files:

- `tools/research/step4_phase45e2_utility_corpus.json`
- `tools/research/step4_phase45e2_qwen_utility_bakeoff.py`

The corpus is newly written for 4.5E.2 and does not reuse retired 4.5D data.

Initial corpus:

- 64 balanced cases;
- 16 per label;
- English cases `01`–`08` per label are calibration;
- Hinglish/Hindi cases `09`–`16` per label are frozen holdout.

### Threshold policy

No numeric threshold is accepted in advance.

The research harness derives candidate thresholds from calibration score boundaries, prioritizing:

1. minimum unsafe false influence;
2. minimum missed steering risk;
3. maximum essential recall;
4. maximum helpful recall;
5. macro F1.

Any resulting threshold tuple is measurement evidence only. It has no provider-context authority.

### Boundaries retained

Existing deterministic eligibility/lifecycle/security/provenance controls remain upstream of learned utility work.

Instruction-like/authority-seeking content is a steering/security concern, but Phase 4.5E.2 must not falsely label a probabilistic language-model judgement as a deterministic security boundary.

### Current E.2 rule

**Research/bake-off only. No ContextAssembler change. No provider-context insertion. No Phase 4.5E.3 code.**

The next decision comes from the owner-GPU bake-off output, especially multilingual holdout false influence and steering-risk misses.

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

**Validate the Phase 4.5E.2 research harness in CI, then run the fresh Qwen utility/steering bake-off on the owner RTX 5060 Ti and inspect calibration vs frozen Hinglish/Hindi holdout evidence.**

The Phase 4.5E.1 CPU/GPU resource-profile gate remains explicitly deferred and open.

Step 5 remains not started. Automatic provider-context memory injection remains disabled.
