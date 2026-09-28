# Phase 10A — Autonomous Operations Control Plane Research

## Status

**RESEARCH COMPLETE — ARCHITECTURE PROPOSAL REQUIRES OWNER APPROVAL — 2026-09-28**

This document records the repository inspection and external technology research used
to design Phase 10A. It is research evidence only. It does not authorize Phase-10A
implementation and does not expand JARVIS Authority.

The permanent engineering sequence remains:

```text
research thoroughly -> architecture -> owner approval -> isolated implementation
-> CI -> owner-machine acceptance when required -> docs -> merge
```

## 1. Required outcome

The owner-approved whole-JARVIS north star defines the next missing layer as an
Autonomous Operations Control Plane above existing WorkItems and EngineeringChanges.

Its purpose is to let JARVIS answer, continuously and durably:

1. What is JARVIS expected to achieve or preserve?
2. What is actually true now?
3. Is there a meaningful gap?
4. If there is a gap, what is the least-powerful safe response?
5. Should JARVIS remain quiet, invoke an existing deterministic controller, create
   durable work, create a governed EngineeringChange, or ask the owner?
6. How does JARVIS avoid duplicate work, flapping, runaway activity and notification
   noise?
7. How does every autonomous action remain traceable to owner intent, registered
   obligations, evidence and existing Authority?

Phase 10A occurs before Phase 11 autonomous capability-gap detection. It therefore
builds the reason-for-work and portfolio-management substrate without yet granting
JARVIS a general capability-gap generator.

## 2. Permanent constraints from accepted architecture

Phase 10A must preserve these accepted truths:

- JARVIS may manage JARVIS, but JARVIS must never become its own source of Authority.
- WorkItem + DBOS remain durable execution truth/mechanics.
- EngineeringChange remains the governed multi-stage change lifecycle.
- Authority / OPA / approvals / permits remain the action authorization boundary.
- Self Model + Health Registry remain canonical component/dependency/health truth.
- Capability Registry remains canonical capability desired/effective lifecycle truth.
- EngineeringKnowledge remains canonical verified engineering-experience knowledge.
- Phase-10 EngineeringLearning remains downstream advisory learning, not Authority.
- OperationalEvent/OpenTelemetry remain supporting evidence, not canonical lifecycle
  truth.
- Phase-9 full external physical-device lifecycle remains deferred and must not be
  represented as proven.
- Phase 10A must not become a second agent framework, scheduler, knowledge store,
  capability registry, authority system or deployment system.

## 3. Repository inspection

### 3.1 WorkItem / DBOS is already the durable execution substrate

`jarvis.work.models` already provides:

- durable WorkItem identity;
- explicit lifecycle states including queued, running, waiting, owner-blocked, paused,
  retrying and terminal states;
- priority classes;
- dependency links;
- work types for research, diagnostics, development, monitoring, reminders, Hands and
  generic work;
- immutable versioned updates.

`jarvis.work.store.SQLiteWorkStore` is explicitly JARVIS-owned canonical work truth.
It also exposes `extension_transaction()` and protected extension codecs for additive
JARVIS domain tables.

`jarvis.work.orchestrator.WorkOrchestrator` already provides idempotent work
submission, active-work reconciliation, pause/resume/cancel and reprioritization.

`jarvis.work.dbos_backend` already provides the durable workflow mechanics. DBOS must
preserve the canonical WorkItem ID as workflow ID. Waiting time is durable and does not
consume semantic-work budget.

Research conclusion: **do not build another task/workflow engine for Phase 10A.**

### 3.2 EngineeringChange already owns governed novel engineering

`jarvis.engineering_change` already owns:

- durable program-level change state;
- research and development stages backed by WorkItems;
- exact architecture artifacts;
- owner-gated architecture/acceptance/promotion boundaries;
- strong owner verification;
- exact process contracts and stage provenance.

An autonomy controller may create or recommend an EngineeringChange, but it cannot
approve its own architecture or protected promotion.

Research conclusion: **Phase 10A creates intent/work; EngineeringChange continues to
own governed engineering.**

### 3.3 Self Model + Health Registry already provide actual-state foundations

`jarvis.self_model` provides:

- version-controlled component descriptors;
- component hierarchy;
- explicit dependencies and criticality;
- affected/dependent component queries;
- deterministic system snapshots.

`HealthRegistry` records fresh typed health evidence and explicitly states that an
LLM never writes health state.

Research conclusion: **system-state aggregation should adapt these sources, not create
a parallel health database.**

### 3.4 Capability Registry already demonstrates the right reconciliation style

`CapabilityLifecycleReconciler` is an accepted JARVIS example of:

- durable desired state;
- actual compatibility/provider/health evidence;
- deterministic desired -> effective reconciliation;
- fail-closed projection;
- transition fencing;
- bounded periodic reconciliation;
- no model decision at the truth boundary.

Research conclusion: **Phase 10A should generalize this controller pattern at the
whole-system coordination level while leaving capability truth inside the existing
registry.**

### 3.5 Authority already distinguishes proactive/system-origin actions

The current Authority model already includes:

- `ActionOrigin.PROACTIVE`;
- `ActionOrigin.SYSTEM`;
- risk classification;
- approval requirements;
- execution permits;
- audit;
- pre-execution revalidation;
- explicit flags for background/proactive, self-modification, permission changes,
  security changes and external side effects.

Research conclusion: **Phase 10A must feed existing Authority where execution requires
authorization; it must not add a second permission model.**

### 3.6 Existing resource and progress models are reusable

The work subsystem already has:

- deterministic resource leases;
- engineering resource capacities;
- global work concurrency;
- deterministic progress/ETA derived from canonical work truth.

These can feed portfolio decisions and SystemState without making the model provider
guess operational state.

## 4. External control-plane research

### 4.1 Kubernetes controllers — ADAPT THE CONTROL-LOOP PATTERN

Kubernetes defines controllers as control loops that watch current state and make or
request changes to move it toward desired state. Kubernetes deliberately favors
multiple focused controllers rather than one monolithic controller.

Useful Phase-10A patterns:

- desired state and current state are separate;
- reconciliation is repeated and idempotent;
- the controller usually requests work through another canonical API instead of doing
  all work itself;
- each controller owns only the resources/facts in its scope;
- controller failure is expected, so replay must be safe.

Disposition: **ADAPT semantics; DO NOT adopt Kubernetes as the JARVIS runtime.**

Reference:
https://kubernetes.io/docs/concepts/architecture/controller/

### 4.2 Kubernetes spec/status and observed-generation ideas — ADAPT

Kubernetes objects separate desired `spec` from current `status`. Newer Kubernetes
APIs also use observed-generation tracking so status can be tied to the version of
desired state that produced it.

Useful Phase-10A patterns:

- every DesiredState has a generation/revision;
- each reconciliation result records the desired generation it evaluated;
- stale evaluation must not satisfy a newer desired state;
- current status should report what generation was actually handled.

Disposition: **ADAPT generation binding; do not clone Kubernetes object schemas.**

References:
https://kubernetes.io/docs/concepts/overview/working-with-objects/
https://kubernetes.io/docs/concepts/workloads/pods/

### 4.3 Kubernetes HPA — ADAPT STABILIZATION / TOLERANCE / RATE LIMITING

Horizontal Pod Autoscaler behavior includes:

- configurable tolerance so small metric variation does not trigger action;
- stabilization windows to reduce flapping;
- rate/velocity policies limiting how fast changes occur;
- conservative handling when input metrics are missing.

These are directly applicable to autonomous work creation.

Phase-10A equivalent controls should include:

- deadband/tolerance where a DesiredState supports numeric thresholds;
- consecutive-observation or minimum-age requirements;
- stabilization windows;
- cooldowns;
- action-rate budgets;
- fail-closed behavior when required evidence is missing/stale.

Disposition: **ADAPT anti-thrash patterns.**

References:
https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/
https://kubernetes.io/docs/reference/kubernetes-api/autoscaling/horizontal-pod-autoscaler-v2/

### 4.4 Crossplane — ADAPT OBSERVE-FIRST + RECONCILE TOKENS

Crossplane exposes explicit management policies including an observe-only mode. It
also supports a reconcile-request token and records the last handled token, so replaying
the same request does not imply a new management request.

Useful Phase-10A patterns:

- production rollout begins observe/shadow-first;
- reconciliation requests have stable identities;
- the system records the exact request/generation handled;
- periodic polling is a safety sweep, while explicit state-change signals may trigger
  immediate reconciliation;
- management scope should be explicit rather than implied by existence of a controller.

Disposition: **ADAPT patterns; DO NOT adopt Crossplane as the JARVIS control plane.**

References:
https://docs.crossplane.io/latest/guides/import-existing-resources/
https://docs.crossplane.io/v2.3/managed-resources/managed-resources/

### 4.5 Prometheus Alertmanager — ADAPT OWNER-ATTENTION SEMANTICS

Alertmanager provides mature patterns for:

- deduplicating repeated alerts;
- grouping related alerts;
- inhibiting derivative alerts while a root-cause alert is active;
- repeat notification intervals;
- silences.

Phase 10A needs the equivalent for owner attention so autonomy does not become
notification spam.

Disposition: **ADAPT dedupe/group/inhibition/re-notify concepts into JARVIS durable
OwnerAttentionItem; do not adopt Alertmanager as canonical owner-attention storage.**

References:
https://prometheus.io/docs/alerting/latest/configuration/
https://next.prometheus.io/docs/alerting/latest/alertmanager/

### 4.6 DBOS — KEEP AS DURABLE EXECUTION, NOT DOMAIN TRUTH

DBOS provides:

- durable workflows that resume after interruption;
- queues with concurrency/rate control;
- workflow IDs/deduplication;
- scheduled workflows with deterministic schedule firing identity.

JARVIS already uses DBOS, so Phase 10A should keep it.

However:

- Objective/DesiredState/Finding/Attention truth belongs in JARVIS-owned domain
  persistence;
- DBOS system tables must not become the only canonical autonomy state;
- reconciliation correctness must not depend on one particular scheduling mechanism.

Disposition: **KEEP DBOS for durable WorkItem execution; optionally use its scheduling
capabilities after pinned-version compatibility is verified during implementation.**

References:
https://docs.dbos.dev/python/tutorials/scheduled-workflows
https://docs.dbos.dev/python/reference/queues

### 4.7 Temporal — REJECT FOR PHASE 10A

Temporal offers mature durable workflows, timers, signals and replay semantics.
Those capabilities overlap with the already-accepted DBOS + WorkItem substrate.

Adopting Temporal now would add:

- a second durable workflow system;
- migration and operational complexity;
- competing execution truth;
- no unique Phase-10A requirement that DBOS cannot satisfy.

Disposition: **REJECT for Phase 10A; reconsider only with concrete evidence that the
existing DBOS substrate cannot meet a future requirement.**

Reference:
https://docs.temporal.io/tasks

### 4.8 IBM autonomic-computing architecture — ADAPT THE OBJECTIVE MODEL

IBM autonomic-computing research frames self-management as behavior driven by
human-specified high-level objectives and emphasizes self-configuration,
self-optimization, self-healing and self-protection.

This aligns with the accepted JARVIS north star.

Useful Phase-10A lesson:

- the system acts against explicit high-level objectives/policies;
- self-management does not mean inventing its own constitutional goals;
- objective/utility concepts can guide later optimization, but Phase 10A should begin
  with deterministic measurable DesiredState contracts rather than opaque model-defined
  utility.

Disposition: **ADAPT principles; no IBM framework dependency.**

References:
https://research.ibm.com/publications/autonomic-computing-architectural-approach-and-prototype
https://research.ibm.com/publications/an-architectural-approach-to-autonomic-computing

## 5. Technology disposition summary

| Technology / pattern | Disposition | Reason |
| --- | --- | --- |
| Existing WorkItem + SQLite WorkStore | KEEP | canonical durable work truth already accepted |
| Existing DBOS | KEEP | durable execution/recovery/queues already accepted |
| Existing EngineeringChange | KEEP | canonical governed engineering lifecycle |
| Existing Self Model + Health Registry | KEEP | canonical component/dependency/health truth |
| Existing Capability reconciler | KEEP / REUSE PATTERN | proven desired/effective reconciliation |
| Existing Authority / OPA | KEEP | constitutional action boundary |
| Kubernetes controller model | ADAPT | excellent desired/current reconciliation semantics |
| Kubernetes HPA stabilization | ADAPT | mature anti-flapping/rate-limit patterns |
| Crossplane observe-first/reconcile token | ADAPT | safe shadow rollout and replay semantics |
| Alertmanager grouping/inhibition | ADAPT | owner-attention noise control |
| IBM autonomic objectives/self-* model | ADAPT | aligns with whole-JARVIS north star |
| Temporal | REJECT FOR 10A | duplicates DBOS durable execution |
| Kubernetes/Crossplane runtime | REJECT | unnecessary second control plane/platform |
| New agent framework | REJECT | would create competing orchestration/control truth |
| New event database | REJECT | canonical JARVIS stores already exist |
| New vector DB / knowledge graph | REJECT | unrelated to Phase-10A control truth |

## 6. Research conclusions for canonical Phase-10A objects

### Objective

A durable reason for work.

Allowed origins initially:

- accepted owner objective;
- version-controlled registered system obligation.

A model may help explain or decompose an objective, but it cannot silently create a
new constitutional/system obligation.

### DesiredState

A typed, checkable target condition.

A DesiredState must identify:

- objective/obligation source;
- target identity;
- evaluator/rule key + version;
- required input fact namespaces;
- success condition;
- tolerance/stabilization policy where applicable;
- priority/horizon/constraints;
- generation.

A free-form model statement is not sufficient DesiredState truth.

### SystemState

A deterministic point-in-time aggregate of canonical source facts.

SystemState is **derived evidence**, not a second mutable source of truth.

Each fact should preserve:

- source namespace;
- source identity/version/digest;
- target;
- typed value/state;
- observation time;
- freshness;
- evidence references.

The aggregate snapshot should have a canonical digest so a Finding can prove exactly
what actual state it evaluated.

### AutonomyFinding

A durable evidence-backed statement that a DesiredState is:

- SATISFIED;
- VIOLATED;
- UNKNOWN/INCONCLUSIVE;
- STABILIZING;
- RESOLVED.

Only supported deterministic evaluators may establish these states.

### ActionCandidate

A typed proposed response, not execution Authority.

Initial response classes should be:

- NO_ACTION;
- EXISTING_CONTROLLER;
- WORK_ITEM;
- ENGINEERING_CHANGE;
- OWNER_ATTENTION.

A candidate records expected effect, evidence, reversibility, resource/cost class,
dependencies, risk metadata and the existing downstream boundary that must handle it.

### OwnerAttentionItem

A durable escalation object separate from notification transport.

It should support:

- fingerprint/deduplication;
- grouping/root-cause link;
- inhibition/supersession;
- priority;
- required owner input/decision;
- consequence of waiting;
- linked Objective/Finding/ActionCandidate;
- re-notification interval;
- lifecycle such as OPEN / ACKNOWLEDGED / RESOLVED / EXPIRED / SUPERSEDED.

Existing WorkDelivery/TTS can deliver an attention item, but delivery is not canonical
attention truth.

### OutcomeRecord

Do not create another operational-outcome database.

Phase 10A should represent OutcomeRecord as an immutable reference envelope linking an
ActionCandidate to existing canonical terminal truth such as:

- WorkItem/WorkStep;
- EngineeringChange;
- PromotionAttempt/ProductionObservation;
- capability lifecycle outcome;
- RepairAttempt;
- Phase-10 EngineeringOutcome where applicable.

## 7. Reconciliation design conclusions

The control loop should be:

```text
accepted Objective / registered obligation
        |
        v
DesiredState registry + persisted instances
        |
        v
read-only SystemState adapters
        |
        v
canonical SystemStateSnapshot digest
        |
        v
deterministic DesiredState evaluator
        |
        +--> satisfied -> remain quiet / resolve old finding
        |
        +--> unknown -> no autonomous action; optionally escalate if persistent policy says so
        |
        +--> violated but unstable -> STABILIZING
        |
        +--> sustained violation -> AutonomyFinding
                                      |
                                      v
                              ActionResolverPolicy
                                      |
                                      v
                               ActionCandidate
                                      |
                           mode / budget / dedupe
                                      |
          +---------------------------+---------------------------+
          |                           |                           |
 existing controller             durable WorkItem          EngineeringChange
          |                           |                           |
          +--------------------- existing governance -------------+
                                      |
                                 owner attention
                              only when genuinely needed
```

The reconciler itself should not contain an unrestricted model planning loop.

## 8. Anti-thrash / anti-runaway requirements

Phase 10A must include explicit deterministic controls from its first implementation:

1. stable Finding identity;
2. replay-idempotent ActionCandidate identity;
3. no duplicate active downstream WorkItem/EngineeringChange for the same candidate;
4. minimum evidence age or consecutive observations where appropriate;
5. per-rule deadband/tolerance where applicable;
6. stabilization windows;
7. per-finding cooldown after dispatch;
8. bounded retry/backoff for repeatedly blocked candidates;
9. per-objective active-work limit;
10. global autonomous-work creation limit;
11. owner-attention grouping/dedup/inhibition;
12. stale/missing required evidence => no autonomous state-changing action;
13. resolved actual state closes/supersedes the active finding;
14. restart/replay must recreate no duplicate work.

Budgets are throttles, not permission grants. They can make autonomy *more restrictive*
than Authority but can never make an otherwise unauthorized action allowed.

## 9. Portfolio research conclusion

Do not introduce an opaque LLM score as the canonical scheduler.

Use deterministic ordered factors such as:

1. explicit owner priority;
2. registered obligation criticality (security/safety/availability where applicable);
3. deadline/urgency;
4. dependency-unblocking value;
5. current impact scope;
6. age/starvation prevention;
7. resource availability.

Risk affects execution/owner-gating through Authority; it should not be conflated with
priority.

The result may map to existing WorkPriority LOW/NORMAL/HIGH/URGENT while preserving the
full decision factors as provenance.

## 10. Rollout-mode research conclusion

A control plane should not jump directly from code to unrestricted production
autonomy.

Proposed modes:

- **OFF** — controller disabled;
- **OBSERVE** — derive SystemState only;
- **SHADOW** — persist findings/candidates but dispatch nothing and notify no owner;
- **ASSISTED** — may create only explicitly admitted low-risk background
  monitoring/research/diagnostic WorkItems and durable owner-attention items; all
  downstream Authority/gates remain active;
- **ACTIVE_BOUNDED** — reserved for a separately accepted future production policy.

Phase-10A implementation/acceptance should default production to SHADOW. An isolated
acceptance harness may exercise ASSISTED behavior without enabling broad production
autonomy.

## 11. Explicit non-goals

Phase 10A does not:

- implement Phase-11 general autonomous capability-gap detection;
- implement Phase-12 autonomous optimization experiments;
- implement a future generalized AuthorityEnvelope;
- delegate protected architecture/promotion approval to JARVIS;
- create hidden model-generated objectives;
- replace WorkItem, DBOS, EngineeringChange, Authority, Self Model, Health Registry,
  Capability Registry or EngineeringKnowledge;
- turn OperationalEvent/OTel into lifecycle truth;
- adopt Kubernetes, Crossplane or Temporal;
- create a second durable work engine;
- create a new universal Knowledge Fabric;
- prove the deferred Phase-9 external physical-device lifecycle.

## 12. Architecture questions resolved by research

### Should SystemState be a new canonical mutable database?

**No.** It is a derived, digest-bound snapshot over canonical source facts. Persist a
bounded snapshot/evidence record for replay and audit, but canonical truth stays in the
source systems.

### Should the controller execute arbitrary actions directly?

**No.** It emits typed ActionCandidates routed into existing deterministic controllers,
WorkItems, EngineeringChanges or owner attention.

### Should a model decide whether DesiredState is satisfied?

**No for initial Phase 10A.** Satisfaction is deterministic through registered
versioned evaluators. Models may later help research/explain novel conditions without
becoming truth.

### Should owner attention reuse WorkDelivery as its only state?

**No.** Delivery is transport. OwnerAttentionItem must remain durable until the actual
owner dependency is resolved.

### Should Phase 10A introduce a new scheduler/orchestrator?

**No.** Reuse WorkItem + DBOS and existing resource/priority mechanics.

### Should the reconciler itself be durable?

Its *decisions and identities* must be durable/replay-safe. The loop process does not
need to be durable if every run rebuilds from canonical state and idempotent persisted
records. Startup + state-change hints + periodic safety sweep provide recovery.

## 13. Recommended architecture direction

Proceed with a thin JARVIS-owned `jarvis.autonomy` domain layer that:

1. persists Objective, DesiredState, Finding, ActionCandidate and OwnerAttentionItem as
   additive WorkStore domain tables;
2. derives SystemState through read-only adapters;
3. uses registered deterministic DesiredState evaluators;
4. uses idempotent reconciliation to create findings/candidates;
5. routes candidates to existing control/work/change/attention boundaries;
6. applies explicit anti-thrash and activity budgets;
7. begins in SHADOW mode;
8. proves behavior through deterministic replay before any bounded assisted production
   mode is considered.

This architecture preserves the accepted subsystem boundaries while adding the missing
whole-JARVIS reason-for-work layer.
