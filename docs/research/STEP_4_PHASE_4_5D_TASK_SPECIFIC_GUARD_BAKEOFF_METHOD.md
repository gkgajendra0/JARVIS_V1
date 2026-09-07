# Step 4 Phase 4.5D — Task-Specific Local Guard Bake-Off Method

## Status

**FROZEN DEVELOPMENT METHOD V2 — MODEL SELECTION ONLY, NOT ACCEPTANCE**

Phase 4.5E remains blocked.

Method V2 is a pre-execution correction. The earlier unexecuted draft omitted the already accepted JARVIS Qwen3 embedding backbone and did not record the resource metrics required by the handover. No owner bake-off evidence existed when this correction was made, so adding the required Qwen baseline and resource measurements is not post-result tuning. The corpus, classifier, labels, semantic gates and tie-break rules remain unchanged.

## Why this bake-off exists

Fresh V4 acceptance isolated the current `LocalZeroShotMemoryAnswerTypeGuard` as the Phase 4.5D blocker. The provider-backed run and a separate zero-cloud deterministic-proposal run both showed severe over-veto of legitimate current-value comparisons. The zero-cloud run also exposed one Hinglish negation false release.

The existing guard uses a generic multilingual NLI model as a seven-way zero-shot classifier. That was useful as a development probe, but it is not sufficiently task-specific for a memory release boundary.

Current research supports the SetFit pattern for small-data text classification:

- a SentenceTransformer embedding body;
- a lightweight classification head;
- scikit-learn Logistic Regression is SetFit's recommended/default head;
- the approach supports multilingual classification.

We intentionally do **not** add the SetFit package to the owner environment for this bake-off. JARVIS already pins `sentence-transformers==6.0.1`, `transformers==5.16.1`, and `scikit-learn==1.9.0`. SetFit 1.1.3 still has an open Transformers-5 compatibility issue. Reusing the mature SentenceTransformer + scikit-learn components directly avoids destabilizing the frozen Torch/Transformers environment.

Research also reviewed newer multilingual embedding alternatives. `nomic-ai/nomic-embed-text-v2-moe` and `Alibaba-NLP/gte-multilingual-base` both require `trust_remote_code=True` in their documented SentenceTransformer paths, which conflicts with this bake-off's pinned-code/reproducibility boundary. `google/embeddinggemma-300m` is classification-capable and multilingual, but JARVIS already tested and rejected EmbeddingGemma in the accepted 4.5C retrieval line; this guard iteration therefore prioritizes the already accepted Qwen backbone rather than introducing another model family. None of those exclusions is a permanent claim about model quality.

Research references:

- https://huggingface.co/docs/setfit/how_to/classification_heads
- https://huggingface.co/docs/setfit/en/conceptual_guides/setfit
- https://github.com/huggingface/setfit/issues/629
- https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
- https://huggingface.co/intfloat/multilingual-e5-small
- https://huggingface.co/sentence-transformers/paraphrase-multilingual-mpnet-base-v2
- https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe
- https://huggingface.co/Alibaba-NLP/gte-multilingual-base
- https://huggingface.co/google/embeddinggemma-300m
- https://scikit-learn.org/stable/model_persistence.html

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

All candidates use an immutable model revision and the exact same downstream classifier.

### A — multilingual MiniLM

- model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- revision: `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`
- embedding dimension: 384
- ~118M parameters
- multilingual, including Hindi
- input contract: raw query text
- truncation: none

### B — multilingual E5 small

- model: `intfloat/multilingual-e5-small`
- revision: `fd1525a9fd15316a2d503bf26ab031a61d056e98`
- embedding dimension: 384
- multilingual model card tags 94 languages
- input contract: prefix every classification text with `query: `, because the E5 model card recommends the query prefix when embeddings are used as features for linear-probe classification
- truncation: none

### C — multilingual MPNet

- model: `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`
- revision: `4328cf26390c98c5e3c738b4460a05b95f4911f5`
- embedding dimension: 768
- ~0.3B parameters
- heavier quality-ceiling candidate
- input contract: raw query text
- truncation: none

### D — existing JARVIS Qwen3 reuse baseline

- model: `Qwen/Qwen3-Embedding-0.6B`
- revision: `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`
- embedding dimension: **256**
- ~0.6B parameters
- 100+ languages
- the model card explicitly includes text classification among supported/evaluated tasks
- input contract: raw query text
- truncation: `truncate_dim=256`

Qwen is mandatory in this bake-off because it is already accepted and revision-pinned in JARVIS. The 256d setting deliberately tests the existing JARVIS dimensional contract instead of giving Qwen a new 1024d production shape. Qwen supports Matryoshka/user-defined dimensions from 32 to 1024.

Qwen also supports custom task instructions, but this bake-off does **not** invent a classifier-specific Qwen instruction. Raw `model.encode(sentences)` is an officially supported SentenceTransformer path, and avoiding a custom prompt keeps the comparison prompt-free except where a model-author contract explicitly requires a fixed prefix (E5). If Qwen later needs instruction optimization, that would require a separate fresh development method rather than tuning this holdout.

The only candidate-specific preprocessing allowed is the frozen model-author/deployment contract listed above. No per-result prompt changes, template changes, hyperparameter changes, or threshold fitting are allowed.

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

## Frozen measurements

For every candidate the harness records:

- false allows and false vetoes;
- direct-current and comparison allow recall;
- negation false allows;
- English/Hindi/Hinglish allow recall;
- per-label exact recall;
- accuracy and eight-class macro-F1;
- model load time;
- holdout embedding milliseconds per query;
- embedding dimension;
- parameter count and parameter bytes;
- sampled process RSS at model-load/train/holdout/fit boundaries and candidate-local sampled RSS delta;
- per-candidate `torch.cuda.max_memory_allocated` after resetting CUDA peak statistics.

Resource measurements are diagnostics, not semantic acceptance substitutes. RSS is explicitly labeled sampled rather than claimed as an exact continuous high-water mark.

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

## Production artifact direction after a winner exists

Do not serialize a fitted sklearn estimator with `pickle`/`joblib`. Current scikit-learn guidance states that pickle-based formats can execute arbitrary code when loaded; `skops.io` is safer but would add another runtime dependency and still couples loading to the sklearn environment.

For this specific linear head, the preferred production direction is a simple data-only artifact containing:

- immutable backbone model ID + revision;
- input prefix and truncation dimension;
- embedding dimension;
- ordered class labels;
- `LogisticRegression.coef_` and `intercept_` numeric arrays;
- classifier configuration;
- training corpus SHA-256;
- Python/numpy/scikit-learn versions used to train;
- training code/repository SHA;
- artifact SHA-256.

Inference can reproduce multinomial argmax directly from normalized embeddings and frozen coefficients without unpickling executable Python objects. Exact artifact format and round-trip tests are frozen only after a winner exists; no artifact is created during model selection.

## After a candidate is selected

A development winner does **not** close Phase 4.5D.

Next steps are:

1. freeze the selected embedding model/revision;
2. freeze the trained classifier artifact/coefficients, class order, training-corpus hash, dependency versions, training SHA and artifact checksum;
3. replace the generic NLI production guard cleanly with the selected task-specific guard behind the existing `MemoryAnswerTypeGuard` protocol;
4. remove/retire dead NLI production code after compatibility tests;
5. create a completely fresh, never-exposed V5 provider-independent acceptance corpus;
6. pass V5 and record a green closure SHA;
7. only then mark Phase 4.5D complete and unblock 4.5E.

Provider-adapter natural-language conformance remains a separate, small bounded integration test. It does not own canonical memory truth.
