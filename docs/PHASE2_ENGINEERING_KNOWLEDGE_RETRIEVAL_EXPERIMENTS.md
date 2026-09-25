# Phase 2I — EngineeringKnowledge Retrieval Experiment Policy

## Status

**IMPLEMENTATION COMPLETE — BASELINE RETAINED PENDING OWNER-MACHINE EVIDENCE**

Phase 2I does not add a new vector database, reranker or retrieval dependency by default.

The accepted Phase-2 baseline remains:

```text
exact identifiers / evidence references
        +
SQLite FTS5 unicode61 / BM25
        +
Qwen3-Embedding-0.6B @ 256 dimensions
        +
exact NumPy cosine ranking
        +
RRF
        +
applicability / lifecycle / integrity / sensitivity gates
```

The purpose of this phase is to make optional improvements measurable and fail-closed rather than adopt technology by reputation.

## Experiment matrix

The code-owned matrix is `PHASE2I_RETRIEVAL_VARIANTS` in
`jarvis.engineering_knowledge.benchmarking`.

It includes:

- Qwen embedding dimensions 256 / 512 / 1024;
- FTS5 `unicode61` baseline versus `trigram`;
- Qwen3-Reranker-0.6B over a bounded first-stage window;
- exact NumPy vector scoring baseline;
- sqlite-vec;
- LanceDB;
- Qdrant.

The latter three remain dependency experiments, not production dependencies.

## Evidence rule

A candidate may be considered adoptable only when all of the following hold:

1. baseline and candidate use the same qrel corpus version and K;
2. the baseline itself passes the zero-tolerance safety gate;
3. the candidate passes the zero-tolerance safety gate;
4. recall does not regress beyond an explicit measured policy;
5. requested latency / CPU / RSS / VRAM / disk evidence exists;
6. requested resource ratios stay within an explicit measured policy;
7. nDCG or MRR improves by an explicit policy threshold.

The comparison code intentionally has no product-wide hard-coded "good enough" quality or resource threshold. Those values must be chosen from measured baseline evidence on the owner machine.

## Qwen dimension experiments

The current Qwen adapter already passes `truncate_dim` to the pinned model.

Phase 2I therefore exposes reviewed experiment contracts for:

- 256 dimensions;
- 512 dimensions;
- 1024 dimensions.

All dimensions use the same pinned model ID and revision. The retrieval encoder now accepts an explicit `EmbeddingContract` so these experiments do not require code forks.

Because the engineering embedding table stores one derived vector per revision, dimension experiments should run on isolated benchmark databases or rebuild the derived index between variants. Canonical EngineeringKnowledge is unaffected.

## Reranker experiment

The existing pinned Qwen3-Reranker-0.6B adapter may be benchmarked over a bounded candidate window.

It is not inserted into the production EngineeringKnowledge path merely because the adapter exists. It must improve the Phase-2H corpus under measured owner-machine cost.

## Vector backend experiments

sqlite-vec, LanceDB and Qdrant remain optional experiments.

Phase 2 does not gain an external service requirement. A backend can replace exact NumPy scoring only after benchmark evidence demonstrates a meaningful benefit at the expected EngineeringKnowledge scale and preserves:

- local/offline behavior where required;
- deterministic applicability filtering before ranking;
- canonical SQLite independence;
- rebuildability;
- provenance/integrity gates;
- acceptable operational complexity.

## Current decision

No optional retrieval technology is adopted in Phase 2I before owner-machine evidence.

This is not a negative judgment about the candidate technologies. It is the deliberate result of the project rule:

```text
measure first -> compare -> adopt only on evidence
```

The current simple baseline is therefore retained for Phase 2J acceptance.

## Phase 2J benchmark

Owner-machine acceptance should run the Phase-2H corpus and capture the real baseline first.

Where practical, the benchmark may then evaluate the built-in candidates (Qwen dimensions, trigram support, bounded reranker). Optional external vector backends should only be installed if a measured scale problem makes their evaluation justified; Phase 2J does not require installing them merely to prove that the baseline works.

No experiment may weaken the zero-tolerance safety gate.
