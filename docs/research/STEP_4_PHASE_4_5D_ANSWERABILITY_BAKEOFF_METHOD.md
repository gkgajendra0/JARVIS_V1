# Step 4 Phase 4.5D — Answerability Component Bake-Off V1

## Status

**FROZEN DEVELOPMENT METHOD — ZERO-TRAINING MATURE-COMPONENT SCREEN, NOT ACCEPTANCE**

Phase 4.5D remains active. Phase 4.5E remains blocked.

This method replaces the unexecuted custom eight-class fine-tune V3. It was frozen before any owner model result existed.

### Pre-scoring Transformers v5 compatibility amendment

The first owner launch at repository SHA `f488a1b26a13f00ef78ba3239f919da77c47438a` stopped before the first QA case was scored because Transformers `5.16.1` no longer registers the legacy text `question-answering` pipeline. The environment, frozen corpus hash, first model revision, Safetensors load and CUDA path all succeeded; no output evidence file was written. Therefore the V1 corpus remains unexposed to model results.

Research confirmed that Transformers v5 still supports `AutoModelForQuestionAnswering` and native `start_logits` / `end_logits` inference. V1 is amended only at the execution-adapter layer: the removed convenience pipeline is replaced with a JARVIS-local deterministic adapter over those native logits. Corpus, candidate checkpoints, gates, tie-breaks, languages and no-threshold rule are unchanged.

## Decision being tested

The release boundary is reframed from query-only intent classification to evidence sufficiency:

> Given an already-eligible canonical memory fact and the user's question, can a mature local model identify supported evidence or correctly abstain?

The experiment has two separate native-task lanes because open-value questions and boolean comparisons are different established NLP tasks.

### Lane A — extractive QA with no-answer

Input:

- raw user question;
- one deterministic canonical-memory sentence containing the current subject, relation and value.

Output:

- exact evidence span when the fact answers the question;
- empty/no-answer when the fact is insufficient.

Transformers v5 native `AutoModelForQuestionAnswering` logits are used directly. Valid context spans compete with the tokenizer CLS/no-answer position. The decision compares `start_logit + end_logit` for CLS against the best valid context span; because the same start/end softmax denominators apply to every candidate, this preserves the native SQuAD-2 ranking without introducing a fitted threshold.

### Lane B — native multilingual NLI

Input:

- canonical memory as the premise;
- a structured comparison proposition as the hypothesis.

Output:

- `entailment` ~= YES;
- `contradiction` ~= NO;
- `neutral` ~= IDK / abstain.

This reuses the exact mDeBERTa checkpoint that JARVIS previously used as a zero-shot query-intent classifier, but exercises it in its native NLI task instead. The previous zero-shot use remains retired; this is a materially different input/output contract.

## Why these are mature components rather than another custom model

The research basis is established QA/NLI behavior:

- SQuAD 2.0 formalized answerable vs unanswerable extractive QA;
- Read + Verify separated answer extraction from verification;
- TyDi QA minimal answers include answer spans plus YES/NO/NULL behavior;
- GAAMA/PrimeQA use boolean answer classification with a no-answer state;
- native NLI directly exposes entailment / contradiction / neutral.

No model in this bake-off is trained or fine-tuned by JARVIS.

Research references:

- https://aclanthology.org/P18-2124/
- https://ojs.aaai.org/index.php/AAAI/article/view/4619
- https://aclanthology.org/2020.tacl-1.30/
- https://aclanthology.org/2022.naacl-main.79/
- https://arxiv.org/abs/2206.08441
- https://huggingface.co/docs/transformers/main/tasks/question_answering
- https://github.com/huggingface/course/issues/1211
- https://huggingface.co/deepset/xlm-roberta-base-squad2
- https://huggingface.co/timpal0l/mdeberta-v3-base-squad2
- https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7

## Fresh frozen corpus

Generator:

- `tools/research/step4_phase45d_answerability_cases.py`.

Frozen deterministic payload SHA-256:

`3e2bd6830df3d08b3ea4ce8e045ee78cf562c228c5b0d2e5e094ffa42b6b44a3`

Shape:

- 8 completely new synthetic canonical facts;
- English, Hindi and Hinglish;
- 288 extractive-QA cases;
- 96 QA answerable cases;
- 192 QA no-answer cases;
- 96 NLI cases;
- total component cases: 384.

The harness checks zero exact normalized question overlap against:

- retired V4 final composite acceptance queries;
- exposed Method V2 task-specific guard train + holdout queries.

Neither retired corpus is used for training or scoring.

### QA answerable families

Four independent direct-current paraphrase families per fact/language. Every answerable QA case expects the exact current canonical value as the evidence span.

### QA no-answer families

The current fact is intentionally insufficient for:

- reason/explanation;
- provenance/actor;
- replacement/successor timing;
- separate related record;
- advice;
- previous/historical value;
- wrong relation;
- wrong subject.

A non-empty answer on any of these cases is an unauthorized evidence release.

### NLI families

Per fact/language:

- true current-value proposition -> entailment;
- false alternative-value proposition -> contradiction;
- unrelated relation proposition -> neutral;
- negation of the true current value -> contradiction.

The `question` field is retained for human traceability. The component benchmark scores the frozen `premise` + `hypothesis` pair because proposition extraction/planning is a separate integration problem.

## Canonical context contract

The experiment does not feed arbitrary provider prose to the models. Each case uses a deterministic natural rendering of the structured canonical subject, relation and current value.

This mirrors the existing canonical assertion schema, which already owns `subject`, `predicate`, `value` and `normalized_text`. If this architecture survives component selection, production will use a JARVIS-owned renderer over structured canonical fields rather than allowing the provider to establish the evidence text.

## Lane A candidates

### A1 — XLM-R SQuAD 2.0

- model: `deepset/xlm-roberta-base-squad2`;
- revision: `a5fab9908c8d856e8c583fd41ba6d92444e46477`;
- task: extractive QA with SQuAD-2 no-answer behavior;
- multilingual XLM-R backbone;
- Safetensors required;
- `trust_remote_code=False`.

### A2 — multilingual DeBERTa SQuAD 2.0

- model: `timpal0l/mdeberta-v3-base-squad2`;
- revision: `08d6e89c7a6557f967db2e1021f7f640483400ed`;
- task: extractive QA with SQuAD-2 no-answer behavior;
- 94-language mDeBERTa backbone;
- Safetensors required;
- `trust_remote_code=False`.

Both run in ordinary FP32, one at a time on the owner CUDA path. No quantization or precision-specific tuning is introduced in model selection.

Frozen QA inference contract:

```text
adapter = transformers_v5_native_qa_logits
null candidate = CLS start_logit + end_logit
span candidate = best valid context start_logit + end_logit
null wins only when strictly greater
max_sequence_length = 256
max_answer_length = 16
fitted probability threshold = none
trust_remote_code = false
weights = safetensors only
```

Answer comparison only applies Unicode normalization, case-folding, whitespace trimming and boundary punctuation stripping. It does not fuzzy-match, stem or semantically rescue a wrong span.

## Lane B candidate

### B1 — existing pinned mDeBERTa native NLI

- model: `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`;
- revision: `b5113eb38ab63efdd7f280f8c144ea8b13f978ce`;
- labels frozen by model config: entailment / neutral / contradiction;
- decision: argmax only;
- batch size: 32;
- max length: 256;
- fitted probability threshold: none;
- Safetensors required;
- `trust_remote_code=False`.

This checkpoint is already pinned in the repository, so the experiment does not introduce another NLI family before testing the mature native task we already possess.

## Dedicated dependency contract

Optional group:

`phase45d-answerability`

Development-only dependencies:

- Transformers `5.16.1` — existing accepted JARVIS version;
- SentencePiece `0.2.2` — tokenizer runtime required by the selected multilingual families;
- psutil `7.2.2` — resource diagnostics.

The owner Torch `2.13.0+cu132` / Torchvision `0.28.0+cu132` contract remains unchanged and is not reinstalled by this group.

No `datasets`, `accelerate`, SetFit or task-specific training stack is required.

## Frozen QA development gates

A QA candidate must satisfy all simultaneously:

1. zero unauthorized non-empty releases on all no-answer cases;
2. zero wrong non-empty evidence spans on answerable cases;
3. overall exact answerable evidence recall >= `0.90`;
4. English, Hindi and Hinglish answerable evidence recall each >= `0.85`;
5. native no-answer decision only — no JARVIS-fitted threshold;
6. zero cloud/provider calls.

A wrong evidence span is unsafe even if it came from the same canonical sentence.

## Frozen NLI development gates

The native NLI candidate must satisfy all simultaneously:

1. zero entailment/contradiction releases on neutral/unknown cases;
2. zero wrong boolean verdicts on answerable comparisons;
3. exact comparison recall across entailment/contradiction targets >= `0.90`;
4. English, Hindi and Hinglish comparison recall each >= `0.85`;
5. argmax only — no probability threshold;
6. zero cloud/provider calls.

Predicting `neutral` on an answerable comparison is a false veto, not an unsafe release. Predicting the opposite boolean label is an unsafe wrong verdict.

## Frozen QA tie-break

Only QA candidates passing every gate are selectable. Tie-break order:

1. fewer unauthorized releases;
2. fewer wrong-evidence releases;
3. higher answerable recall;
4. higher minimum language recall;
5. lower inference milliseconds/case;
6. lower CUDA peak delta.

## Measurements

Each model run records:

- semantic safety/recall metrics;
- per-language and per-family metrics;
- false-veto and unsafe case IDs;
- model load time;
- inference time and ms/case;
- parameter count/bytes;
- sampled process RSS;
- CUDA baseline/peak/delta;
- exact model ID and revision;
- Torch / Transformers / GPU environment.

Models load sequentially and are released between runs.

## Result handling

Output:

`.step4-phase45d-answerability-bakeoff-v1.json`

The harness refuses to overwrite an existing result.

A composite development pass requires:

- at least one QA candidate to pass and win the frozen QA tie-break;
- the native NLI lane to pass all frozen NLI gates.

Even a composite development pass does **not** authorize a production change or fresh final acceptance yet. It authorizes the next development step only:

1. freeze the selected mature components and exact contracts;
2. extend the provider-independent query proposal/policy so boolean propositions and polarity can be represented without granting the provider release authority;
3. implement JARVIS-owned canonical evidence rendering and answer composition behind the existing authority boundary;
4. benchmark a separate output-grounding rail if Gemini phrasing remains in the factual path;
5. create a completely fresh final acceptance corpus only after the complete implementation contract is frozen.

If either lane fails, retire this exposed corpus and diagnose the failure class. Do not tune thresholds, rewrite the exposed cases or train on them and call the rerun the same evidence.
