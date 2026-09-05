# Step 4 — Phase 4.5B Retrieval Core Result

Date: 2026-09-05

## Status

**PHASE 4.5B COMPLETE — ELIGIBLE-CURRENT FTS5 + EXACT DENSE COSINE + DETERMINISTIC RRF IMPLEMENTED AND AUTOMATED VALIDATION PASSED.**

## Implemented production surface

Added:

- `src/jarvis/memory/retrieval.py`
- `tests/test_memory_retrieval.py`

Phase 4.5B deliberately does **not** import or load Sentence Transformers, Torch, CUDA, the Qwen embedding model, or the Qwen reranker. It accepts an already-produced 256-dimensional query vector and ranks only eligible canonical memory.

## Eligibility before ranking

The retrieval core filters canonical eligibility before lexical or dense ranking.

Current production rules:

- only `current_semantic_assertion` records participate;
- `AuthorityClass.UNTRUSTED` is prohibited from retrieval;
- `Sensitivity.SECRET_PROHIBITED` is prohibited from retrieval;
- local retrieval may include `STANDARD`, `PRIVATE`, and `LOCAL_ONLY`;
- cloud-context retrieval may include `STANDARD` and `PRIVATE`, but not `LOCAL_ONLY`;
- authority and sensitivity are checked on both the assertion and its provenance source;
- retrieval eligibility never grants mutation authority or establishes truth.

This prevents a standard-labeled assertion backed by a local-only or untrusted source from bypassing provenance policy.

## Safe FTS5 query contract

Natural user text is never passed directly into the FTS5 query grammar.

The implementation preserves the exact lexical transformation measured in the Phase-4 research harness:

1. tokenize Unicode word-like terms locally;
2. case-fold tokens;
3. remove the fixed stopword set;
4. de-duplicate while preserving first occurrence;
5. quote every remaining token as an FTS5 string;
6. join quoted tokens with explicit `OR`;
7. bind the complete MATCH expression as a SQL parameter.

User punctuation/operators therefore cannot silently become FTS5 syntax.

## Dense retrieval contract

Dense retrieval uses exact local dot-product/cosine ranking over normalized vectors stored by Phase 4.5A.

A stored derivative participates only when all of the following match the selected embedding contract:

- model ID;
- immutable model revision;
- dimension;
- dtype;
- byte order;
- normalized flag;
- SHA-256 fingerprint of the current canonical `normalized_text`.

A stale or mismatched vector is ignored until rebuilt. Canonical memory remains untouched.

No ANN index or vector database is introduced.

## RRF contract

The production first-stage fusion matches the measured research contract:

- equal lexical/dense weight;
- RRF rank constant `k=60`;
- lexical window `10`;
- deterministic exact-score tie order:
  1. dense rank;
  2. lexical rank;
  3. stable assertion ID.

The first-stage result exposes lexical, dense and fused ranks/scores as evidence metadata.

## Historical-change semantics clarified by CI

An initial test incorrectly expected the replacement created by a canonical historical change to be absent from current retrieval.

The runtime behavior was correct:

- the superseded old assertion is excluded;
- the replacement is the new current canonical assertion and may be retrieved;
- until the replacement receives its own embedding, it may participate lexically but has no dense rank;
- the old assertion's embedding is not reused for the replacement.

The test was corrected to assert these semantics rather than changing valid runtime behavior.

Fix commit:

- `e50e2d73057c1bc35d2fc5d4be305defeb1a92c4` — `Fix historical replacement retrieval expectation`.

## Automated validation

Tests cover:

- FTS5 operator/punctuation neutralization;
- deterministic RRF exact-score ties;
- fail-closed untrusted/secret eligibility;
- local versus cloud-context sensitivity behavior;
- assertion + provenance-source filtering;
- superseded history exclusion;
- current replacement inclusion;
- no dense rank for a replacement without its own vector;
- stale content fingerprint exclusion from dense retrieval;
- deterministic exact dense ordering and evidence metadata.

GitHub Actions run `33983727641` on head `e50e2d73057c1bc35d2fc5d4be305defeb1a92c4` completed with:

- Ruff: PASS;
- pytest: PASS;
- Windows DPAPI: PASS;
- Windows Hello helper: PASS.

## Security/authority result

Phase 4.5B remains a read/rank derivative:

- no canonical write is exposed;
- no model output becomes truth;
- no provider history becomes memory;
- no local-only content may enter a cloud-target retrieval request;
- stale derivatives cannot override current canonical data;
- forgotten or superseded records cannot be resurrected through dense ranking.

## Next

Proceed to **Phase 4.5C — revision-pinned lazy Qwen embedding/reranker adapters and measured owner-machine Torch/CUDA coexistence**.

Do not wire semantic retrieval into the production voice path until the selected local models are proven compatible with the accepted Step-3 vision/Torch environment.
