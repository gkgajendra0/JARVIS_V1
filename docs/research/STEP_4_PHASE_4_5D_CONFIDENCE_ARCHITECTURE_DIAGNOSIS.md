# Step 4 Phase 4.5D — Confidence Architecture Diagnosis

## Status

**ACTIVE — remain inside Phase 4.5D. Phase 4.5E is blocked.**

## Evidence that is now retired development data

The first fresh 320-query acceptance corpus has been executed and exposed. It is now permanently retired from final acceptance and may be used only for development diagnostics.

Retrieval quality itself was strong:

- calibration positive top-1: 96/96;
- validation positive top-1: 63/64 (`0.984375`);
- validation positive Recall@3: 64/64 (`1.0`).

The acceptance failure came from the release-confidence layer, not first-stage retrieval/reranking quality.

## What was ruled out

### 30-way Bonferroni-Holm

No MAPIE-valid policy was found. With only 96 safe calibration positives, even a hypothetical zero-error rule releasing all 96 has best-case p-value approximately `0.95^96 = 0.0072688567`, while the first 30-way Holm/Bonferroni level is approximately `0.05 / 30 = 0.0016666667`. The original multiple-testing design was therefore underpowered by construction.

### Split Fixed Sequence Testing

The first SFST diagnostic initially omitted `binary=True` in MAPIE's independent ordering step. That was corrected because precision uses binary losses and MAPIE's calibration path applies the binary Hoeffding-Bentkus test.

After correction, SFST still found no valid policy.

The stronger result is the per-policy audit: **zero of the 30 score+margin rules is valid even as a single hypothesis at alpha 0.05**.

The best observed rule in the frozen grid was approximately:

- reranker score >= `6`;
- reranker margin >= `12`;
- released `19` calibration cases;
- TP `18`;
- FP `1`;
- empirical precision `0.947368`;
- positive release recall `0.1875`.

Because its empirical precision is already below the `0.95` target, no multiple-testing method can honestly certify it at that operating point.

Conclusion: the blocker is no longer Holm/SFST. The existing rectangular `reranker_score AND reranker_margin` confidence family is insufficient on the retired development evidence.

## Research-first next layer

The production Qwen reranker instruction is already strict: it asks whether a memory directly and sufficiently answers the query and rejects merely related, missing-detail, contradictory or negated documents. Rewriting that instruction again without evidence would be guesswork.

Two mature alternatives were identified:

1. combine evidence JARVIS already computes with a low-capacity calibrated/selective classifier;
2. add an independent multilingual NLI/entailment verifier if existing evidence cannot separate safe vs unsafe releases.

Sentence Transformers documents NLI cross-encoders as premise/hypothesis entailment-vs-neutral-vs-contradiction classifiers. A mature multilingual candidate is `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`, trained on XNLI plus a multilingual NLI corpus and advertised for 100 languages. It is not selected yet.

Scikit-learn's probability-calibration guidance supports cross-validated confidence estimation and notes that LogisticRegression is a reasonable low-capacity calibrated baseline. This path is cheaper than adding a third transformer and should be measured first.

## Development-only feature-gate diagnostic

Harness:

- `tools/research/step4_phase45d_feature_gate_diagnostic.py`

Input:

- the already-exposed `.step4-phase45d-final-acceptance.json` only;
- no Qwen/CUDA inference;
- no canonical DB changes.

Compared feature sets:

### Baseline

- reranker top score;
- reranker top1-top2 margin.

### Full existing retrieval evidence

- reranker top score;
- reranker margin;
- dense cosine score;
- fused RRF score;
- lexical-hit indicator;
- reciprocal lexical rank;
- reciprocal dense rank.

Excluded from the model deliberately:

- language;
- category;
- case ID;
- expected memory ID.

Evaluation protocol:

- `StratifiedKFold(n_splits=5, shuffle=True, random_state=45)`;
- `StandardScaler + LogisticRegression`;
- out-of-fold `predict_proba` only;
- ROC-AUC;
- average precision;
- best development-only empirical recall at precision >= `0.95`.

No threshold or probability from this retired corpus is eligible for production.

## Decision rule after the diagnostic

If full existing retrieval evidence improves both discrimination metrics and yields useful >=95% empirical precision on out-of-fold predictions, freeze the low-capacity confidence model architecture on retired development data and use a new untouched corpus for independent MAPIE threshold calibration plus held-out validation.

If it does not, do not add more handcrafted retrieval features or lower the target. Benchmark an independent multilingual entailment/answerability verifier before changing production architecture.

## Permanent constraints

- target precision remains `0.95`;
- confidence level remains `0.95`;
- no final acceptance corpus is rerun after labels/results are exposed;
- retrieval never establishes canonical truth;
- no `LOCAL_ONLY` or `SECRET_PROHIBITED` memory can be released to cloud context;
- Phase 4.5E remains blocked until Phase 4.5D genuinely passes.
