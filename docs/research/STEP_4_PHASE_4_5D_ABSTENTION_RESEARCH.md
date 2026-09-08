# Step 4 — Phase 4.5D Abstention Calibration Research

Date: 2026-09-05

## Status

**RESEARCH COMPLETE — MEASURED CALIBRATION HARNESS NEXT.**

Phase 4.5D must decide when semantic retrieval is strong enough to release evidence and when JARVIS should abstain. No score cutoff is accepted from the earlier small retrieval/model-selection corpus.

## Research-first findings

### 1. Qwen reranker output is a decision score, not an already-calibrated probability

Official Qwen3-Reranker-0.6B usage documents that Sentence Transformers returns raw logit differences by default. Example relevant/irrelevant pairs can produce values such as positive `7.625` and negative `-11.375`.

Qwen documents an optional sigmoid transform for 0–1 output, but this is a monotonic transform of the same ranking signal. Sentence Transformers likewise documents raw/logit CrossEncoder outputs and notes that sigmoid changes the numeric range without changing rank order.

Therefore JARVIS must **not** interpret a raw reranker value such as `8.0`, `0.0`, or `-2.0` as a universal probability or invent a threshold from model-card examples.

Sources:

- https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- https://www.sbert.net/docs/cross_encoder/usage/usage.html
- https://sbert.net/docs/package_reference/cross_encoder/model.html

### 2. Threshold selection should be treated as a labeled binary release/abstain problem

For each query, the operational question is:

> Is the proposed top-1 memory correct and safe enough to release, or should retrieval abstain?

Scikit-learn's precision-recall tooling explicitly accepts non-thresholded decision scores and computes precision/recall operating points across thresholds. DET-style analysis similarly exposes false-positive/false-negative tradeoffs across score thresholds.

This matches JARVIS better than treating cosine/logit values as probabilities.

Sources:

- https://scikit-learn.org/stable/modules/generated/sklearn.metrics.precision_recall_curve.html
- https://scikit-learn.org/stable/modules/generated/sklearn.metrics.det_curve.html

### 3. Calibration and evaluation data must be separated

Scikit-learn's calibration guidance warns that fitting/calibrating and evaluating on the same data produces optimistic estimates. A calibrator should be fitted on data independent from its final evaluation data.

JARVIS will therefore maintain an explicit `calibration` split and a held-out `validation` split. The validation labels must not influence threshold/rule selection.

Source:

- https://scikit-learn.org/stable/modules/calibration.html

### 4. Do not add a learned probability calibrator yet

Platt/sigmoid, isotonic, or temperature calibration are mature tools when enough representative independent data exists. Phase 4.5D starts with a comparatively small hand-curated JARVIS-specific corpus.

Adding a fitted probabilistic model now would create another learned component and risk overfitting without a demonstrated need.

Initial Phase-4.5D therefore evaluates simple transparent decision rules directly over measured retrieval signals. A learned calibrator remains deferred until real usage provides enough independent labeled examples.

### 5. Candidate evidence signals

The existing selected retrieval pipeline already exposes useful independent signals:

- reranker top-1 raw score;
- reranker top-1 minus top-2 score margin;
- dense cosine score for the winning candidate;
- first-stage lexical rank/presence;
- first-stage dense rank;
- RRF fused rank/score.

The calibration harness will compare simple policy families rather than assume one signal is sufficient:

1. `rerank_score >= S`;
2. `rerank_score >= S AND rerank_margin >= M`;
3. `rerank_score >= S AND dense_score >= D`;
4. `rerank_score >= S AND rerank_margin >= M AND dense_score >= D`.

Threshold candidates are derived only from observed calibration scores (including midpoints), not arbitrary hand-written numbers.

### 6. Safety objective

A false release means JARVIS supplies an incorrect or unsupported memory as evidence to the model context. That is more harmful than abstaining and letting JARVIS say it does not have reliable memory evidence.

Rule selection will therefore be lexicographic:

1. minimize false releases on the calibration split;
2. among equally safe rules, maximize correct positive releases/recall;
3. prefer the simpler rule when performance is tied;
4. freeze the selected rule;
5. evaluate it unchanged on held-out validation.

A validation false release is a blocking result. It does **not** trigger threshold hand-tuning on validation; the corpus/rule family must be expanded and recalibrated instead.

This does not assign a universal numeric precision target in advance. The measured frontier will be documented before a production rule is accepted.

## Corpus design

The expanded corpus must contain substantially more than the original 20-query selection corpus and deliberately cover hard abstention boundaries.

### Positive cases

- direct paraphrases;
- semantic paraphrases with low lexical overlap;
- English;
- Hindi;
- Hinglish;
- cross-lingual query/document pairs;
- preference/fact/rule/project/self-knowledge distinctions;
- close semantic distractors where the correct memory must still win.

### Abstain cases

- genuinely absent facts;
- near-miss questions about a related but unstored attribute;
- ambiguous questions that do not identify one reliable memory;
- forgotten facts;
- superseded/current-vs-old confusion;
- local-only/secret-prohibited concepts that are not eligible for cloud release;
- untrusted/poison-style assertions;
- adversarial lexical overlap;
- negated questions;
- entities sharing vocabulary with a stored memory but asking a different relation.

### Split discipline

Cases are assigned to `calibration` or `validation` in the corpus file before model execution.

Near-duplicate paraphrases of the same semantic intent should not be split blindly across calibration/validation; semantic families should be distributed intentionally to reduce leakage.

## Required reporting

The harness must emit, at minimum:

- corpus counts by split, label, language, and category;
- retrieval top-1/top-3 accuracy for positive cases;
- false-release count for abstain cases;
- raw per-case top-1 reranker score;
- top-1/top-2 margin;
- winner dense score where available;
- lexical/dense/RRF metadata;
- calibration policy frontier;
- selected calibration-only policy, if one exists;
- held-out validation confusion counts and precision/recall;
- per-language validation breakdown;
- failure-case IDs with enough non-secret synthetic context to diagnose them;
- timing and CUDA peak observations.

## Permanent boundaries

- calibration cannot create or mutate canonical memory;
- retrieval remains evidence ranking only;
- no validation-label tuning after the rule is frozen;
- no provider/cloud call is needed for calibration;
- no second cloud provider is introduced;
- no raw personal production memory is required in the research corpus;
- no secret values are placed in corpus fixtures;
- no vector database/ANN extension is introduced;
- no autonomous code modification or self-repair authority is added.

## Implementation decision

Build a **research-only expanded corpus + calibration harness using the actual production Qwen adapters and the same selected FTS5/dense/RRF contract**.

Do not add a production abstention threshold until the owner RTX run produces the calibration and held-out validation evidence.
