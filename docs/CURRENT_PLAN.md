# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — PHASE 4.5D ACTIVE — V1 AND V2 RELEASE-CONFIDENCE ARCHITECTURES REJECTED — RETRIEVAL-DEPTH + SEMANTIC-VERIFIER DEVELOPMENT DIAGNOSIS NEXT — PHASE 4.5E BLOCKED**

This file is the operational source of truth. Detailed measured evidence belongs in `docs/research/`; accepted architecture belongs in ADRs / `docs/CURRENT_ARCHITECTURE.md` only after acceptance.

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
- canonical eligibility/security filtering occurs before ranking and is independent of learned confidence;
- current runtime/config/repository truth outranks learned self-memory;
- production cloud intelligence remains under the one-provider contract (`JARVIS_AI_PROVIDER=gemini`);
- Step 4 grants no autonomous repair, deployment, or authority expansion.

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
- current canonical embedding contract: normalized 256d;
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

- Qwen hybrid Recall@1 `0.9412`, Recall@3 `1.0000`, MRR `0.9608` on the model-selection corpus;
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

Encrypted canonical memory kernel, temporal lifecycle, FTS5 synchronization/rebuild, secure physical forget and exact current queries accepted.

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

Goal: decide whether an **already-eligible canonical memory** may be released as query evidence. This gate has no mutation or truth authority.

#### V1 raw score/margin — REJECTED

The first 64-case experiment produced zero false releases but only about `18.75%` held-out positive recall and `0%` Hindi recall. Exposed/retired.

#### Fresh 320-case V1 — REJECTED / RETIRED

Retrieval itself was strong:

- validation Top-1 `63/64 = 98.44%`;
- Recall@3 `64/64 = 100%`.

The 30-policy `reranker_score AND margin` family failed MAPIE/Holm. Corrected SFST diagnosis showed `0/30` policies valid even as individual alpha-0.05 tests. Best calibration rule produced `18 TP / 1 FP`, precision `0.947368`, recall `0.1875`.

Therefore the rectangular score+margin family is permanently rejected.

#### Learned seven-feature diagnostic — INSUFFICIENT

Retired 320-case five-fold OOF `StandardScaler + LogisticRegression`:

- ROC-AUC `0.892574`;
- AP `0.885079`;
- best recall at empirical precision >= 0.95: `0.295597`.

Below the frozen `0.40` development recall floor.

#### mMARCO independent verifier — PROMISING ON OLD DEVELOPMENT, REJECTED AS FINAL V2 VERIFIER

Model:

`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`

Revision:

`1427fd652930e4ba29e8149678df786c240d8825`

On the retired 320 cases it improved the combined development point to:

- `87 TP / 4 FP`;
- precision `0.956044`;
- recall `0.547170`;
- EN `0.462963`;
- HI `0.769231`;
- Hinglish `0.396226`.

This justified a fresh V2 acceptance experiment but did not itself establish acceptance.

#### Final V2 acceptance — **FAIL_ACCEPTANCE / RETIRED**

Owner run SHA:

`7d9bc60bb37953ba1d6b45c7b46a136b1397203f`

Exact SHA passed Ruff, pytest, Windows DPAPI and Windows Hello CI.

Owner V2 evidence:

- `.step4-phase45d-final-v2-acceptance.json`;
- SHA-256 `bb718e2a7df71ea8b05b90e45b3aa0718643c1cf94323a03ae47a7a33d97bf0a`;
- run once only; do not overwrite/rerun for acceptance.

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_FINAL_V2_RESULT.md`.

V2 corpus:

- 1,800 total queries;
- calibration `600 release + 600 abstain`;
- validation `300 release + 300 abstain`;
- validation positives exactly 100 EN + 100 HI + 100 Hinglish;
- validation labels were not used to tune V2.

V2 ranking:

Calibration:

- Top-1 `533/600 = 0.888333`;
- Recall@3 `533/600 = 0.888333`.

Validation:

- Top-1 `266/300 = 0.886667`;
- Recall@3 `266/300 = 0.886667`.

Validation language ranking:

- EN `97/100 = 0.97`;
- HI `73/100 = 0.73`;
- Hinglish `96/100 = 0.96`.

Critical interpretation: Top-1 and Recall@3 are exactly identical in both splits. Whenever the correct memory entered the three-candidate set, Qwen reranked it to #1. Every ranking miss is therefore a first-stage/candidate-window miss, not a reranker ordering miss inside the available three.

Validation Hindi relation-level weak points:

- region `0/10`;
- sync `3/10`;
- shell `5/10`;
- editor `7/10`;
- most other Hindi relations `9/10` or `10/10`.

V2 confidence:

- MAPIE valid thresholds: `0`;
- no preregistered probability threshold from `0.50` to `0.999` achieved empirical precision `0.95` on calibration;
- at threshold `0.999`: `76 TP / 29 FP`, precision `0.723810`, positive recall `0.126667`;
- best empirical precision among preregistered thresholds was only about `0.736`.

The frozen logistic model learned a negative reranker-margin coefficient (`-2.1205555`), which made small-margin ambiguous/relation-mismatch cases pathologically high-confidence on V2. At probability >= `0.999`, the 29 calibration false positives were dominated by relation mismatch (19), ambiguous (9) and near miss (1).

Therefore V2 failure is **not** merely MAPIE power/sample-size failure. The frozen confidence architecture itself did not transfer.

mMARCO is also no longer the selected final verifier. It is an IR passage-ranking model; V2 demonstrated that retrieval relevance is not equivalent to JARVIS's stricter semantic-sufficiency requirement.

---

## Active 4.5D development direction after V2

V2 is now exposed and may be used only as retired development evidence. **Do not create V3 yet.**

### 1. Retrieval-depth diagnostic — NEXT

Research evidence from the standard retrieve→rerank architecture says the efficient retriever should build a substantially wider shortlist before CrossEncoder reranking. The current hard top-3 cut is now directly contradicted by V2 evidence.

Keep Qwen 0.6B + 256d unchanged first and measure positive first-stage recall at candidate depths:

- 3;
- 5;
- 10;
- 20;
- 50;
- 100 when practical.

Then measure Qwen reranked Top-1 for the useful wider depths, broken down by EN/HI/Hinglish and relation.

This is a development bake-off on exposed V2, **not acceptance**.

### 2. Embedding dimension only if retrieval depth is insufficient

Qwen3-Embedding-0.6B supports Matryoshka dimensions through 1024.

If wider 256d retrieval does not provide adequate recall, compare 256 vs 512 vs 1024 on retired development data. Do not alter the canonical 256d contract before evidence supports it.

### 3. Semantic verifier/confidence redesign

The old mMARCO + frozen logistic gate is rejected.

Now that fresh V2 failed, a BGE bake-off is justified. Start with mature Apache-2.0 multilingual candidates rather than custom training:

- `BAAI/bge-reranker-v2-m3` as the primary independent multilingual candidate;
- retain Qwen reranker as the accepted ranking baseline;
- add another verifier only if it provides materially distinct evidence and acceptable licensing/runtime characteristics.

`mixedbread-ai/mxbai-rerank-base-v2` is a possible Apache-2.0 multilingual development comparator if BGE evidence is insufficient.

Do not treat raw relevance score as semantic truth. Any final gate must distinguish exact/direct answerability from related-but-insufficient documents, especially relation mismatch, ambiguity, near miss and unsupported detail.

Any learned confidence estimator must be trained on exposed development data only, and probability calibration/risk calibration must remain statistically separated from model fitting.

### 4. Fresh V3 only after architecture selection

After development evidence selects and freezes a materially better architecture:

- generate completely new calibration/validation data;
- ensure broader query paraphrase/template diversity before the split;
- freeze model revisions/features/protocol first;
- fit only on retired development data;
- use fresh calibration for risk control;
- expose fresh validation only once;
- validation may reject but never tune the system.

Frozen acceptance principles remain:

- precision target `0.95`;
- confidence `0.95`;
- overall positive release recall >= `0.40`;
- each EN/HI/Hinglish positive release recall >= `0.25`;
- strong retrieval ranking gates;
- zero security-boundary release;
- no validation-driven retuning;
- synthetic acceptance does not establish exchangeability with future owner traffic;
- later shadow-labelled operational monitoring remains required.

---

## Phase 4.5E — BLOCKED

Do **not** wire semantic retrieval into `ContextAssembler` / Gemini conversation.

4.5E may begin only after 4.5D has a fresh accepted architecture, durable owner evidence, synchronized docs and a green exact owner-run SHA.

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
9. **4.5D — ACTIVE: V2 rejected; retrieval-depth and semantic-verifier development bake-off next.**
10. **4.5E — BLOCKED.**
11. 4.6 — NOT STARTED.
12. 4.7 — NOT STARTED.
13. 4.8 — NOT STARTED.

---

## Do not repeat / do not do next

Do not:

- rerun or overwrite V2 acceptance evidence;
- reuse V2 as acceptance evidence;
- start 4.5E;
- wire retrieval into Gemini conversation;
- lower `0.95` precision or `0.95` confidence to obtain a pass;
- lower overall `0.40` or language `0.25` recall floors;
- rescue the rejected score+margin family;
- rescue the rejected V2 logistic threshold by threshold tuning;
- treat mMARCO as the accepted final verifier;
- rerun Qwen vs EmbeddingGemma selection;
- rerun 4.5C owner compatibility unless contracts change;
- change Qwen revisions or Torch/Torchvision casually;
- disturb accepted Step-3 audio/vision architecture;
- weaken historical/forgotten/local-only/secret/untrusted eligibility filters;
- let learned confidence create, modify, resurrect or establish canonical truth.

---

## Immediate Next Action

**IMPLEMENT A DEVELOPMENT-ONLY V2 RETRIEVAL-DEPTH DIAGNOSTIC ON THE CURRENT 256D QWEN STACK, PASS CI, THEN RUN IT ON THE OWNER RTX.**

Only if wider retrieval depth is insufficient should the next diagnostic alter embedding dimension.

In parallel, prepare the research harness for a stricter multilingual semantic-verifier bake-off beginning with BGE reranker v2-m3. Do not generate fresh V3 acceptance data until these development questions are resolved.
