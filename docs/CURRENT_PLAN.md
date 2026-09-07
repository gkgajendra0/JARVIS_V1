# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — PHASE 4.5D ACTIVE — V4 / METHOD V2 / ANSWERABILITY V1 / QUESTION-ROLE V1 FAILED + RETIRED — CUSTOM FINE-TUNE V3 SUPERSEDED BEFORE EXECUTION — GLiClass UPSTREAM-CONTRACT RUNTIME SANITY DIAGNOSTIC PREPARED / PRE-OWNER — PHASE 4.5E BLOCKED**

This file is the operational source of truth. Detailed measurements and retired experiments belong in `docs/research/`; only accepted architecture belongs in ADRs / `docs/CURRENT_ARCHITECTURE.md`.

---

## Permanent Step-4 constraints

- not every sentence becomes durable memory;
- explicit current owner input outranks passive inference, old memory, or stale preference;
- durable memory carries provenance + freshness/verification metadata;
- correction, historical change, retraction, and forgetting are distinct;
- session context is separate from durable memory;
- provider history/caches are not canonical memory;
- secrets are never normal durable memory/model context;
- models do not write persistent memory directly;
- `MemoryService` is the sole durable mutation facade;
- `ContextAssembler` is the sole Step-4 model-context release owner;
- retrieval ranks already-eligible canonical records and never establishes truth;
- canonical eligibility/security filtering occurs before learned ranking/judging;
- current runtime/config/repository truth outranks learned self-memory;
- production cloud intelligence remains under one provider switch (`JARVIS_AI_PROVIDER=gemini`);
- learned components may veto/select a route only within explicitly frozen contracts; they never create canonical truth;
- Step 4 grants no autonomous repair, deployment, code-modification, or authority expansion.

---

## Accepted Step-4 foundation

### Canonical memory + security

- SQLCipher 4.17.0 Community / SQLite 3.53.3 canonical relational store;
- FTS5 derived lexical index;
- JARVIS-owned temporal/current lifecycle;
- random SQLCipher key protected by Windows DPAPI user scope + purpose binding;
- no graph/vector service as canonical truth owner.

### Phase 4.4 structured extraction

Selected provider model: **`gemini-3.5-flash-lite`**.

Owner acceptance proved session-local candidate quarantine, disposal on session close, no implicit durable write, no cross-session resurrection, and preserved Step-3 audio/vision behavior.

### Phase 4.5 retrieval family accepted through 4.5C

**Embedding:** `Qwen/Qwen3-Embedding-0.6B`

- revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- normalized 256d contract;
- exact local cosine.

**First stage:**

- eligible-current SQLite FTS5 lexical rank;
- exact Qwen dense rank;
- equal-weight RRF, `k=60`;
- development retrieval candidate depth `10` where applicable.

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

Development evidence already proved top-10 first-stage + reranked positive recall `900/900` on the exposed V2 corpus. Do not swap Qwen models or embedding dimensions merely to fix 4.5D semantics.

### Structured exact-facet direction retained

The structured-query-planner diagnostic established that exact canonical facet lookup itself is valuable:

- deterministic lifecycle/security boundaries remained intact;
- no wrong-memory release among intended exact-current targets;
- demonstrated false releases were **question-focus errors**: why/reason, who/provenance, replacement/successor, and linked-record questions were incorrectly routed to the current-value facet.

Existing `MemoryQueryProposal` / `MemoryQueryPolicy` remains provider-independent authority scaffolding. Provider proposals are advisory; deterministic JARVIS policy and canonical lookup remain authoritative.

---

## Phase status

- **4.0A — COMPLETE:** stable conversation provenance + neutral DPAPI boundary.
- **4.1 — COMPLETE:** encrypted canonical memory kernel, temporal lifecycle, FTS5 synchronization, secure forget.
- **4.2 — COMPLETE:** bounded `LiveContext` + deterministic `ContextAssembler`.
- **4.3 — COMPLETE:** governed explicit remember / inspect / correct / forget through production voice path.
- **4.4 — COMPLETE:** structured extraction + session-local candidate quarantine; implicit auto-admission disabled.
- **4.5A — COMPLETE:** encrypted derived-vector lifecycle.
- **4.5B — COMPLETE:** production lexical+dense+RRF retrieval core.
- **4.5C — COMPLETE:** revision-pinned lazy Qwen embedding/reranker adapters + owner RTX coexistence.
- **4.5D — ACTIVE:** safe semantic route / evidence-release semantics.
- **4.5E — BLOCKED:** do not wire semantic memory retrieval into normal Gemini conversation yet.
- **4.6–4.8 — NOT STARTED.**

---

# Phase 4.5D — active problem

Goal: safely determine **what answer role the user is requesting** and whether an already-eligible canonical current fact is allowed to answer it.

The retained end-state direction remains layered and fail-closed:

```text
raw user query
    ↓
provider structured proposal (advisory)
    AND
independent semantic validation / abstention signal
    ↓ strict consensus
JARVIS deterministic policy / lifecycle / security / grounding
    ↓
exact canonical facet lookup
    ↓
if comparison and answerability is already established:
    downstream truth evaluator may answer YES/NO
    ↓
deterministic factual composition
```

No learned component may resurrect forgotten data, expose local-only/secret data, invent a canonical facet/value, or override JARVIS policy.

---

## Retired evidence

### V4 final composite acceptance — FAIL / RETIRED

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_V4_ACCEPTANCE_RESULT.md`.

Never rerun, tune on, train on, or score replacement candidates on V4 query text/results. V4 remains an exact-query deny-list and architectural evidence only.

### Task-specific local guard Method V2 — FAIL / RETIRED

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_TASK_SPECIFIC_GUARD_BAKEOFF_V2_RESULT.md`.

Owner SHA:

`d9dc8cc06edd81288c6af370c0032a7f771e8b23`

Every frozen-embedding + LogisticRegression candidate violated the zero-false-allow boundary. Do not rerun/tune Method V2.

### Custom eight-class fine-tune V3 — SUPERSEDED BEFORE EXECUTION

The prepared mmBERT/XLM-R custom fine-tune was never owner-run. Its executable path was removed before training/scoring after deeper mature-solution research.

Historical method:

- `docs/research/STEP_4_PHASE_4_5D_TASK_GUARD_FINETUNE_V3_METHOD.md`.

There is no V3 result evidence.

### Answerability Component Bake-Off V1 — FAIL / RETIRED

Durable owner result:

- `docs/research/STEP_4_PHASE_4_5D_ANSWERABILITY_BAKEOFF_V1_RESULT.md`.

Owner SHA:

`97c26819ddcaa66e7b3a8822ef23fe40ee8c4ced`

Frozen corpus SHA:

`3e2bd6830df3d08b3ea4ce8e045ee78cf562c228c5b0d2e5e094ffa42b6b44a3`

Key result:

- XLM-R SQuAD2: `45` unauthorized no-answer releases + `2` wrong evidence spans; answerable recall `0.604167`;
- mDeBERTa SQuAD2: `39` unauthorized no-answer releases + `8` wrong evidence spans; answerable recall `0.718750`;
- native multilingual NLI: all `24/24` neutral/unknown cases forced to YES/NO, but answerable comparison recall `1.000000` with zero wrong YES↔NO verdicts.

**Diagnosis:** generic SQuAD2 readers are unsafe as evidence-release authorities. Native NLI is useful only as a downstream truth evaluator after an independent answerability gate has already established that a comparison is answerable. Do not rerun or threshold-tune this corpus.

### Question-Role Bake-Off V1 — FAIL / RETIRED

Method:

- `docs/research/STEP_4_PHASE_4_5D_QUESTION_ROLE_BAKEOFF_V1_METHOD.md`.

Durable owner result:

- `docs/research/STEP_4_PHASE_4_5D_QUESTION_ROLE_BAKEOFF_V1_RESULT.md`.

Owner SHA:

`bd67a91ff6dda4875ca62375c8a497d56c5ae315`

Frozen corpus SHA:

`bb09a6a6b7c6f9248c48f35a39e5f4f8002f678a471d4752152c6a6b26cd4c21`

Owner result:

| Candidate | Unsafe false approvals | False vetoes | Allow recall | Exact role accuracy | Macro-F1 | Behavior | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| GLiClass Multilang Mini | 0 | 96 | 0.000000 | 0.100000 | 0.018182 | predicted `broad_recall` for all 480 cases | FAIL |
| GLiClass Multilang Ultra | 0 | 96 | 0.000000 | 0.100000 | 0.018182 | predicted `historical_value` for all 480 cases | FAIL |

Both models had EN / HI / Hinglish allow recall `0.0`. The zero unsafe-approval count is not a safety success because neither model approved any allow case at all.

**Diagnosis:** the frozen V1 formulation is unusable and permanently retired. The universal one-class collapse is pathological enough that it does not, by itself, prove GLiClass is generally incapable of multilingual intent classification.

Ultra also emitted a Transformers-v5 tied-weight / missing-key warning for `model.encoder_model.encoder.embed_tokens.weight`. The same warning is an acknowledged upstream GLiClass issue; maintainers have stated that it is a warning and that the model otherwise works, so the warning alone cannot be treated as the root cause.

Do not rerun Question-Role V1, alter its prompt/labels and call it the same experiment, fit thresholds on it, train on it, or score new candidates on its 480 exposed queries.

---

# Immediate 4.5D diagnostic — GLiClass upstream-contract runtime sanity

Purpose: separate **runtime/checkpoint/pipeline compatibility** from the failed JARVIS V1 formulation before abandoning or reusing the GLiClass family.

This is a tiny diagnostic, not a JARVIS benchmark and not an acceptance test.

Harness:

- `tools/research/step4_phase45d_gliclass_runtime_sanity_v1.py`
- `tests/test_phase45d_gliclass_runtime_sanity_v1.py`

It uses only public GLiClass model-card examples:

- English NASA topic classification;
- documented English alarm-intent classification;
- German NASA classification;
- Arabic NASA text with English labels;
- French government text with English economy/politics labels.

It also compares individual inference against a shared-label batch made only from those public examples.

### Frozen diagnostic constraints

- same pinned Mini/Ultra revisions used in Question-Role V1;
- accepted owner runtime unchanged;
- no Question-Role V1 query text;
- no JARVIS custom role labels;
- no JARVIS task prompt;
- no training;
- no threshold fitting;
- zero cloud/provider calls;
- Safetensors-only / `trust_remote_code=False`;
- separate output artifact `.step4-phase45d-gliclass-runtime-sanity-v1.json`;
- refuses overwrite;
- cannot authorize production, Question-Role V1 rerun, final acceptance, or Phase 4.5E.

### Frozen diagnostic interpretation

If the documented public examples also collapse, or shared-label batch top labels materially disagree with individual inference, reject GLiClass from the accepted runtime path.

If the documented public examples behave normally and batch/individual behavior is consistent, treat the accepted runtime as usable and retain Question-Role V1 as a **formulation/design failure**. Do not rerun V1; research and freeze a separate next architecture/corpus.

No conclusion about a next production guard may be made from this sanity diagnostic alone.

---

## Phase 4.5E — BLOCKED

Do **not** wire semantic memory retrieval into `ContextAssembler` / normal Gemini conversation.

4.5E may begin only after 4.5D has a fresh accepted end-to-end architecture, durable owner evidence, synchronized docs, and a green exact closure SHA.

---

## Do not repeat / do not do next

Do not:

- rerun/tune V4;
- rerun/tune Method V2;
- resurrect the removed custom V3 fine-tune;
- rerun or threshold-tune Answerability V1;
- rerun Question-Role V1;
- reuse exposed V1/V2/V4/question-role case text as fresh scoring data;
- fit GLiClass confidence/margin thresholds on the exposed 480 question-role cases;
- train/fine-tune on the exposed 480 question-role cases;
- add hand-written Hindi/Hinglish keyword patches;
- downgrade Transformers for GLiNER2.5;
- bypass GLiNER2 dependency safety with `--no-deps`;
- swap Qwen embedding/reranker or embedding dimensions merely to fix answer-role semantics;
- weaken lifecycle/security filters;
- let any learned component create, modify, resurrect, or establish canonical truth;
- start 4.5E.

---

## Immediate Next Action

**DO NOT RUN THE GLiClass RUNTIME SANITY DIAGNOSTIC UNTIL ITS EXACT FINAL BRANCH SHA HAS FULL GREEN CI.**

Before owner execution, certify on one exact SHA:

- Ruff formatting + lint;
- full pytest;
- Windows DPAPI;
- Windows Hello;
- no temporary workflow/script artifacts;
- diagnostic-only contract unchanged;
- exact Mini/Ultra revisions unchanged;
- owner Torch/Torchvision/Transformers/GLiClass versions unchanged.

After certification, run the runtime sanity diagnostic once. Do not rerun Question-Role V1 regardless of its result.
