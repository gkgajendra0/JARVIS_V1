# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — PHASE 4.5D ACTIVE — V4 / METHOD V2 / ANSWERABILITY V1 FAILED + RETIRED — CUSTOM FINE-TUNE V3 SUPERSEDED BEFORE EXECUTION — QUESTION-ROLE BAKE-OFF V1 FROZEN / PRE-OWNER — PHASE 4.5E BLOCKED**

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

The current architecture hypothesis is deliberately split:

```text
raw user query
    ↓
provider structured proposal (advisory)
    AND
local independent question-role veto
    ↓ strict consensus
JARVIS deterministic policy / lifecycle / security / grounding
    ↓
exact canonical facet lookup
    ↓
if comparison: downstream truth evaluator may answer YES/NO
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

Every frozen-embedding + LogisticRegression candidate violated the zero-false-allow boundary:

| Candidate | False allows | Allow recall | Comparison recall | Macro-F1 |
| --- | ---: | ---: | ---: | ---: |
| MiniLM L12 | 9 | 0.791667 | 0.625000 | 0.646962 |
| E5-small | 11 | 0.854167 | 0.708333 | 0.726627 |
| MPNet-base-v2 | 12 | 0.854167 | 0.750000 | 0.809516 |
| Qwen3-Embedding 0.6B / 256d | 14 | 0.791667 | 0.625000 | 0.623784 |

Do not rerun/tune Method V2.

### Custom eight-class fine-tune V3 — SUPERSEDED BEFORE EXECUTION

The prepared mmBERT/XLM-R custom fine-tune was never owner-run. Its executable path was removed before training/scoring after deeper mature-solution research. Historical rationale remains in:

- `docs/research/STEP_4_PHASE_4_5D_TASK_GUARD_FINETUNE_V3_METHOD.md`.

There is no V3 result evidence.

### Answerability Component Bake-Off V1 — FAIL / RETIRED

Method:

- `docs/research/STEP_4_PHASE_4_5D_ANSWERABILITY_BAKEOFF_METHOD.md`.

Durable owner result:

- `docs/research/STEP_4_PHASE_4_5D_ANSWERABILITY_BAKEOFF_V1_RESULT.md`.

Owner SHA:

`97c26819ddcaa66e7b3a8822ef23fe40ee8c4ced`

Frozen corpus SHA:

`3e2bd6830df3d08b3ea4ce8e045ee78cf562c228c5b0d2e5e094ffa42b6b44a3`

Result:

| Component | Unsafe release result | Answerable / comparison recall | Result |
| --- | --- | ---: | --- |
| XLM-R SQuAD2 | 45 unauthorized no-answer releases + 2 wrong evidence spans | 0.604167 | FAIL |
| mDeBERTa SQuAD2 | 39 unauthorized no-answer releases + 8 wrong evidence spans | 0.718750 | FAIL |
| native mDeBERTa NLI | 24/24 neutral/unknown cases forced to YES/NO; 0 wrong YES↔NO verdicts | 1.000000 | FAIL |

Language QA recall also showed the multilingual-backbone limitation: mDeBERTa achieved EN `0.96875` but HI and Hinglish only `0.59375` each.

**Diagnosis:** generic SQuAD2 readers are unsafe as evidence-release authorities; native NLI is excellent at truth classification once a comparison is answerable but is unsafe as an abstention authority. V1 is exposed and retired. Do not threshold-tune or rerun it.

---

# Active 4.5D development direction — multilingual question-role veto

The next test is intentionally narrower than QA or query+document semantic sufficiency.

Question being tested:

> Can a mature multilingual zero-shot classifier identify the **type of answer requested by the raw user query** well enough to veto inappropriate exact-current-fact routing?

This reuses the retained structured exact-facet architecture instead of adding another document reader.

## Why GLiNER2.5 is not the next implementation

GLiNER2.5 Multi was researched as a current schema-conditioned multilingual alternative. Its current local dependency contract requires Transformers `<5`, while JARVIS is accepted on Transformers `5.16.1`.

Therefore do not:

- downgrade the accepted Transformers runtime;
- install GLiNER2 with `--no-deps` / unsupported compatibility bypasses;
- use a third-party workaround in the memory safety boundary.

GLiNER2.5 remains a future/watchlist candidate when upstream supports the accepted runtime cleanly.

## Selected mature family — GLiClass Multilang

`gliclass==0.1.20` explicitly supports Transformers `>=5` and Torch `>=2`.

This is materially different from the prior failed GLiClass binary semantic judge:

- old task: `query + memory document → RELEASE/ABSTAIN`, margin threshold calibrated on exposed data — retired;
- new task: `raw query → one requested answer role`, native **single-label softmax argmax**, no memory document, no confidence threshold.

The GLiClass implementation itself uses threshold only for multi-label mode; single-label mode always uses softmax argmax.

---

## Question-Role Bake-Off V1 — FROZEN / PRE-OWNER

Method:

- `docs/research/STEP_4_PHASE_4_5D_QUESTION_ROLE_BAKEOFF_V1_METHOD.md`.

Harness:

- `tools/research/step4_phase45d_question_role_cases.py`;
- `tools/research/step4_phase45d_question_role_bakeoff.py`;
- `tests/test_phase45d_question_role_bakeoff.py`.

Optional dependency group:

- `.[phase45d-question-role]`
- `gliclass==0.1.20`
- `psutil==7.2.2`

The group does not pin/reinstall Torch or Transformers; the accepted owner versions must remain intact.

### Fresh frozen corpus

- 8 fresh synthetic subjects/facts;
- EN / HI / Hinglish;
- 10 semantic answer roles;
- 2 paraphrases per fact/language/role;
- total `480` cases;
- `96` allow cases;
- `384` veto cases;
- payload SHA-256 `bb09a6a6b7c6f9248c48f35a39e5f4f8002f678a471d4752152c6a6b26cd4c21`;
- exact-query deny-list against Answerability V1, Method V2 train+holdout, and V4;
- zero task-specific training;
- zero cloud/provider calls.

### Frozen answer roles

Only these may approve the exact current-fact path:

1. `current_value`
2. `current_value_comparison`

These veto it:

3. `reason_explanation`
4. `provenance_actor`
5. `replacement_successor`
6. `related_record`
7. `historical_value`
8. `external_source`
9. `broad_recall`
10. `advice_or_other`

Positive and negated present-value comparisons are both deliberately classified as `current_value_comparison`; negation alone is not a veto.

### Frozen candidates

Both were frozen before any fresh-corpus owner result:

1. `knowledgator/gliclass-multilang-mini`
   - revision `0bd888b6c3ef9fca5f0a9d407bddfbbc7623486b`.
2. `knowledgator/gliclass-multilang-ultra`
   - revision `9d6ca10258a3bddcf05b88c89cb8a8390e87e90c`.

Candidates run sequentially, Safetensors-only, `trust_remote_code=False`. If Ultra cannot fit on the accepted RTX path, record `RESOURCE_REJECTED`; do not change precision, quantize, or swap models after evidence is visible.

### Frozen inference contract

- `classification_type = single-label`;
- decision = native softmax argmax;
- fitted threshold = none;
- few-shot examples = zero;
- fixed task prompt and fixed descriptive role labels;
- max length `256`;
- batch `8`;
- zero cloud calls.

### Frozen development gates

A candidate must satisfy every gate:

1. **zero unsafe false approvals** from any of the 384 veto cases;
2. **zero wrong allow modes** between direct current-value and current-value-comparison;
3. overall exact allow-role recall >= `0.90`;
4. exact `current_value` recall >= `0.90`;
5. exact `current_value_comparison` recall >= `0.90`;
6. EN allow recall >= `0.85`;
7. HI allow recall >= `0.85`;
8. Hinglish allow recall >= `0.85`;
9. argmax only / no threshold;
10. zero cloud/provider calls.

Exact 10-role accuracy and macro-F1 are diagnostic only.

### Development-pass meaning

A passing candidate does **not** authorize production or final acceptance.

It authorizes only a **fresh composite integration benchmark** using:

```text
provider structured proposal
AND
local question-role approval
AND
deterministic JARVIS policy / exact facet / security
→ exact lookup
```

For approved comparisons only, the already-pinned native NLI may be tested downstream as YES/NO truth evaluation because V1 showed perfect answerable comparison recall with zero wrong verdicts. It must not become the abstention gate.

Only after the complete composite contract is frozen and passes fresh development evidence may a never-exposed final acceptance be created.

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
- reuse any exposed V1/V2/V4 text as fresh scoring data;
- alter Question-Role V1 prompt, labels, cases, candidate set, revisions, gates, or argmax contract after owner results and call it the same evidence;
- fit GLiClass confidence/margin thresholds on the fresh 480 cases;
- train/fine-tune on the fresh 480 cases;
- add hand-written Hindi/Hinglish keyword rules;
- downgrade Transformers for GLiNER2.5;
- bypass GLiNER2 dependency safety with `--no-deps`;
- swap Qwen embedding/reranker or embedding dimensions merely to fix answer-role semantics;
- weaken lifecycle/security filters;
- let any learned component create, modify, resurrect, or establish canonical truth;
- start 4.5E.

---

## Immediate Next Action

**DO NOT RUN QUESTION-ROLE V1 UNTIL THE EXACT FINAL BRANCH SHA HAS FULL GREEN CI.**

Before owner execution, certify on one exact SHA:

- Ruff formatting + lint;
- full pytest;
- Windows DPAPI;
- Windows Hello;
- no temporary workflows/scripts;
- frozen corpus hash `bb09a6a6b7c6f9248c48f35a39e5f4f8002f678a471d4752152c6a6b26cd4c21`;
- exact GLiClass model revisions above;
- owner Torch/Torchvision/Transformers versions unchanged.

Only after that certification issue the one-time owner run command. Output must be written once to:

`.step4-phase45d-question-role-bakeoff-v1.json`

After owner evidence exists, do not rerun the experiment.
