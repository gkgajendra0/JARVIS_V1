# Phase 2 — EngineeringKnowledge Implementation Plan

## Status

**IMPLEMENTED — OWNER-MACHINE ACCEPTED 2026-09-25**

Canonical final acceptance record: `PHASE2_ENGINEERING_KNOWLEDGE_ACCEPTANCE_2026-09-25.md`.

Date: 2026-09-24

This plan translates the approved Phase-2 research and architecture into isolated implementation slices.

Permanent repository governance remains:

```text
research
-> architecture
-> owner approval
-> isolated implementation / PR
-> CI
-> owner-machine acceptance
-> documentation
-> explicit owner merge approval
-> protected-main merge
```

This plan is retained as the implementation/acceptance contract that was executed. Phase 2 is complete for its defined scope.

---

## 1. Base and branch strategy

Canonical base: protected `main`.

Do not continue implementation from the retired Phase-1H working branch.

Recommended implementation branch family:

- `feature/phase2a-engineeringknowledge-core`
- later follow-up branches only if the change remains easier to verify as separate slices.

The current documentation reconciliation should merge before code implementation so the repository itself contains the approved Phase-2 contract.

---

## 2. Implementation sequence

### Phase 2A — Core contracts and schema

Implement:

- EngineeringKnowledge identity;
- immutable revisions;
- lifecycle enums/events;
- evidence and links;
- applicability;
- facet metadata;
- attestation shape;
- content-digest contract.

Add new checksum migration(s) to the existing engineering schema.

Acceptance:

- migration upgrades an existing Phase-1H DB;
- old incident/RepairAttempt data remains readable;
- downgrade/newer-schema conditions fail safely;
- revision immutability is enforced.

### Phase 2B — Registry and versioned facets

Implement:

- `EngineeringKnowledgeFacetRegistry`;
- exact schema registration;
- unknown-facet preservation/fail-closed decision behavior;
- facet validation;
- canonical digesting;
- deterministic searchable-text projection;
- registered applicability matcher boundary.

Initial facet:

- repair playbook/finding v1.

Acceptance:

- known facet validates;
- malformed facet rejects;
- unknown facet persists but is ineligible for decision use;
- facet digest changes when canonical payload changes.

### Phase 2C — Deterministic REPAIR projector

Implement a projector from accepted repair evidence into candidate knowledge.

Input requirements:

- existing incident;
- completed RepairAttempt;
- recovered verdict;
- valid verification result;
- immutable trigger/policy provenance.

No model call.

Acceptance:

- verified repair creates one deterministic candidate;
- failed/inconclusive repair does not create accepted knowledge;
- duplicate projection is idempotent;
- source incident/attempt lineage is exact.

### Phase 2D — Lifecycle and promotion

Implement:

- candidate -> staged;
- staged -> accepted/rejected;
- accepted -> retired/superseded;
- transition audit;
- `KnowledgePromotionPolicy`.

Initial promotion policy is strict and repair-specific.

Acceptance:

- illegal transitions fail;
- model confidence cannot promote;
- rejected/retired records are not current accepted knowledge;
- supersession keeps history.

### Phase 2E — Applicability

Implement registered matchers for initial namespaces:

- JARVIS component;
- platform;
- JARVIS revision identity/range where deterministic;
- package/dependency identity/version where available;
- device/model;
- firmware/protocol with explicit matcher type.

Acceptance:

- exact match works;
- explicit mismatch excludes;
- unresolved required matcher fails closed;
- similar semantic content cannot override an applicability failure.

### Phase 2F — Retrieval

Reuse/adapt proven personal-memory retrieval concepts.

Implement:

- current accepted knowledge view;
- exact lookup;
- FTS5/BM25;
- Qwen embedding storage for knowledge revisions;
- dense ranking;
- RRF;
- deterministic constraints before ranking;
- evidence/provenance result envelope.

Acceptance:

- local-only retrieval;
- FTS-only fallback when embeddings unavailable;
- stale/rejected/retired knowledge excluded;
- retrieval result exposes why it was eligible.

### Phase 2G — Security and protected payload

Implement:

- secret-prohibited admission checks;
- evidence source trust classification;
- quarantine/staging for untrusted extracted knowledge;
- poisoning regression corpus;
- sensitivity filtering;
- integrity validation.

Only if Phase-2 data requires protected payloads, add:

- DPAPI-wrapped master key;
- authenticated AES-GCM record payload;
- associated-data binding to revision/facet/schema identity.

Do not add a whole-DB encryption dependency to deterministic Self-Repair in this phase.

### Phase 2H — Evaluation harness

Build JARVIS EngineeringKnowledge qrel corpus.

Test categories:

- exact crash signature;
- code symbol;
- paraphrase;
- Hinglish/multilingual;
- component/version/device constraints;
- stale/superseded knowledge;
- contradictions;
- similar-but-inapplicable fixes;
- no-answer;
- poisoned evidence;
- secret-like content;
- unknown facet;
- cross-process/future extension cases.

Measure:

- Recall@K;
- Precision@K;
- MRR;
- nDCG;
- false-positive/no-answer rate;
- applicability violations;
- stale-result rate;
- leakage rate;
- latency;
- CPU/RAM/VRAM;
- disk/index rebuild cost.

### Phase 2I — Optional retrieval improvements

Benchmark, do not assume:

- Qwen dimensions 256 vs 512 vs 1024;
- FTS trigram;
- Qwen3-Reranker-0.6B top-K;
- sqlite-vec;
- LanceDB;
- Qdrant.

Adoption rule:

No extra dependency or model is accepted unless the JARVIS benchmark shows a meaningful benefit with acceptable resources and operational complexity.

### Phase 2J — Final acceptance/reconciliation

Run full repository gates plus owner-machine acceptance.

Update:

- CURRENT_ARCHITECTURE only after production acceptance;
- CURRENT_PLAN;
- PROJECT_STATE;
- PRODUCT/ROADMAP if status changes materially;
- Phase-2 acceptance record.

Do not mark Phase 2 done from CI alone.

---

## 3. Expected code layout

Recommended package:

```text
src/jarvis/engineering_knowledge/
    __init__.py
    models.py
    registry.py
    lifecycle.py
    applicability.py
    provenance.py
    attestations.py
    projector.py
    retrieval.py
    security.py
    service.py
```

Persistence remains integrated with the engineering DB migration boundary under `jarvis.incidents` unless implementation evidence shows a cleaner rename/migration is required.

Avoid premature package moves that destabilize accepted Phase-1 Self-Repair imports.

---

## 4. Initial schema direction

Exact DDL is finalized in implementation review, but semantic tables should cover:

- knowledge identity;
- immutable revision;
- facet;
- applicability;
- evidence;
- knowledge-evidence link;
- lifecycle event;
- attestation;
- embedding/derived search metadata if stored in the engineering DB.

Do not encode the current list of future knowledge kinds as a closed SQL enum.

---

## 5. Required tests

### Unit

- typed model validation;
- canonicalization/digests;
- facet registry;
- lifecycle transitions;
- promotion policy;
- applicability;
- projector idempotency;
- secret rejection;
- integrity failure;
- retrieval fusion.

### Migration

- empty DB;
- current Phase-1H DB;
- interrupted migration behavior;
- checksum mismatch;
- schema too new;
- existing RepairAttempt preservation.

### Security

- prompt-injection strings inside evidence;
- protected-field tampering;
- fake owner approval;
- fake verifier claims;
- secret-like values;
- malicious unknown facet;
- poisoned retrieval content.

### Integration

- real Phase-1 repair record -> candidate -> staged/accepted -> retrieval;
- supersession;
- offline/no-model retrieval;
- embedding outage fallback;
- EngineeringKnowledge DB/read failure negative control proving R2 repair independence.

### Performance/evaluation

- qrel retrieval corpus;
- p50/p95;
- CPU/RAM/VRAM;
- index rebuild.

---

## 6. Owner-machine acceptance matrix

Must prove at least:

1. create real repair candidate from accepted repair evidence;
2. inspect exact provenance back to incident/attempt/verifier;
3. promote through allowed lifecycle;
4. retrieve it from a paraphrased query;
5. exact component/version constraints are honored;
6. wrong-applicability knowledge is excluded;
7. superseded knowledge does not appear as current accepted truth;
8. poisoned evidence remains non-authoritative;
9. fake instructions inside evidence do not change Authority;
10. secret-like content is rejected;
11. embeddings disabled -> lexical/exact retrieval still works;
12. EngineeringKnowledge disabled/unavailable -> accepted R2 Self-Repair still recovers;
13. unknown future facet does not crash JARVIS and cannot influence decisions;
14. a second future test facet can be registered without creating a new database/authority path.

---

## 7. Performance budget principle

Do not define arbitrary absolute budgets before measurement.

First capture baseline on the owner machine, then require Phase 2 to remain bounded.

Track:

- startup impact;
- idle RAM;
- embedding model RAM/VRAM;
- retrieval p95;
- write latency;
- migration time;
- DB growth;
- rebuild time.

A retrieval feature that improves relevance but materially harms the production JARVIS baseline may be rejected.

---

## 8. Rollback/failure strategy

Phase-2 code must be additive to accepted Phase-1 behavior.

If new knowledge functionality fails:

- disable EngineeringKnowledge consumer path;
- preserve deterministic repair policies;
- preserve incident/RepairAttempt persistence;
- keep canonical Phase-1 recovery operational.

No Phase-2 migration may silently destroy pre-existing engineering data.

---

## 9. Documentation reconciliation before implementation

This documentation slice must:

- correct the north-star status now that it is on protected main;
- remove the stale reference to missing `REPAIR_KNOWLEDGE_RESEARCH_AND_DESIGN.md`;
- record the full Phase-2 research;
- freeze the owner-approved architecture;
- record this implementation plan;
- explicitly preserve open-ended engineering-process extensibility.

Only after this docs slice is reviewed, CI-clean and explicitly merged should implementation begin from the resulting protected-main head.

---

## 10. Definition of done

Phase 2 is **DONE / OWNER-MACHINE ACCEPTED 2026-09-25**. The completion criteria below were satisfied:

- code exists and passes repository gates;
- migration is proven against accepted data;
- REPAIR first vertical works without an LLM;
- knowledge lifecycle/provenance/applicability/integrity are demonstrated;
- hybrid local retrieval passes the JARVIS evaluation corpus;
- security/poisoning gates pass;
- owner-machine acceptance passes;
- R2 independence negative control passes;
- documentation is reconciled;
- the owner explicitly approves final merge.
