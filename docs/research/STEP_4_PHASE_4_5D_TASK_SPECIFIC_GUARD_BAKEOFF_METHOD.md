# Step 4 Phase 4.5D — Task-Specific Local Guard Bake-Off Method

## Status

**FROZEN DEVELOPMENT METHOD — MODEL SELECTION ONLY, NOT ACCEPTANCE**

Phase 4.5E remains blocked.

## Why this bake-off exists

Fresh V4 acceptance isolated the current `LocalZeroShotMemoryAnswerTypeGuard` as the Phase 4.5D blocker. The provider-backed run and a separate zero-cloud deterministic-proposal run both showed severe over-veto of legitimate current-value comparisons. The zero-cloud run also exposed one Hinglish negation false release.

The existing guard uses a generic multilingual NLI model as a seven-way zero-shot classifier. That was useful as a development probe, but it is not sufficiently task-specific for a memory release boundary.

Current research supports the SetFit pattern for small-data text classification:

- a SentenceTransformer embedding body;
- a lightweight classification head;
- scikit-learn Logistic Regression is SetFit's recommended/default head;
- the approach is prompt-free and supports multilingual classification.

We intentionally do **not** add the SetFit package to the owner environment for this bake-off. JARVIS already pins `sentence-transformers==6.0.1`, `transformers==5.16.1`, and the owner environment has `scikit-learn==1.9.0`. Reusing those mature components avoids introducing another dependency into a deliberately frozen Torch/Transformers environment.

Research references:

- https://huggingface.co/docs/setfit/how_to/classification_heads
- https://huggingface.co/docs/setfit/en/conceptual_guides/setfit
- https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
- https://huggingface.co/intfloat/multilingual-e5-small
- https://huggingface.co/sentence-transformers/paraphrase-multilingual-mpnet-base-v2

## Architecture under evaluation

```text
query
→ frozen multilingual SentenceTransformer
→ normalized sentence embedding
→ fixed scikit-learn LogisticRegression
→ argmax answer-type class
→ ALLOW only current_value/current_value_comparison
→ existing deterministic JARVIS grounding / policy / lifecycle / exact lookup
```

This bake-off evaluates only the classifier boundary. It makes zero Gemini/OpenAI calls and does not modify canonical memory truth.

## New taxonomy

Eight classes are frozen before the bake-off:

1. `current_value`
2. `current_value_comparison`
3. `reason_explanation`
4. `provenance_actor`
5. `replacement_successor`
6. `related_record`
7. `negated_or_contradicted`
8. `other_or_advice`

Release-eligible semantic classes are only:

- `current_value`
- `current_value_comparison`

All other classes are vetoes.

Negation is now explicit because fresh V4 produced one Hinglish negation false release. This is an architectural class change, not a threshold fit.

## Development corpus

The bake-off uses a completely new synthetic corpus:

- 3 languages: English, Hindi, Hinglish;
- 8 labels;
- 288 train cases;
- 192 holdout cases;
- train and holdout use disjoint facts/subjects;
- train and holdout use disjoint paraphrase templates;
- each fact appears across every class so the classifier cannot solve the task by memorizing a subject/value;
- class/language balance is exact;
- no exact normalized query overlap between train and holdout;
- no exact normalized query overlap with retired V4.

Frozen corpus SHA-256:

`ae854ed664ef6ee0214f65f5fe4b252099fd1dcaea00c13aaf7789cd84afd3ab`

Retired V4 is used only as a deny-list for exact-query overlap. V4 labels/results are not training or scoring data.

## Candidates

All candidates use their immutable model revision and the exact same downstream classifier.

### A — multilingual MiniLM

- model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- revision: `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`
- embedding dimension: 384
- ~118M parameters
- multilingual, including Hindi

### B — multilingual E5 small

- model: `intfloat/multilingual-e5-small`
- revision: `fd1525a9fd15316a2d503bf26ab031a61d056e98`
- embedding dimension: 384
- multilingual model card currently tags 94 languages

### C — multilingual MPNet

- model: `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`
- revision: `4328cf26390c98c5e3c738b4460a05b95f4911f5`
- embedding dimension: 768
- ~0.3B parameters
- heavier quality-ceiling candidate

No candidate-specific prompt engineering is allowed. Raw query text is encoded for every candidate.

## Frozen classifier configuration

Every candidate uses:

```text
sklearn.linear_model.LogisticRegression
solver = lbfgs
C = 1.0
max_iter = 2000
random_state = 45
class_weight = none
probability threshold = none
decision = argmax predict()
```

No hyperparameter search and no threshold fitting are allowed.

## Frozen development continuation gates

A candidate is eligible for architecture review only if all are true on the never-trained-on holdout:

1. zero false allows across all veto targets;
2. zero negation false allows;
3. overall allow recall >= `0.90`;
4. direct-current allow recall >= `0.90`;
5. comparison allow recall >= `0.85`;
6. English, Hindi, and Hinglish allow recall each >= `0.85`;
7. eight-class macro-F1 >= `0.85`;
8. argmax-only decision; no probability threshold;
9. zero cloud/provider calls;
10. V4 is not used for training or scoring.

These are development gates, not acceptance gates.

## Candidate selection

Only candidates passing every development gate are selectable. Tie-breaking is frozen in this order:

1. fewer false allows;
2. fewer negation false allows;
3. higher comparison allow recall;
4. higher overall allow recall;
5. higher macro-F1;
6. lower holdout embedding latency.

If no candidate passes, no production guard change is authorized.

## After a candidate is selected

A development winner does **not** close Phase 4.5D.

Next steps are:

1. freeze the selected embedding model/revision;
2. freeze the trained classifier artifact/coefficients, class order, training-corpus hash, scikit-learn version, and artifact checksum;
3. replace the generic NLI production guard cleanly with the selected task-specific guard;
4. remove/retire dead NLI production code after compatibility tests;
5. create a completely fresh, never-exposed V5 provider-independent acceptance corpus;
6. pass V5 and record a green closure SHA;
7. only then mark Phase 4.5D complete and unblock 4.5E.

Provider-adapter natural-language conformance remains a separate, small bounded integration test. It does not own canonical memory truth.
