# Step 4 Phase 4.5D — Answerability Verifier Development Method

## Status

**RESEARCH COMPLETE — DEVELOPMENT-ONLY METHOD FROZEN — NOT ACCEPTANCE**

The V2 acceptance architecture failed. The V2 retrieval-depth diagnostic then showed that the existing Qwen stack reaches 100% positive candidate recall and 100% reranked Top-1 accuracy on all 900 exposed V2 positive cases when the candidate window is widened to ten.

The remaining problem is therefore the release-confidence / answerability decision.

## Research question

For an already-eligible canonical memory selected by the frozen Qwen retrieval/reranking stack, which mature local model most directly answers this question:

> Does the selected memory actually contain enough information to answer the user's memory question, rather than merely being topically relevant?

## Why the mMARCO verifier is retired

The V2 independent verifier used:

`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`

That model is a multilingual query/passage **relevance** CrossEncoder. V2 demonstrated that relevance score was not stable enough for release confidence:

- the frozen learned gate found no MAPIE-valid threshold;
- absolute verifier scores shifted sharply between calibration and validation query wording;
- high-confidence unsafe cases were dominated by relation mismatch / ambiguous semantic-neighbor cases.

This is a task mismatch: generic retrieval relevance is weaker than the required assertion that the selected memory directly answers the question.

## Mature alternatives considered

### Generic rerankers

`BAAI/bge-reranker-v2-m3` is a strong, efficient multilingual reranker. Its model card explicitly describes it as a query/document relevance scorer. This makes it a valid future control, but it addresses substantially the same generic-relevance task that mMARCO failed to turn into a robust release-confidence signal.

Source:

- https://huggingface.co/BAAI/bge-reranker-v2-m3

### Multilingual NLI

`MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` is a strong multilingual entailment classifier trained on MNLI + XNLI. NLI is closer to support/grounding than retrieval relevance and remains a strong fallback.

However, the JARVIS input is naturally a **question + candidate memory**, while NLI expects a declarative premise + hypothesis. Using NLI cleanly would require either a question-to-claim transformation or a second generated answer, adding another transformation/model boundary before the actual support test.

Source:

- https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli

### Multilingual extractive QA with no-answer support — selected first

`deepset/xlm-roberta-base-squad2-distilled` is a multilingual XLM-R extractive question-answering model distilled from Deepset's multilingual XLM-R large QA model and trained on SQuAD 2.0.

SQuAD 2.0 explicitly includes questions for which the supplied context does not contain an answer. That directly matches the JARVIS release question better than a generic relevance scorer:

- input: memory question + selected memory text;
- model decides an answer span versus the no-answer location;
- the answerable-vs-null score difference becomes a direct development signal.

The model is approximately 0.3B parameters and MIT licensed.

Selected immutable revision:

`c1bbfe57bc3335c37960a48c5628ba26d7e9e3b7`

Sources:

- https://huggingface.co/deepset/xlm-roberta-base-squad2-distilled
- https://huggingface.co/deepset/xlm-roberta-base-squad2-distilled/commit/c1bbfe57bc3335c37960a48c5628ba26d7e9e3b7
- https://huggingface.co/docs/transformers/tasks/question_answering

## Development architecture under test

```text
canonical eligibility
 -> FTS5 lexical + Qwen dense
 -> equal-weight RRF
 -> top 10
 -> Qwen3-Reranker-0.6B + frozen JARVIS instruction
 -> selected Top-1 memory
 -> multilingual SQuAD2 answerability verifier
 -> answerability margin / no-answer evidence
```

This is **development-only**. It does not yet replace the production top-3 contract or create a release policy.

## Frozen answerability model for the bake-off

Model:

`deepset/xlm-roberta-base-squad2-distilled`

Revision:

`c1bbfe57bc3335c37960a48c5628ba26d7e9e3b7`

Constraints:

- `trust_remote_code=False`;
- use safetensors when available;
- existing repo `transformers==5.16.1` dependency only;
- owner CUDA path;
- no Torch/Torchvision change;
- max sequence length 384;
- max answer length 30 tokens;
- top 20 start/end indices considered when finding best legal non-null span.

## Score definition

Use the standard SQuAD2-style null-vs-answer comparison.

For each question/context pair:

1. `null_score = start_logit[CLS] + end_logit[CLS]`;
2. find the highest legal non-null context span score `best_span_score = start_logit[i] + end_logit[j]` where `j >= i` and span length <= 30;
3. define:

```text
answerability_margin = best_span_score - null_score
```

Higher margin means stronger evidence that the supplied memory contains an extractive answer.

Do not treat the extracted answer text as canonical truth. It is only diagnostic evidence for the release gate.

## Development corpus

Reuse the fully exposed V2 corpus because this experiment is architecture selection only.

- 1,800 total V2 queries;
- 1,200 calibration partition cases;
- 600 validation partition cases;
- V2 labels are development-only after the failed final acceptance;
- the V2 calibration/validation wording shift is intentionally preserved as a stress test of score transfer.

The Qwen retrieval/reranking stage must be rerun at top ten because the old V2 artifact only stored the old top-three selected candidate.

## Development evaluation

The bake-off reports:

- ROC-AUC and average precision for `safe_to_release`;
- answerability-margin quantiles for safe vs unsafe cases;
- best calibration threshold with empirical precision >= 0.95, chosen by recall;
- frozen-threshold transfer to the V2 validation partition;
- validation precision and positive recall;
- EN / HI / Hinglish validation recall;
- false releases by category;
- security-boundary releases;
- QA model load time, scoring throughput and peak CUDA allocation.

The V2 validation partition is now exposed and therefore may inform development architecture selection, but none of these values are final acceptance evidence.

## Development selection rule

The QA answerability approach is strong enough to freeze for a fresh V3 acceptance only if the **calibration-selected threshold** transfers to exposed V2 validation with all of the following empirical development conditions:

1. precision >= 0.95;
2. positive release recall >= 0.40;
3. EN recall >= 0.25;
4. HI recall >= 0.25;
5. Hinglish recall >= 0.25;
6. zero historical / forgotten / local-only / secret / untrusted boundary releases.

These are development selection floors, not statistical acceptance guarantees.

If the task-matched QA verifier fails this transfer test, do not generate V3. Research the next task-matched fallback, with multilingual NLI/grounding preferred before spending a large benchmark on another generic relevance scorer.

## Fresh acceptance boundary

A successful development result only authorizes freezing the candidate architecture. Final Phase 4.5D still requires:

- a completely fresh V3 corpus whose labels are not used for model/feature selection;
- independent calibration and untouched validation;
- MAPIE or equivalent statistically valid precision control at target precision 0.95 / confidence 0.95;
- frozen recall/language/security gates;
- one-shot owner run on an exact green SHA;
- durable result and closure documentation.

Phase 4.5E remains blocked until that fresh acceptance passes.
