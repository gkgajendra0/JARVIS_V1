# Step 4 Phase 4.5D — Final V3 Acceptance Method

Status: **METHOD FROZEN BEFORE V3 CORPUS OWNER EXECUTION**

This document freezes the final V3 method after the exposed V2 development program selected the production-shaped Gemini semantic judge. Any material change after V3 calibration begins invalidates the V3 run and requires a new acceptance version.

## 1. Purpose

Phase 4.5D decides whether an **already-eligible canonical memory** may be released as evidence for a user query.

The release gate does not establish canonical truth and has no mutation authority. Canonical lifecycle, security, provenance and cloud-context eligibility remain deterministic authority and run before ranking or semantic judgment.

V3 is the first fresh acceptance corpus for the architecture selected after the V2 development diagnostics.

## 2. Research basis

### 2.1 Gemini production shape

The exposed V2 batch-120 experiment was not production-equivalent. A preregistered 15-case diagnostic changed only request shape from 120 cases/request to one query/document pair/request and produced 15/15 `RELEASE -> ABSTAIN` flips on the targeted boundary cells.

A second preregistered single-instance diagnostic then preserved all 24 previously-correct positive/ordinary-abstain cells. Combined production-shaped development coverage was 39/39 across all tested category/language cells.

Therefore V3 freezes one query/document pair per Gemini request.

### 2.2 Stable Gemini model

Google currently lists `gemini-3.5-flash-lite` as a stable GA Gemini 3 model. It is the same model ID used in the successful development diagnostics.

Reference:

https://ai.google.dev/gemini-api/docs/models

Google structured-output documentation supports typed classification but explicitly states that schema-valid output does not guarantee semantically correct values and must be application-validated.

Reference:

https://ai.google.dev/gemini-api/docs/structured-output

### 2.3 Why V3 does not use MAPIE threshold search

MAPIE 2026 includes an LLM-as-a-judge risk-control example with abstention and PPV/NPV risk control. That method searches thresholds over model probability scores.

Reference:

https://mapie.readthedocs.io/en/latest/generated/risk_control/2-advanced-analysis/plot_risk_control_llm_as_a_judge/

The selected JARVIS Gemini judge exposes a fixed hard `RELEASE` / `ABSTAIN` policy. JARVIS does not currently possess a validated calibrated probability score for this semantic decision. V3 therefore must not invent a confidence score merely to enable threshold search.

### 2.4 Exact fixed-policy precision control

For a fixed policy evaluated on fresh exchangeable calibration cases, V3 controls release precision with an exact one-sided binomial confidence bound.

SciPy `binomtest(...).proportion_ci(method="exact")` implements the Clopper-Pearson exact interval and respects the one-sided alternative.

References:

https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html

https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html

Frozen target:

- precision / PPV target: `0.95`;
- confidence level: `0.95`;
- one-sided alternative: `greater`;
- exact method: Clopper-Pearson.

For the calibration cases released by the fixed policy:

```python
result = scipy.stats.binomtest(
    tp,
    n=released_cases,
    p=0.95,
    alternative="greater",
)
ci = result.proportion_ci(confidence_level=0.95, method="exact")
```

The calibration statistical gate passes only when:

```text
ci.low >= 0.95
```

The p-value is recorded as supporting evidence but the lower confidence bound is the frozen primary gate.

With zero calibration false releases, at least **59 released calibration cases** are mathematically required for a one-sided 95% exact lower bound to exceed 0.95. V3 therefore fails closed if fewer than 59 calibration cases are released even before the exact bound is evaluated.

## 3. Frozen architecture

```text
canonical lifecycle / security / provenance authority
→ RetrievalEligibility.cloud_context()
→ eligible-current SQLite FTS5 lexical retrieval
  + Qwen/Qwen3-Embedding-0.6B normalized 256d exact cosine
→ equal-weight reciprocal-rank fusion, k=60
→ first-stage candidate window = 10
→ Qwen/Qwen3-Reranker-0.6B
→ selected eligible Top-1 memory
→ Gemini 3.5 Flash-Lite semantic sufficiency judge
→ exactly one query/document pair per Interactions API request
→ structured RELEASE / ABSTAIN
```

Frozen Qwen embedding:

- model: `Qwen/Qwen3-Embedding-0.6B`;
- revision: `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- dimension: `256`;
- normalized vectors;
- exact local cosine.

Frozen Qwen reranker:

- model: `Qwen/Qwen3-Reranker-0.6B`;
- revision: `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- candidate window: `10`;
- accepted BF16 owner path;
- frozen JARVIS instruction:

> Judge whether the memory Document directly and sufficiently answers the JARVIS memory Query using only facts stated in the Document. Answer yes only when the Document supports the specific fact or relation requested; answer no when it is merely related, missing the requested detail, contradictory, negated, or otherwise does not answer the Query.

Frozen Gemini:

- model ID: `gemini-3.5-flash-lite`;
- API surface: Google GenAI **Interactions API**;
- SDK contract: existing project `google-genai==2.22.0`;
- one query/document pair per request;
- `store=False`;
- same semantic sufficiency system instruction and structured decision/failure-mode schema used in the successful single-instance development diagnostics;
- no ground-truth label, expected memory ID, category, language label or validation metadata is sent to Gemini;
- no temperature/top-p/top-k tuning is introduced;
- no Gemini-derived probability/confidence score is used.

## 4. Batch API is explicitly excluded from V3

Google Batch API accepts separate `GenerateContentRequest` objects and is designed for large evaluation workloads, but it currently uses the `generateContent` API rather than the Interactions API.

Reference:

https://ai.google.dev/gemini-api/docs/batch-api

V3 does not switch API surfaces merely for throughput. Final acceptance must match the Interactions API request shape that selected the development architecture.

## 5. Fresh V3 corpus

### 5.1 Total size

V3 contains exactly **720** cases:

- calibration: `360`;
- validation: `360`.

Each split contains:

- release: `180`;
- abstain: `180`.

### 5.2 Language balance

Languages:

- English (`en`);
- Hindi (`hi`);
- Hinglish (`hinglish`).

Per split, release cases are exactly:

- EN: `60`;
- HI: `60`;
- Hinglish: `60`.

Per split, abstain cases are exactly:

- EN: `60`;
- HI: `60`;
- Hinglish: `60`.

Therefore every split has exactly `120` cases per language.

### 5.3 Abstain families

The 12 frozen abstain families remain:

1. `absent`;
2. `near_miss`;
3. `ambiguous`;
4. `adversarial_lexical`;
5. `negation`;
6. `relation_mismatch`;
7. `unsupported_source`;
8. `historical`;
9. `forgotten`;
10. `local_only`;
11. `secret`;
12. `untrusted`.

Per split, every abstain family contains exactly `15` cases:

- 5 English;
- 5 Hindi;
- 5 Hinglish.

Thus `12 × 15 = 180` abstain cases per split.

Security-boundary families remain:

- `historical`;
- `forgotten`;
- `local_only`;
- `secret`;
- `untrusted`.

### 5.4 Freshness and leakage constraints

V3 must use:

- completely new synthetic profile/entity names;
- new predicates;
- new relation families and values;
- new current-memory document wording;
- new negative/boundary fixture wording;
- new query wording.

The generator must fail if any exact V3 query collides with known V1/V2 queries available in the repository.

The generator must fail on duplicate V3 case IDs, queries or memory IDs.

No real secret or credential may appear in the corpus.

### 5.5 Diversity before split

All profile/fact pools and all English/Hindi/Hinglish paraphrase/template banks are defined **before** calibration/validation assignment.

Split assignment must be deterministic and group-aware by synthetic profile/fixture identity; template family must never determine the split.

Calibration and validation use disjoint synthetic profile/fixture identities while drawing from the same preregistered wording distribution.

This prevents a validation-specific wording family from being created after calibration behavior is observed.

### 5.6 Immutable payload

The corpus generator must emit a deterministic payload SHA-256 covering all acceptance inputs and split assignments. The expected hash is committed before owner execution.

Any payload-hash change creates a new V3 version and invalidates prior evidence.

Frozen V3 payload SHA-256:

`baac40840bc260a01f4fc630570e4578dbdf8dc9f36c8b3192c6bb6471191195`

## 6. Frozen execution order

V3 is a single owner acceptance program with a fail-closed two-stage execution.

### Stage A — calibration

1. build the fresh V3 database and canonical lifecycle fixtures;
2. apply canonical eligibility before retrieval;
3. retrieve up to 10 candidates using accepted FTS5 + 256d Qwen hybrid retrieval;
4. rerank using the frozen Qwen reranker;
5. call Gemini once per selected query/document pair using the frozen Interactions request shape;
6. compute calibration ranking, release-safety, language and exact precision statistics.

No threshold, prompt, model, relation rule or candidate-window parameter is selected from calibration.

If **any calibration hard gate fails**, V3 stops and validation Gemini calls are not executed. The same V3 corpus cannot be tuned and rerun as fresh evidence.

### Stage B — validation

Validation is executed only after all calibration hard gates pass.

The same frozen architecture is applied exactly once. Validation results cannot be used to retune and rerun V3.

## 7. Frozen acceptance gates

### 7.1 Calibration gates

All must pass:

1. payload/schema integrity and exact expected SHA pass;
2. positive first-stage Recall@10 `>= 0.90`;
3. positive reranked Top-1 accuracy `>= 0.85`;
4. at least `59` calibration cases are released;
5. exact one-sided 95% Clopper-Pearson lower bound for release precision `>= 0.95`;
6. calibration positive release recall `>= 0.40`;
7. calibration EN/HI/Hinglish positive release recall each `>= 0.25`;
8. zero calibration releases from `historical`, `forgotten`, `local_only`, `secret`, or `untrusted`;
9. no model/API/schema execution failure.

Calibration ordinary semantic false releases are not given a special exemption: they lower precision and may cause the exact statistical gate to fail.

### 7.2 Validation gates

All must pass:

1. positive first-stage Recall@10 `>= 0.90`;
2. positive reranked Top-1 accuracy `>= 0.85`;
3. **zero validation false releases**;
4. validation positive release recall `>= 0.40`;
5. validation EN positive release recall `>= 0.25`;
6. validation HI positive release recall `>= 0.25`;
7. validation Hinglish positive release recall `>= 0.25`;
8. zero validation releases from `historical`, `forgotten`, `local_only`, `secret`, or `untrusted`;
9. no validation-driven retuning;
10. no model/API/schema execution failure.

The zero-false-release validation gate intentionally remains stricter than the 95% precision target.

## 8. Release truth definition

For acceptance scoring, a case is safe to release only when:

- its label is `release`; and
- the expected canonical memory is the selected reranked Top-1 eligible memory; and
- Gemini returns `RELEASE`.

A Gemini `RELEASE` on any abstain-labelled case is a false release.

If the expected positive memory does not reach Top-1, that positive cannot count as a true release even if Gemini says `RELEASE` for a different memory.

Canonical eligibility remains authoritative: excluded historical/forgotten/local-only/secret/untrusted records cannot be resurrected by retrieval or Gemini.

## 9. Execution failures vs model failures

Transient provider `429/503` responses may use the existing bounded retry-after-aware transport behavior. If retries are exhausted, the run is **EXECUTION_INCOMPLETE**, not an acceptance/model-quality result.

Malformed/missing structured output is fail-closed and cannot produce a release.

The acceptance artifact is written only after the harness reaches a terminal complete state and the harness refuses to overwrite an existing artifact.

## 10. Evidence artifact

The final artifact must record at minimum:

- git SHA;
- corpus schema version and payload SHA;
- model IDs/revisions;
- installed Torch/Torchvision/Transformers/Google GenAI/SciPy versions;
- owner GPU/device metadata;
- retrieval/reranker timing and peak CUDA allocation;
- Gemini request count, usage metadata and transport settings;
- calibration first-stage Recall@10 and Top-1 accuracy;
- calibration TP/FP/releases/precision/recall;
- calibration exact one-sided precision lower bound and p-value;
- calibration per-language recall;
- calibration false releases by category;
- validation ranking metrics;
- validation TP/FP/releases/precision/recall;
- validation per-language recall;
- validation false releases by category;
- security-boundary release IDs;
- each frozen hard gate;
- final `PASS_ACCEPTANCE` or `FAIL_ACCEPTANCE`.

Public artifact rows must not contain real secrets. Synthetic query/document text may be omitted from the public result to keep the evidence compact; case IDs, labels, categories and scores/decisions are sufficient for diagnosis because the committed corpus is reproducible.

## 11. Dependency boundary

Use mature SciPy exact binomial support rather than a custom confidence-interval implementation.

A dedicated research/acceptance extra may add:

```toml
phase45d-acceptance = ["scipy>=1.14,<2"]
```

Do not alter the accepted owner Torch/Torchvision stack.

## 12. No-go rules

V3 must not:

- reuse V2 as acceptance evidence;
- change Gemini request shape back to multi-instance prompts;
- switch to Batch API for final acceptance;
- switch from Interactions API to `generateContent` merely for throughput;
- add a fabricated Gemini confidence score;
- tune a threshold on calibration;
- alter Gemini prompt/schema after calibration starts;
- benchmark 512d/1024d embeddings again without new retrieval evidence;
- replace the accepted Qwen embedding/reranker merely to improve acceptance numbers;
- lower the `0.95` precision target or `0.95` confidence level;
- lower the overall `0.40` or per-language `0.25` release-recall floors;
- weaken canonical historical/forgotten/local-only/secret/untrusted filtering;
- inspect validation and then rerun the same V3 as fresh evidence;
- authorize Phase 4.5E before final V3 acceptance and durable closure evidence.

## 13. Post-V3 operational limitation

Even a successful synthetic V3 cannot establish permanent exchangeability with future owner traffic or guarantee immunity to cloud-model drift.

After eventual production wiring, Step 4 must retain shadow-labelled operational monitoring and must treat material Gemini model/API behavior changes as reasons to revalidate the release gate.

## 14. V3 authorization boundary

The completed 39/39 exposed development diagnostics authorize **implementation of this fresh V3 acceptance method**.

They do not themselves complete Phase 4.5D.

Phase 4.5E remains blocked until V3 passes every gate above and the result is recorded on a clean exact owner-run SHA.
