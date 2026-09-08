# Step 4 Phase 4.5D — Multilingual Zero-Shot Answer-Type Diagnostic Method

## Status

**FROZEN DEVELOPMENT-ONLY METHOD. NOT ACCEPTANCE EVIDENCE. PHASE 4.5E REMAINS BLOCKED.**

This diagnostic is frozen after the NLI-as-answerability experiment failed and before any zero-shot answer-type score is observed.

## Why this diagnostic exists

The structured-query planner diagnostic showed that deterministic lifecycle/security and exact-facet lookup are directionally correct, but six ordinary-semantic queries were incorrectly released because the interpreter recognized a valid subject/relation while misunderstanding **what kind of answer the user requested**.

The demonstrated false-release classes were:

- `near_miss`: asks **why** the recorded value was chosen;
- `unsupported_source`: asks **who** recommended/provided the value;
- `negation`: asks which value **replaced** a rejected value;
- `adversarial_lexical`: asks for a **related record** such as an approval ticket.

The NLI release-guard diagnostic then showed that a meta-level answerability hypothesis is the wrong formulation: it classified all ten correct releases as neutral/contradiction and retained none.

The next mature task formulation is therefore multilingual **zero-shot classification of the question's requested answer type**.

The pinned model `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` is explicitly published for multilingual zero-shot classification in addition to NLI. Reusing the already-downloaded model avoids adding another dependency or cloud provider.

## Architecture role

This experiment does **not** create another JARVIS brain.

Production remains governed by the single provider selector:

```text
JARVIS_AI_PROVIDER -> JarvisConfig.ai_provider
```

If answer-type classification proves useful, it is a local deterministic/veto-support component under `MemoryEvidenceGate`, analogous to other local specialist models. It may only prevent a release. It may never:

- create a canonical fact;
- select a different memory;
- revive historical/forgotten memory;
- widen source/sensitivity eligibility;
- modify the active brain/provider;
- authorize Phase 4.5E by itself.

## Frozen model

- model: `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`
- revision: `b5113eb38ab63efdd7f280f8c144ea8b13f978ce`
- local inference only;
- `trust_remote_code=False`;
- safetensors only;
- max length: `256`;
- one model load;
- no Gemini calls;
- no Qwen calls;
- no fitted threshold.

## Frozen zero-shot formulation

For each user query, score the following seven mutually exclusive candidate answer types with the standard NLI zero-shot pattern.

Machine keys and frozen natural-language descriptions:

1. `current_value`
   - `the current recorded value of a known property`
2. `current_value_comparison`
   - `whether a supplied value matches the current recorded value of a known property`
3. `reason_explanation`
   - `the reason why a recorded value was chosen or used`
4. `provenance_actor`
   - `who recommended, supplied, selected, or originated a recorded value`
5. `replacement_successor`
   - `the value that replaced a rejected, previous, or superseded value`
6. `related_record`
   - `a separate related record or linked object rather than the recorded property value itself`
7. `other_or_advice`
   - `advice, another preference, or information not represented by the recorded property value itself`

Frozen hypothesis template:

```text
This question asks for {candidate_description}.
```

For every query/candidate pair:

- premise = exact exposed user query text;
- hypothesis = frozen template above;
- obtain the model's entailment logit;
- softmax the seven entailment logits across candidate answer types;
- top probability wins;
- no probability threshold is fitted or applied.

This follows the model's published zero-shot classification use rather than the failed meta-answerability use.

## Frozen case selection: 30 exposed semantic-current queries

Reuse the exact 45-case selection rule from `STEP_4_PHASE_4_5D_STRUCTURED_QUERY_PLANNER_DIAGNOSTIC_METHOD.md`, then exclude only the five deterministic security/lifecycle categories:

- historical;
- forgotten;
- local_only;
- secret;
- untrusted.

No query text is edited.

The remaining set is exactly 30 cases:

### Allow targets: 12

- 9 direct/cross-lingual current-value queries -> expected `current_value`;
- 3 `relation_mismatch` comparison queries -> expected `current_value_comparison`.

For release-policy purposes, either of these two top labels is an **ALLOW answer type**.

### Veto targets: 18

Three languages each for six categories:

- `near_miss` -> expected `reason_explanation`;
- `unsupported_source` -> expected `provenance_actor`;
- `negation` -> expected `replacement_successor`;
- `adversarial_lexical` -> expected `related_record`;
- `absent` -> expected `related_record`;
- `ambiguous` -> expected `other_or_advice`.

Any top label other than `current_value` or `current_value_comparison` is a **VETO answer type**.

The primary safety metric is allow/veto behavior. Exact seven-way class accuracy is diagnostic only.

## Persisted evidence

Persist per case:

- case ID;
- language;
- source category;
- expected answer-type key;
- expected allow/veto disposition;
- top answer-type key;
- top probability;
- all seven zero-shot probabilities;
- final local answer-type allow/veto decision;
- whether exact answer type matched.

Do not persist query text or canonical memory values.

## Frozen continuation gates

This remains development evidence only. It is promising enough for architecture review only if all of the following hold:

1. zero false ALLOW decisions across all 18 veto-target queries;
2. at least `10/12` allow-target queries receive an ALLOW answer type;
3. at least `8/9` direct current-value queries receive ALLOW;
4. all `3/3` relation-comparison queries receive ALLOW;
5. each language receives ALLOW on at least `3/4` of its allow-target queries;
6. zero Gemini calls;
7. zero Qwen calls;
8. no threshold fitting;
9. the classifier remains veto-only with respect to memory release authority.

Do not lower these gates after observing the result.

## Interpretation

### If all continuation gates pass

The answer-type guard becomes a development candidate to compose with:

```text
provider-neutral MemoryQueryInterpreter proposal
-> deterministic grounding
-> deterministic eligible facet validation
-> local answer-type veto
-> exact eligible-current facet lookup
-> TrustedMemoryEvidence or ABSTAIN
```

A larger retired development review may then be designed before any fresh acceptance corpus.

### If false ALLOW decisions remain

Do not tune probability thresholds on the exposed 30 rows. Inspect which answer types are confused and research a more explicit typed semantic-parser/query-algebra approach.

### If recall collapses

Reject the local zero-shot guard. Do not retain it merely because it blocks false releases.

## Non-goals

This diagnostic does not:

- re-run Gemini;
- compare brain providers;
- change `JARVIS_AI_PROVIDER`;
- invoke Qwen retrieval/reranking;
- alter canonical security/lifecycle policy;
- reuse untouched V3 validation;
- constitute acceptance evidence;
- authorize Phase 4.5E.
