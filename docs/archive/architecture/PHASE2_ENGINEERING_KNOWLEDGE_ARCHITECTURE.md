# Phase 2 — EngineeringKnowledge Architecture

## Status

**OWNER-APPROVED ARCHITECTURE — 2026-09-24**

This document freezes the Phase-2 architecture before implementation.

Research basis: `PHASE2_ENGINEERING_KNOWLEDGE_RESEARCH.md`.

Implementation sequence: `PHASE2_ENGINEERING_KNOWLEDGE_IMPLEMENTATION_PLAN.md`.

---

## 1. Goal

Build one durable, extensible engineering-knowledge substrate that lets JARVIS reuse verified engineering lessons across:

- known repair;
- unknown investigation/source repair;
- capability acquisition;
- future engineering process families not known today.

The architecture must improve engineering intelligence without creating new execution authority.

---

## 2. Non-negotiable invariants

1. **EngineeringKnowledge is advisory, never executable Authority.**
2. **Accepted deterministic Self-Repair must work when EngineeringKnowledge is unavailable.**
3. **Canonical truth is JARVIS-owned.**
4. **Models may propose/extract/summarize; deterministic contracts own admission, lifecycle, verification and eligibility.**
5. **External research is evidence, not accepted truth by default.**
6. **Secrets are prohibited from EngineeringKnowledge.**
7. **Unknown facet schemas fail closed for decision use.**
8. **Derived indexes/graphs are rebuildable and never canonical.**
9. **Historical revisions are immutable.**
10. **Future process families plug into shared contracts rather than create parallel knowledge/authority systems.**

---

## 3. Architecture

```text
                      ENGINEERING KNOWLEDGE CORE
                               |
             +-----------------+-----------------+
             |                                   |
        STABLE CORE                        VERSIONED FACETS
             |                                   |
  identity / revision                     repair.*
  lifecycle                               diagnostic.*
  provenance                              capability.*
  bitemporal state                        integration.*
  applicability                           architecture.*
  verification                            evaluation.*
  sensitivity                             operations.*
  integrity                               future.*
             |                                   |
             +-----------------+-----------------+
                               |
                     CANONICAL SQLITE STORE
                               |
             +-----------------+-----------------+
             |                 |                 |
         exact/index        FTS5/BM25       Qwen embeddings
             |                 |                 |
             +------------ retrieval/RRF --------+
                               |
                  applicability + evidence gate
                               |
              consumers / engineering processes
```

---

## 4. Stable canonical objects

### 4.1 EngineeringKnowledgeIdentity

Represents one logical knowledge item across revisions.

Required fields:

- `knowledge_id`;
- `created_at`;
- `created_by`;
- optional human-readable stable label.

### 4.2 EngineeringKnowledgeRevision

Immutable revision of one logical knowledge item.

Required fields:

- `revision_id`;
- `knowledge_id`;
- `revision_number`;
- parent/supersession lineage;
- `kind_namespace`;
- normalized summary/search text;
- `valid_from`, `valid_to`;
- `system_from`, `system_to`;
- lifecycle state;
- sensitivity;
- freshness/revalidation state;
- canonical digest;
- creation provenance.

A correction creates a new revision.

### 4.3 EngineeringKnowledgeFacet

Versioned extension payload attached to a revision.

Required fields:

- `revision_id`;
- `facet_type`;
- `schema_id`;
- `schema_version`;
- `schema_digest`;
- `producer`;
- `payload` or protected-payload reference;
- `payload_digest`.

The stable core does not need to know every future facet type.

### 4.4 EngineeringApplicability

Describes when a knowledge revision may be used.

Examples of target namespaces:

- JARVIS component;
- platform/OS;
- JARVIS revision;
- package/dependency;
- device model;
- firmware;
- protocol/API version;
- capability ID;
- environment/profile.

Required applicability constraints fail closed when unresolved.

### 4.5 EngineeringEvidence

Canonical reference to evidence.

Evidence examples:

- incident;
- RepairAttempt;
- runtime observation;
- verifier result;
- repository commit;
- PR;
- CI run;
- test artifact;
- benchmark;
- owner acceptance;
- vendor/standard documentation;
- web research.

Each item records source class, canonical reference, timestamps, sensitivity and integrity metadata.

### 4.6 KnowledgeEvidenceLink

Typed relationship between a revision and evidence.

Initial link types:

- `SUPPORTS`;
- `REFUTES`;
- `DERIVED_FROM`;
- `VERIFIED_BY`;
- `ACCEPTED_BY`;
- `OBSERVED_IN_PRODUCTION`.

### 4.7 EngineeringAttestation

Typed verification statement compatible in spirit with in-toto:

- subject;
- subject digest;
- predicate type;
- producer/verifier;
- expected contract;
- observed result;
- verdict;
- timestamps;
- evidence references.

Phase 2 need not sign attestations yet, but the model must be future-compatible.

### 4.8 KnowledgeLifecycleEvent

Append-only lifecycle audit.

Initial states:

```text
CANDIDATE
   |
   v
STAGED
   |
   +--> REJECTED
   |
   v
ACCEPTED
   |
   +--> RETIRED
   |
   +--> SUPERSEDED
```

Transitions require deterministic policy and evidence.

---

## 5. Facet registry

Introduce a `EngineeringKnowledgeFacetRegistry`.

Each registered facet handler defines:

- facet type/name;
- exact supported schema ID/version;
- parser/validator;
- canonicalization rules;
- duplicate/conflict key logic where applicable;
- applicability extraction;
- safe searchable text projection;
- protected fields;
- revalidation rules.

An unknown facet:

- may remain stored/preserved;
- may not be used to make engineering decisions;
- may not be promoted based on unknown semantics;
- must not crash retrieval of known facets.

Initial registered family:

`jarvis.repair.*`

Future families plug into the registry.

---

## 6. Open-ended process extensibility

Process types and knowledge facets are separate concerns.

A future engineering process may reuse existing knowledge facets or define new ones.

The shared substrate remains:

- EngineeringKnowledge;
- WorkItems;
- Authority;
- provenance;
- verification;
- promotion;
- acceptance.

Adding a future process must not require a new memory database or new authority system.

---

## 7. REPAIR first vertical

The first Phase-2 vertical is deterministic repair knowledge.

Input:

```text
resolved engineering incident
+ RepairAttempt
+ immutable trigger/policy snapshots
+ verification result
+ recovered verdict
```

Projector:

```text
typed deterministic projector
        |
        v
RepairKnowledge CANDIDATE
```

No LLM is required to create the initial candidate.

The repair facet should capture:

- component;
- trigger/failure signature;
- policy/action identity;
- preconditions;
- successful engineering sequence;
- verification contract/result;
- applicability;
- required resources;
- source incident/attempt;
- JARVIS revision/environment;
- replay/revalidation information.

---

## 8. Promotion policy

Introduce `KnowledgePromotionPolicy`.

Initial principle:

A record may become ACCEPTED only when required evidence is present and no blocking contradiction/applicability uncertainty exists.

Evidence dimensions remain separate:

- source trust;
- verification method;
- verification result;
- applicability;
- freshness;
- lifecycle.

A model confidence number never determines promotion.

Accepted advisory knowledge still has no execution permit.

Any transformation from knowledge into a `RepairPolicy`, capability or protected source change is a separate governed engineering change.

---

## 9. Provenance

Adopt W3C-PROV semantics without requiring RDF.

Conceptual mapping:

```text
Entity:
  evidence / artifact / knowledge revision

Activity:
  repair / research / test / benchmark /
  acceptance / production observation

Agent:
  owner / deterministic JARVIS subsystem /
  model+version / CI / tool / service
```

Provenance must answer:

- why does JARVIS believe this;
- where did it come from;
- what produced it;
- what verified it;
- what code/device/environment did it apply to;
- what superseded/refuted it later.

---

## 10. Temporal model

Use the bitemporal pattern already proven in JARVIS memory:

- valid time: when the knowledge is applicable in the engineering world;
- system time: when JARVIS learned/recorded/superseded it.

Do not delete old truth merely because a newer revision exists.

---

## 11. Integrity

Canonical payload/facet digests use:

```text
RFC-8785-compatible JSON canonicalization
        ->
SHA-256
```

Store algorithm/canonicalization identifiers with the digest where needed.

Integrity mismatch fails closed.

---

## 12. Retrieval

Initial retrieval pipeline:

```text
query/context
  |
  v
lifecycle + sensitivity filter
  |
  v
applicability filter
  |
  +--> exact identifier/signature retrieval
  |
  +--> FTS5/BM25
  |
  +--> Qwen dense retrieval
          |
          v
        RRF
          |
          v
optional benchmark-proven reranker
          |
          v
evidence/provenance eligibility gate
```

Initial backend:

- existing SQLite;
- FTS5;
- Qwen3-Embedding-0.6B;
- exact NumPy similarity;
- RRF.

Future vector/graph indexes sit behind a replaceable adapter and are rebuildable from canonical data.

---

## 13. Security model

### Admission

External evidence is untrusted until classified and validated.

Flow:

```text
raw evidence
 -> source classification
 -> secret rejection/redaction
 -> poisoning/instruction-aware screening
 -> candidate extraction/projector
 -> CANDIDATE
 -> verification/staging
 -> promotion policy
```

### Secrets

Passwords, tokens, API keys and credentials must not enter EngineeringKnowledge.

Future SecretBroker owns secret material.

### Sensitive payloads

Do not make Phase-1 repair depend on SQLCipher.

If Phase-2 facets need protected content:

- store canonical non-secret metadata in engineering SQLite;
- store encrypted payload using a DPAPI-protected master key and authenticated encryption;
- bind ciphertext to revision/facet/schema identity using associated data.

### Authority

Knowledge retrieval cannot mint or lower permissions.

Authority remains the only action authorization boundary.

---

## 14. Failure behavior

Required degradation behavior:

- embeddings unavailable -> exact + FTS retrieval remains;
- reranker unavailable -> RRF remains;
- optional protected payload unavailable -> sensitive detail omitted/fails closed;
- cloud provider unavailable -> accepted local knowledge still retrievable;
- derived index corrupt -> rebuild from canonical SQLite;
- EngineeringKnowledge unavailable -> deterministic registered Self-Repair remains functional.

---

## 15. Observability

Reuse OpenTelemetry.

Important event families:

- candidate created;
- staged;
- accepted;
- rejected;
- retired/superseded;
- retrieval;
- applicability rejection;
- integrity failure;
- protected-payload failure;
- promotion decision.

Do not log secrets or unredacted sensitive payloads.

---

## 16. Explicit non-goals for Phase 2

Phase 2 does not implement:

- DiagnosticModelRouter;
- unknown-incident AI diagnosis;
- autonomous source repair;
- EngineeringChange lifecycle;
- DependencyBroker;
- SecretBroker;
- dynamic capability package lifecycle;
- autonomous capability acquisition;
- automatic protected-main merge/deploy;
- self-evolution;
- a mandatory vector database;
- a mandatory graph database.

It builds the shared knowledge substrate those later phases will consume.

---

## 17. Phase-2 architecture exit criteria

Architecture implementation is acceptable only when:

1. verified repair outcomes can deterministically create provenance-linked candidates;
2. lifecycle transitions are deterministic/auditable;
3. unknown facet semantics fail closed;
4. immutable revisions and supersession work;
5. applicability excludes wrong version/device/environment knowledge;
6. accepted knowledge is retrievable through local hybrid retrieval;
7. rejected/retired/superseded knowledge cannot silently return as current accepted truth;
8. poisoned/untrusted evidence cannot gain authority;
9. secrets cannot be admitted;
10. integrity corruption is detected;
11. EngineeringKnowledge outage cannot break accepted R2 Self-Repair;
12. the schema can add a future knowledge/process family without creating a parallel silo.
