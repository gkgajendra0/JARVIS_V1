# Step 4 Phase 4.5D — Multilingual NLI Release-Guard Development Diagnostic Method

## Status

**Frozen development-only method. Not acceptance evidence. Does not authorize Phase 4.5E.**

This diagnostic follows the failed 45-case structured-query planner development run. It reuses only already-exposed/retired V2 development evidence and therefore cannot become fresh V3 acceptance evidence.

## Why this diagnostic exists

The structured exact-facet architecture retained deterministic security boundaries and eliminated free-text top-k retrieval from ordinary exact current fact lookup, but Gemini alone produced six ordinary-semantic false releases.

Those false releases were concentrated in Hindi/Hinglish question-focus errors:

- asking **why** a value was chosen;
- asking for an **approval ticket** created after setting a value;
- asking which value **replaced** a rejected value;
- asking **who recommended** a value.

The selected canonical facet was related to the query, but the requested answer was not the canonical value itself.

The next experiment therefore tests a question-focus guard, not another document relevance verifier.

## Research basis

Selected mature candidate:

- model: `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`
- immutable revision: `b5113eb38ab63efdd7f280f8c144ea8b13f978ce`
- architecture: mDeBERTa-v3-base / DeBERTaV2 sequence classification
- task: multilingual natural language inference / zero-shot classification
- parameters: about 0.3B
- safetensors weights: about 558 MB
- license: MIT

The model card states that the model supports NLI over 100 pretraining languages and was fine-tuned on XNLI plus the multilingual-NLI-26lang-2mil7 corpus. Hindi is explicitly present in the NLI fine-tuning data. The multilingual training also includes mixed-language premise/hypothesis pairs, including English hypotheses paired with non-English premises, which supports using one fixed English policy hypothesis against Hindi queries.

The model card documents label order:

```text
0 = entailment
1 = neutral
2 = contradiction
```

References:

- https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7
- https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7/tree/main
- https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7/commit/b5113eb38ab63efdd7f280f8c144ea8b13f978ce

## Why MuRIL is not the first implementation

Google MuRIL is specifically pretrained on 17 Indian languages and their transliterated counterparts, so it is relevant to Hinglish. However, the released `google/muril-base-cased` artifact is a pretrained base encoder, not a ready-made NLI classifier for this question-focus task.

Using MuRIL here would require custom supervised fine-tuning and a new labeled dataset. Research-first policy therefore evaluates the mature ready-made multilingual NLI classifier first.

Reference:

- https://huggingface.co/google/muril-base-cased

## Frozen source artifact

Input artifact:

```text
.step4-phase45d-v2-structured-query-planner-diagnostic-v1.json
```

Required source status:

```text
DEVELOPMENT_STRUCTURED_QUERY_PLANNER_DIAGNOSTIC_COMPLETE
```

Required frozen source summary:

- cases: 45
- released cases: 16
- exact true releases: 10
- false/wrong releases: 6
- target release cases: 12
- target abstain cases: 33

The diagnostic must fail closed if these source counts do not match. It must not overwrite its output.

## Frozen evaluated population

Evaluate **only the 16 rows already released** by the current structured planner/evidence path.

This is intentional:

- an NLI release guard may only veto an otherwise releasable exact-facet plan;
- it may not rescue an abstained query;
- it may not choose another facet;
- it may not create canonical truth;
- it may not change security eligibility.

The 16 source releases consist of:

- 10 correct exact canonical releases;
- 6 demonstrated ordinary-semantic false releases.

The two current target-release false negatives remain untouched by this diagnostic and are a separate recall problem.

## Query reconstruction

The source artifact does not persist user query text. For each selected case ID, reconstruct the exact exposed V2 query transiently from:

```text
tools/research/step4_phase45d_final_v2_cases.py
```

The query is used only in memory for NLI inference and must not be persisted to the result artifact.

## Selected facet policy hypothesis

For each source release, use the already-proposed canonical `subject` and `predicate` from the structured planner artifact.

Map the synthetic predicate to its stable English relation surface using the frozen V2 `CurrentFact` metadata. No canonical memory value is needed or exposed.

Use exactly one fixed English hypothesis template:

```text
The user's question can be answered solely by the current recorded {relation} for {subject}.
```

Examples:

- direct current-value lookup -> should entail;
- current-value relation comparison -> should entail;
- why chosen -> should be neutral or contradiction;
- who recommended -> should be neutral or contradiction;
- which value replaced a rejected value -> should be neutral or contradiction;
- which approval ticket was created -> should be neutral or contradiction.

The hypothesis template is frozen before observing any NLI output.

## Model execution

Default owner path:

- device: CUDA
- dtype: FP32 for conservative mDeBERTa compatibility
- `model.eval()`
- `torch.inference_mode()`
- tokenizer/model loaded with the pinned immutable revision
- `trust_remote_code=False`
- maximum sequence length: 256
- batch size: 16

Do not change the accepted owner Torch/Torchvision installation.

## Frozen primary guard rule

No threshold is fitted in this diagnostic.

For each of the 16 source releases:

```text
guard_allow = argmax(entailment, neutral, contradiction) == entailment
```

If the top NLI class is neutral or contradiction, the guard would veto that release.

Persist all three raw softmax probabilities so later development analysis can inspect score separation without rerunning the model. Any later threshold policy would require a separately frozen method and cannot turn this exposed V2 run into acceptance evidence.

## What is measured

Report:

- source release rows = 16
- source correct releases = 10
- source false releases = 6
- guarded releases
- retained correct releases
- blocked correct releases
- surviving false releases
- blocked false releases
- guarded precision
- retained-correct recall relative to the 10 currently correct releases
- retained-correct counts by language
- surviving false-release IDs by category/language
- NLI top-label counts by source correctness/category/language
- entailment score distributions for source-correct vs source-false releases
- per-case entailment/neutral/contradiction probabilities

Do not persist:

- query text
- hypothesis text
- canonical memory value
- normalized assertion text
- external evidence text

## Frozen continuation gates

The NLI guard is promising for architecture review only if all are true under the untuned argmax rule:

1. **zero** of the six demonstrated false releases survive;
2. at least **8/10** currently correct releases are retained;
3. English retains at least **3/4** currently correct English releases;
4. Hindi retains at least **2/3** currently correct Hindi releases;
5. Hinglish retains at least **2/3** currently correct Hinglish releases;
6. no query/hypothesis/canonical value is persisted;
7. the guard remains veto-only and does not alter canonical selection/eligibility.

These are development continuation gates, not statistical precision guarantees.

## Interpretation

### Zero surviving false releases with acceptable retention

The NLI guard becomes a promising independent precision component for the structured architecture. The next architecture review must still address the two existing planner recall misses separately before any fresh V3 method is frozen.

### Some false releases survive

Do not tune the exposed V2 cases into a hand-written threshold or keyword list. Inspect raw score separation and failure classes. Research the next mature answer-type/semantic-parser option before changing production behavior.

### Correct releases are heavily blocked

The NLI hypothesis/model pairing is too conservative or not task-matched. Reject it for this role rather than lowering production precision requirements.

## Non-goals

This diagnostic does not:

- rerun Gemini;
- modify the Gemini query-interpreter prompt;
- rerun Qwen;
- fit a threshold;
- train or fine-tune any model;
- modify canonical eligibility/security policy;
- rescue planner abstentions;
- create V3 acceptance evidence;
- wire memory into live voice/context;
- authorize Phase 4.5E.
