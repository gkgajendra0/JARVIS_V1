# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — PHASE 4.5D ACTIVE — V4 + METHOD V2 FAILED / RETIRED — CUSTOM FINE-TUNE V3 SUPERSEDED BEFORE EXECUTION — ANSWERABILITY COMPONENT BAKE-OFF V1 FROZEN — PHASE 4.5E BLOCKED**

This file is the operational source of truth. Detailed measurements and retired experiments belong in `docs/research/`; only fresh accepted architecture belongs in ADRs / `docs/CURRENT_ARCHITECTURE.md`.

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
- canonical eligibility/security filtering occurs before ranking and remains independent of learned confidence;
- current runtime/config/repository truth outranks learned self-memory;
- production cloud intelligence remains under the one-provider contract (`JARVIS_AI_PROVIDER=gemini`);
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
- lexical window `10`.

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

Development retrieval-depth diagnosis proved that the exposed V2 positive corpus reached first-stage and reranked recall `900/900` once the candidate window was increased to top 10. Therefore do not switch embedding/reranker or test 512d/1024d merely to fix 4.5D answerability.

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
- **4.5D — ACTIVE:** safe evidence-release semantics.
- **4.5E — BLOCKED:** do not wire semantic memory retrieval into normal Gemini conversation yet.
- **4.6–4.8 — NOT STARTED.**

---

# Phase 4.5D — active problem

Goal: decide whether an **already-eligible canonical memory** actually contains evidence sufficient to answer the user's question. This layer has no mutation, lifecycle, security, or canonical-truth authority.

The provider-independent authority architecture remains selected: provider adapters may propose structured semantics, but JARVIS-owned policy, lifecycle/security eligibility, canonical lookup, evidence rendering and final release authority remain deterministic.

## Retired evidence

### Score/margin and learned confidence families — RETIRED

Earlier V1/V2 experiments established that reranker score/margin and learned confidence are not safe semantic-sufficiency authorities. See the existing Phase 4.5D research result documents. Do not rescue these families through threshold tuning.

### V4 final composite acceptance — FAIL / RETIRED

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_V4_ACCEPTANCE_RESULT.md`.

Provider-backed V4 produced zero false releases but only `53/90 = 0.588889` exact target recall; comparison recall was `0.166667`. Provider-independent core V4 produced `58/90 = 0.644444` exact target recall plus one Hinglish negation false release. The generic zero-shot answer-type guard vetoed `24/30` legitimate comparisons in both paths.

V4 is exposed and retired. Never rerun it, tune on it, train on its query text, or score replacement candidates on it. It may be used only as an exact-query deny-list and architectural evidence.

### Task-specific local guard Method V2 — FAIL / RETIRED

Owner-run SHA:

`d9dc8cc06edd81288c6af370c0032a7f771e8b23`

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_TASK_SPECIFIC_GUARD_BAKEOFF_V2_RESULT.md`.

Frozen-embedding + LogisticRegression results:

| Candidate | False allows | Overall allow recall | Comparison recall | Macro-F1 | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| multilingual MiniLM L12 | 9 | 0.791667 | 0.625000 | 0.646962 | FAIL |
| multilingual E5-small | 11 | 0.854167 | 0.708333 | 0.726627 | FAIL |
| multilingual MPNet-base-v2 | 12 | 0.854167 | 0.750000 | 0.809516 | FAIL |
| Qwen3-Embedding-0.6B 256d | 14 | 0.791667 | 0.625000 | 0.623784 | FAIL |

Every candidate violated the zero-false-allow boundary. The frozen-body linear-probe architecture is permanently retired. Do not rerun Method V2 or tune its exposed holdout.

### Custom eight-class encoder fine-tune V3 — SUPERSEDED BEFORE EXECUTION

A mmBERT/XLM-R end-to-end fine-tune was prepared after Method V2 but never owner-run. Deeper research showed that query-only eight-class intent classification still does not directly solve evidence sufficiency.

The V3 executable corpus, harness, tests, temporary workflow and fine-tuning dependency group were removed before any model training or holdout scoring. Historical rationale remains in:

- `docs/research/STEP_4_PHASE_4_5D_TASK_GUARD_FINETUNE_V3_METHOD.md`.

There is no V3 result evidence.

---

# Active 4.5D direction — answerability / evidence sufficiency

Deep research found mature task families that more directly match the boundary:

1. **extractive QA with a no-answer state** for open current-value questions;
2. **native NLI** for boolean comparisons: entailment / contradiction / neutral ~= YES / NO / IDK;
3. a later independent **grounding/output rail** if Gemini is allowed to paraphrase released evidence.

This replaces the idea of a single query-only memory-intent classifier.

## Answerability component bake-off V1 — FROZEN / ZERO-TRAINING / NEXT

Method:

- `docs/research/STEP_4_PHASE_4_5D_ANSWERABILITY_BAKEOFF_METHOD.md`.

Harness:

- `tools/research/step4_phase45d_answerability_cases.py`;
- `tools/research/step4_phase45d_answerability_bakeoff.py`;
- `tests/test_phase45d_answerability_bakeoff.py`.

Frozen fresh corpus:

- 8 new facts;
- English / Hindi / Hinglish;
- 288 QA cases = 96 answerable + 192 no-answer;
- 96 native NLI cases;
- total component cases `384`;
- payload SHA-256 `3e2bd6830df3d08b3ea4ce8e045ee78cf562c228c5b0d2e5e094ffa42b6b44a3`;
- zero exact normalized question overlap with retired V4 or exposed Method V2;
- zero task-specific training;
- zero cloud/provider calls.

### QA candidates

1. `deepset/xlm-roberta-base-squad2`
   - revision `a5fab9908c8d856e8c583fd41ba6d92444e46477`.
2. `timpal0l/mdeberta-v3-base-squad2`
   - revision `08d6e89c7a6557f967db2e1021f7f640483400ed`.

Frozen QA contract (pre-scoring Transformers-v5 execution amendment):

- first owner launch on `f488a1b26a13f00ef78ba3239f919da77c47438a` failed before scoring because Transformers `5.16.1` removed the legacy text QA pipeline; no result file was written and the corpus remains unexposed;
- native `AutoModelForQuestionAnswering` start/end logits;
- deterministic CLS/no-answer vs best valid context-span comparison;
- strict null-win rule (`null_score > best_span_score`);
- max sequence length `256`;
- max answer length `16`;
- FP32;
- Safetensors only;
- `trust_remote_code=False`;
- no JARVIS-fitted probability threshold.

QA gates require simultaneously:

- zero unauthorized non-empty releases on no-answer cases;
- zero wrong non-empty evidence spans on answerable cases;
- overall answerable exact-evidence recall >= `0.90`;
- each language answerable recall >= `0.85`.

### Native NLI candidate

Reuse the already-pinned checkpoint:

`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`

Revision:

`b5113eb38ab63efdd7f280f8c144ea8b13f978ce`

Important: its old **zero-shot query-intent** use remains retired. V1 exercises the model in its native premise/hypothesis NLI task.

Frozen NLI contract:

- labels: entailment / neutral / contradiction;
- argmax only;
- max length `256`;
- batch `32`;
- Safetensors only;
- `trust_remote_code=False`;
- no probability threshold.

NLI gates require simultaneously:

- zero entailment/contradiction releases on neutral/unknown cases;
- zero wrong boolean verdicts;
- comparison exact recall >= `0.90`;
- each language comparison recall >= `0.85`.

### Development-pass meaning

A composite V1 pass requires at least one QA reader to pass plus native NLI to pass. **A component pass does not authorize a production change.**

If V1 passes, next development work is:

1. freeze selected component contracts;
2. extend `MemoryQueryProposal` / deterministic policy to represent comparison proposition and polarity without giving provider authority;
3. implement JARVIS-owned canonical evidence rendering and deterministic factual composition;
4. benchmark a separate output-grounding rail if Gemini phrasing remains in the factual path;
5. freeze the complete architecture;
6. only then create a completely fresh final acceptance corpus.

If V1 fails, retire this exposed corpus and research the failure class. Do not tune thresholds or rewrite cases after seeing results and call the rerun V1.

---

## Phase 4.5E — BLOCKED

Do **not** wire semantic retrieval into `ContextAssembler` / normal Gemini conversation.

4.5E may begin only after 4.5D has a fresh accepted end-to-end architecture, durable owner evidence, synchronized docs and a green exact closure SHA.

---

## Do not repeat / do not do next

Do not:

- rerun V4 provider-backed or provider-independent acceptance;
- train, tune, or score replacement models on V4 query text/results;
- rerun Method V2 or modify its exposed corpus/gates and call it fresh evidence;
- run the removed custom eight-class V3 fine-tune;
- alter answerability V1 corpus, gates, candidate revisions, task mapping or no-threshold policy after owner results and still call it V1;
- use QA/NLI confidence scores to post-hoc rescue a failed V1;
- treat a V1 component pass as production authorization or final acceptance;
- modify production answer-type behavior before the replacement architecture is fully implemented and freshly accepted;
- reuse V2/V4 as fresh acceptance;
- treat retrieval-depth diagnostics as acceptance;
- test 512d/1024d embeddings now;
- swap accepted Qwen embedding/reranker merely to fix answerability;
- start 4.5E;
- change Qwen revisions or Torch/Torchvision casually;
- disturb accepted Step-3 audio/vision architecture;
- weaken historical/forgotten/local-only/secret/untrusted eligibility filters;
- let learned confidence create, modify, resurrect or establish canonical truth.

---

## Immediate Next Action

**RUN THE FROZEN ZERO-CLOUD ANSWERABILITY COMPONENT BAKE-OFF V1 ON THE OWNER RTX MACHINE — ONLY AFTER THE EXACT BRANCH SHA IS GREEN.**

Before the owner run:

- verify the exact branch SHA supplied after CI;
- verify `.step4-phase45d-answerability-bakeoff-v1.json` is absent;
- verify corpus SHA-256 `3e2bd6830df3d08b3ea4ce8e045ee78cf562c228c5b0d2e5e094ffa42b6b44a3`;
- install/use `.[phase45d-answerability]`;
- preserve Torch `2.13.0+cu132`, Torchvision `0.28.0+cu132`, Transformers `5.16.1`;
- verify SentencePiece `0.2.2` and psutil `7.2.2`;
- do not run cloud/provider diagnostics in parallel.

Output is written once to:

`.step4-phase45d-answerability-bakeoff-v1.json`

Phase 4.5E remains blocked regardless of component results until the complete replacement architecture passes a completely fresh final acceptance.
