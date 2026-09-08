# Step 4 Phase 4.5E.2 — Qwen Utility / Steering Bake-off Result

## Status

**QWEN THREE-PROMPT UTILITY GATE REJECTED — KEEP QWEN FOR RETRIEVAL/RERANKING ONLY — NO MEMORY INJECTION**

Date: 2026-09-08

Branch: `implementation/step-4-phase45e2-utility-gate`

Owner-machine result artifact:

- file: `phase45e2_qwen_utility.json`
- SHA-256: `2e3330ae9abaebfa4304c47b239aea1f20bcf3a6033e22792e1a325bc3ccf89d`
- size: 38,209 bytes
- model: `Qwen/Qwen3-Reranker-0.6B`
- revision: `e61197ed45024b0ed8a2d74b80b4d909f1255473`
- device: `cuda:0`

This result rejects only the proposed Phase 4.5E.2 use of the reranker as a multi-axis memory influence classifier. It does **not** invalidate the already-accepted use of Qwen3-Reranker for Phase 4.5C/E.1 semantic reranking.

## Corpus and run

The first E.2 corpus contained 64 balanced cases:

- 16 `ESSENTIAL`;
- 16 `HELPFUL`;
- 16 `UNNECESSARY`;
- 16 `STEERING_RISK`.

The first 32 English cases were calibration. The remaining 32 Hinglish/Hindi cases were held out and were not used by the threshold search.

The harness measured three task-specific Qwen scores over each query/memory pair:

- essential;
- helpful;
- steering.

Threshold selection prioritized false-influence prevention before utility recall.

## Calibration result

Selected thresholds:

- essential: `Infinity`;
- helpful: `-8.90625`;
- steering: `-6.65625`.

The `Infinity` essential threshold is itself an important failure signal: the optimizer could not retain an ESSENTIAL release path while satisfying the higher-priority safety objectives with these three scores.

Calibration metrics:

- unsafe false influence: **0**;
- missed steering: **0**;
- `ESSENTIAL` recall: **0.0**;
- `HELPFUL` recall: **0.25**;
- `UNNECESSARY` recall: **0.625**;
- `STEERING_RISK` recall: **1.0**;
- macro F1: **0.413520**.

Every calibration `ESSENTIAL` case was classified as `STEERING_RISK`.

## Frozen multilingual holdout result

Holdout metrics:

- unsafe false influence: **4**;
- missed steering: **1**;
- `ESSENTIAL` precision/recall/F1: **0 / 0 / 0**;
- `HELPFUL` precision/recall/F1: **0 / 0 / 0**;
- `UNNECESSARY` precision: **0.75**;
- `UNNECESSARY` recall: **0.375**;
- `STEERING_RISK` precision: **0.291667**;
- `STEERING_RISK` recall: **0.875**;
- macro F1: **0.234375**.

This is not an acceptable influence gate. It simultaneously blocks all useful multilingual memory influence and still releases four unrelated memories as `HELPFUL`.

### Unsafe false-influence examples

The four holdout `UNNECESSARY` cases incorrectly classified as `HELPFUL` were deliberately chosen lexical/semantic collision cases:

1. a Python-dictionary question paired with a remembered preferred airport;
2. a Snowflake-clustering question paired with a remembered snow-boot size;
3. a falcon-bird question paired with a remembered test vehicle named Falcon;
4. a Java-Spring-framework question paired with a remembered spring-trip month.

These are exactly the class of false associations that Phase 4.5E.2 must reject before any future provider-context injection is considered.

One `STEERING_RISK` case was classified as `UNNECESSARY`. That is a taxonomy miss, but because both labels are no-influence outcomes it is less dangerous than the four `UNNECESSARY -> HELPFUL` releases.

## Score-shape diagnosis

The three prompt scores are highly collinear across the 64 cases:

- essential vs helpful Pearson correlation: approximately **0.990**;
- essential vs steering: approximately **0.972**;
- helpful vs steering: approximately **0.976**.

In practice the three prompt variants behaved mostly like different views of the same query/document relatedness signal rather than independent essentiality, safe-helpfulness, and steering dimensions.

Direct personal recall cases frequently received high positive `steering` scores even though the steering instruction explicitly defined directly requested personal facts as non-steering. That made steering precedence swallow the ESSENTIAL class.

The result is consistent with the model's underlying role. Qwen3-Reranker is instruction-aware and supports custom reranking instructions, but its SentenceTransformers path still produces a binary yes/no logit-difference score for whether a document meets the instructed query requirement. It is a strong reranker, not a purpose-trained four-way policy classifier.

Sources:

- https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- https://www.sbert.net/docs/package_reference/cross_encoder/model.html
- https://www.sbert.net/docs/package_reference/cross_encoder/modules.html

## Performance was not the rejection reason

Owner-machine performance was reasonable:

- model load: **4.0936 s**;
- peak CUDA allocation: **2,173,275,136 bytes** (~2.02 GiB);
- per-prompt p50: roughly **76 ms**;
- three-prompt p50: **228.251 ms**;
- three-prompt p95: **254.019 ms**.

The candidate is rejected for semantic/safety quality, not latency or GPU feasibility.

## Methodological consequence

The original multilingual holdout has now been inspected. It remains valid evidence for rejecting this Qwen candidate, but it must not be treated as a blind holdout for selecting the next technology.

Any next model bake-off must therefore use a **new frozen E.2 evaluation set** created before the new candidates are run. This avoids model-selection leakage from the already-observed first holdout.

## Fresh research after rejection

The observed failure calls for a classifier designed for semantic class decisions rather than another retrieval-score prompt tweak.

Two mature multilingual NLI/zero-shot candidates are appropriate for a second research bake-off:

1. `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli`
   - multilingual NLI / zero-shot classification;
   - 100+ language support claimed by the model card;
   - distilled six-layer model intended for high inference speed and lower memory use.

2. `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`
   - multilingual NLI / zero-shot classification;
   - 0.3B parameters;
   - trained on XNLI plus more than 2.7 million multilingual NLI pairs across 27 languages;
   - training explicitly includes mixed English-hypothesis / non-English-premise pairs, which maps well to JARVIS using fixed English policy hypotheses against English/Hinglish/Hindi query-memory pairs;
   - model card reports Hindi XNLI accuracy of 0.769.

Sources:

- https://huggingface.co/MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli
- https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7

The next experiment should compare these candidates sequentially on the owner GPU so peak memory is measured per model rather than loading both simultaneously.

## Decision

**Reject Qwen task-prompt decomposition for Phase 4.5E.2 influence authority.**

Retain Qwen3-Reranker for the accepted retrieval/reranking role.

Do not tune the three prompt strings against the now-observed holdout. Do not lower safety priority to recover recall. Do not implement Phase 4.5E.3.

Next Phase 4.5E.2 work is a fresh, frozen multilingual NLI classification bake-off with no production runtime changes and no provider-context insertion.
