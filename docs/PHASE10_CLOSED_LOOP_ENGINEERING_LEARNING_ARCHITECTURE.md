# Phase 10 — Closed-Loop Engineering Learning Architecture

## Status

**OWNER APPROVED — 2026-09-28**

This architecture is subordinate to:

1. `AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md`;
2. `UNIVERSAL_KNOWLEDGE_AND_DISCOVERY_MASTER_PLAN.md`;
3. `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`.

It does not broaden Authority and does not implement Phase 10A.

## 1. Architectural objective

Create one deterministic bridge from canonical engineering outcomes to
EngineeringKnowledge without introducing another work engine, knowledge database,
agent framework, authority system or observability truth.

```text
RepairAttempt / PromotionAttempt / ProductionObservation /
CapabilityCompatibility / Acquisition evidence
        |
        v
OutcomeSourceAdapter
        |
        v
EngineeringOutcomeV1
        |
        v
EngineeringLearningEligibilityPolicy
        |
        v
EngineeringLearningProjector
        |
        v
EngineeringKnowledgeCandidateBundle
        |
        v
EngineeringKnowledge lifecycle / supersession
        |
        v
existing EngineeringKnowledge retrieval
```

## 2. Permanent invariants

1. EngineeringKnowledge remains advisory truth, never execution Authority.
2. Phase 10 cannot deploy, enable, disable, merge, approve or mutate production.
3. Safety actions such as rollback never depend on successful learning.
4. Only canonical persisted evidence may create verified learning.
5. Model confidence cannot create verified truth.
6. Unknown/inconclusive attribution fails closed.
7. External provider/hardware failures cannot be silently blamed on a candidate.
8. All learned records preserve exact provenance, evidence and applicability.
9. Knowledge revisions remain immutable.
10. Contradiction is represented by a new revision and lifecycle supersession, not row mutation.
11. Replaying the same source outcome is idempotent.
12. Learning remains restart-safe and can reconcile missed terminal outcomes.
13. Existing Phase 2/6/7/8/9 canonical stores remain the source of truth for their domains.
14. No Phase-10 object may become a second canonical release/package/work/authority record.
15. Phase 10 remains engineering-specific; it must not prematurely become the Universal
    Knowledge Fabric.
16. New facet schemas are registered and fail closed if unknown.
17. Applicability is narrow by default; unsupported generalization is prohibited.
18. Accepted negative evidence is first-class knowledge, not discarded history.

## 3. New package boundary

Introduce `jarvis.engineering_learning`.

This package owns the learning pipeline only. It depends on existing canonical systems
but none depend on it for safety-critical completion.

Expected modules:

```text
engineering_learning/
  __init__.py
  models.py
  facets.py
  policy.py
  adapters.py
  projector.py
  lifecycle.py
  reconciliation.py
  evaluation.py
```

The exact module split may evolve while preserving the contracts in this document.

## 4. EngineeringOutcomeV1

`EngineeringOutcomeV1` is a normalized immutable observation of one exact engineering
subject.

Required identity/lineage fields:

- outcome_id;
- source_kind;
- source_identity;
- subject_type;
- subject_id;
- subject_digest;
- change_id when applicable;
- candidate_id/digest when applicable;
- release_sha/package identity when applicable;
- result;
- attribution;
- reason_codes;
- evidence references;
- applicability facts;
- observed_at_epoch;
- producer/schema version.

Outcome IDs are deterministic from canonical source identity + subject digest + schema
version so replay produces the same identity.

### Result vocabulary

Initial result classes:

- SUCCESS;
- FAILURE;
- BLOCKED;
- ROLLED_BACK;
- INCONCLUSIVE.

### Attribution vocabulary

Initial attribution classes:

- CANDIDATE;
- EXTERNAL_PROVIDER;
- EXTERNAL_HARDWARE;
- ENVIRONMENT;
- COMPATIBILITY;
- UNKNOWN;
- NOT_APPLICABLE.

Adapters must map only evidence they can prove. They may not infer a stronger causal
attribution than the source provides.

## 5. Outcome source adapters

Adapters normalize existing canonical records and must remain read-only.

Initial sources:

### PromotionOutcomeAdapter

Consumes Phase-7 PromotionAttempt, production_observation artifacts and deployment /
rollback metadata.

Produces:

- verified production success;
- candidate-local production regression;
- external-provider/hardware blocker evidence;
- unknown/inconclusive evidence;
- rollback outcome.

### RepairOutcomeAdapter

Consumes verified RepairAttempt / incident records.

Reuses existing repair knowledge semantics rather than duplicating the Phase-2 repair
projector. Phase 10 may reference this outcome lineage but must preserve the accepted
repair projector as canonical for repair-finding knowledge unless architecture evidence
later justifies consolidation.

### CapabilityCompatibilityOutcomeAdapter

Consumes exact Phase-8 compatibility reports and package/release identity.

Produces exact READY/BLOCKED/RESTART_REQUIRED compatibility outcome evidence.

### AcquisitionOutcomeAdapter

Consumes Phase-9 acquisition lineage where a terminal verified candidate/package outcome
exists. It must not claim the deferred Phase-9 real external lifecycle was proven.

## 6. Learning facets

Add registered engineering facets rather than a new knowledge database.

### `jarvis.engineering.outcome` v1

Captures the exact engineering subject, result, reason codes, verification/observation
summary and lineage.

### `jarvis.engineering.regression` v1

Captures verified negative evidence such as a candidate-local production failure,
verification failure or rollback cause. It is accepted knowledge when evidence is
strong enough, even though the candidate failed.

### `jarvis.engineering.compatibility` v1

Captures exact compatible/incompatible relationships and constraints.

These facets remain engineering-domain objects. Future Universal Knowledge Fabric work
may compose or project them; it must not be assumed that all cross-domain knowledge will
use these facet types.

## 7. Learning eligibility

`EngineeringLearningEligibilityPolicy` is deterministic.

It returns:

- eligible / ineligible;
- disposition;
- reason codes;
- required evidence IDs;
- whether supersession evaluation is permitted.

Initial dispositions:

- POSITIVE;
- NEGATIVE;
- COMPATIBILITY;
- INCONCLUSIVE;
- IGNORE.

Examples:

- production healthy + exact release/candidate + required observation -> POSITIVE;
- candidate-local failure + exact candidate + rollback/observation evidence -> NEGATIVE;
- external provider/hardware failure -> INCONCLUSIVE for candidate causality;
- compatibility READY/BLOCKED with exact report digest -> COMPATIBILITY;
- UNKNOWN attribution -> INCONCLUSIVE.

No model invocation is required for this policy.

## 8. Projection

`EngineeringLearningProjector` creates an
`EngineeringKnowledgeCandidateBundle`.

Projection must include:

- stable knowledge identity;
- immutable revision;
- one or more registered learning facets;
- exact applicability;
- immutable EngineeringEvidence references;
- evidence links;
- attestation(s);
- CANDIDATE lifecycle event.

Knowledge IDs should be stable around the reusable engineering proposition, while
revision IDs include revision number/subject/evidence identity. Exact formulas are
implementation details but must be deterministic and test-covered.

## 9. Lifecycle and supersession

Introduce an engineering-learning lifecycle policy layered on the existing
`KnowledgeLifecycleService` primitives.

Promotion to ACCEPTED requires:

- registered facet schemas;
- integrity-valid candidate;
- required evidence;
- supported applicability;
- non-inconclusive learning disposition;
- subject/evidence digests bound to the projected revision.

Supersession is allowed only when:

1. both old and new revisions refer to the same stable knowledge identity;
2. new verified evidence materially contradicts or narrows the older accepted proposition;
3. the new revision is ACCEPTED first;
4. the old revision is then transitioned to SUPERSEDED with evidence linking the reason.

No accepted revision is edited in place.

## 10. Reconciliation

`EngineeringLearningReconciler` is a narrow restart-safe learning reconciler.

It may:

- scan bounded terminal engineering outcomes;
- normalize them;
- idempotently project missing knowledge candidates;
- advance deterministic knowledge lifecycle transitions where policy permits;
- report blockers/inconclusive outcomes.

It may not:

- create arbitrary engineering projects;
- prioritize portfolio work;
- detect general capability gaps;
- alter Authority;
- mutate production.

Those are Phase 10A/11 concerns.

## 11. Retrieval integration

Phase 10 does not create a new retrieval system.

Accepted current learning is indexed by the existing EngineeringKnowledge retrieval
pipeline. Rejected, retired and superseded revisions remain historical evidence but
must not return as current accepted truth.

Future Phase-6/engineering research may retrieve:

- successful precedent;
- failed candidate/regression precedent;
- exact compatibility precedent.

Retrieved knowledge remains advisory.

## 12. Failure isolation

Learning is downstream of operational safety.

```text
production failure
   -> rollback / safe recovery completes
   -> engineering lifecycle records canonical outcome
   -> learning reconciler attempts learning
```

If projection, indexing or lifecycle promotion fails:

- the canonical operational outcome remains intact;
- rollback remains intact;
- the failure is observable;
- reconciliation may retry later;
- no safety gate is weakened.

## 13. Evidence hierarchy

Primary canonical evidence:

1. typed JARVIS lifecycle stores and immutable artifacts;
2. verifier/acceptance outputs bound to exact subject digest;
3. deployment/rollback/package compatibility records.

Supporting evidence:

- OperationalEvent;
- OpenTelemetry traces/metrics/logs;
- bounded local evidence queries.

Supporting telemetry may strengthen context but cannot override canonical lifecycle
identity or attribution.

## 14. Acceptance boundary

Phase 10 is complete only when deterministic replay and owner-machine acceptance prove:

- verified success creates accepted retrievable learning;
- candidate-local failure creates accepted negative knowledge;
- external failures do not poison candidate knowledge;
- unknown attribution fails closed;
- exact compatibility outcomes create scoped compatibility knowledge;
- contradiction produces immutable successor + SUPERSEDED prior revision;
- restart/replay creates no duplicates;
- tampered/missing evidence fails closed;
- superseded/rejected knowledge cannot silently become current;
- existing Phase 2/6/7/8/9 regressions stay green;
- downstream engineering retrieval can consume Phase-10 learning without gaining Authority.

## 15. Future Knowledge Fabric compatibility

Phase 10 is the engineering-specific mature example of verified experience-derived
knowledge.

It must preserve concepts useful to the future Universal Knowledge Fabric:

- normalized claims;
- evidence/provenance;
- time/freshness;
- assumptions/applicability;
- supporting/contradicting evidence;
- verification state;
- supersession history.

It must not force the future universal system to use EngineeringKnowledge as its only
canonical storage model.
