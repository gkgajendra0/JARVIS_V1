# Step 4 Phase 4.5D — Question-Role Bake-Off V1 Method

## Status

**FROZEN DEVELOPMENT METHOD — ZERO-TRAINING NATIVE INTENT CLASSIFICATION, NOT ACCEPTANCE**

Phase 4.5D remains active. Phase 4.5E remains blocked.

This method is frozen before any owner result from the fresh question-role corpus exists.

---

## Why this experiment exists

The completed Answerability Component Bake-Off V1 proved that mature generic QA/NLI components do not by themselves satisfy the JARVIS release boundary.

Durable V1 result:

- `docs/research/STEP_4_PHASE_4_5D_ANSWERABILITY_BAKEOFF_V1_RESULT.md`

Owner V1 evidence showed:

- XLM-R SQuAD2: `45` unauthorized no-answer releases, `2` wrong evidence releases, answerable recall `0.604167`;
- mDeBERTa SQuAD2: `39` unauthorized no-answer releases, `8` wrong evidence releases, answerable recall `0.718750`;
- native multilingual NLI: `24` unauthorized YES/NO releases on all `24` neutral/unknown cases, but `1.000000` comparison recall and `0` wrong YES↔NO verdicts.

Therefore V1 is retired. Do not threshold-tune or rerun it.

The useful architectural conclusion is narrower:

1. retrieval/reranking is not the remaining blocker;
2. deterministic exact-facet lookup remains valuable;
3. native NLI is strong at truth evaluation **after** a proposition has already been established as answerable;
4. the remaining blocker is **question focus / requested answer role / safe abstention**.

The earlier structured-query-planner diagnostic reached the same conclusion independently: its false releases were why/who/replacement/linked-record questions incorrectly routed to an exact current-value facet. Exact lookup itself did not select the wrong canonical value and deterministic security boundaries remained intact.

---

## Decision being tested

Can a mature multilingual zero-shot classifier, used in its native single-label intent-classification role, act as an **independent veto signal** for the existing structured exact-facet path?

Input:

- raw user query only.

The local classifier does **not** receive:

- canonical memory values;
- retrieved memory text;
- case IDs;
- language metadata;
- expected labels;
- provider proposal output.

Output:

- exactly one requested answer role by native single-label softmax argmax.

Only two roles may approve continuation toward the current exact-fact path:

1. `current_value`
2. `current_value_comparison`

All other roles veto that path:

3. `reason_explanation`
4. `provenance_actor`
5. `replacement_successor`
6. `related_record`
7. `historical_value`
8. `external_source`
9. `broad_recall`
10. `advice_or_other`

The classifier has no authority to select a facet, establish truth, access a memory value, bypass lifecycle/security policy, or release model context. It can only approve/veto the semantic route.

---

## Why this is materially different from retired experiments

### Different from Method V2

Method V2 used:

```text
raw query → frozen general embedding → LogisticRegression → custom 8-class taxonomy
```

The embedding body was never trained for the task and all four candidates violated the zero-false-allow boundary.

Question-Role V1 instead uses a mature model specifically trained for multilingual zero-shot text classification and applies its native single-label classification interface. There is no JARVIS-trained head.

### Different from the previous GLiClass semantic-judge experiment

GLiClass Multilang Mini was previously tested in a different task:

```text
query + selected memory document → binary RELEASE / ABSTAIN → calibrated margin threshold
```

That experiment failed and remains retired for binary semantic-sufficiency judging.

Question-Role V1 does **not** reopen that result. The new task is:

```text
raw user query → one semantic answer role → softmax argmax
```

No memory document is supplied and no threshold is fitted. This is the model's native intent/classification use case.

### Different from generic NLI

Native NLI remains retired as an answerability/abstention authority. Its V1 result is retained only as evidence that, once an answerable comparison proposition is safely established, it may later be useful as a downstream YES/NO truth evaluator.

---

## Research-first model selection

### GLiNER2.5 considered but not selected

Current GLiNER2.5 Multi is attractive because it provides multilingual schema-driven extraction and classification. However, current `gliner2` local dependencies require `transformers>=4.38,<5`, while the accepted JARVIS environment is frozen on Transformers `5.16.1`.

This experiment therefore does **not**:

- downgrade Transformers;
- install GLiNER2 with dependency bypasses;
- use unsupported `--no-deps` compatibility assumptions.

GLiNER2.5 remains a future/watchlist candidate once upstream supports the accepted runtime cleanly.

### Selected mature family — GLiClass Multilang

Package:

`gliclass==0.1.20`

Its current package contract supports:

- Torch `>=2.0.0`;
- Transformers `>=5.0.0`;
- NumPy `>=2.0.0`.

That is compatible with the accepted owner runtime.

GLiClass native single-label postprocessing applies softmax across candidate labels and returns argmax. The threshold argument is used only for multi-label classification. Therefore Question-Role V1 has no fitted or hidden decision threshold.

---

## Frozen candidates

Both candidates are frozen **before any fresh-corpus owner result** so the experiment cannot expose Mini and then decide afterward to model-hop to Ultra.

### Candidate A — Multilang Mini

- model: `knowledgator/gliclass-multilang-mini`
- revision: `0bd888b6c3ef9fca5f0a9d407bddfbbc7623486b`
- package: `gliclass==0.1.20`
- Safetensors required
- `trust_remote_code=False`

### Candidate B — Multilang Ultra

- model: `knowledgator/gliclass-multilang-ultra`
- revision: `9d6ca10258a3bddcf05b88c89cb8a8390e87e90c`
- package: `gliclass==0.1.20`
- Safetensors required
- `trust_remote_code=False`

The candidates run sequentially. If Ultra cannot fit on the accepted owner RTX path, the harness records `RESOURCE_REJECTED`; it does not change precision, quantize, alter the corpus, or substitute another model after evidence is visible.

---

## Fresh frozen corpus

Generator:

- `tools/research/step4_phase45d_question_role_cases.py`

Frozen deterministic payload SHA-256:

`bb09a6a6b7c6f9248c48f35a39e5f4f8002f678a471d4752152c6a6b26cd4c21`

Shape:

- 8 completely fresh synthetic subjects/facts;
- English / Hindi / natural Hinglish-style templates;
- 10 answer roles;
- 2 paraphrase families per fact/language/role;
- `480` total cases;
- `96` exact-current-path allow cases;
- `384` veto cases.

The harness exact-normalizes and deny-lists all queries from:

- Answerability Component Bake-Off V1;
- exposed Method V2 task-specific guard train + holdout;
- retired V4 final composite acceptance.

Those corpora are not used for training or scoring.

### Important comparison/negation coverage

`current_value_comparison` intentionally includes both positive and negated surface forms, for example the semantic shapes:

- “Is X still the current value?”
- “The current value is not Y, right?”

A negated comparison is not automatically a veto. It still requests a boolean judgment about the present canonical value.

---

## Frozen classification contract

```text
package = gliclass==0.1.20
classification_type = single-label
decision = softmax argmax
threshold used for decision = false
few-shot examples = 0
max_length = 256
batch_size = 8
weights = safetensors only
trust_remote_code = false
cloud/provider calls = 0
```

Fixed task instruction:

> Classify only the type of answer the user is requesting from personal memory. Choose exactly one answer role. Do not decide whether a mentioned value is true. A yes/no or negated question about whether the present value is X is a current value comparison. Questions asking why, who, what replaced it, a linked record, past state, an external source, broad recall, or advice are not current-value lookups.

The 10 descriptive English labels are frozen in the harness. GLiClass Multilang is explicitly designed for cross-lingual text/label classification, so no translated label set or per-language prompt is introduced after results are visible.

---

## Frozen development gates

A candidate passes only if **all** are satisfied:

1. zero unsafe false approvals:
   - no veto-role case may be predicted as `current_value` or `current_value_comparison`;
2. zero wrong allow modes:
   - a direct current-value query may not be approved as comparison, and a comparison may not be approved as direct current-value;
3. exact overall allow-role recall >= `0.90`;
4. `current_value` exact recall >= `0.90`;
5. `current_value_comparison` exact recall >= `0.90`;
6. English allow-role recall >= `0.85`;
7. Hindi allow-role recall >= `0.85`;
8. Hinglish allow-role recall >= `0.85`;
9. single-label argmax only; no fitted threshold;
10. zero cloud/provider calls.

Exact 10-role accuracy and macro-F1 are diagnostic measurements, not substitutes for the safety gates.

---

## Frozen tie-break

Only candidates passing every gate are selectable.

Tie-break order:

1. fewer unsafe false approvals;
2. fewer wrong allow-mode decisions;
3. higher exact allow recall;
4. higher minimum language allow recall;
5. higher exact 10-role accuracy;
6. higher macro-F1;
7. lower inference milliseconds/case;
8. lower CUDA peak delta.

---

## Measurements

For each completed candidate, record:

- unsafe false approvals;
- wrong allow-mode cases;
- false vetoes;
- exact allow recall;
- exact 10-role accuracy;
- macro-F1;
- per-language allow recall;
- per-role precision/recall;
- complete role confusion counts;
- unsafe / wrong-mode / false-veto case IDs;
- model ID and immutable revision;
- parameter count and bytes;
- load time;
- inference time and ms/case;
- sampled RSS;
- CUDA baseline/peak/delta;
- exact Torch / Transformers / GLiClass / GPU environment.

Output:

`.step4-phase45d-question-role-bakeoff-v1.json`

The harness refuses overwrite/reuse.

---

## What a development pass means

A passing candidate does **not** authorize production and does **not** close 4.5D.

It authorizes only the next fresh development step:

1. freeze the selected local role-classifier contract;
2. extend the structured query proposal only as needed to distinguish direct-value vs comparison composition without giving the provider authority;
3. build strict fail-closed consensus:

```text
Gemini/provider structured proposal selects an eligible exact facet
AND
local role classifier approves the matching current answer role
AND
deterministic JARVIS policy validates lifecycle/security/grounding
→ exact canonical lookup

otherwise → ABSTAIN
```

4. for approved comparisons, evaluate the already-pinned native NLI only as downstream truth evaluation, not as the abstention gate;
5. run a completely fresh composite integration benchmark;
6. only after the full implementation contract is frozen create a never-exposed final acceptance corpus.

Phase 4.5E remains blocked throughout.

---

## If V1 fails

Retire this corpus and diagnose the failure class.

Do **not**:

- change the prompt after seeing results and rerun the same corpus;
- rename/rewrite labels and call the rerun the same evidence;
- fit confidence/margin thresholds on these 480 cases;
- train/fine-tune on these cases;
- model-hop to an unfrozen checkpoint after observing results;
- weaken the zero-unsafe-approval gate;
- add hand-written Hindi/Hinglish keyword patches;
- claim production readiness or start Phase 4.5E.
