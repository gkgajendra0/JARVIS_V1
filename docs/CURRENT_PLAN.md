# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — PHASE 4.5D ACTIVE — V4 FAILED / RETIRED — TASK-SPECIFIC LOCAL GUARD BAKE-OFF METHOD V2 FROZEN — PHASE 4.5E BLOCKED**

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

## Active 4.5D direction — JARVIS-SIDE TASK-SPECIFIC LOCAL GUARD REPLACEMENT

The provider-independent memory-authority architecture remains selected: provider adapters may propose structured query intent, but deterministic JARVIS grounding, lifecycle/security eligibility and exact canonical lookup own release authority. `JARVIS_AI_PROVIDER` remains the single production provider selector.

### V4 fresh final composite acceptance — FAIL_ACCEPTANCE / RETIRED

Frozen V4 corpus SHA-256:

`69666a37d436828b1d65827852f9e43d524253608209275205c41a36f8accadf`

The quota-safe provider-backed owner run completed all `255` cases with exactly `66` logical Gemini calls and `66` API attempts. Quota was **not** the blocker.

Provider-backed result:

- exact target releases `53/90`;
- false releases `0`;
- wrong-target releases `0`;
- security-boundary releases `0`;
- empirical precision `1.0`;
- overall release recall `0.588889`;
- direct-current recall `0.800000`;
- current-value-comparison recall `0.166667`;
- EN `0.666667`, HI `0.566667`, Hinglish `0.533333`;
- the local zero-shot guard vetoed `24/30` legitimate comparison targets.

A separately frozen provider-independent core acceptance then ran the same V4 corpus with **zero cloud/provider calls** and deterministic hostile proposals.

Provider-independent core result:

- exact target releases `58/90`;
- false releases `1`: `v4_a0073`, Hinglish `negation`;
- wrong-target releases `0`;
- security-boundary releases `0`;
- security authority-only precheck failures `0`;
- overall release recall `0.644444`;
- direct-current recall `0.866667`;
- comparison recall `0.200000`;
- the same local guard again vetoed `24/30` legitimate comparison targets.

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_V4_ACCEPTANCE_RESULT.md`.

### V4 diagnosis — COMPLETE

The failure is now isolated to the generic multilingual zero-shot NLI answer-type guard, not retrieval, Gemini quota, provider planning, canonical lifecycle/security authority or exact canonical lookup. The guard is too conservative on legitimate comparison questions and missed one Hinglish negation boundary.

V4 is exposed and **retired acceptance evidence**. Do not rerun it, tune thresholds on it, train a replacement on its query text, or score replacement candidates on it. V4 may be used only as an exact-query deny-list and as architectural evidence that comparison and negation need explicit representation.

The existing `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` zero-shot guard is therefore retired as the selected production design. Production behavior is not changed until a replacement wins the frozen development bake-off.

### Task-specific local guard bake-off — METHOD V2 FROZEN / DEVELOPMENT-ONLY

Research selected the SetFit-style pattern without adding the SetFit package itself: a frozen multilingual SentenceTransformer produces normalized query embeddings and a fixed scikit-learn `LogisticRegression` head performs task-specific classification. This reuses the already-compatible owner stack instead of disturbing pinned Torch/Transformers.

Before any owner bake-off result existed, the unexecuted first method draft was corrected to include the already accepted JARVIS Qwen3 embedding backbone as a mandatory reuse baseline and to record latency/model-size/RAM/VRAM diagnostics required by the frozen handover. The corpus, labels, logistic head, semantic gates and tie-break rules were not changed. This correction is frozen as Method V2 and is not post-result tuning.

New eight-class taxonomy:

1. `current_value`;
2. `current_value_comparison`;
3. `reason_explanation`;
4. `provenance_actor`;
5. `replacement_successor`;
6. `related_record`;
7. `negated_or_contradicted`;
8. `other_or_advice`.

Only `current_value` and `current_value_comparison` may continue. The classifier remains veto-only and cannot establish canonical truth.

Development corpus:

- `288` train cases;
- `192` never-trained-on holdout cases;
- exact English / Hindi / Hinglish and eight-class balance;
- disjoint train/holdout facts and paraphrase templates;
- zero exact normalized train/holdout overlap;
- zero exact normalized overlap with retired V4;
- V4 is not used for training or scoring.

Frozen development corpus SHA-256:

`ae854ed664ef6ee0214f65f5fe4b252099fd1dcaea00c13aaf7789cd84afd3ab`

Candidates, all with the same frozen logistic head and no threshold fitting:

- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` @ `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`;
- `intfloat/multilingual-e5-small` @ `fd1525a9fd15316a2d503bf26ab031a61d056e98`;
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` @ `4328cf26390c98c5e3c738b4460a05b95f4911f5`;
- existing JARVIS `Qwen/Qwen3-Embedding-0.6B` @ `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`, raw-query input, normalized `truncate_dim=256` reuse baseline.

The bake-off records false allows/vetoes, direct/comparison/language recall, negation false allows, per-class recall, macro-F1/accuracy, model load time, embedding latency, parameter count/bytes, sampled process RSS and per-candidate CUDA peak allocation. Resource metrics are diagnostics and do not replace the frozen semantic gates.

Frozen development gates require simultaneously: zero false allows, zero negation false allows, overall allow recall >= `0.90`, direct >= `0.90`, comparison >= `0.85`, each language >= `0.85`, eight-class macro-F1 >= `0.85`, argmax-only/no threshold, zero cloud calls, and no V4 training/scoring.

Method:

- `docs/research/STEP_4_PHASE_4_5D_TASK_SPECIFIC_GUARD_BAKEOFF_METHOD.md`.

Harness:

- `tools/research/step4_phase45d_task_specific_guard_bakeoff.py`;
- `tools/research/step4_phase45d_task_specific_guard_cases.py`.

If no candidate passes every frozen development gate, no production guard change is authorized. If a candidate passes and wins the frozen tie-break, freeze its model/revision plus classifier artifact/coefficients, class order, training-corpus hash, sklearn version and artifact checksum; then implement the production task-specific guard and create a completely fresh V5 provider-independent acceptance corpus. A development bake-off pass alone does not close 4.5D.

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
9. **4.5D — ACTIVE: V4 completed and failed/retired; generic zero-shot NLI guard isolated as the blocker; corrected zero-cloud task-specific local guard bake-off Method V2 frozen and next.**
10. **4.5E — BLOCKED.**
11. 4.6 — NOT STARTED.
12. 4.7 — NOT STARTED.
13. 4.8 — NOT STARTED.

---

## Do not repeat / do not do next

Do not:

- rerun V4 provider-backed or provider-independent acceptance;
- tune thresholds, train, or score replacement candidates on V4 query text/results;
- modify the frozen Method V2 corpus/gates/candidate preprocessing after seeing owner bake-off results and still call the rerun the same development evidence;
- install SetFit or change Torch/Torchvision merely for this bake-off;
- modify the production answer-type guard before a candidate passes the frozen bake-off;
- rerun or overwrite V2 acceptance evidence;
- reuse V2 as fresh acceptance evidence;
- treat the retrieval-depth diagnostic as acceptance;
- test 512d/1024d embeddings now; the Qwen guard reuse baseline is deliberately the existing 256d contract and top-10 256d retrieval already reached `900/900` on exposed development positives;
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

**RUN THE FROZEN ZERO-CLOUD TASK-SPECIFIC LOCAL GUARD BAKE-OFF METHOD V2 ON THE OWNER RTX MACHINE.**

This is development model selection only. It uses a new `288`-train / `192`-holdout corpus and makes zero Gemini/OpenAI calls. It must not use V4 for training or scoring.

Before the owner run:

- use the exact green repository SHA supplied with the owner command;
- verify `.step4-phase45d-task-specific-guard-bakeoff-v1.json` is absent;
- verify the development corpus SHA is `ae854ed664ef6ee0214f65f5fe4b252099fd1dcaea00c13aaf7789cd84afd3ab`;
- install/use the dedicated `phase45d-task-guard` optional dependency set, including pinned `scikit-learn==1.9.0` and `psutil==7.2.2`;
- keep owner Torch `2.13.0+cu132`, Torchvision `0.28.0+cu132`, Transformers `5.16.1` and SentenceTransformers `6.0.1`;
- do not run cloud-provider diagnostics in parallel.

If one candidate passes every frozen development gate, record the result, freeze the winner artifact/contract, implement the production replacement cleanly, and then design a never-exposed V5 provider-independent acceptance. If no candidate passes, research the failure class and create a new development iteration without tuning against this holdout or V4.

Phase 4.5E remains blocked until a fresh V5 acceptance passes and 4.5D has durable closure evidence on a green exact SHA.
