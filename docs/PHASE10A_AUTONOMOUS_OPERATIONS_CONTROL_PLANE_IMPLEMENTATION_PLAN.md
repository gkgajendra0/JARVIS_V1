# Phase 10A — Autonomous Operations Control Plane Implementation Plan

## Status

**PROPOSED IMPLEMENTATION PLAN — BLOCKED ON OWNER ARCHITECTURE APPROVAL — 2026-09-28**

Architecture:
`PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_ARCHITECTURE.md`.

Research:
`PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_RESEARCH.md`.

This document sequences implementation only. It grants no implementation permission
until the owner approves the Phase-10A architecture.

## Permanent implementation rules

Every slice must preserve:

- current Authority / OPA / approvals / permits;
- protected-main governance;
- WorkItem + DBOS execution truth;
- EngineeringChange owner gates;
- Self Model / Health Registry truth;
- Capability Registry truth;
- EngineeringKnowledge / Phase-10 advisory-learning boundary;
- exact evidence/provenance;
- fail-closed behavior for unknown schemas/rules/evidence;
- production SHADOW default;
- the Phase-9 full external physical-device lifecycle remains a separate deferred whole-system validation item and is not claimed or absorbed by Phase 10A.

No slice may introduce a new runtime framework or database.

## 10A.1 — contracts and durable autonomy store

### Deliver

- `jarvis.autonomy` package boundary;
- ObjectiveV1;
- DesiredStateV1;
- StabilizationPolicyV1;
- AutonomyFindingV1 + append-only finding events;
- ActionCandidateV1;
- OwnerAttentionItemV1 + attention events;
- AutonomyOutcomeRecordV1 reference envelope;
- ReconcileRunV1;
- mode/budget contracts;
- `AutonomyStore` additive WorkStore tables;
- schema ledger/checksum;
- deterministic canonical IDs/digests.

### Prove

- exact round-trip persistence;
- payload codec protection;
- CAS/version conflicts fail closed;
- duplicate IDs are idempotent or conflict explicitly;
- schema tamper/unknown version fails closed;
- no second SQLite/database path exists.

## 10A.2 — SystemState aggregation

### Deliver

- SystemStateFactV1;
- SystemStateSnapshotV1;
- source registry;
- read-only adapters for:
  - Self Model / Health Registry;
  - WorkStore;
  - EngineeringChange;
  - incidents;
  - Capability Registry;
  - model/provider routing;
  - resource state where canonical;
  - promotion observation where explicitly required;
- snapshot canonical digest;
- source freshness/error/incomplete semantics.

### Prove

- adapters never mutate source systems;
- same canonical inputs => same normalized fact digest;
- stale/missing required source is represented explicitly;
- source error cannot be silently converted into a violation;
- supporting telemetry cannot override canonical truth.

## 10A.3 — DesiredState rules and stabilization

### Deliver

- DesiredStateRuleRegistry;
- component-health rule;
- capability-effective-state rule;
- durable-work rule;
- objective completion aggregation;
- generation binding;
- SATISFIED / VIOLATED / UNKNOWN / STABILIZING evaluation;
- tolerance/deadband hooks;
- consecutive-observation and age stabilization;
- recovery stabilization;
- cooldown policy.

### Prove

- unknown rule version fails closed;
- stale evaluation cannot satisfy a newer generation;
- transient violation does not produce ACTIVE finding;
- sustained violation does;
- stable recovery resolves;
- missing evidence stays UNKNOWN.

## 10A.4 — findings and action resolution

### Deliver

- deterministic finding lifecycle;
- stable finding identity;
- finding event ledger;
- ActionResolverRegistry;
- response classes:
  - NO_ACTION;
  - EXISTING_CONTROLLER;
  - WORK_ITEM;
  - ENGINEERING_CHANGE;
  - OWNER_ATTENTION;
- deterministic candidate identity;
- root/suppression relationships;
- replay-safe dispatch-intent records without live dispatch yet.

### Prove

- same active gap => one finding;
- same finding/policy/generation => one candidate;
- resolved finding makes old candidate obsolete;
- deterministic controller wins over new agentic work;
- unsupported action mapping fails closed.

## 10A.5 — budgets, portfolio and owner attention

### Deliver

- AutonomyBudgetPolicyV1;
- budget-window accounting;
- PortfolioPrioritizer;
- explicit priority-factor provenance;
- WorkPriority mapping;
- OwnerAttention fingerprint/group/inhibition/re-notify;
- durable attention lifecycle;
- WorkDelivery adapter for notifications.

### Prove

- missing budget blocks ASSISTED dispatch;
- budget exhaustion creates no new work;
- portfolio ordering is deterministic;
- owner priority is preserved;
- root-cause attention inhibits derivative spam;
- repeated same attention is deduplicated;
- re-notify interval is respected;
- notification failure does not delete canonical attention truth.

## 10A.6 — shadow and assisted dispatch bridges

### Deliver

- AutonomyMode runtime configuration;
- SHADOW dispatch policy;
- isolated ASSISTED policy;
- replay-safe dispatch link store;
- WorkOrchestrator bridge for registered MONITORING/RESEARCH/DIAGNOSTICS work;
- ChangeCoordinator bridge for governed EngineeringChange creation;
- existing-controller registry/bridge;
- owner-attention delivery bridge;
- downstream source identity linking.

### Prove

- production default is SHADOW;
- SHADOW creates zero WorkItems/EngineeringChanges/notifications;
- isolated ASSISTED replay creates exactly one intended WorkItem;
- duplicate reconcile/restart creates no duplicate downstream object;
- autonomous EngineeringChange still reaches owner architecture gate;
- executor side effects remain under current Authority;
- no generic shell/capability invocation is introduced.

## 10A.7 — reconciliation runtime and acceptance

### Deliver

- AutonomyReconciler;
- bounded reconcile batch;
- STARTUP / STATE_CHANGE_HINT / PERIODIC / MANUAL_TEST triggers;
- in-process single-run lock;
- handled reconcile-token semantics;
- periodic safety sweep;
- clean runtime shutdown;
- locked replay corpus;
- Windows owner-machine acceptance harness;
- documentation/state reconciliation after acceptance.

### Minimum locked replay corpus

At least the 30 architectural cases covering:

- quiet healthy state;
- missing/stale evidence;
- transient/sustained/recovered violation;
- replay/restart idempotency;
- deterministic-controller routing;
- diagnostics/work/change routing;
- SHADOW zero dispatch;
- isolated ASSISTED bounded dispatch;
- existing Authority preservation;
- owner-attention dedupe/inhibition/re-notify;
- budget/cooldown;
- portfolio ordering;
- malformed evidence/rules;
- desired generation binding;
- reconcile token idempotency;
- canonical downstream outcome linkage;
- no self-approval;
- protected repo/production immutability.

### Existing regressions

Final CI must also preserve accepted Phase 6/7/8/9/10 regression lanes and promotion
policy.

## Branch / PR strategy after approval

Use isolated implementation branches/PRs per slice or tightly coupled slice group.

Recommended sequence:

```text
10A.1 contracts/store
 -> CI / merge green
10A.2 SystemState
 -> CI / merge green
10A.3 rules/stabilization
 -> CI / merge green
10A.4 findings/resolution
 -> CI / merge green
10A.5 budgets/portfolio/attention
 -> CI / merge green
10A.6 dispatch bridges
 -> CI / merge green
10A.7 final replay/acceptance
 -> CI
 -> owner-machine acceptance
 -> canonical acceptance docs
 -> merge / close Phase 10A
```

Intermediate green implementation PRs may be merged under the owner's standing
authorization to continue within an owner-approved architecture. Any material
architecture change must return to owner approval before implementation continues.

## Stop conditions requiring owner input

Implementation must stop for owner input when:

- the architecture needs material revision;
- enabling a more permissive production autonomy mode is proposed;
- a new Authority/delegation mechanism is required;
- owner-machine acceptance requires local action;
- protected promotion policy requires explicit owner action;
- a test demonstrates that an accepted security/governance boundary cannot be
  preserved.

Provider quota, unsupported external hardware or other external limitations must be
recorded truthfully; they are not permission to weaken acceptance criteria.

## Completion criterion

Phase 10A is DONE only after exact-head CI and owner-machine acceptance prove that
JARVIS can repeatedly:

```text
read accepted objective/obligation
-> derive/check DesiredState
-> observe canonical actual state
-> remain quiet when aligned
-> create one evidence-backed finding when sustainably misaligned
-> select one bounded response without duplicate/thrash
-> route through existing Work/Engineering/Authority boundaries
-> preserve meaningful owner attention
-> survive restart/replay
-> never self-grant Authority
```

Production autonomy remains SHADOW unless a separately explicit owner decision enables
a more permissive mode.
