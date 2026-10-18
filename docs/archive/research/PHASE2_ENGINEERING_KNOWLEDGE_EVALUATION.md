# Phase 2H — EngineeringKnowledge Evaluation Harness

## Status

**IMPLEMENTATION SLICE — EVALUATION CONTRACT**

This document describes the deterministic benchmark contract added in Phase 2H.

## Purpose

Phase 2H does not declare retrieval "good" from a few happy-path tests. It creates a repeatable qrel corpus and scoring harness so later retrieval changes can be compared against the same evidence.

Canonical corpus:

`benchmarks/engineering_knowledge_qrels_v1.json`

Harness:

`jarvis.engineering_knowledge.evaluation`

## Corpus coverage

The v1 qrel corpus explicitly covers:

- exact crash signatures;
- code symbols;
- paraphrases;
- Hinglish/multilingual queries;
- component applicability;
- package/version applicability;
- device/firmware applicability;
- stale/superseded knowledge;
- contradictory/refuted knowledge;
- semantically similar but inapplicable knowledge;
- no-answer behavior;
- poisoned/instruction-like evidence;
- secret-like content;
- unknown facets;
- local/private leakage boundaries;
- future engineering-process extensibility.

The corpus uses stable symbolic document keys. Benchmark runners map those keys to the concrete revisions generated for a run. This prevents benchmark identity from depending on random database IDs.

## Metrics

The harness reports:

- Recall@K;
- Precision@K;
- MRR;
- nDCG@K;
- no-answer false-positive rate;
- applicability-violation rate;
- stale-result rate;
- leakage rate;
- p50/p95 wall latency;
- p50/p95 process CPU time;
- optional peak RSS;
- optional peak VRAM;
- optional disk/index size;
- optional rebuild latency.

No arbitrary relevance threshold is introduced in Phase 2H. Baselines are measured first.

## Safety gate

The following are zero-tolerance benchmark failures:

- an applicability-forbidden result is returned;
- stale/superseded knowledge is returned where explicitly prohibited;
- private/secret material leaks into a prohibited context;
- a no-answer/security case returns a result.

This safety gate is independent of semantic ranking quality. Higher Recall or nDCG cannot compensate for an applicability or leakage violation.

## Resource probes

The evaluation harness records wall and process CPU time directly.

RSS, VRAM, disk size and rebuild time are supplied through a small resource-probe contract because reliable collection is platform-specific. Owner-machine acceptance may provide Windows/NVIDIA-aware probes without changing the metric contract.

## Phase 2I relationship

Phase 2I must use this corpus and metric contract to compare optional retrieval changes such as:

- embedding dimensions;
- FTS tokenizer variants;
- Qwen reranking;
- sqlite-vec;
- LanceDB;
- Qdrant.

An optional technology is not adopted merely because it is available. It must improve the JARVIS benchmark without violating the zero-tolerance safety gate or imposing unacceptable owner-machine resource/operational cost.

## Phase 2J relationship

The final owner-machine acceptance run must include:

- corpus/retrieval execution against the integrated EngineeringKnowledge stack;
- local resource measurements;
- real Qwen model behavior where available;
- R2 Self-Repair independence negative control.

CI evidence remains necessary but is not sufficient to declare Phase 2 complete.
