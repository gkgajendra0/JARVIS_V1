# Step 4 Phase 4.5D — Task-Specific Local Guard Bake-Off Method V2 Result

## Status

**FAILED DEVELOPMENT GATE — EXPOSED / RETIRED**

Phase 4.5D remains active. Phase 4.5E remains blocked.

This document records the owner RTX run of the frozen Method V2 development bake-off. Method V2 is now exposed development evidence and must not be rerun, threshold-tuned, or used as fresh acceptance evidence.

## Owner run contract

Repository SHA:

`d9dc8cc06edd81288c6af370c0032a7f771e8b23`

Frozen corpus SHA-256:

`ae854ed664ef6ee0214f65f5fe4b252099fd1dcaea00c13aaf7789cd84afd3ab`

Environment checks passed before execution:

- GPU: NVIDIA GeForce RTX 5060 Ti;
- Torch `2.13.0+cu132`;
- Torchvision `0.28.0+cu132`;
- Transformers `5.16.1`;
- SentenceTransformers `6.0.1`;
- scikit-learn `1.9.0`;
- psutil `7.2.2`;
- CUDA available;
- zero Gemini/OpenAI calls.

The Hugging Face Windows symlink-cache warning was non-fatal and affected disk-cache efficiency only; all four immutable candidates loaded and completed.

## Frozen gates

A candidate had to satisfy all of the following on the never-trained-on holdout:

1. zero false allows;
2. zero negation false allows;
3. overall allow recall >= `0.90`;
4. direct-current allow recall >= `0.90`;
5. comparison allow recall >= `0.85`;
6. each language allow recall >= `0.85`;
7. eight-class macro-F1 >= `0.85`;
8. argmax only, no probability threshold;
9. zero cloud calls;
10. retired V4 not used for training or scoring.

## Results

| Candidate | False allows | Overall allow recall | Direct recall | Comparison recall | Macro-F1 | Holdout ms/query | Sampled RSS delta | CUDA peak delta | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| multilingual MiniLM L12 | 9 | 0.791667 | 0.958333 | 0.625000 | 0.646962 | 0.2632 | 1,037,230,080 B | 537,652,224 B | FAIL |
| multilingual E5-small | 11 | 0.854167 | 1.000000 | 0.708333 | 0.726627 | 0.2649 | 340,541,440 B | 505,324,544 B | FAIL |
| multilingual MPNet-base-v2 | 12 | 0.854167 | 0.958333 | 0.750000 | 0.809516 | 0.5586 | 359,878,656 B | 1,175,579,648 B | FAIL |
| Qwen3-Embedding-0.6B 256d | 14 | 0.791667 | 0.958333 | 0.625000 | 0.623784 | 2.4197 | 455,921,664 B | 1,770,743,296 B | FAIL |

Harness decision:

```json
{
  "selected_candidate": null,
  "candidate_selected": false,
  "production_guard_change_authorized": false,
  "fresh_v5_acceptance_authorized": false,
  "phase45e_authorized": false
}
```

## Diagnosis

The failure is architectural, not a candidate tie-break issue.

Every frozen embedding + fixed LogisticRegression candidate produced multiple false allows (`9` to `14`). Therefore none can satisfy the release boundary regardless of relative recall or latency.

The direct-current class is not the main weakness: all candidates reached at least `0.958333` direct recall. The persistent weaknesses are:

- false allows on veto classes;
- current-value-comparison separation (`0.625` to `0.75` recall);
- eight-class semantic separation (best macro-F1 `0.809516`, below `0.85`).

The best Method V2 model by macro-F1, multilingual MPNet-base-v2, still produced `12` false allows and missed the comparison floor. The fastest/lighter candidates also failed the semantic safety boundary. Qwen reuse did not rescue the frozen-linear-head design and was materially slower/heavier for this task.

The correct conclusion is **not** to tune a probability threshold, logistic hyperparameters, prompts, class weights, or the exposed holdout. The frozen-body linear-probe architecture itself is retired for this guard.

## Research-driven next direction

Current SetFit documentation makes the missing step explicit: SetFit first fine-tunes the SentenceTransformer body with contrastive learning and only then trains the classification head. Method V2 intentionally skipped that body fine-tuning to preserve the owner stack, so it was a linear probe rather than full SetFit training.

Current multilingual encoder research also provides a more task-aligned path: `jhu-clsp/mmBERT-base` is a 307M-parameter modern multilingual encoder trained across 1800+ languages and reports stronger classification performance than XLM-R. Standard Transformers sequence-classification fine-tuning is directly supported without introducing a cloud dependency.

The next development iteration should therefore test **task-specific encoder fine-tuning**, not more frozen embedding models.

Constraints for the next iteration:

- completely fresh train/holdout text and facts; no Method V2 query reuse;
- Method V2 and V4 may be used only as exact-query deny-lists / architectural evidence, never training or scoring data;
- preserve the eight semantic classes and the zero-false-allow rule unless a separately frozen architectural method justifies a change before any new result is seen;
- no threshold fitting;
- zero cloud/provider calls;
- no production guard change until a fresh development winner exists;
- fresh final acceptance remains required after implementation.

## Decision

**Method V2 is permanently retired as the selected guard architecture.**

No production guard change is authorized from this result. Do not generate V5 acceptance yet. The next work is a new research-frozen task-specific encoder-fine-tuning development method and a completely fresh corpus.
