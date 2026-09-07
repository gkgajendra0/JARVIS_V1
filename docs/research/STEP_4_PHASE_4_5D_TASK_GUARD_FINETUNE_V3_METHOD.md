# Step 4 Phase 4.5D — Task-Guard Fine-Tune V3 Method

## Status

**FROZEN DEVELOPMENT METHOD V3 — END-TO-END LOCAL CLASSIFIER MODEL SELECTION, NOT ACCEPTANCE**

Phase 4.5D remains active. Phase 4.5E remains blocked.

This method was frozen only after Method V2 completed and failed every candidate. Method V2 is exposed/retired and is not training or scoring data for V3.

## Why V3 exists

Method V2 tested four frozen multilingual embedding bodies plus the same fixed LogisticRegression head. Every candidate produced multiple false allows (`9` to `14`), comparison recall stayed between `0.625` and `0.75`, and the best eight-class macro-F1 was `0.809516`.

That result rejects the **frozen-encoder linear-probe** architecture for this release boundary. It does not justify threshold tuning or another embedding-only bake-off.

The next architecture must make the semantic encoder itself task-specific.

## Research basis

Two mature paths were reviewed after the V2 failure.

### Proper SetFit semantics

Current SetFit documentation describes a two-stage method:

1. fine-tune the SentenceTransformer body with contrastive learning;
2. train a lightweight classification head over the resulting embeddings.

Method V2 intentionally performed only the second idea: the embedding bodies remained frozen. Therefore Method V2 was not full SetFit training.

The SetFit package itself is still not introduced into JARVIS because its open Transformers-5 compatibility issue remains unresolved for the current published package line. JARVIS keeps the accepted Transformers `5.16.1` environment rather than downgrading it for SetFit.

### Direct multilingual sequence classification

The guard is fundamentally a short-text classification task, so direct supervised encoder fine-tuning is more task-aligned than forcing a retrieval embedding model to stay frozen.

`jhu-clsp/mmBERT` is the selected modern primary family for this experiment:

- modern multilingual encoder architecture;
- trained on 3T+ tokens;
- 1800+ language coverage;
- model authors report improved classification performance over XLM-R;
- small model: about 140M parameters;
- base model: about 307M parameters;
- standard Hugging Face Transformers fine-tuning path.

`FacebookAI/xlm-roberta-base` remains the established multilingual encoder baseline so the experiment does not assume the newer family must win.

All selected immutable revisions expose safetensors weights, and V3 requires `use_safetensors=True` plus `trust_remote_code=False`.

Research references:

- https://huggingface.co/docs/setfit/index
- https://huggingface.co/blog/setfit
- https://github.com/huggingface/setfit/issues/629
- https://huggingface.co/jhu-clsp/mmBERT-small
- https://huggingface.co/jhu-clsp/mmBERT-base
- https://huggingface.co/FacebookAI/xlm-roberta-base
- https://huggingface.co/docs/transformers/main/training
- https://huggingface.co/docs/transformers/main_classes/trainer
- https://huggingface.co/docs/transformers/v5.16.0/accelerate
- https://pypi.org/project/datasets/5.0.1/
- https://pypi.org/project/accelerate/1.14.0/

## Architecture under evaluation

```text
query
→ immutable multilingual pretrained encoder
→ end-to-end supervised fine-tuning on fresh eight-class JARVIS corpus
→ model-native sequence-classification head
→ argmax eight-class prediction
→ ALLOW only current_value/current_value_comparison
→ existing deterministic JARVIS grounding / lifecycle / security / exact lookup
```

The classifier remains veto-only. It cannot create canonical truth, bypass eligibility, resurrect forgotten memory, or establish that a retrieved value is true.

## Taxonomy

V3 deliberately preserves the Method V2 eight-class taxonomy so this experiment isolates the representation/training architecture rather than changing both taxonomy and model simultaneously:

1. `current_value`;
2. `current_value_comparison`;
3. `reason_explanation`;
4. `provenance_actor`;
5. `replacement_successor`;
6. `related_record`;
7. `negated_or_contradicted`;
8. `other_or_advice`.

Only the first two classes are release-eligible.

## Fresh development corpus

V3 uses a completely new synthetic corpus:

- English, Hindi, Hinglish;
- eight labels;
- `384` train cases;
- `192` never-trained-on holdout cases;
- exact class/language balance;
- 16 train facts and 8 disjoint holdout facts;
- rotating train paraphrase templates;
- separate holdout paraphrase templates;
- zero normalized train/holdout query overlap;
- zero exact normalized overlap with retired V4;
- zero exact normalized overlap with all exposed Method V2 train and holdout queries.

Frozen corpus source:

- file: `tools/research/step4_phase45d_task_guard_finetune_v3_cases.py`;
- Git blob SHA: `77f614d34b94e44277f4bf4bdaffa5da22989268`.

The harness recomputes the Git blob identity before loading any model. It also records the deterministic payload SHA-256 in the result JSON.

Retired corpora are deny-lists only. Their labels/results are not V3 training or scoring data.

## Candidates

### A — mmBERT small

- model: `jhu-clsp/mmBERT-small`;
- revision: `0eb3d056ec1d6333cf4e19b0966dfde342a41a3a`;
- family: ModernBERT/mmBERT;
- approximately 140M parameters;
- immutable revision includes safetensors weights.

### B — mmBERT base

- model: `jhu-clsp/mmBERT-base`;
- revision: `eaee9e8f76c40fd045034538248ad9d59f380aac`;
- family: ModernBERT/mmBERT;
- approximately 307M parameters;
- immutable revision includes safetensors weights.

### C — XLM-R base

- model: `FacebookAI/xlm-roberta-base`;
- revision: `42f548f32366559214515ec137cdd16002968bf6`;
- family: XLM-R;
- established massively multilingual baseline;
- immutable revision adds safetensors weights.

No generic zero-shot NLI model, retrieval embedding model, Gemini call, or OpenAI call is part of this bake-off.

## Frozen training configuration

Every candidate uses the same training contract:

```text
task = 8-class sequence classification
max_length = 128
epochs = 5
per-device train batch = 8
gradient accumulation = 2
effective batch = 16
learning rate = 2e-5
weight decay = 0.01
warmup ratio = 0.10
scheduler = linear
BF16 = true
FP16 = false
TF32 = false
gradient checkpointing = true
seed = 45
data seed = 45
training-time holdout evaluation = none
early stopping = none
hyperparameter search = none
probability threshold = none
release decision = argmax class only
```

The holdout is evaluated exactly once after fixed training completes. It is not used for checkpoint selection, early stopping, learning-rate choice, epoch choice, or threshold fitting.

## Dependency contract

New development-only optional dependency set:

`phase45d-task-guard-finetune`

Pinned additions:

- Transformers `5.16.1` — already accepted in JARVIS;
- Datasets `5.0.1`;
- Accelerate `1.14.0`;
- scikit-learn `1.9.0` for metrics;
- psutil `7.2.2` for resource diagnostics.

The owner Torch `2.13.0+cu132` / Torchvision `0.28.0+cu132` contract is not changed or reinstalled by this optional set.

## Frozen measurements

For each candidate V3 records:

- false allows;
- false vetoes;
- negation false allows;
- overall allow recall;
- direct-current allow recall;
- current-value-comparison allow recall;
- English/Hindi/Hinglish allow recall;
- per-label exact recall;
- eight-class accuracy and macro-F1;
- training time;
- inference milliseconds/query;
- model load time;
- parameter count and parameter bytes;
- sampled process RSS;
- per-candidate CUDA peak allocation.

Only a candidate passing every semantic gate is saved locally as a candidate artifact. Failed candidate weights are not retained by the harness. If multiple models pass, only the selected winner remains in the local artifact directory.

## Frozen development gates

A candidate must satisfy all simultaneously:

1. zero false allows across all veto targets;
2. zero negation false allows;
3. overall allow recall >= `0.90`;
4. direct-current allow recall >= `0.90`;
5. comparison allow recall >= `0.85`;
6. English, Hindi and Hinglish allow recall each >= `0.85`;
7. eight-class macro-F1 >= `0.85`;
8. argmax only, no probability threshold;
9. zero cloud/provider calls;
10. retired V4 and Method V2 corpora are not used for training or scoring.

These remain development gates, not final acceptance gates.

## Frozen tie-break

Only passing candidates are selectable. Tie-break order:

1. fewer false allows;
2. fewer negation false allows;
3. higher comparison allow recall;
4. higher overall allow recall;
5. higher macro-F1;
6. lower inference milliseconds/query;
7. fewer parameter bytes.

Because passing already requires zero false allows and zero negation false allows, the first two rules preserve the safety-first contract explicitly.

## Result handling

If no candidate passes, V3 is retired and no production guard change is authorized. Do not tune V3's exposed holdout.

If a candidate passes:

1. keep the exact saved winner artifact from the owner bake-off;
2. record its model/revision, tokenizer/config, safetensors checksums, training corpus source blob, payload SHA-256, dependency versions, repository SHA and result JSON;
3. implement it behind the existing `MemoryAnswerTypeGuard` protocol;
4. remove dead generic NLI production code only after compatibility tests;
5. create a completely fresh provider-independent final acceptance corpus;
6. pass that fresh acceptance before closing Phase 4.5D;
7. only then unblock 4.5E.

A V3 development pass alone never authorizes semantic retrieval into the Gemini conversation.
