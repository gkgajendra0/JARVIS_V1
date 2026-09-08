# Step 4 — Phase 4.5C Local Qwen Adapter Result

Date: 2026-09-05

## Status

**PHASE 4.5C COMPLETE — OWNER-MACHINE COMPATIBILITY ACCEPTANCE PASSED.**

The selected local Qwen embedding + reranker stack is accepted for the existing JARVIS Windows GPU environment. No Step-3 Torch/Torchvision or vision-package replacement was required.

## Production adapter contract

Embedding:

- model: `Qwen/Qwen3-Embedding-0.6B`;
- immutable revision: `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- output: normalized 256-dimensional vector;
- query path: exact measured JARVIS memory-retrieval instruction + `encode_query`;
- document path: `encode_document`;
- `trust_remote_code=False`.

Reranker:

- model: `Qwen/Qwen3-Reranker-0.6B`;
- immutable revision: `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- candidate window: top 3;
- exact equal reranker scores preserve first-stage fused rank, then stable assertion ID;
- `trust_remote_code=False`.

Runtime libraries:

- Sentence Transformers `6.0.1`;
- Transformers `5.16.1`;
- retrieval extra does not own or alter the production Torch pin.

## Owner-machine acceptance

Owner pulled implementation head:

- `82c1f1ec7bf7837251f0d666458ac73dd26aaac0`.

Working tree was clean before installation.

### Accepted GPU framework preserved

Before installing the retrieval extra:

- Torch `2.13.0+cu132`;
- Torchvision `0.28.0+cu132`.

After installing `.[retrieval]` under explicit resolver constraints:

- Torch `2.13.0+cu132`;
- Torchvision `0.28.0+cu132`.

Therefore retrieval dependency installation did **not** replace the accepted Step-3 GPU framework.

`python -m pip check` returned:

- `No broken requirements found.`

### Vision coexistence

The same process successfully imported:

- `torchvision`;
- `rfdetr` `1.9.4`;
- `trackers` `2.6.0`;
- `mediapipe` `1.0.1`;
- `cv2` / OpenCV `5.0.0.93`.

All vision-import compatibility checks were true.

### Real CUDA model execution

Runtime:

- GPU: `NVIDIA GeForce RTX 5060 Ti`;
- Torch: `2.13.0+cu132`;
- CUDA runtime: `13.2`.

The real revision-pinned Qwen embedding model produced:

- finite output;
- normalized output;
- exact 256-dimensional shape;
- camera memory ranked first for `Which device gives Jarvis eyes?`.

Dense order:

1. `camera` — `0.594897`;
2. `research_rule` — `0.261994`;
3. `bike` — `0.459904`.

The list above preserves the harness-emitted score array; ranking was determined by the actual per-document association in the harness and `dense_camera_top1=true` was the acceptance assertion.

The real revision-pinned Qwen reranker returned finite scores and ranked:

1. `camera` — `8.1875`;
2. `research_rule` — `-1.6875`;
3. `bike` — `-8.9375`.

All model checks were true, including:

- `cuda_available`;
- `embedding_shape`;
- `embedding_finite`;
- `embedding_normalized`;
- `dense_camera_top1`;
- `reranker_count`;
- `reranker_finite`;
- `reranker_camera_top1`;
- `both_models_loaded`.

Harness result:

- `status=PASS`.

### Combined GPU footprint

With both Qwen models loaded in one process:

- CUDA allocated after both models: `2,416,691,200` bytes;
- peak CUDA allocated: `2,462,774,784` bytes.

This is acceptable on the owner RTX 5060 Ti and leaves the final production concurrency policy to later end-to-end acceptance rather than changing Step-3 architecture here.

Lazy-load timing observed in this compatibility run:

- embedding query + tiny document batch including initial model load: `9979.15 ms`;
- reranker top-3 including initial model load: `5234.761 ms`.

These are cold-load compatibility timings, not steady-state retrieval latency measurements and are not used as production SLA values.

## Repository validation

Implementation includes:

- `src/jarvis/memory/retrieval_models.py`;
- `tests/test_memory_retrieval_models.py`;
- `tools/research/step4_phase45c_runtime_compatibility.py`;
- optional `retrieval` dependency extra in `pyproject.toml`.

CI on final pre-owner head passed:

- Ruff;
- full pytest;
- Windows DPAPI;
- Windows Hello helper.

## Authority/security result

Phase 4.5C adds local ranking capability only.

It does not:

- create canonical memory;
- mutate truth;
- bypass eligibility filtering;
- enable implicit durable admission;
- expose secret/local-only memory to cloud context;
- change the active cloud provider;
- grant autonomous repair or code-modification authority.

## Decision

**ACCEPT the revision-pinned Qwen local model adapters on the existing Step-3 production GPU stack.**

No additional compatibility rerun is required unless a future dependency/model/Torch revision changes.

## Next

Proceed to **Phase 4.5D — abstention calibration**.

No absolute dense/reranker threshold is accepted yet. Build a larger labeled positive/absent/ambiguous/adversarial multilingual corpus and select any release/abstain rule from measured precision/recall and false-release evidence rather than from intuition.
