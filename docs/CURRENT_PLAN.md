# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — PHASE 4.5D ACTIVE — PROVIDER-INDEPENDENT COMPOSITE GATE SELECTED — FRESH FINAL ACCEPTANCE QUOTA-INTERRUPTED / CORPUS PRESERVED — PHASE 4.5E BLOCKED**

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

## Active 4.5D direction — PROVIDER-INDEPENDENT COMPOSITE GATE SELECTED / FRESH ACCEPTANCE NEXT

Fresh V3 is **FAIL_CALIBRATION / RETIRED** and its validation half remains unexposed. The later Gemini 3.8 diagnostic attempt ended in provider quota/transport failure and produced no model-quality evidence. Do not treat that quota event as a model rejection.

After V3, Phase 4.5D was redesigned so canonical memory release does not depend on whichever conversational brain provider is active.

### Provider-independent exact-fact architecture — SELECTED DEVELOPMENT CANDIDATE

Production-shaped contract:

```text
JARVIS_AI_PROVIDER-selected BrainProvider adapter
→ structured MemoryQueryProposal (proposal only; no truth/release authority)
→ local multilingual answer-type veto
→ deterministic JARVIS grounding + canonical facet validation
→ deterministic lifecycle / authority / sensitivity eligibility
→ unique exact current-facet lookup
→ TrustedMemoryEvidence or ABSTAIN
```

Key invariants:

- `JARVIS_AI_PROVIDER` remains the single production provider selector;
- provider adapters are compatibility drivers, not independent memory authorities;
- the planner receives only the user utterance plus already-eligible `(subject_scope, subject, predicate)` keys, never JARVIS-injected canonical values;
- exact validated current-fact lookup is indexed canonical SQLite lookup and does not require Qwen embedding/reranking;
- zero matching current rows → abstain;
- more than one matching current row → conflict/abstain;
- local semantic guard is veto-only and cannot create truth, select another memory, resurrect forgotten/history, or override security;
- provider or local-guard failures fail closed.

### Development evidence — COMPLETE

Structured planner diagnostic on retired V2:

- 45 cases;
- 12 target releases / 33 target abstains;
- 10 exact releases;
- 6 ordinary-semantic false releases;
- zero security-boundary releases.

Standalone NLI-as-answerability was rejected after blocking all 10 correct releases as well as all six false releases.

Standalone multilingual zero-shot answer-type classification retained all 12 legitimate release targets but had two `absent` false allows, so it was rejected as a standalone release authority and retained only as an independent veto.

Frozen composite AND-gate diagnostic on the same exposed 45 rows:

- exact releases `10/12 = 0.833333`;
- direct exact releases `8/9`;
- relation-comparison exact releases `2/3`;
- English `4/4`, Hindi `3/4`, Hinglish `3/4`;
- **false releases `0`**;
- wrong-target releases `0`;
- security-boundary releases `0`;
- all frozen continuation checks passed;
- `promising_for_fresh_acceptance_design = true`.

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_COMPOSITE_MEMORY_GATE_DIAGNOSTIC_RESULT.md`.

The selected local veto is:

- `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`;
- revision `b5113eb38ab63efdd7f280f8c144ea8b13f978ce`;
- seven frozen answer types;
- argmax-only, no fitted threshold;
- only `current_value` and `current_value_comparison` may continue.

Production-shaped implementation exists in:

- `src/jarvis/memory/answer_type_guard.py`;
- `src/jarvis/memory/guarded_query_coordinator.py`;
- the existing provider-neutral planner / grounding / evidence-gate modules.

### Fresh final composite acceptance — FROZEN / FIRST OWNER EXECUTION QUOTA-INTERRUPTED / RERUN UNCHANGED AFTER QUOTA

Method:

- `docs/research/STEP_4_PHASE_4_5D_FINAL_COMPOSITE_ACCEPTANCE_METHOD.md`.

Fresh corpus:

- 255 total queries;
- 90 release targets;
- 165 abstain targets;
- 55 synthetic documents;
- 30 release targets per language;
- 11 abstain families × 5 cases × 3 languages;
- fresh subjects/predicates/values/wording;
- exact normalized query overlap with retired V2/V3 fails closed;
- no real secrets.

Frozen corpus SHA-256:

`69666a37d436828b1d65827852f9e43d524253608209275205c41a36f8accadf`

Acceptance gates include zero false/wrong/security releases, exact-memory release only, overall release recall >= `0.75`, direct recall >= `0.75`, comparison recall >= `0.60`, each language >= `0.65`, and one-sided exact 95% released-precision lower bound >= `0.95`.

There is no calibration split because the selected architecture has no learned threshold to fit. If this fresh corpus fails, it is exposed/retired and must not be tuned and rerun as fresh evidence.

The owner acceptance uses current `gemini-3.5-flash-lite` only as the structured proposal adapter. This does **not** make memory authority Gemini-specific and does not add another production provider switch.

First owner execution on `2026-09-06` used SHA `6cba430ca9d8ea8c95c542c0664e64bd9cffbd21`, passed environment/corpus preflight, and began the frozen 255-case run. Google returned HTTP `429` after case 31 for `generativelanguage.googleapis.com/generate_content_free_tier_requests` with limit `500`. The harness terminated before writing a complete artifact.

Per the frozen method, this is **EXECUTION_FAILURE_QUOTA**, not `FAIL_ACCEPTANCE`. The first 31 partial console observations are non-evidentiary and must not be used for tuning. The corpus remains the same fresh acceptance corpus and may be rerun unchanged once sufficient provider quota is available.

Durable execution record:

- `docs/research/STEP_4_PHASE_4_5D_FINAL_COMPOSITE_ACCEPTANCE_EXECUTION_FAILURE.md`.


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
9. **4.5D — ACTIVE: provider-independent composite gate selected; fresh final composite acceptance frozen; first execution ended in provider quota failure before a complete artifact; rerun unchanged after quota is available.**
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

**RERUN THE EXACT SAME FROZEN FINAL COMPOSITE ACCEPTANCE ONLY AFTER THE GEMINI PROJECT HAS SUFFICIENT REQUEST QUOTA.**

The first owner execution on SHA `6cba430ca9d8ea8c95c542c0664e64bd9cffbd21` stopped after case 31 because Google returned HTTP `429` for the free-tier request quota (`generate_content_free_tier_requests`, limit `500`) on `gemini-3.5-flash-lite`. No complete acceptance artifact, summary, or decision was produced.

Durable execution record:

- `docs/research/STEP_4_PHASE_4_5D_FINAL_COMPOSITE_ACCEPTANCE_EXECUTION_FAILURE.md`.

This is transport/quota failure only. The frozen corpus, model, prompt/schema, local guard, request shape, deterministic policy, acceptance gates, and corpus SHA remain unchanged. Do not tune against the 31 partial printed results and do not create a replacement corpus.

Before rerun, verify the final acceptance artifact is still absent and the frozen corpus SHA remains `69666a37d436828b1d65827852f9e43d524253608209275205c41a36f8accadf`. Then execute the same acceptance harness with `--device cuda --gemini-rpm 12` after the relevant quota resets or the same project has adequate paid quota.

Phase 4.5E remains blocked until a complete fresh final artifact passes every frozen gate and closure evidence is recorded on a green exact SHA.
