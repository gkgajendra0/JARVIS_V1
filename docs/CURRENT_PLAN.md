# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — PHASE 4.5D ACTIVE — QWEN TOP-10 + GEMINI SINGLE-INSTANCE DEVELOPMENT ARCHITECTURE SELECTED 39/39 — FRESH V3 METHOD/CORPUS/HARNESS FROZEN — OWNER V3 ACCEPTANCE NEXT — PHASE 4.5E BLOCKED**

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

## Active 4.5D direction — FRESH V3 ACCEPTANCE

Development architecture selection is complete. V2 remains exposed and retired and cannot be reused as acceptance evidence.

### Selected production-shaped architecture

The two preregistered single-instance diagnostics passed exactly:

- boundary cells: `15/15` correct;
- additional positive/ordinary-semantic cells: `24/24` preserved;
- combined production-shaped development coverage: `39/39`, zero regressions;
- EN, HI and Hinglish all represented.

Selected V3 pipeline:

```text
canonical eligibility/security authority
→ eligible FTS5 + Qwen3-Embedding-0.6B 256d exact cosine
→ equal-weight RRF, k=60
→ top 10
→ Qwen3-Reranker-0.6B with frozen instruction
→ eligible Top-1
→ gemini-3.5-flash-lite
→ exactly one query/document pair per Interactions API request
→ structured RELEASE / ABSTAIN
```

Durable development evidence:

- `docs/research/STEP_4_PHASE_4_5D_GEMINI_SINGLE_INSTANCE_BOUNDARY_RESULT.md`;
- `docs/research/STEP_4_PHASE_4_5D_GEMINI_SINGLE_INSTANCE_COVERAGE_RESULT.md`.

### Fresh V3 — METHOD/CORPUS/HARNESS FROZEN, NOT YET RUN

Frozen method:

- `docs/research/STEP_4_PHASE_4_5D_FINAL_V3_METHOD.md`.

Fresh corpus:

- `tools/research/step4_phase45d_final_v3_cases.py`;
- `720` cases total;
- calibration: `180 release + 180 abstain`;
- validation: `180 release + 180 abstain`;
- positive cases per split: `60 EN + 60 HI + 60 Hinglish`;
- every one of the 12 abstain families: `5 EN + 5 HI + 5 Hinglish` per split;
- calibration/validation synthetic profile identities are disjoint;
- exact V2 query reuse is prohibited;
- no real secrets;
- frozen payload SHA-256: `baac40840bc260a01f4fc630570e4578dbdf8dc9f36c8b3192c6bb6471191195`.

Acceptance harness:

- `tools/research/step4_phase45d_final_v3_acceptance.py`;
- Qwen candidate window `10`;
- Gemini Interactions API only;
- one query/document pair per request;
- fixed hard RELEASE/ABSTAIN policy, no fitted Gemini threshold and no fabricated confidence score;
- fresh calibration first;
- exact one-sided Clopper-Pearson precision lower bound via SciPy;
- precision target `0.95`, confidence `0.95`;
- at least `59` calibration releases required;
- validation API calls are blocked unless every calibration hard gate passes;
- validation requires zero false releases;
- output refuses overwrite;
- validation is never used for retuning.

The V3 owner run is now authorized once the frozen implementation reaches a clean exact SHA with all CI jobs green. This is still synthetic acceptance; later shadow-labelled operational monitoring remains required.

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
9. **4.5D — ACTIVE: development architecture selected 39/39; fresh V3 method/corpus/harness frozen; owner V3 acceptance next.**
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
- reopen rejected verifier/model search unless fresh V3 evidence fails the frozen selected architecture;
- alter the frozen V3 corpus, prompt, API shape, model revisions or gates after owner acceptance begins;
- rerun Qwen vs EmbeddingGemma selection;
- rerun 4.5C owner compatibility unless contracts change;
- change Qwen revisions or Torch/Torchvision casually;
- disturb accepted Step-3 audio/vision architecture;
- weaken historical/forgotten/local-only/secret/untrusted eligibility filters;
- let learned confidence create, modify, resurrect or establish canonical truth.

---

## Immediate Next Action

**PASS THE FROZEN FRESH V3 CORPUS/HARNESS THROUGH CI ON A CLEAN EXACT SHA, THEN RUN V3 ONCE ON THE OWNER RTX.**

The owner run must use payload SHA `baac40840bc260a01f4fc630570e4578dbdf8dc9f36c8b3192c6bb6471191195`, Qwen candidate window `10`, the Gemini Interactions API with exactly one query/document pair per request, and the exact statistical gates in `STEP_4_PHASE_4_5D_FINAL_V3_METHOD.md`.

If calibration fails, validation must remain unexecuted and this V3 is retired. If validation executes, it is exposed once and cannot be used to retune or rerun V3 as fresh evidence. Phase 4.5E remains blocked until a passing V3 result is durably recorded and closed on a green exact SHA.
