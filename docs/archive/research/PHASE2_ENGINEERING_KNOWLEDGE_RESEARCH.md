# Phase 2 — EngineeringKnowledge Research

## Status

**OWNER-APPROVED RESEARCH BASIS — 2026-09-24**

This document records the research used to design Phase 2 of the governed autonomous-engineering program.

It is research evidence, not production truth and not execution authority. The canonical architecture decision is `PHASE2_ENGINEERING_KNOWLEDGE_ARCHITECTURE.md`; the execution sequence is `PHASE2_ENGINEERING_KNOWLEDGE_IMPLEMENTATION_PLAN.md`.

---

## 1. Research question

Phase 2 must let JARVIS retain verified engineering knowledge so it does not repeatedly rediscover the same repair, diagnosis, integration or capability-building lesson.

The design must also support engineering process families not known today.

The research therefore asked:

1. what existing JARVIS foundations can be reused;
2. whether a complete external agent-memory framework should own EngineeringKnowledge;
3. how to preserve provenance, temporal truth, applicability and supersession;
4. how to retrieve technical knowledge efficiently without making a vector database canonical truth;
5. how to defend persistent engineering memory from poisoning;
6. how to support future process types without schema rewrites or parallel knowledge silos;
7. how to keep EngineeringKnowledge advisory rather than executable Authority;
8. how to avoid making accepted deterministic Self-Repair depend on Phase-2 learning infrastructure.

---

## 2. Existing JARVIS baseline

Repository inspection established that JARVIS already owns most of the infrastructure required for Phase 2.

### Engineering persistence

`src/jarvis/incidents/` already provides:

- SQLite/WAL engineering persistence;
- incidents and evidence references;
- durable `RepairAttempt` records;
- immutable repair trigger/policy snapshots;
- policy digests;
- typed verification results;
- component/action history;
- versioned/checksummed engineering-schema migrations.

This should be extended rather than replaced.

### Personal-memory patterns worth reusing

`src/jarvis/memory/` already proves several useful patterns:

- bitemporal `valid_from/valid_to` and `system_from/system_to`;
- immutable supersession/correction semantics;
- source provenance;
- sensitivity classification;
- verification state;
- deterministic lifecycle operations;
- SQL FTS5/BM25 retrieval;
- Qwen3 embeddings pinned to an exact model revision;
- Reciprocal Rank Fusion;
- exact metadata narrowing before ranking;
- evidence gating;
- SQLCipher + DPAPI protection for the separate personal-memory domain.

EngineeringKnowledge is a different canonical domain and must not be merged into personal memory, but these semantics should be reused.

### Existing retrieval model

The accepted memory subsystem already demonstrates:

```text
structured eligibility/filtering
        +
FTS5/BM25 lexical retrieval
        +
Qwen3 dense retrieval
        |
        v
Reciprocal Rank Fusion
```

That is a strong local-first Phase-2 starting point.

---

## 3. External research and technology dispositions

### 3.1 OpenLineage facets — ADAPT STRONGLY

OpenLineage keeps a stable core model while attaching independently versioned facets. Facets identify an immutable schema URL and producer.

Useful JARVIS pattern:

```text
stable EngineeringKnowledge core
        +
versioned typed facets
```

This directly supports future process families without redesigning the canonical core.

Reference:
https://openlineage.io/docs/spec/facets/

### 3.2 JSON Schema 2020-12 — ADOPT AS FACET DESCRIPTION CONTRACT

Use canonical schema identifiers for facet contracts and generate/validate schemas from typed JARVIS models where practical.

The running JARVIS must only make engineering decisions from facet schemas it explicitly understands.

Reference:
https://json-schema.org/specification

### 3.3 W3C PROV — ADAPT SEMANTICS

W3C PROV models provenance using Entity, Activity and Agent relationships.

For JARVIS:

- Entity: evidence, commit, test artifact, device observation, benchmark, knowledge revision;
- Activity: repair, research, test, benchmark, acceptance, production observation;
- Agent: deterministic JARVIS subsystem, model/version, CI, owner, tool/service.

Do not add RDF or a dedicated provenance server merely to conform to PROV. Adopt the semantic model in relational structures.

Reference:
https://www.w3.org/TR/prov-dm/

### 3.4 in-toto Attestation Framework v1.2 — ADAPT STRONGLY

in-toto separates:

- subject;
- typed predicate;
- statement;
- authentication envelope.

This is a strong future-compatible model for JARVIS verification evidence.

Phase 2 should shape internal attestations so later source repair, capability packages and promotion can reuse them.

References:
https://github.com/in-toto/attestation/blob/main/spec/README.md
https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md

### 3.5 RFC 8785 JSON Canonicalization Scheme — ADOPT CONTRACT

Cryptographic digests need an invariant representation across future Python, mobile and server implementations.

Use RFC 8785-compatible canonical JSON before SHA-256 for canonical payload/facet digests.

Reference:
https://www.rfc-editor.org/rfc/rfc8785.html

### 3.6 SQLite FTS5/BM25 — KEEP

FTS5 already provides local BM25 ranking and a trigram tokenizer useful for substring-heavy technical identifiers and error fragments.

Initial Phase 2 should stay on the existing SQLite boundary.

Benchmark trigram indexing only where it measurably improves code/error lookup.

Reference:
https://www.sqlite.org/fts5.html

### 3.7 Qwen3-Embedding-0.6B — KEEP AND BENCHMARK DIMENSIONS

JARVIS already pins Qwen3-Embedding-0.6B.

Published properties relevant to Phase 2 include:

- 0.6B parameters;
- 32K sequence length;
- 1024 maximum embedding dimension;
- Matryoshka/custom-dimension support;
- instruction-aware retrieval;
- multilingual and code retrieval over 100+ languages.

Current JARVIS stores 256-dimensional embeddings. Phase-2 benchmarks should compare 256/512/1024 on the JARVIS corpus rather than changing dimensions by assumption.

Reference:
https://qwenlm.github.io/blog/qwen3-embedding/

### 3.8 Qwen3-Reranker-0.6B — BENCHMARK, DO NOT REQUIRE

The matching reranker can improve precision after first-stage retrieval but adds model cost and latency.

Only evaluate it on a small top-K set after FTS+dense+RRF retrieval. Adopt only if JARVIS-specific evaluation justifies the resource cost.

Reference:
https://qwenlm.github.io/blog/qwen3-embedding/

### 3.9 Qdrant — FUTURE SCALE/DISTRIBUTED DERIVED INDEX

Qdrant provides hybrid dense/sparse retrieval, RRF and multistage reranking. Its documentation also recommends expensive reranking only over a smaller candidate set.

It is not needed for initial Phase 2 because adding a service would create another operational owner before corpus size justifies it.

If used later, Qdrant is a rebuildable derived index, never canonical EngineeringKnowledge.

References:
https://qdrant.tech/documentation/search/hybrid-queries/
https://qdrant.tech/documentation/tutorials-basics/reranking-hybrid-search/

### 3.10 LanceDB — FUTURE EMBEDDED DERIVED INDEX

Potential future local vector/index backend when exact NumPy scans cease to meet JARVIS latency/resource targets.

Do not adopt before the benchmark demonstrates need.

### 3.11 sqlite-vec — WATCH

Attractive because it stays in SQLite, but its pre-v1 status and expected breaking changes make it inappropriate as a Phase-2 correctness dependency.

### 3.12 Graphiti — ADAPT TEMPORAL/PROVENANCE CONCEPTS ONLY

Graphiti demonstrates useful patterns:

- temporal knowledge;
- provenance to source data;
- incremental updates;
- historical queries;
- knowledge-graph retrieval.

Do not make an LLM-extracted graph canonical engineering truth. A future graph should be rebuildable from accepted EngineeringKnowledge.

Reference:
https://github.com/getzep/graphiti

### 3.13 Cognee / Mem0 / Letta / LangGraph memory — DO NOT MAKE CANONICAL OWNER

These systems contain useful agent-memory ideas, but JARVIS already owns:

- canonical persistence;
- lifecycle;
- Authority;
- WorkItems;
- retrieval;
- incidents;
- verification.

Adding another complete memory/orchestration runtime would create overlapping truth ownership.

Use them as pattern/reference sources, not as the Phase-2 control plane.

### 3.14 OWASP Agent Memory Guard — ADAPT SECURITY PATTERNS

Persistent memory is a privileged attack surface. OWASP Agent Memory Guard demonstrates:

- read/write screening;
- quarantine/block/redact policy actions;
- integrity baselines;
- protected-key concepts;
- memory-poisoning benchmarks.

It is an OWASP Incubator project, so JARVIS should adopt the patterns and build them into its own deterministic lifecycle rather than make this tool a canonical dependency.

References:
https://owasp.org/projects/agent-memory-guard
https://github.com/OWASP/www-project-agent-memory-guard

### 3.15 AES-GCM / NIST SP 800-38D — USE FOR OPTIONAL PROTECTED PAYLOADS

If sensitive engineering payloads must be stored, use authenticated encryption while keeping secrets prohibited from EngineeringKnowledge.

Reference:
https://csrc.nist.gov/pubs/sp/800/38/d/final

---

## 4. Final technology disposition

### Keep

- existing engineering SQLite database;
- WAL;
- versioned/checksummed engineering migrations;
- deterministic incident/RepairAttempt evidence;
- SQLite FTS5/BM25;
- Qwen3-Embedding-0.6B;
- RRF;
- OpenTelemetry;
- existing DPAPI key-protection primitive;
- existing Authority boundary.

### Adopt/adapt

- OpenLineage-style independently versioned facets;
- JSON Schema contracts;
- W3C-PROV-style provenance semantics;
- in-toto-style typed attestations;
- RFC-8785-compatible canonical hashing;
- bitemporal/supersession semantics already proven in JARVIS personal memory;
- memory-poisoning quarantine and integrity patterns.

### Benchmark before adoption

- Qwen3-Reranker-0.6B;
- Qwen embedding dimensions 256/512/1024;
- FTS5 trigram path for error/code fragments;
- sqlite-vec;
- LanceDB;
- Qdrant;
- derived knowledge graph.

### Reject as Phase-2 canonical owner

- external full agent-memory framework;
- vector database as source of truth;
- graph database as source of truth;
- arbitrary JSON knowledge with no registered schema;
- LLM confidence as verification;
- unrestricted knowledge-to-execution promotion.

---

## 5. Key architectural research findings

### 5.1 EngineeringKnowledge is not permission

The central invariant is:

```text
knowledge != instruction
knowledge != authority
knowledge != RepairPolicy
knowledge != capability permission

knowledge = reusable evidence-backed engineering understanding
```

Even ACCEPTED knowledge cannot execute an action.

### 5.2 Current process families are not exhaustive

Known consumers today:

1. deterministic repair;
2. unknown investigation/source repair;
3. owner-requested or later autonomously detected capability evolution.

These are initial process types, not a permanent enumeration.

Future process families must plug into the same core through registered contracts.

### 5.3 Stable core + versioned facets is the correct extension model

Do not encode every future domain as columns or SQL enums.

Keep a stable canonical envelope and attach registered versioned facets such as:

- `jarvis.repair.playbook/v1`;
- `jarvis.diagnostic.finding/v1`;
- `jarvis.capability.knowledge/v1`;
- `jarvis.integration.knowledge/v1`;
- future unknown types.

An unknown facet may be preserved but cannot influence decisions until a matching handler/schema is registered.

### 5.4 Revision history should be immutable

Corrections create new revisions.

Previous revisions remain historical evidence.

Use explicit lineage/supersession rather than mutating the past.

### 5.5 Applicability must precede semantic relevance

A semantically similar repair can still be wrong for the current:

- component;
- OS;
- JARVIS revision;
- device;
- firmware;
- dependency;
- environment.

Retrieval must filter applicability before ranking whenever the required constraints are known.

Unknown required applicability fails closed.

### 5.6 Evidence dimensions are better than one confidence score

Do not collapse trust into one floating-point confidence value.

Keep separate:

- source trust;
- verification method;
- verification result;
- applicability;
- freshness;
- lifecycle.

Model confidence may be recorded as diagnostic metadata only.

### 5.7 Initial REPAIR learning can be deterministic

A resolved incident plus a successful typed `RepairAttempt` and verifier result already provides structured evidence.

The first RepairKnowledge candidate projector should not need an LLM.

This saves cost and prevents hallucinated lessons.

### 5.8 Canonical truth must survive index loss

FTS, embeddings, vector indexes and future graphs are derived.

If they fail:

```text
canonical EngineeringKnowledge
        ->
rebuild derived indexes
```

Never the reverse.

### 5.9 Phase-1 deterministic repair must survive Phase-2 failure

If EngineeringKnowledge is unavailable, corrupted or disabled, accepted R2 Self-Repair must continue operating from registered deterministic policies.

No learning component becomes a hard dependency of Loop A.

---

## 6. Security conclusions

### Threats

- prompt/memory poisoning;
- malicious README/web/vendor content;
- untrusted logs containing instructions;
- secret/credential leakage into durable knowledge;
- stale knowledge;
- tampered facets/evidence;
- unknown schemas;
- retrieval of inapplicable knowledge;
- model-generated self-verification;
- knowledge silently becoming execution policy.

### Required controls

- evidence source classification;
- candidate quarantine;
- secret rejection before persistence;
- sensitivity classification;
- canonical content digests;
- lifecycle audit events;
- registered facet schemas;
- provenance;
- independent verification;
- applicability gates;
- integrity checks;
- protected payload encryption only when required;
- Authority remains a separate service.

---

## 7. Protected payload conclusion

Do not convert the accepted Phase-1H engineering incident store wholesale to SQLCipher in Phase 2.

Reason: the deterministic repair loop should not acquire a new SQLCipher/key-availability dependency.

Preferred pattern:

```text
engineering SQLite
  -> canonical non-secret metadata
  -> lifecycle/provenance/digests
  -> sanitized retrieval text

optional protected payload
  -> DPAPI-wrapped master key
  -> per-record/per-revision encryption
  -> AES-GCM authenticated payload
```

Actual secrets remain prohibited and belong to the future SecretBroker.

---

## 8. Retrieval benchmark requirement

Before adding a reranker/vector DB/graph index, create a JARVIS-specific benchmark.

Required query classes:

- exact crash/error signature;
- code symbol;
- paraphrased symptom;
- Hinglish/multilingual query;
- device/firmware/version constraint;
- stale knowledge;
- superseded knowledge;
- contradictory evidence;
- similar-but-inapplicable repair;
- no-safe-answer;
- poisoned evidence;
- secret-like content;
- future unknown facet;
- cross-process retrieval.

Metrics:

- Recall@K;
- Precision@K;
- MRR;
- nDCG;
- no-answer false-positive rate;
- stale-result rate;
- applicability-violation rate;
- protected-data leakage rate;
- p50/p95 latency;
- CPU/RAM/VRAM;
- storage size;
- index rebuild time;
- embedding throughput.

Canonical evaluation should use known relevant IDs/qrels rather than an LLM judge.

---

## 9. Research conclusion

Phase-2 research is complete enough for architecture freeze and implementation.

Chosen direction:

```text
JARVIS-owned canonical EngineeringKnowledge
+ immutable revisions
+ registered versioned facets
+ provenance and attestations
+ bitemporal/applicability semantics
+ existing SQLite/FTS5/Qwen/RRF retrieval
+ deterministic evidence/promotion gates
+ poisoning defenses
+ replaceable derived indexes
```

Do not add another memory brain.

Do not put models in the Authority path.

Do not optimize for hypothetical scale before JARVIS-specific benchmarks prove the need.
