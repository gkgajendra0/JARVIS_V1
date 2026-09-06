# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — PHASE 4.5D ACTIVE — TOP-10 QWEN DEVELOPMENT RETRIEVAL PASSED — QA + GLICLASS REJECTED — GEMINI SINGLE-INSTANCE BOUNDARY 15/15 PASSED — 24-CASE PRODUCTION-SHAPE COVERAGE DIAGNOSTIC NEXT — PHASE 4.5E BLOCKED**

This file is the operational source of truth. Detailed measurements belong in `docs/research/`; only fresh accepted architecture belongs in ADRs / `docs/CURRENT_ARCHITECTURE.md`.

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

Selected model: **`gemini-3.5-flash-lite`**.

Owner acceptance proved session-local candidate quarantine, disposal on session close, no implicit durable write, no cross-session resurrection, and preserved Step-3 audio/vision behavior.

### Phase 4.5 model family accepted through 4.5C

**Embedding:** `Qwen/Qwen3-Embedding-0.6B`

- revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- canonical embedding contract remains normalized 256d;
- frozen JARVIS retrieval instruction;
- exact local cosine.

**First stage:**

- eligible-current SQLite FTS5 lexical rank;
- exact Qwen dense rank;
- equal-weight RRF, `k=60`;
- lexical window `10`;
- no ANN/vector extension until scale evidence requires it.

**Reranker:** `Qwen/Qwen3-Reranker-0.6B`

- revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- frozen JARVIS memory instruction;
- BF16 owner path;
- deterministic tie handling.

Frozen instruction:

> Judge whether the memory Document directly and sufficiently answers the JARVIS memory Query using only facts stated in the Document. Answer yes only when the Document supports the specific fact or relation requested; answer no when it is merely related, missing the requested detail, contradictory, negated, or otherwise does not answer the Query.

Owner selection evidence before 4.5D:

- Qwen hybrid Recall@1 `0.9412`, Recall@3 `1.0000`, MRR `0.9608` on the original model-selection corpus;
- EmbeddingGemma rejected after hybrid regression;
- accepted owner Torch `2.13.0+cu132`, Torchvision `0.28.0+cu132`;
- simultaneous Qwen embedding/reranker operation passed on RTX 5060 Ti 8GB;
- combined Qwen peak CUDA allocation approximately `2.46 GB`.

Do not rerun the old embedding bake-off or Phase 4.5C compatibility unless model/dependency contracts materially change.

---

## Phase status

### 4.0A — COMPLETE

Stable conversation provenance and neutral DPAPI security boundary accepted.

### 4.1 — COMPLETE

Encrypted canonical memory kernel, temporal lifecycle, FTS5 synchronization/rebuild, secure physical forget and exact-current queries accepted.

### 4.2 — COMPLETE

Bounded `LiveContext` + deterministic `ContextAssembler` accepted. Provider history remains non-canonical.

### 4.3 — COMPLETE

Governed explicit `remember / inspect / correct / forget` accepted through the production voice path. Do not repeat owner acceptance.

### 4.4 — COMPLETE

Structured extraction + session-local candidate quarantine accepted. Implicit auto-admission remains disabled. Do not repeat owner acceptance.

### 4.5A — COMPLETE

Encrypted derived-vector lifecycle accepted with canonical FK/cascade lineage, immutable model metadata, stale-vector failure and secure derived-vector deletion.

### 4.5B — COMPLETE

Production lexical+dense+RRF retrieval core accepted with eligibility before ranking, safe FTS grammar, exact cosine, deterministic ordering and no vector DB at current scale.

### 4.5C — COMPLETE

Lazy revision-pinned Qwen embedding/reranker adapters and owner RTX coexistence accepted. Normal CI does not load GPU models.

### 4.5D — ACTIVE

Goal: decide whether an **already-eligible canonical memory** may be released as query evidence. This gate has no mutation or canonical-truth authority.

#### V1 raw score/margin — REJECTED

The first 64-case experiment produced zero false releases but only about `18.75%` held-out positive recall and `0%` Hindi recall. Exposed/retired.

#### Fresh 320-case V1 — REJECTED / RETIRED

Retrieval itself was strong:

- validation Top-1 `63/64 = 98.44%`;
- Recall@3 `64/64 = 100%`.

The rectangular `reranker_score AND margin` family failed statistical risk control. Corrected diagnosis showed no candidate rule was adequate. Best calibration rule produced `18 TP / 1 FP`, precision `0.947368`, recall `0.1875`.

The score+margin family is permanently rejected.

#### Learned seven-feature diagnostic — INSUFFICIENT

Retired 320-case five-fold OOF `StandardScaler + LogisticRegression`:

- ROC-AUC `0.892574`;
- AP `0.885079`;
- best recall at empirical precision >= `0.95`: `0.295597`.

Below the frozen `0.40` development recall floor.

#### mMARCO independent verifier — REJECTED AS FINAL RELEASE VERIFIER

Model:

`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`

Revision:

`1427fd652930e4ba29e8149678df786c240d8825`

It was promising on the retired 320-case development set, where the combined development point reached precision `0.956044` and recall `0.547170`. That justified one fresh V2 experiment.

Fresh V2 then showed that generic query/passage relevance did not transfer into a robust semantic-sufficiency release signal. mMARCO remains useful historical development evidence but is no longer the selected final verifier.

#### Final V2 acceptance — FAIL_ACCEPTANCE / RETIRED

Owner-run SHA:

`7d9bc60bb37953ba1d6b45c7b46a136b1397203f`

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_FINAL_V2_RESULT.md`.

V2 corpus:

- 1,800 total queries;
- calibration `600 release + 600 abstain`;
- validation `300 release + 300 abstain`;
- validation positives exactly `100 EN + 100 HI + 100 Hinglish`;
- validation labels were not used to tune V2.

V2 ranking:

- calibration Top-1 and Recall@3: `533/600 = 0.888333`;
- validation Top-1 and Recall@3: `266/300 = 0.886667`;
- validation EN `0.97`, HI `0.73`, Hinglish `0.96`.

Because Top-1 and Recall@3 were exactly identical, every V2 positive ranking miss was a candidate-window miss: whenever the correct memory entered the three-candidate set, Qwen reranked it to #1.

V2 confidence:

- MAPIE valid thresholds: `0`;
- at frozen probability threshold `0.999`: `76 TP / 29 FP`, precision `0.723810`;
- high-confidence false releases were dominated by relation mismatch and ambiguity;
- V2 calibration-to-validation wording change also exposed severe absolute-score shift in the mMARCO verifier.

Therefore V2 failure was architectural, not merely insufficient calibration sample size.

---

## Post-V2 retrieval-depth diagnosis — COMPLETE / DEVELOPMENT-ONLY

Owner-run exact SHA:

`e99d8eae60f0ec49a0b04b445a3116c51efcc27c`

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_V2_RETRIEVAL_DEPTH_RESULT.md`.

The exposed V2 positive set (`900` cases) was rerun using the same 256d Qwen embedding and the same Qwen reranker, varying only how many first-stage candidates were allowed to reach reranking.

First-stage positive recall:

- top 3: `799/900 = 0.887778`;
- top 5: `847/900 = 0.941111`;
- top 10: `900/900 = 1.000000`;
- top 20/50/100: `900/900 = 1.000000`.

Qwen reranked Top-1:

- window 3: `799/900 = 0.887778`;
- window 5: `847/900 = 0.941111`;
- window 10: `900/900 = 1.000000`;
- window 20: `900/900 = 1.000000`.

### Retrieval decision

This development result isolates the V2 ranking problem:

- **top-3 candidate starvation is confirmed**;
- the existing Qwen3-Embedding-0.6B 256d contract is sufficient on the exposed development corpus;
- the existing Qwen3-Reranker-0.6B orders every positive correctly once the correct memory reaches a 10-candidate shortlist;
- **do not benchmark 512d/1024d now**;
- **do not switch embedding/reranker models merely to fix V2 ranking**;
- use a **top-10 candidate window in the next development architecture**;
- this does not become the production contract until fresh final acceptance passes.

---

## Active 4.5D development direction — GEMINI SINGLE-INSTANCE COVERAGE DIAGNOSTIC

V2 is fully exposed and may be used only for development architecture selection. **Do not create V3 yet.**

### Rejected development verifiers

- mMARCO generic relevance verifier: rejected as final semantic-sufficiency verifier after V2 transfer failure;
- multilingual SQuAD2 answerability verifier: rejected after failing frozen development transfer floors;
- GLiClass multilingual zero-shot classifier: no calibration threshold reached the frozen `0.95` precision target.

### Gemini batch-120 semantic-judge bake-off — NOT PRODUCTION-EQUIVALENT

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_SEMANTIC_JUDGE_BAKEOFF_RESULT.md`.

Owner-run exact SHA:

`cdbc89a51728c8134e5182980b6885f2d2ccfa91`

Qwen candidate depth 10 reproduced positive ranking perfectly: `900/900` Top-1 across exposed V2 positives.

Under the quota-compatible 120-case Gemini request shape, validation produced `300 TP / 125 FP`, precision `0.705882`, recall `1.0`. All 125 false releases were exactly the five boundary groups: `25 historical + 25 forgotten + 25 local_only + 25 secret + 25 untrusted`; the other 175 ordinary semantic abstentions had zero false releases.

### Gemini single-instance boundary diagnostic — COMPLETE / PASSED

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_GEMINI_SINGLE_INSTANCE_BOUNDARY_RESULT.md`.

Owner-run exact SHA:

`e645fe8ab469d962bc2bcc23f11db8da650d9279`

The frozen 15-case diagnostic selected one already-exposed validation case for every boundary category/language cell and changed only Gemini request shape from 120 cases/request to one case/request.

Exact result:

- prior batch-120 RELEASE: `15/15`;
- single-instance RELEASE: `0/15`;
- single-instance ABSTAIN: `15/15`;
- RELEASE→ABSTAIN flips: `15/15`;
- all five boundary categories passed `3/3`;
- EN, HI and Hinglish each passed `5/5`;
- `batching_confound_observed = true`.

Therefore the batch-120 boundary failures are not valid production-equivalent evidence. Request shape materially changes Gemini behavior on this task.

Research alignment:

- ACL 2026 reports multi-instance LLM degradation beginning around 20–100 instances and larger collapse at higher instance counts;
- Google structured-output guidance guarantees syntax, not semantic correctness, and requires application validation;
- MAPIE now documents LLM-as-a-judge risk control with abstention and held-out statistical control.

### Frozen next diagnostic — 24 additional single-instance cells

Harness:

- `tools/research/step4_phase45d_gemini_single_instance_coverage_diagnostic.py`.

Output:

- `.step4-phase45d-v2-gemini-single-instance-coverage-diagnostic-v1.json`.

The diagnostic does **not** rerun the 15 boundary calls. It requires the completed boundary artifact, then uses 24 additional already-exposed V2 validation cases:

- one previously-correct positive per language = `3`;
- `absent`, `near_miss`, `ambiguous`, `adversarial_lexical`, `negation`, `relation_mismatch`, `unsupported_source` × EN/HI/Hinglish = `21` ordinary abstains;
- total new Gemini calls = `24`;
- exactly one query/document pair per Gemini request;
- same canonical eligibility, Qwen 256d, top-10 retrieval and frozen Qwen reranker;
- selected Top-1 memory must reproduce the prior source artifact;
- no GLiClass, no threshold fitting and no validation-driven tuning.

Frozen interpretation:

- all 24 preserve the previously-correct decision + the completed 15/15 boundary result => `39/39` production-shape development cells correct and Gemini is selected for **fresh V3 design**;
- any single regression blocks V3 and triggers architecture review before multilingual NLI/grounding fallback.

Selection for V3 design is not final acceptance. A future V3 must still be completely fresh and statistically controlled.

---

## Fresh V3 boundary — NOT YET AUTHORIZED

Only after development evidence selects and freezes a materially better architecture may V3 be generated.

A future V3 must:

- use completely new calibration/validation data;
- include broader paraphrase/template diversity before the split;
- freeze model revisions/features/protocol before labels are exposed;
- use development data only for model/architecture selection;
- use fresh calibration for statistically valid precision control;
- expose fresh validation once;
- never use validation to retune the same acceptance corpus.

Frozen final acceptance principles remain:

- precision target `0.95`;
- confidence `0.95`;
- overall positive release recall >= `0.40`;
- EN/HI/Hinglish positive release recall each >= `0.25`;
- strong retrieval-ranking gates;
- zero security-boundary release;
- no validation-driven retuning;
- synthetic acceptance does not establish exchangeability with future owner traffic;
- later shadow-labelled operational monitoring remains required.

---

## Phase 4.5E — BLOCKED

Do **not** wire semantic retrieval into `ContextAssembler` / Gemini conversation.

4.5E may begin only after 4.5D has a fresh accepted architecture, durable owner evidence, synchronized docs and a green exact owner-run closure SHA.

### Later phases — NOT STARTED

- 4.6 episodic/reflection memory;
- 4.7 JARVIS self-knowledge;
- 4.8 hardening/final Step-4 acceptance.

---

## Remaining implementation order

1. 4.0A — COMPLETE.
2. 4.1 — COMPLETE.
3. 4.2 — COMPLETE.
4. 4.3 — COMPLETE.
5. 4.4 — COMPLETE.
6. 4.5A — COMPLETE.
7. 4.5B — COMPLETE.
8. 4.5C — COMPLETE.
9. **4.5D — ACTIVE: top-10 retrieval complete; boundary single-instance 15/15 passed; 24-case coverage diagnostic next.**
10. **4.5E — BLOCKED.**
11. 4.6 — NOT STARTED.
12. 4.7 — NOT STARTED.
13. 4.8 — NOT STARTED.

---

## Do not repeat / do not do next

Do not:

- rerun or overwrite V2 acceptance evidence;
- reuse V2 as fresh acceptance evidence;
- treat the retrieval-depth diagnostic as acceptance;
- test 512d/1024d embeddings now; top-10 256d retrieval already reached `900/900` on exposed development positives;
- swap Qwen embedding/reranker merely to fix V2 ranking;
- start 4.5E;
- wire retrieval into Gemini conversation;
- lower `0.95` precision or `0.95` confidence to obtain a pass;
- lower overall `0.40` or language `0.25` recall floors;
- rescue the rejected score+margin family;
- rescue the rejected V2 logistic gate through threshold tuning;
- treat mMARCO as the accepted final verifier;
- jump to BGE or multilingual NLI before resolving the frozen 24-case Gemini single-instance coverage diagnostic;
- generate V3 before development architecture selection is complete;
- rerun Qwen vs EmbeddingGemma selection;
- rerun 4.5C owner compatibility unless contracts change;
- change Qwen revisions or Torch/Torchvision casually;
- disturb accepted Step-3 audio/vision architecture;
- weaken historical/forgotten/local-only/secret/untrusted eligibility filters;
- let learned confidence create, modify, resurrect or establish canonical truth.

---

## Immediate Next Action

**PASS THE 24-CASE GEMINI SINGLE-INSTANCE COVERAGE DIAGNOSTIC THROUGH CI ON A CLEAN EXACT SHA, THEN RUN IT ONCE ON THE OWNER RTX.**

Use the existing completed batch-120 semantic-judge artifact and the completed 15-case boundary artifact as immutable development inputs. Do not overwrite or rerun either one. If all 24 additional cells preserve their previously-correct decisions, freeze Gemini single-instance as the development semantic judge and design a completely fresh V3 acceptance with statistical precision control. Any regression blocks V3 and returns Phase 4.5D to architecture research.

V3 remains unauthorized until this diagnostic passes. Phase 4.5E remains blocked.