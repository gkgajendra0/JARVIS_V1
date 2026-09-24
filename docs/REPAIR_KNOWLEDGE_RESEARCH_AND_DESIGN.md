# Phase 2 RepairKnowledge Research and Architecture Decision

## Status

**RESEARCH COMPLETE — IMPLEMENTATION DEFERRED UNTIL PHASE 1H SELF-REPAIR FOUNDATION HARDENING IS ACCEPTED**

Research completed: 2026-09-24  
Protected-main baseline reviewed: `7cd4ab241d4706130a82636657da25eaf639d961`

This document preserves the technology and architecture research completed before
implementation of Self-Repair / Self-Evolution Phase 2. It is intentionally a
research/design record only. It does not create execution authority and does not
mark RepairKnowledge as implemented.

The canonical forward program remains
`docs/SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md`.

---

## 1. Question

Before implementing RepairKnowledge, determine whether JARVIS should:

1. build a bespoke engineering-memory layer;
2. adopt an existing case-based reasoning or agent-memory system;
3. wrap an existing technology behind a JARVIS-owned boundary;
4. adopt open standards for provenance and portable procedural knowledge; or
5. change the current Phase-2 architecture before code is written.

The design must preserve existing JARVIS ownership boundaries:

- JARVIS owns canonical incident and repair truth;
- learned knowledge is not executable authority;
- RepairPolicy remains deterministic and version-controlled;
- models may reason over knowledge but cannot promote themselves into execution;
- Loop-B learning failure must never disable deterministic Loop-A runtime repair;
- provider/model/vector/database choices must remain replaceable.

---

## 2. Existing repository constraints

The current accepted foundation already has:

- a separate local operational engineering SQLite database;
- canonical engineering incidents;
- durable `RepairAttempt` records;
- deterministic `RepairPolicy` / `RepairRegistry`;
- Self-Awareness reads over engineering incident history;
- a distinct SQLCipher personal-memory subsystem;
- durable WorkItems/DBOS for orchestration;
- isolated development worktrees and protected-main governance.

Therefore RepairKnowledge must not become:

- another owner of incident truth;
- a second personal-memory subsystem;
- another workflow store;
- an executable RepairPolicy registry;
- a model-owned opaque vector database.

The natural canonical persistence boundary is the existing engineering database,
with RepairKnowledge isolated behind its own service/store/migration surface.

---

## 3. Technology landscape reviewed

### 3.1 Case-Based Reasoning / CBRKit

CBRKit is a Python case-based reasoning toolkit implementing the classic
**Retrieve -> Reuse -> Revise -> Retain** pattern and supporting structured
similarity, BM25, embeddings, evaluation, SQL/vector backends and multiple model
providers.

Sources:

- https://wi2trier.github.io/cbrkit/
- https://github.com/wi2trier/cbrkit
- https://pypi.org/project/cbrkit/

Relevance to JARVIS:

RepairKnowledge is fundamentally a case-based reasoning problem:

```text
new failure
-> represent deterministic failure case
-> retrieve verified prior cases
-> reuse engineering knowledge
-> verify actual repair outcome
-> retain/supersede experience
```

Decision:

**ADOPT THE CBR ARCHITECTURAL PATTERN, DO NOT DEPEND ON CBRKIT YET.**

Reasons:

- current CBRKit 1.6.0 requires Python >=3.13 while JARVIS is >=3.11;
- the project is still marked Beta;
- canonical engineering truth must not depend on one retrieval library;
- exact deterministic matching is required before probabilistic similarity.

JARVIS should define a replaceable `RepairKnowledgeRetriever` boundary so a future
CBRKit adapter can be added without changing canonical storage or lifecycle.

---

### 3.2 ACE — Agentic Context Engineering

ACE treats accumulated experience as an evolving playbook and separates generation,
reflection/curation and deterministic merge mechanics.

Sources:

- https://github.com/rrahimi-uci/agentic-context-engineering
- https://arxiv.org/abs/2510.04618

Useful pattern:

```text
verified outcome
-> reflector proposes lesson/delta
-> curator proposes ADD / REVISE / SUPERSEDE
-> deterministic merge
-> new versioned playbook
```

Decision:

**ADOPT THE INCREMENTAL, VERSIONED, DETERMINISTIC-MERGE PATTERN FOR LATER
CLOSED-LOOP LEARNING.**

A model must never rewrite the full accepted RepairKnowledge corpus in place.
Future AI may propose deltas, but deterministic JARVIS code owns lifecycle,
supersession and final durable state.

---

### 3.3 Agent Skills open format

Agent Skills provides a portable package format centered on `SKILL.md`, references,
assets and optional scripts. The format is increasingly portable across agent
runtimes.

Sources:

- https://github.com/agentskills/agentskills
- https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx
- https://developers.openai.com/api/docs/guides/tools-skills

Decision:

**USE ONLY AS A FUTURE PORTABLE PROJECTION OF ACCEPTED REPAIR KNOWLEDGE.**

Canonical ownership remains:

```text
JARVIS RepairKnowledge
    -> optional read-only renderer
    -> Agent Skills-compatible package
```

Not:

```text
SKILL.md
    -> canonical JARVIS repair truth
```

Initial RepairKnowledge skill projections must prohibit executable scripts and
permission expansion. Knowledge portability must never imply authority portability.

---

### 3.4 Hermes procedural memory / skills

Hermes provides reusable learned procedures/skills and demonstrates a useful
separation between compact memory and longer procedural knowledge.

Source:

- https://github.com/NousResearch/hermes-agent

Decision:

**ADOPT PATTERNS, NOT THE HERMES RUNTIME.**

JARVIS already owns orchestration, memory, Authority, incidents and repair policy.
Embedding Hermes as a second orchestration/authority owner would duplicate truth.

---

### 3.5 W3C PROV

W3C PROV models provenance through entities, activities, agents and explicit
derivation relationships.

Sources:

- https://www.w3.org/TR/prov-primer/
- https://www.w3.org/TR/prov-overview/

Decision:

**ADOPT THE SEMANTIC MODEL, NOT RDF/PROV INFRASTRUCTURE.**

RepairKnowledge should record explicit relationships such as:

```text
knowledge derived_from incident
knowledge generated_by verified repair attempt
knowledge supported_by verifier evidence
knowledge supersedes prior knowledge
repair attempt used policy/version
verification generated evidence
```

This is stronger than opaque provenance JSON.

---

### 3.6 in-toto / SLSA provenance

in-toto and SLSA provide software supply-chain provenance and attestations describing
what produced an artifact, what inputs were used and how it was built.

Sources:

- https://in-toto.io/
- https://slsa.dev/spec/v1.2/provenance

Decision:

**PREPARE THE EVIDENCE SCHEMA FOR FUTURE ATTESTATION REFERENCES; INTEGRATE LATER
DURING SOURCE-REPAIR / DEPLOYMENT PHASES.**

RepairKnowledge evidence should be capable of referencing immutable artifact digests,
commits, tests and future attestations without a schema redesign.

---

### 3.7 Graphiti / Zep temporal knowledge graph

Graphiti provides temporal knowledge graphs combining graph, lexical and semantic
retrieval.

Sources:

- https://github.com/getzep/graphiti
- https://help.getzep.com/graphiti/

Decision:

**DEFER.**

It introduces unnecessary graph/model/embedding infrastructure for the current
RepairKnowledge corpus. Re-evaluate when JARVIS has a large connected body of
components, failures, skills, versions, models and benchmarks where graph traversal
provides measurable value.

---

### 3.8 Mem0 / Letta / NeMo memory

These systems are primarily agent/user/conversation or archival memory frameworks.

Sources:

- https://mem0.ai/
- https://docs.letta.com/
- https://docs.nvidia.com/nemo/microservices/latest/manage/memory.html

Decision:

**DO NOT USE FOR CANONICAL REPAIRKNOWLEDGE.**

Engineering repair truth must not become model-managed conversational memory.

---

### 3.9 sqlite-vec and external vector databases

sqlite-vec is attractive because it can add local vector search inside SQLite, but it
remains pre-v1 and vector retrieval is not required for Phase 2 correctness.

Source:

- https://github.com/asg017/sqlite-vec

Decision:

**DEFER VECTOR RETRIEVAL.**

Qdrant/other separate vector services are also unnecessary for the current scale.
Semantic retrieval should remain a rebuildable/replaceable index over canonical
RepairKnowledge.

---

### 3.10 EXAR

EXAR is described as a unified experience-grounded agentic reasoning architecture
from the CBRKit research group.

Source:

- https://github.com/wi2trier/exar

At research time the repository is essentially an early skeleton and not mature
enough to adopt.

Decision:

**WATCH, DO NOT DEPEND ON IT.**

---

## 4. Revised canonical Phase-2 architecture

```text
                 JARVIS ENGINEERING EXPERIENCE
                            |
             +--------------+---------------+
             |                              |
         Incident                     RepairAttempt
             |                              |
             +--------------+---------------+
                            |
                     Provenance Graph
                   (relational, PROV-like)
                            |
                            v
                    RepairKnowledge
               canonical immutable version
                            |
          +-----------------+------------------+
          |                 |                  |
      signature          playbook          verifier
          |                 |                  |
          +-----------------+------------------+
                            |
                       lifecycle
         CANDIDATE -> STAGED -> ACCEPTED
              |          |        |
           REJECTED   REJECTED  RETIRED
                            |
                            v
                   Retrieval Boundary
                            |
       +--------------------+--------------------+
       |                    |                    |
   exact match       CBR-style similarity    FTS5/BM25
       |                    |                    |
       +--------------------+--------------------+
                            |
                            v
              Accepted knowledge result
                            |
            +---------------+-----------------+
            |                                 |
      DiagnosticModelRouter             Skill Renderer
         Phase 3 later              Agent Skills-compatible
```

The first implementation must remain completely usable without an LLM, embeddings,
network access or an external database.

---

## 5. Canonical RepairKnowledge contract

Recommended semantic fields:

```text
RepairKnowledge
- knowledge_id
- lineage_id
- version
- lifecycle
- component_id
- failure_signature
  - trigger_source
  - component_id
  - reason_code
  - health_states
- failure_signature_hash
- symptom_summary
- diagnosis_summary
- repair_sequence[]
- verification_contract
- required_capabilities[]
- evidence_grade
- confidence?                 # advisory only
- content_hash
- supersedes_knowledge_id?
- superseded_by_knowledge_id?
- created_at
- updated_at
```

Provenance must be normalized rather than embedded as one opaque blob.

Required provenance/evidence classes should support:

- Incident;
- RepairAttempt;
- incident evidence;
- verifier evidence;
- policy/version snapshot;
- commit SHA;
- pull request;
- regression test;
- deployment result;
- future in-toto/SLSA attestation.

---

## 6. Lifecycle and anti-resurrection rules

Allowed transitions:

```text
CANDIDATE -> STAGED
CANDIDATE -> REJECTED

STAGED -> ACCEPTED
STAGED -> REJECTED

ACCEPTED -> RETIRED
```

`REJECTED` and `RETIRED` are terminal for that immutable knowledge version.

Each transition must append durable history containing:

- from_state;
- to_state;
- reason;
- decision/provenance reference;
- timestamp.

Duplicate detection uses deterministic normalized content/signature hashes.

Exact duplicate behavior:

```text
same content_hash
-> do not create duplicate knowledge
-> attach additional provenance where valid
```

A repeated observation must not silently reactivate `REJECTED` or `RETIRED`
knowledge.

Supersession is explicit and versioned. A new candidate does not retire an accepted
version until the newer version independently reaches `ACCEPTED`.

---

## 7. Candidate creation rule

The deterministic verified path should require at minimum:

```text
Incident
  resolved/closed
  root_cause present
  accepted_fix present

+

RepairAttempt
  same incident
  completed
  verdict = RECOVERED
  deterministic verifier proof present

+

immutable policy/trigger provenance

-> RepairKnowledge CANDIDATE
```

Phase-1H must first strengthen historical RepairAttempt provenance and verifier
semantics so Phase 2 does not learn from weak evidence.

No model confidence score can substitute for the above proof.

---

## 8. Retrieval strategy

Progressive retrieval should be:

### Tier 1 — exact deterministic signature

- component;
- trigger source;
- reason code;
- health state;
- environment/version constraints where applicable.

### Tier 2 — structured case similarity

Weighted deterministic similarity over stable case fields.

### Tier 3 — SQLite FTS5/BM25

Search symptom, diagnosis and playbook text locally.

SQLite FTS5 is already sufficient for this secondary retrieval tier:

- https://www.sqlite.org/fts5.html

### Tier 4 — semantic/vector retrieval

Only after an evaluation corpus demonstrates added value.

Possible future adapters:

- CBRKit;
- sqlite-vec;
- LanceDB;
- another replaceable local/vector implementation.

Semantic indexes remain rebuildable derivatives, never canonical truth.

---

## 9. Execution/authority boundary

The most important invariant:

```text
RepairKnowledge
    helps diagnosis/reasoning

RepairKnowledge
    != RepairPolicy
    != ActionPermit
    != Authority
```

Even `ACCEPTED` RepairKnowledge cannot:

- create a RepairAction;
- register itself as RepairPolicy;
- lower risk;
- expand permissions;
- execute shell/process/Git mutations;
- merge/deploy itself.

Promotion into an executable RepairPolicy is a separate version-controlled
engineering change with tests, review and repair-policy acceptance.

This boundary is reinforced by current recovery research showing that accurate root
cause identification does not imply valid recovery action selection.

R2Act reference:

- https://arxiv.org/abs/2607.04623

---

## 10. Failure isolation

RepairKnowledge belongs to Loop B. Loop B must not become a dependency of Loop A.

Therefore:

```text
RepairKnowledge store/migration/retrieval failure
-> RepairKnowledge unavailable
-> deterministic existing R1/R2 repair continues
```

The implementation should use the same engineering database file where appropriate
for relational provenance, but RepairKnowledge initialization/migration/service
failure must be isolated from the existing runtime repair controller.

---

## 11. Technology decisions

| Technology / concept | Decision |
| --- | --- |
| SQLite engineering DB | USE as canonical Phase-2 persistence boundary |
| Case-Based Reasoning | ADOPT as core retrieval/learning model |
| CBRKit | DESIGN adapter boundary; do not depend on it yet |
| SQLite FTS5/BM25 | USE for secondary local textual retrieval |
| W3C PROV concepts | ADOPT semantic provenance relationships |
| in-toto / SLSA | PREPARE evidence references; integrate later |
| ACE | ADOPT deterministic incremental playbook-evolution pattern later |
| Agent Skills | future read-only portable projection |
| Hermes | borrow procedural-memory patterns only |
| Graphiti/Zep | DEFER |
| Mem0/Letta/NeMo memory | DO NOT use as canonical RepairKnowledge |
| sqlite-vec / vector DB | DEFER until measured need |
| EXAR | WATCH |

---

## 12. Implementation readiness decision

The Phase-2 architecture research is complete enough to implement without another
technology-selection round.

However implementation is intentionally **blocked** until Phase 1H hardening is
accepted because the Phase-1 audit found weaknesses in:

- restart-budget reset semantics;
- aggregate target-level circuit breaking;
- typed verifier proof;
- deterministic precondition evaluation;
- historical policy/trigger provenance;
- operational engineering DB migrations;
- Windows process-tree ownership;
- supervisor survivability;
- production supervisor separation from Git development/update duties.

RepairKnowledge must not learn from or build authority-adjacent behavior on top of
weak repair evidence.

---

## 13. Phase-2 implementation gate after Phase 1H

Only after Phase 1H acceptance:

1. define RepairKnowledge domain objects;
2. add engineering-DB migrations;
3. add normalized provenance;
4. implement lifecycle/history;
5. implement deterministic duplicate/supersession semantics;
6. implement exact + structured + FTS retrieval;
7. create candidates from verified historical repairs;
8. prove accepted knowledge cannot execute or mutate RepairPolicy;
9. add repository acceptance tests;
10. owner-machine acceptance;
11. reconcile canonical docs;
12. proceed to DiagnosticModelRouter only after independent Phase-2 acceptance.
