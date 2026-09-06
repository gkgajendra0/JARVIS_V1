# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — PHASE 4.5D ACTIVE — V1 SCORE/MARGIN FAMILY REJECTED — INDEPENDENT VERIFIER SELECTED — FINAL V2 LEARNED-CONFIDENCE ACCEPTANCE IMPLEMENTED / CI + OWNER RUN NEXT — PHASE 4.5E BLOCKED**

This file is the operational source of truth for current work. Detailed measured evidence belongs in `docs/research/`; accepted architecture belongs in ADRs and `docs/CURRENT_ARCHITECTURE.md` only after acceptance.

---

## Permanent Step-4 constraints

- not every sentence becomes durable memory;
- explicit current owner input outranks passive inference, old memory, or stale preference;
- durable memory carries provenance + time/freshness/verification metadata;
- correction, historical change, retraction, and forgetting are distinct;
- session context is separate from durable memory;
- provider history/caches are not canonical memory;
- transient emotional interpretations stay transient by default;
- secrets are never normal durable memory/model context;
- models do not write persistent memory directly;
- `MemoryService` is the sole durable mutation facade;
- `ContextAssembler` is the sole Step-4 model-context release owner;
- retrieval ranks eligible canonical records and never establishes truth;
- canonical eligibility/security filtering occurs before ranking and remains independent of learned confidence;
- raw full transcripts/provider payloads are not archived merely because available;
- current runtime/config/repository truth outranks learned self-memory;
- one active cloud-AI provider/account owns production cloud intelligence at a time;
- current production cloud provider is Gemini through `JARVIS_AI_PROVIDER=gemini`;
- local models do not create a second cloud-provider dependency;
- Step 4 grants no autonomous repair, code modification, deployment, or authority expansion.

---

## Accepted Step-4 technology

### Canonical memory + security

- SQLCipher 4.17.0 Community / SQLite 3.53.3 canonical relational store;
- FTS5 derived lexical index with secure-delete behavior;
- JARVIS-owned bitemporal/current lifecycle;
- random 32-byte SQLCipher key protected by Windows DPAPI user scope + purpose binding;
- no graph/vector service as canonical truth owner.

### Active cloud-AI provider

ADR-015 establishes one canonical production provider through `JARVIS_AI_PROVIDER` / `JarvisConfig.ai_provider`.

Current active provider: **Gemini**.

Voice, scripted cloud TTS, structured memory extraction and future cloud-reasoning/tool workloads remain inside that provider family/account.

### Phase 4.4 structured extraction

Selected model: **`gemini-3.5-flash-lite`**.

Owner acceptance proved session-local candidate quarantine, physical disposal on session close, no implicit durable write, no cross-session resurrection, and stable Step-3 audio/vision behavior.

### Phase 4.5 retrieval stack

**Embedding:** `Qwen/Qwen3-Embedding-0.6B`

- immutable revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- normalized 256-dimensional output;
- exact frozen JARVIS memory retrieval instruction;
- local exact cosine initially.

**First stage:**

- eligible-current SQLite FTS5 lexical rank;
- exact Qwen dense rank;
- equal-weight RRF, `k=60`, lexical window `10`;
- no ANN/vector extension until scale evidence requires it.

**Reranker:** `Qwen/Qwen3-Reranker-0.6B`

- immutable revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- top 3 candidates;
- BF16 owner path;
- deterministic tie handling;
- frozen JARVIS memory-specific instruction:

> Judge whether the memory Document directly and sufficiently answers the JARVIS memory Query using only facts stated in the Document. Answer yes only when the Document supports the specific fact or relation requested; answer no when it is merely related, missing the requested detail, contradictory, negated, or otherwise does not answer the Query.

Owner selection evidence:

- Qwen hybrid Recall@1 `0.9412`, Recall@3 `1.0000`, MRR `0.9608` on the model-selection corpus;
- EmbeddingGemma rejected after real hybrid regression;
- owner RTX compatibility preserved Torch `2.13.0+cu132`, Torchvision `0.28.0+cu132`, Step-3 vision imports, and simultaneous Qwen embedding+reranker operation;
- combined Qwen peak CUDA allocation approximately `2.46 GB`.

Do not rerun embedding selection or Phase 4.5C compatibility unless those frozen contracts change.

---

## Phase status

### Phase 4.0A — COMPLETE

Stable conversation provenance and neutral DPAPI security boundary accepted.

### Phase 4.1 — COMPLETE

Encrypted canonical memory kernel, temporal lifecycle, FTS5 synchronization/rebuild, secure physical forget and exact current queries accepted.

### Phase 4.2 — COMPLETE

Bounded `LiveContext` + deterministic `ContextAssembler` accepted. Provider history remains non-canonical.

### Phase 4.3 — COMPLETE

Governed explicit `remember / inspect / correct / forget` accepted through the production voice path. Do not repeat owner acceptance.

### Phase 4.4 — COMPLETE

Structured extraction + session-local candidate quarantine accepted. Implicit auto-admission remains disabled. Do not repeat owner acceptance.

### Phase 4.5A — COMPLETE

Encrypted derived-vector lifecycle accepted:

- SQLCipher-derived vectors;
- canonical FK / `ON DELETE CASCADE`;
- immutable model/revision/dimension/dtype/byte-order/fingerprint lineage;
- stale vectors fail closed;
- canonical forget physically removes derived vectors.

### Phase 4.5B — COMPLETE

Production lexical + dense + RRF retrieval core accepted:

- eligibility before ranking;
- safe FTS5 MATCH construction;
- exact dense cosine;
- stale-vector exclusion;
- equal RRF;
- deterministic ordering;
- no vector DB required at current measured scale.

### Phase 4.5C — COMPLETE

Lazy revision-pinned Qwen embedding/reranker adapters and owner RTX coexistence accepted. Normal CI does not load GPU models.

### Phase 4.5D — ACTIVE

Goal: decide whether an **already-eligible canonical memory** may be released as query evidence. The confidence gate has no mutation or truth authority.

#### 4.5D V1 raw reranker threshold — REJECTED

The first 64-case calibration/validation experiment achieved zero false releases but only approximately `18.75%` held-out positive recall and `0%` Hindi positive recall. The corpus is exposed/retired and development-only.

#### Frozen reranker instruction bake-off — COMPLETE

On retired development data, the JARVIS-specific reranker instruction improved confidence quality without ranking/language regression and became the production default.

#### Fresh 320-case acceptance V1 — EXPOSED / RETIRED / NOT ACCEPTED

Retrieval itself was strong:

- validation positive top-1 `63/64 = 98.44%`;
- validation Recall@3 `64/64 = 100%`.

The blocker was release confidence, not retrieval ranking.

The original 30-policy `reranker_score AND margin` MAPIE/Holm procedure found zero valid policies. Corrected SFST diagnosis showed **0/30 policies were valid even as individual 0.05 tests**. Best calibration rule (`score=6`, `margin=12`) produced `18 TP / 1 FP`, precision `0.947368`, recall `0.1875`.

Therefore the two-feature rectangular rule family is permanently rejected. Do not rescue it through different multiple-testing correction, more tuning, or reuse of the exposed corpus.

#### Existing-evidence learned diagnostic — COMPLETE / INSUFFICIENT

Development-only five-fold stratified OOF `StandardScaler + LogisticRegression` result:

- score+margin: ROC-AUC `0.887769`, AP `0.876022`, best recall `0.207547` at empirical precision >= `0.95`;
- full seven retrieval features: ROC-AUC `0.892574`, AP `0.885079`, best recall `0.295597` at empirical precision >= `0.95`.

Seven existing signals improve discrimination but fail the frozen `0.40` development recall floor.

#### Independent verifier — SELECTED DEVELOPMENT SIGNAL

Selected lightweight verifier:

`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`

- immutable revision `1427fd652930e4ba29e8149678df786c240d8825`;
- Apache-2.0;
- multilingual mMARCO query/passage CrossEncoder;
- Hindi represented in source training data;
- `trust_remote_code=False`;
- owner run scoring approximately `1.6153 ms/pair` after model load/cache;
- peak verifier CUDA allocation approximately `531 MB`.

Owner development-only result on the exposed 320 cases:

- independent verifier alone: recall `0.415094` at empirical precision `0.956522`;
- full retrieval evidence + verifier: ROC-AUC `0.895972`, AP `0.910776`;
- combined best development point: `87 TP / 4 FP`, precision `0.956044`, positive recall `0.547170`;
- EN recall `0.462963`;
- HI recall `0.769231`;
- Hinglish recall `0.396226`.

This clears the pre-registered development recall floors and is the strongest architecture tested so far. It is **promising, not accepted**. `BAAI/bge-reranker-v2-m3` remains deferred.

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_INDEPENDENT_VERIFIER_RESULT.md`.

#### Final V2 confidence architecture — FROZEN / IMPLEMENTED

Candidate pipeline under acceptance:

```text
canonical eligibility
 -> FTS5 lexical + Qwen dense
 -> equal-weight RRF
 -> top 3
 -> Qwen reranker + frozen JARVIS instruction
 -> returned top candidate
 -> mMARCO independent verifier
 -> frozen StandardScaler + low-capacity LogisticRegression confidence probability
 -> MAPIE split-fixed-sequence precision control
 -> release / abstain
```

Frozen eight features:

1. reranker score;
2. reranker margin;
3. dense cosine;
4. fused RRF score;
5. lexical-hit indicator;
6. reciprocal lexical rank;
7. reciprocal dense rank;
8. independent verifier score.

Excluded from the learned gate:

- language;
- category/case ID;
- expected-memory ID;
- validation-only metadata.

Frozen estimator:

```text
StandardScaler
 -> LogisticRegression(
      solver="lbfgs",
      max_iter=2000,
      random_state=45
    )
```

Training/order-learning separation:

- exposed retired 320 cases may fit this already-selected low-capacity model;
- Qwen retrieval is **not rerun** on retired cases;
- the frozen verifier may rescore retired query/top-document pairs only to reconstruct its selected eighth feature;
- the retired development set learns MAPIE SFST hypothesis order with `binary=True`;
- new V2 calibration is statistically independent from order learning;
- V2 validation labels never influence fitting, feature selection, threshold ordering or threshold calibration.

MAPIE research controller:

- version `1.5.0`;
- risk `precision` / PPV;
- target precision `0.95`;
- confidence `0.95`;
- FWER `split_fixed_sequence`;
- best valid threshold selected by recall;
- no valid threshold = fail closed.

Why SFST: precision is non-monotonic in the threshold; MAPIE's split fixed-sequence method learns a candidate order on independent data and tests that fixed sequence on calibration data without the old unordered 30-way Holm burden.

Method record:

- `docs/research/STEP_4_PHASE_4_5D_FINAL_V2_METHOD.md`.

#### Fresh V2 corpus — FROZEN / IMPLEMENTED

New deterministic synthetic corpus:

- total `1,800` queries;
- calibration `600 release + 600 abstain`;
- validation `300 release + 300 abstain`;
- validation release queries: exactly `100 EN + 100 HI + 100 Hinglish`;
- no exact-query reuse from retired 64-case or 320-case corpora;
- fixed abstain categories:
  - absent;
  - near miss;
  - ambiguous;
  - adversarial lexical overlap;
  - negation;
  - relation mismatch;
  - unsupported source/detail;
  - historical;
  - forgotten;
  - local-only;
  - secret;
  - untrusted;
- deterministic payload SHA-256;
- duplicate case/query text fails closed;
- no real credentials/secrets.

Sample-size rationale:

At precision target `0.95` and one-sided alpha `0.05`, exact-binomial scale intuition requires approximately:

- 59 released examples for zero observed errors;
- 93 for one error;
- 124 for two;
- 153 for three;
- 181 for four;
- 208 for five;
- 234 for six.

These counts are explanatory only; MAPIE remains the acceptance controller. With `600` positive calibration cases, the `0.40` recall floor corresponds to `240` true-positive releases, intentionally correcting the old 96-positive underpowered design.

Generator:

- `tools/research/step4_phase45d_final_v2_cases.py`.

One-shot harness:

- `tools/research/step4_phase45d_final_v2_acceptance.py`.

New evidence file:

- `.step4-phase45d-final-v2-acceptance.json`.

The harness refuses to overwrite an existing V2 evidence file.

#### Frozen V2 validation gates

V2 passes only if all are true:

1. MAPIE finds a statistically valid threshold at precision target `0.95`, confidence `0.95`;
2. validation positive top-1 retrieval accuracy >= `0.85`;
3. validation positive Recall@3 >= `0.90`;
4. observed validation false releases = `0`;
5. overall positive release recall >= `0.40`;
6. English positive release recall >= `0.25`;
7. Hindi positive release recall >= `0.25`;
8. Hinglish positive release recall >= `0.25`;
9. zero released historical/forgotten/local-only/secret/untrusted boundary query;
10. no validation-driven retuning.

A V2 failure rejects this frozen architecture. It does not authorize editing the system and rerunning the same V2 validation corpus.

Synthetic acceptance cannot prove future owner traffic is exchangeable. Later operational shadow-labelled risk/drift monitoring remains mandatory before making strong real-world statistical claims.

### Phase 4.5E — BLOCKED BY OWNER UNTIL 4.5D COMPLETE

Do **not** integrate semantic retrieval into `ContextAssembler` / Gemini conversation yet.

4.5E may begin only after 4.5D has:

- frozen model/features/protocol;
- fresh powered calibration;
- untouched validation;
- all precision/recall/language/security gates passed;
- durable owner evidence;
- docs synchronized;
- exact owner-run SHA green in CI.

### Phases 4.6–4.8 — NOT STARTED

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
9. **4.5D — ACTIVE: V2 confidence acceptance implemented; exact SHA must pass CI, then one owner RTX V2 run.**
10. **4.5E — BLOCKED.**
11. 4.6 — NOT STARTED.
12. 4.7 — NOT STARTED.
13. 4.8 — NOT STARTED.

---

## Do not repeat / do not do next

Do not:

- start Phase 4.5E;
- wire semantic retrieval into Gemini conversation;
- lower the `0.95` precision or `0.95` confidence targets to obtain a pass;
- lower the `0.40` overall or `0.25` language recall floors to obtain a pass;
- reuse either exposed 4.5D corpus for acceptance;
- rerun the Qwen/EmbeddingGemma embedding bake-off;
- rerun Phase 4.5C owner compatibility;
- revisit the rejected score+margin family or spend more effort on Holm/SFST for that family;
- benchmark BGE unless the lightweight V2 architecture genuinely fails fresh acceptance and new research justifies it;
- change Qwen revisions or Torch/Torchvision casually;
- disturb Step-3 audio/vision architecture;
- weaken forgotten/local-only/secret/untrusted eligibility filters;
- let learned confidence create, modify, resurrect or establish canonical truth.

---

## Immediate Next Action

**WAIT FOR THE EXACT CURRENT V2 IMPLEMENTATION SHA TO PASS CI; THEN RUN THE NEW V2 OWNER RTX ACCEPTANCE ONCE.**

The owner run must use the accepted Windows `.venv`, current Torch/Torchvision stack, the existing retired `.step4-phase45d-final-acceptance.json` only as development input, and the new V2 harness.

A `PASS` or `FAIL_ACCEPTANCE` V2 artifact is valid evidence. Do not overwrite or rerun it to chase a pass.

Do not begin Phase 4.5E afterward unless Phase 4.5D actually passes and closure documentation/CI are complete.
