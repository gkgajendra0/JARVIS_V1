# Phase 10 — Closed-Loop Engineering Learning Research

## Status

**OWNER-APPROVED RESEARCH BASIS — 2026-09-28**

This document records the repository inspection and technology research used to design
Phase 10. It is research evidence, not an implementation bypass and not execution
Authority.

## 1. Required outcome

The authoritative master plan defines Phase 10 narrowly:

> Production outcomes update/supersede EngineeringKnowledge, regressions and
> compatibility knowledge. Failed candidates remain useful negative evidence.

Phase 10 therefore closes the governed engineering loop:

```text
research -> architecture -> development -> verification -> promotion
-> production observation -> verified engineering learning -> future reuse
```

It does not create the Phase-10A autonomous operations controller and does not create
autonomous improvement work. Those remain later phases.

## 2. Repository findings

The repository already contains most of the hard substrate needed for Phase 10.

### EngineeringKnowledge already provides

- immutable identities and revisions;
- parent/supersedes revision links;
- lifecycle states CANDIDATE, STAGED, ACCEPTED, REJECTED, RETIRED, SUPERSEDED;
- bitemporal validity/system time;
- freshness/revalidation state;
- registered versioned facets;
- applicability contracts;
- immutable evidence with provenance/integrity;
- typed evidence links;
- typed attestations with PASS/FAIL/INCONCLUSIVE;
- poisoning/integrity gates;
- local hybrid retrieval;
- deterministic repair knowledge projection and promotion.

The engineering SQLite schema enforces immutability with update/delete-blocking triggers.

### Existing canonical outcome sources

Phase 10 can learn from existing canonical sources rather than inventing new telemetry
truth:

- Phase 1 / self-repair: RepairAttempt and verifier outcome;
- Phase 6: diagnosis, architecture, candidate and exact source revision evidence;
- Phase 7: PromotionAttempt, exact candidate/release identity, ProductionObservation,
  failure attribution, rollback and deployment metadata;
- Phase 8: exact CapabilityCompatibilityReportV1 and lifecycle outcomes;
- Phase 9: owner capability acquisition candidate/package/promotion lineage;
- observability: OperationalEvent, LocalOperationalEvidenceQuery and existing
  OpenTelemetry adapters.

The missing component is a deterministic outcome-to-knowledge learning pipeline.

## 3. Technology research

### OpenTelemetry — ADAPT EXISTING INTEGRATION

JARVIS already pins OpenTelemetry API/SDK/OTLP exporter and owns a telemetry adapter.
OpenTelemetry is useful as supporting operational evidence, not canonical engineering
lifecycle truth. Do not create a second observability stack.

### in-toto Attestation Framework — ADAPT SEMANTICS

The subject-digest + typed predicate + observed result model aligns strongly with the
existing EngineeringAttestation contract. Preserve JARVIS canonical objects and keep
future export/interoperability possible. Do not replace EngineeringKnowledge.

### CDEvents — DEFER / OPTIONAL INTERCHANGE

Useful for external CI/CD event normalization, but it does not solve durable
evidence-backed engineering learning, supersession or applicability. Do not make it
internal truth.

### Argo Rollouts — REJECT AS PHASE-10 PLATFORM

Its progressive delivery analysis/rollback patterns are useful precedent, but JARVIS
already owns governed promotion, release identity, production observation and rollback.
Adopting a Kubernetes controller would duplicate Phase 7.

### Apache DevLake / DORA analytics — OPTIONAL FUTURE ANALYTICS

Useful for aggregate engineering performance metrics, but not a replacement for
immutable JARVIS outcome/evidence/knowledge semantics. Avoid another database and
analytics stack in Phase 10.

### New vector DB / knowledge graph — REJECT

EngineeringKnowledge already owns canonical persistence and derived local retrieval.
A second knowledge store would create competing truth.

### New agent framework — REJECT FOR CORE LEARNING

Phase 10 is primarily deterministic evidence normalization and lifecycle policy.
Model reasoning may later summarize evidence, but model confidence must not create
verified truth.

## 4. North-star alignment

Phase 10 directly supports the owner-approved autonomous self-management north star:
JARVIS must observe results, independently verify them, learn from outcomes and reuse
that learning without turning knowledge into Authority.

It also provides the engineering-specific first-class example of the advanced
Universal Knowledge/Discovery north star's **experience-derived knowledge**.

Permanent boundary:

- EngineeringKnowledge remains canonical for verified engineering experience.
- Phase 10 must preserve provenance, applicability, contradiction and supersession.
- Phase 10 must not claim EngineeringKnowledge is the future universal cross-domain
  Knowledge Fabric.
- Future Knowledge Fabric work may extend/compose these contracts, but Phase 10 must
  remain compatible with that future integration.

## 5. Core research conclusion

Do not build a new learning platform.

Build a thin JARVIS-owned layer:

```text
canonical engineering outcomes
        ->
normalized EngineeringOutcomeV1
        ->
deterministic LearningEligibilityPolicy
        ->
EngineeringKnowledgeCandidateBundle
        ->
existing lifecycle / supersession
        ->
existing retrieval
```

Positive success, negative regression evidence and exact compatibility evidence are all
valuable. Inconclusive/unknown outcomes must fail closed.

## 6. Learning rules

1. Verified production success may become positive engineering knowledge.
2. Verified candidate-local failure may become accepted negative/regression knowledge.
3. External-provider/hardware failure must not be attributed to the candidate.
4. Unknown attribution must not become accepted causal knowledge.
5. Pre-promotion verification failures may become narrowly scoped candidate-negative
   evidence.
6. Compatibility READY/BLOCKED outcomes may become exact compatibility knowledge.
7. Contradictory newer verified evidence creates a new immutable revision and may
   supersede the prior accepted revision.
8. Model output alone cannot promote knowledge.
9. Applicability defaults narrow; generalization requires later independent evidence.
10. Learning failure must never block safety actions such as rollback.

## 7. Sources

Repository sources:

- `AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md`
- `UNIVERSAL_KNOWLEDGE_AND_DISCOVERY_MASTER_PLAN.md`
- `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`
- Phase-2 EngineeringKnowledge research/architecture
- Phase-6/7/8/9 accepted implementations and acceptance records

External references reviewed:

- OpenTelemetry specifications: https://opentelemetry.io/
- in-toto Attestation Framework: https://github.com/in-toto/attestation
- CDEvents: https://cdevents.dev/
- Argo Rollouts: https://argoproj.github.io/rollouts/
- Apache DevLake DORA: https://devlake.apache.org/
