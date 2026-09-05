# Step 4 — Phase 4.5C Local Qwen Adapter Status

Date: 2026-09-05

## Status

**IMPLEMENTATION COMPLETE / OWNER-MACHINE COMPATIBILITY ACCEPTANCE PENDING.**

Phase 4.5C is not closed yet. The production adapter contract is implemented and fake-backed automated tests are present, but the selected Qwen models must still be exercised together inside the accepted owner-machine Step-3 Torch/CUDA/vision environment before production enablement.

## Research-backed dependency decision

The winning Phase-4.5 owner-machine retrieval bake-off used:

- Sentence Transformers `6.0.1`;
- Transformers `5.16.1`;
- Qwen3-Embedding-0.6B;
- Qwen3-Reranker-0.6B.

Production therefore keeps those same Sentence Transformers/Transformers versions instead of introducing a new unmeasured software path.

The existing JARVIS `vision` extra owns the accepted production Torch pin:

- `torch==2.13.0`;
- `torchvision==0.28.0`.

The new `retrieval` extra intentionally contains only:

```toml
retrieval = [
    "sentence-transformers==6.0.1",
    "transformers==5.16.1",
]
```

It does **not** silently select, upgrade or replace Torch. Sentence Transformers 6.x supports Torch versions well below the existing JARVIS 2.13.0 pin, so package metadata does not force a Torch change; real GPU/vision coexistence remains an owner-machine measurement gate.

## Immutable model contracts

Embedding:

- model: `Qwen/Qwen3-Embedding-0.6B`;
- revision: `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- output: normalized 256-dimensional vector;
- query path: JARVIS memory-retrieval instruction + `encode_query`;
- document path: `encode_document`;
- `trust_remote_code=False`.

Reranker:

- model: `Qwen/Qwen3-Reranker-0.6B`;
- revision: `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- candidate window: top 3;
- `trust_remote_code=False`;
- exact equal reranker scores preserve first-stage fused rank, then stable assertion ID.

## Implemented production surface

Added:

- `src/jarvis/memory/retrieval_models.py`;
- `tests/test_memory_retrieval_models.py`;
- optional `retrieval` dependency extra in `pyproject.toml`.

The adapters are deliberately lazy:

- importing JARVIS memory modules does not import Sentence Transformers;
- constructing an adapter does not load a model;
- model/dependency loading occurs only on first real encode/rerank request;
- empty document batches do not trigger a load;
- ordinary unit tests use injected fake model factories and require no GPU/model download.

The adapters validate output shape, finiteness and normalization before returning data to the retrieval core.

No global CUDA cache clearing or process-wide GPU mutation is performed by these adapters, avoiding interference with the accepted vision stack.

## Automated contract tests

Fake-backed tests cover:

- lazy model construction;
- exact immutable revision passed to model constructor;
- CUDA device selection contract;
- `trust_remote_code=False`;
- exact JARVIS query instruction;
- `normalize_embeddings=True`;
- 256-dimensional truncation;
- document/query normalization;
- malformed embedding output rejection;
- reranker top-3 window;
- deterministic exact-score tie handling;
- non-finite reranker score rejection.

## Owner-machine compatibility harness

Added:

- `tools/research/step4_phase45c_runtime_compatibility.py`.

This is an acceptance harness, not production voice orchestration. In one process on the real owner machine it verifies:

- Torch remains release `2.13.0`;
- Sentence Transformers is `6.0.1`;
- Transformers is `5.16.1`;
- CUDA is available;
- existing `torchvision`, `rfdetr`, `trackers`, `mediapipe`, and `cv2` imports still succeed;
- real revision-pinned Qwen embedding produces finite normalized 256d vectors;
- a known camera query ranks the camera memory first in the tiny compatibility corpus;
- the real Qwen reranker returns finite scores and keeps the camera memory first;
- both selected Qwen models remain loaded together;
- combined CUDA allocation/peak is recorded for evidence.

This narrow gate is intentionally before any production voice integration. It is designed to catch dependency or GPU coexistence problems without destabilizing the accepted Step-3 runtime.

## Closure condition

Phase 4.5C may be marked complete only after:

1. repository Ruff/pytest/Windows security CI is green on the implementation/harness head;
2. the owner pulls that head into the accepted Windows `.venv`;
3. installing the `retrieval` extra does not change the accepted Torch release;
4. the compatibility harness returns `status=PASS` with all checks true;
5. the result is recorded as owner-machine evidence.

Only then may Phase 4.5D abstention calibration begin.
