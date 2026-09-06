# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — PHASE 4.5D ACTIVE — FRESH V3 FAIL_CALIBRATION / RETIRED — V3 VALIDATION UNEXPOSED — GEMINI 3.8 FLASH CALIBRATION DIAGNOSTIC NEXT — PHASE 4.5E BLOCKED**

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

## Active 4.5D direction — POST-V3 GEMINI 3.8 CALIBRATION DIAGNOSTIC

Fresh V3 has been executed once and is **FAIL_CALIBRATION / RETIRED**. Do not rerun it, overwrite it, or execute its untouched validation half.

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_FINAL_V3_RESULT.md`.

Frozen owner-run V3 evidence:

- implementation SHA `783a5b49cdf31a957c403066f1ea421c007354a4`;
- corpus SHA-256 `baac40840bc260a01f4fc630570e4578dbdf8dc9f36c8b3192c6bb6471191195`;
- calibration `170 TP / 14 FP`, empirical precision `0.923913`;
- one-sided 95% Clopper-Pearson lower precision bound `0.883609731`;
- positive Recall@10 and reranked Top-1 both `170/180 = 0.944444`;
- EN positive release recall `1.0`, HI `0.833333`, Hinglish `1.0`;
- false releases: `5 positive retrieval misses + 3 near_miss + 1 ambiguous + 1 unsupported_source + 4 historical`;
- security-boundary leaks: four `historical` cases;
- **validation was not executed**.

The failure is not marginal. With `170` true releases, at most `3` false releases would satisfy the frozen exact 95% precision-confidence gate; V3 produced `14`.

### Failure diagnosis

The ten positive Top-10 misses were all Hindi and concentrated in two predicates:

- five `archive_destination` misses; Gemini 3.5 Flash-Lite incorrectly RELEASED all five wrong Top-1 documents;
- five `signin_method` misses; Gemini correctly abstained on all five.

Whenever the expected positive memory entered Top-10, the frozen Qwen reranker placed it Top-1. This keeps the ranking problem localized to first-stage multilingual candidate starvation rather than reranker ordering.

The remaining semantic false releases were concentrated in scope-sensitive cases: Hinglish near-miss/ambiguity, one English unsupported-source query, and Hindi/Hinglish historical queries.

### Research-first next candidate — Gemini 3.8 Flash

Google released stable GA `gemini-3.8-flash` on September 2, 2026 and positions it as its most intelligent Flash model for complex workflows with higher factual rigor. It supports the same Interactions API and structured outputs plus configurable thinking. This is a materially stronger current production model than the failed Flash-Lite judge, so it is the next mature technology to test before adding custom semantic logic.

Frozen development method:

- `docs/research/STEP_4_PHASE_4_5D_GEMINI38_CALIBRATION_DIAGNOSTIC_METHOD.md`.

Harness:

- `tools/research/step4_phase45d_gemini38_calibration_diagnostic.py`.

The diagnostic uses **only the already exposed V3 calibration split** and changes one semantic variable:

```text
same V3 calibration only
same canonical eligibility/security
same Qwen3 256d FTS5 + exact cosine + equal RRF
same Top-10 candidate window
same Qwen3 reranker + frozen instruction
same one-query/document Interactions request shape
same semantic sufficiency prompt + structured schema + store=False

Gemini 3.5 Flash-Lite
        ↓ only changed semantic variable
Gemini 3.8 Flash, thinking_level=medium
```

Before any Gemini 3.8 scoring is accepted as comparable evidence, the harness must reproduce every one of the 360 V3 calibration Top-1 IDs and positive Recall@10/Top-1 flags from the retired owner artifact.

Development selection for a fresh V4 design requires the existing exact precision, recall, language and zero-security-release gates. Even a perfect diagnostic is development evidence only; V4 would need a completely fresh acceptance corpus. The untouched V3 validation split must not be reused as V4 acceptance evidence.

If Gemini 3.8 fails this diagnostic, stop model-hopping and research/implement the structure-aware fallback: parse memory queries into canonical subject/relation/temporal/source constraints, apply deterministic metadata filtering before semantic release, and evaluate multilingual NLI only as a task-matched secondary verifier if needed.

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
9. **4.5D — ACTIVE: V3 FAIL_CALIBRATION / RETIRED with validation unexposed; Gemini 3.8 calibration-only diagnostic next.**
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
- rerun or overwrite the failed V3 acceptance artifact;
- execute the untouched V3 validation half after calibration failure;
- retune the V3 prompt/model/corpus/gates and claim it is still fresh V3 evidence;
- use the untouched V3 validation split as V4 acceptance evidence;
- rerun Qwen vs EmbeddingGemma selection;
- rerun 4.5C owner compatibility unless contracts change;
- change Qwen revisions or Torch/Torchvision casually;
- disturb accepted Step-3 audio/vision architecture;
- weaken historical/forgotten/local-only/secret/untrusted eligibility filters;
- let learned confidence create, modify, resurrect or establish canonical truth.

---

## Immediate Next Action

**PASS THE GEMINI 3.8 CALIBRATION-ONLY DIAGNOSTIC THROUGH CI ON A CLEAN EXACT SHA, THEN RUN IT ONCE AGAINST THE RETIRED OWNER V3 CALIBRATION ARTIFACT.**

The diagnostic must use `.step4-phase45d-final-v3-acceptance.json` only as exposed development input, prove V3 validation was never executed, reproduce all 360 calibration retrieval decisions, and never access the V3 validation split.

If `gemini-3.8-flash` with medium thinking satisfies the frozen exact precision/recall/language/security development gates, freeze it only for **fresh V4 design**. If it fails, move to the researched structure-aware query-planning/metadata-filter architecture rather than prompt-tuning or generic relevance-model cycling.

Phase 4.5E remains blocked.
