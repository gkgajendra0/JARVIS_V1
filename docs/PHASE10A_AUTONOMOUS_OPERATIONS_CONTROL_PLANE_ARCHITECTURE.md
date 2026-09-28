# Phase 10A — Autonomous Operations Control Plane Architecture

## Status

**PROPOSED — OWNER APPROVAL REQUIRED BEFORE IMPLEMENTATION — 2026-09-28**

This architecture is subordinate to:

1. `AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md`;
2. `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`;
3. `UNIVERSAL_KNOWLEDGE_AND_DISCOVERY_MASTER_PLAN.md`;
4. all accepted Authority, WorkItem, EngineeringChange, Self Model, capability,
   promotion, repair and learning contracts.

Research basis:
`PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_RESEARCH.md`.

No Phase-10A runtime implementation is authorized until the owner approves this
architecture.

## 1. Architectural objective

Add one JARVIS-owned control layer that can durably represent accepted objectives,
derive measurable desired state, compare it with canonical actual state, produce
evidence-backed findings, choose the least-powerful safe response, and manage the
resulting portfolio without becoming a second source of execution truth or Authority.

```text
OWNER INTENT / REGISTERED SYSTEM OBLIGATION
                    |
                    v
                Objective
                    |
                    v
              DesiredState
                    |
                    | compare
                    v
      canonical read-only SystemState
                    |
                    v
          DesiredStateEvaluator
                    |
        +-----------+------------+
        |                        |
     satisfied              gap / unknown
        |                        |
     remain quiet          stabilization
                                 |
                                 v
                         AutonomyFinding
                                 |
                                 v
                      ActionResolverPolicy
                                 |
                                 v
                         ActionCandidate
                                 |
                  mode / dedupe / budget
                                 |
         +-----------+-----------+-------------+
         |           |           |             |
   existing       WorkItem  EngineeringChange  OwnerAttention
   controller         |           |             |
         +------------+-----------+-------------+
                      |
              existing governance
                      |
                verified outcome
                      |
                      v
              reconcile again
```

## 2. Permanent invariants

1. **Owner Authority remains external to autonomy.**
   JARVIS may identify work and prepare responses, but cannot grant itself permission.
2. **No hidden objectives.**
   Every active Objective is traceable to an accepted owner source or a
   version-controlled registered system obligation.
3. **DesiredState is checkable.**
   A free-form model claim is not DesiredState truth.
4. **Actual state remains in canonical subsystem stores.**
   SystemState is derived evidence, not a replacement database.
5. **Models do not determine operational truth.**
   Initial satisfaction/violation classification is deterministic and versioned.
6. **The controller requests work; it does not become the work engine.**
   WorkItem + DBOS remain execution truth/mechanics.
7. **Novel engineering remains EngineeringChange.**
   Architecture/acceptance/promotion owner gates remain unchanged.
8. **Execution authorization remains Authority/OPA.**
   ActionCandidate is never an execution permit.
9. **Existing deterministic controllers win over agentic work.**
   The least-powerful reliable response is preferred.
10. **Every autonomous dispatch is evidence-bound and idempotent.**
11. **Missing/stale required evidence fails closed.**
12. **Transient noise must not create repeated autonomous work.**
13. **Budgets only restrict autonomy.**
    A budget can never grant permission that Authority would deny.
14. **Owner attention is durable and deduplicated.**
15. **Phase-10 learning remains advisory.**
16. **Phase 10A does not implement Phase 11 capability-gap discovery or Phase 12
    optimization.**
17. **The deferred Phase-9 external lifecycle remains deferred.**
18. **No new agent framework, scheduler, event DB, vector DB or control-plane service is
    introduced without separate evidence and approval.**

## 3. Package boundary

Introduce a new package:

```text
jarvis/autonomy/
  __init__.py
  models.py
  store.py
  objectives.py
  system_state.py
  adapters.py
  desired_state.py
  findings.py
  actions.py
  portfolio.py
  attention.py
  budgets.py
  reconciliation.py
  runtime.py
  evaluation.py
  acceptance.py
```

The exact file split may change during implementation, but ownership boundaries in this
document must remain fixed.

## 4. Canonical persistence boundary

Phase 10A uses **additive domain tables in the existing protected WorkStore database**.

It does not introduce a second canonical database.

`AutonomyStore` should compose `SQLiteWorkStore` and use its:

- extension transaction boundary;
- payload codec;
- locking;
- WAL configuration;
- existing protected state directory.

A small schema ledger/checksum should protect autonomy-table evolution.

Proposed tables:

```text
autonomy_objectives
autonomy_desired_states
autonomy_findings
autonomy_finding_events
autonomy_action_candidates
autonomy_dispatch_links
autonomy_owner_attention
autonomy_attention_events
autonomy_system_snapshots
autonomy_outcome_links
autonomy_reconcile_runs
autonomy_budget_windows
autonomy_schema
```

No table may duplicate WorkItem steps, EngineeringChange artifacts/gates, health
observations, capability packages, promotion attempts or EngineeringKnowledge.

## 5. ObjectiveV1

`ObjectiveV1` is the durable reason work may exist.

### Required fields

- `objective_id`;
- `origin`;
- `source_identity`;
- `title`;
- `description`;
- `priority`;
- `status`;
- `horizon` / optional deadline;
- `constraint_json`;
- `created_at`;
- `updated_at`;
- `generation`.

### Initial origin vocabulary

- `OWNER`;
- `REGISTERED_SYSTEM_OBLIGATION`.

No `MODEL_GENERATED` objective origin is accepted as active truth in Phase 10A.

A model may propose wording or decomposition, but accepted persistence must be bound to
an owner source or a registered obligation.

### Initial lifecycle

- ACTIVE;
- PAUSED;
- SATISFIED;
- CANCELLED;
- SUPERSEDED.

Objective generation increases whenever accepted desired semantics change.

## 6. DesiredStateV1

A DesiredState is a typed target condition attached to one Objective.

### Required fields

- `desired_state_id`;
- `objective_id`;
- `target_namespace`;
- `target_identity`;
- `rule_key`;
- `rule_version`;
- `expected_json`;
- `required_source_namespaces`;
- `stabilization_policy`;
- `generation`;
- `status`;
- provenance/source identity.

### Rule registry

Introduce `DesiredStateRuleRegistry`.

Each reviewed rule handler provides:

- exact rule key/version;
- expected-value validation;
- required SystemState fact namespaces;
- deterministic evaluation;
- optional tolerance/deadband semantics;
- default stabilization requirements;
- supported ActionResolver key.

Unknown rule versions fail closed.

### Initial rule families

The implementation should begin narrow:

1. **component health obligation**
   - target a registered Self Model component;
   - expected acceptable HealthState set;
   - actual state from Self Model + Health Registry.
2. **capability effective-state obligation**
   - target a registered capability;
   - expected enabled/disabled/effective condition;
   - actual state from Capability Registry projection.
3. **durable work obligation**
   - target accepted WorkItem/Objective linkage;
   - detect terminal completion, durable blocking or lost/recovery-needed work without
     duplicating WorkStore truth.
4. **objective completion aggregation**
   - determine whether all required linked DesiredStates are satisfied.

Provider-cost optimization, generalized performance optimization and arbitrary
capability-gap rules are deferred to later phases.

## 7. SystemStateFactV1 and SystemStateSnapshotV1

### SystemStateFactV1

A normalized read-only fact from a canonical source.

Required semantics:

- `fact_namespace`;
- `source_identity`;
- `source_version_or_digest`;
- `target_namespace`;
- `target_identity`;
- typed `value_json`;
- `observed_at_epoch`;
- `fresh_until_epoch` where applicable;
- `evidence_references`;
- source adapter key/version.

Facts are not freely written by model output.

### SystemStateSnapshotV1

A bounded immutable evidence snapshot created for one reconciliation run.

Fields include:

- snapshot ID;
- canonical digest;
- evaluated source namespaces;
- fact digests/references;
- source errors/incomplete namespaces;
- start/end timestamps;
- producer version.

The snapshot exists for audit/replay. It **does not become the current-state truth
database**.

## 8. Read-only SystemState adapters

Define:

```text
SystemStateSource
  -> source_key/version
  -> read(requested targets/namespaces) -> facts + source status
```

Initial adapters:

### SelfModelHealthSource

Reads:

- component descriptors;
- dependency relationships;
- HealthRegistry snapshots;
- dependency roll-up.

### WorkPortfolioSource

Reads:

- WorkItems;
- WorkSteps;
- waiting/blocking state;
- dependencies;
- priorities;
- deterministic progress/ETA when needed.

### EngineeringChangeSource

Reads active governed change state and current owner/engineering gate boundary.

### IncidentSource

Reads canonical incident state and linked repair/diagnostic evidence.

### CapabilityStateSource

Reads canonical capability desired state, selected package, compatibility and effective
projection.

### ModelProviderStateSource

Reads canonical model-routing/provider health/cooldown evidence. It may inform
resource/blocker state but must not create candidate blame.

### ResourceStateSource

Reads deterministic ResourceLease/host-resource observations where supported.

### ProductionObservationSource

Reads accepted promotion/production state when an Objective explicitly depends on a
deployed release condition.

OpenTelemetry/OperationalEvent may be linked as supporting evidence but cannot override
these canonical adapters.

## 9. Evaluation result contract

A DesiredState evaluator returns one of:

- SATISFIED;
- VIOLATED;
- UNKNOWN;
- STABILIZING.

It also returns:

- exact DesiredState generation;
- snapshot digest;
- reason codes;
- supporting fact digests;
- first/last violation evidence where applicable.

### Fail-closed rules

If a required source is:

- missing;
- stale;
- malformed;
- unsupported;
- digest-inconsistent;

the result is UNKNOWN, not VIOLATED.

UNKNOWN does not create a state-changing autonomous action.

Persistent source-unavailability may itself be handled only by an explicit registered
control-plane-health DesiredState; no generic recursive escalation is implied.

## 10. Stabilization and anti-flapping

Every rule has an explicit `StabilizationPolicyV1`.

Potential fields:

- `required_consecutive_violations`;
- `minimum_violation_age_seconds`;
- `minimum_recovery_age_seconds`;
- `cooldown_after_dispatch_seconds`;
- `numeric_tolerance` where meaningful;
- `renotify_interval_seconds`;
- `max_dispatches_per_window`;
- `window_seconds`.

A VIOLATED evaluator result does not necessarily become an ACTIVE Finding immediately.

The reconciler applies:

```text
single/transient violation
       -> STABILIZING

sustained violation
       -> ACTIVE finding

stable recovery
       -> RESOLVED finding
```

This is the JARVIS adaptation of control-system deadbands/stabilization rather than a
generic delay hardcoded into every rule.

## 11. AutonomyFindingV1

A Finding is durable evidence that one DesiredState needs attention.

### Stable identity

Finding identity should be deterministic from:

- DesiredState identity;
- target identity;
- finding kind;
- rule version.

Repeated observations update the same active finding lifecycle rather than create
duplicates.

### Lifecycle

- STABILIZING;
- ACTIVE;
- RESOLVED;
- SUPPRESSED;
- SUPERSEDED.

The current finding row may be versioned/CAS-updated, while all state transitions are
also recorded in append-only `autonomy_finding_events`.

### Required evidence

An ACTIVE finding records:

- desired generation;
- latest snapshot digest;
- first-seen and last-seen timestamps;
- violation count;
- reason codes;
- exact supporting fact digests;
- root-cause/suppression link when applicable.

## 12. ActionResolverPolicy

The resolver is deterministic and registered by DesiredState rule/finding kind.

It prefers the least-powerful reliable response:

```text
NO_ACTION
-> EXISTING_CONTROLLER
-> WORK_ITEM
-> ENGINEERING_CHANGE
-> OWNER_ATTENTION
```

This ordering is a preference hierarchy, not an automatic permission ladder.

### NO_ACTION

Used when:

- condition resolved;
- finding is informational;
- evidence is insufficient;
- action is inhibited/suppressed;
- no safe response is registered.

### EXISTING_CONTROLLER

References an already accepted deterministic controller, for example a capability
reconciler or accepted self-repair path.

Phase 10A must not duplicate that controller's implementation.

### WORK_ITEM

Creates bounded durable work through the existing WorkOrchestrator.

Initial assisted-mode autonomous work types are limited to explicitly registered,
non-destructive background classes such as:

- MONITORING;
- RESEARCH;
- DIAGNOSTICS.

A WorkItem created autonomously must carry stable source identity linking back to the
ActionCandidate. Reconciliation must find/reuse an existing active or terminal dispatch
instead of duplicating it.

### ENGINEERING_CHANGE

Creates a governed EngineeringChange when novel source/code/capability engineering is
actually needed.

The change then follows all existing research, architecture, owner approval,
verification, acceptance and promotion gates.

Creating the change is not architecture approval.

### OWNER_ATTENTION

Used when the controller needs a genuine owner decision/input or cannot safely proceed.

## 13. ActionCandidateV1

An ActionCandidate is immutable proposal evidence.

Required fields:

- candidate ID;
- finding ID;
- desired-state ID + generation;
- action kind;
- resolver key/version;
- expected effect;
- target;
- evidence/snapshot digest;
- reversibility class;
- resource/cost class;
- downstream risk metadata;
- dependencies;
- mode at evaluation;
- policy reason codes;
- created time.

Candidate identity is deterministic from stable finding/action semantics + desired
generation + resolver version so restart/replay cannot create endless equivalent
candidates.

### Candidate disposition

A separate decision records one of:

- SHADOW_ONLY;
- ADMITTED;
- DEFERRED_BUDGET;
- DEFERRED_COOLDOWN;
- BLOCKED_POLICY;
- INHIBITED;
- OBSOLETE.

The downstream WorkItem/EngineeringChange remains canonical execution state.

## 14. Dispatch links

`autonomy_dispatch_links` binds exactly one admitted candidate to the canonical object
it requested.

Possible link kinds:

- controller invocation/request;
- WorkItem ID;
- EngineeringChange ID;
- OwnerAttentionItem ID.

A unique constraint on candidate + dispatch role makes dispatch replay-safe.

Before dispatch, the control plane must also search for an existing active downstream
object with the same canonical source identity.

## 15. OwnerAttentionItemV1

Owner attention is a canonical dependency, not a TTS/chat notification.

### Required fields

- attention ID;
- fingerprint;
- group/root key;
- linked Objective/Finding/Candidate;
- priority;
- reason codes;
- concise question/required decision;
- option metadata where structured options exist;
- consequence of waiting;
- first/last occurrence;
- next re-notify time;
- status.

### Lifecycle

- OPEN;
- ACKNOWLEDGED;
- RESOLVED;
- EXPIRED;
- SUPERSEDED.

### Noise control

Adapt Alertmanager-style semantics:

- same fingerprint => deduplicate;
- same root/group => group;
- root-cause item may inhibit derivative items;
- unresolved item re-notifies only after its configured interval;
- resolved/superseded derivative attention does not continue notifying.

Existing WorkDelivery/TTS/chat is the delivery transport only.

## 16. AutonomyOutcomeRecordV1

The master plan requires outcome semantics but Phase 10A must not duplicate canonical
outcome truth.

Therefore `AutonomyOutcomeRecordV1` is an immutable **reference envelope** containing:

- ActionCandidate ID;
- dispatch link;
- canonical downstream source kind;
- canonical source ID;
- canonical source digest/version where available;
- terminal status reference;
- verification/observation references;
- Phase-10 EngineeringOutcome ID when one exists;
- recorded timestamp.

The result itself remains owned by the downstream subsystem.

## 17. Autonomy modes

Define:

```text
OFF
OBSERVE
SHADOW
ASSISTED
ACTIVE_BOUNDED
```

### OFF

No control-plane reconciliation.

### OBSERVE

Build and record bounded SystemState snapshots only.

### SHADOW

Evaluate DesiredState, persist findings/candidates/outcome predictions, but:

- dispatch no WorkItem;
- create no EngineeringChange;
- invoke no controller because of Phase 10A;
- send no owner-attention notification.

This is the default production mode for initial Phase-10A deployment.

### ASSISTED

May:

- deliver durable owner-attention items;
- create only explicitly admitted bounded MONITORING/RESEARCH/DIAGNOSTICS WorkItems;
- request only specifically registered existing deterministic controller actions.

All existing downstream Authority/gates remain in force.

### ACTIVE_BOUNDED

Reserved for a later explicitly owner-approved production policy. Merely implementing
the enum does not enable it.

A transition to a more permissive production mode must require explicit owner action
and must never be chosen by the model/controller itself.

## 18. Autonomy budgets

Introduce deterministic `AutonomyBudgetPolicyV1`.

Initial budget dimensions should include:

- maximum concurrently active autonomously-created WorkItems;
- maximum new autonomous WorkItems per time window;
- maximum active candidates per Objective;
- maximum repeated dispatches per Finding/window;
- owner-attention notification limit with urgent/root-cause override;
- provider/model-work ceiling where exact canonical metering exists.

If a budget dimension cannot be measured reliably, it must not be invented.

ASSISTED mode requires an explicit budget policy. Missing/invalid budget => dispatch
fails closed.

Budgets do not grant Authority.

## 19. Portfolio prioritization

Introduce deterministic `PortfolioPrioritizer`.

Do not use an opaque model-generated numeric score as canonical priority.

Use an auditable ordered vector:

1. explicit owner Objective priority;
2. registered obligation criticality;
3. deadline/urgency bucket;
4. current impact scope;
5. dependency-unblocking value;
6. starvation/age bucket;
7. resource feasibility.

Risk is recorded separately for Authority/gating.

The result maps to existing WorkPriority LOW/NORMAL/HIGH/URGENT and stores the input
factors that produced that mapping.

Owner-interactive reasoning remains able to preempt background model reasoning through
the existing InteractiveBrainGate.

## 20. Reconciliation loop

Introduce `AutonomyReconciler`.

One reconciliation run:

1. loads active Objectives + DesiredStates;
2. determines the exact target/source namespaces needed;
3. reads bounded SystemState adapters;
4. creates a digest-bound SystemState snapshot;
5. evaluates each DesiredState deterministically;
6. updates finding stabilization/lifecycle;
7. resolves one ActionCandidate per eligible active finding/policy version;
8. applies inhibition/dedup/cooldown/budget/mode;
9. dispatches admitted candidates through existing boundaries;
10. records dispatch/outcome links;
11. resolves findings whose DesiredState is stably satisfied;
12. emits bounded operational evidence.

### Run identity

Each run has:

- reconcile request/token ID;
- trigger;
- start/end timestamps;
- desired-state generation set/digest;
- snapshot digest;
- status;
- handled token.

Reusing an already handled request token is a no-op.

### Triggers

Initial trigger types:

- STARTUP;
- STATE_CHANGE_HINT;
- PERIODIC;
- MANUAL_TEST.

State-change signals are hints, not truth.

A periodic safety sweep guarantees eventual reconciliation if an event hint is missed.

The trigger mechanism is replaceable. Reconciliation correctness is stored in JARVIS
domain state, not in the scheduler.

## 21. Concurrency and replay safety

Phase 10A assumes the current single canonical JARVIS Core, but must still tolerate
multiple local trigger calls.

Requirements:

- in-process reconcile lock;
- SQLite transaction boundaries;
- deterministic IDs;
- unique constraints on active identities/dispatch links;
- CAS/versioned finding and attention updates;
- bounded batch size;
- no correctness dependence on trigger order;
- startup replay creates no duplicate WorkItem/EngineeringChange/attention.

Do not add distributed leader election in Phase 10A. Future multi-device architecture
can add a single-core/leader boundary when that phase is designed.

## 22. Authority integration

### Work creation versus action execution

Creating a bounded research/diagnostic WorkItem is not permission for its future steps
to bypass Authority.

Any executor operation that currently requires Authority continues to require it and
must carry proactive/system origin as appropriate.

### EngineeringChange

An autonomously-created EngineeringChange:

- starts as a governed proposal/research process;
- cannot self-approve architecture;
- cannot self-accept protected owner-machine gates;
- cannot self-promote protected production changes.

### Existing controller invocation

Only registered deterministic controller operations explicitly marked safe for the
current autonomy mode may be requested. No generic Python/shell/capability invocation is
part of ActionResolverPolicy.

### AuthorityEnvelope

A generalized future AuthorityEnvelope is explicitly deferred. Phase 10A does not
reinterpret budgets or modes as an AuthorityEnvelope.

## 23. Integration with Phase-10 learning

Phase 10A may retrieve accepted EngineeringKnowledge as advisory evidence during
research/diagnostic WorkItems.

It may also link its downstream outcome to a Phase-10 EngineeringOutcome.

It may not:

- use retrieved knowledge as execution permission;
- let a learned precedent override current DesiredState facts;
- let a model or knowledge record mark a Finding resolved without canonical evidence.

## 24. SystemState truth ownership

| Fact | Canonical owner | Phase-10A use |
| --- | --- | --- |
| component topology/dependencies | Self Model | read |
| component health | Health Registry | read |
| work lifecycle | WorkStore | read / create via WorkOrchestrator |
| work execution mechanics | DBOS | request/query support |
| engineering lifecycle | EngineeringChange | read / create governed change |
| incident truth | Incident store | read |
| repair outcome | Self-Repair / incident repair | read/link |
| capability desired/effective state | Capability Registry | read / existing reconciler |
| model/provider route health | Model Router store | read |
| promotion/deployment outcome | Promotion subsystem | read/link |
| engineering learning | EngineeringKnowledge/Phase 10 | advisory read/link |
| action permission | Authority / OPA | existing evaluation only |
| owner attention | Phase 10A | canonical new object |
| objective / desired state | Phase 10A | canonical new object |
| findings / action proposals | Phase 10A | canonical new objects |

## 25. Runtime composition

Phase 10A should be added to the existing `WorkRuntime` composition root as a bounded
service, not a new daemon stack.

Suggested composition:

```text
WorkRuntime
  +-- existing WorkStore / WorkOrchestrator / DBOS
  +-- existing ChangeCoordinator
  +-- existing capability/promotion/model-routing subsystems
  +-- AutonomyStore
  +-- SystemStateAggregator
  +-- DesiredStateRuleRegistry
  +-- ActionResolverRegistry
  +-- PortfolioPrioritizer
  +-- AutonomyReconciler
  +-- PeriodicAutonomyReconciler (trigger only)
```

The periodic wrapper should follow the accepted capability-reconciler pattern:

- bounded interval;
- one run at a time;
- exceptions observable;
- failure does not silently mutate state;
- startup run;
- clean shutdown.

If DBOS scheduled-workflow support on pinned `dbos==2.31.1` is proven useful, the
periodic trigger may later use it. That is an execution detail, not canonical design.

## 26. Initial registered system obligations

Phase 10A should not begin by trying to autonomously optimize everything.

Initial obligation registry should be small and reviewable.

Proposed initial obligations:

1. **control-plane health**
   - accepted core health surfaces must remain observable/fresh;
2. **critical runtime health**
   - explicitly registered critical components must remain within their accepted health
     states;
3. **capability desired/effective alignment**
   - existing capability reconciler remains first responder;
4. **durable work continuity**
   - active canonical work should not silently disappear after runtime restart;
5. **owner-attention integrity**
   - unresolved owner dependencies remain visible without notification spam.

Adding a new registered system obligation is a code/config change subject to the normal
governed engineering path.

## 27. Phase-10A evaluation strategy

Build a deterministic isolated replay harness before any production-assisted mode.

Minimum locked cases should include:

1. all desired states satisfied -> no finding/work/attention;
2. missing required source -> UNKNOWN, no autonomous action;
3. stale required evidence -> UNKNOWN, no autonomous action;
4. single transient violation -> STABILIZING only;
5. sustained violation -> one ACTIVE finding;
6. replay same snapshot -> no duplicate finding;
7. restart replay -> no duplicate candidate/dispatch;
8. stable recovery -> finding RESOLVED;
9. violated component with registered deterministic controller -> controller candidate,
   not EngineeringChange;
10. unknown sustained incident -> exactly one diagnostics/research path;
11. novel engineering-required finding -> exactly one governed EngineeringChange;
12. SHADOW mode -> findings/candidates persist, zero dispatch;
13. ASSISTED bounded diagnostic work -> exactly one WorkItem;
14. action requiring current Authority -> existing Authority still governs execution;
15. owner attention deduplicates repeated finding;
16. root-cause attention inhibits derivative attention;
17. re-notify interval prevents spam;
18. budget exhausted -> candidate deferred, no work creation;
19. cooldown active -> no redispatch;
20. two active Objectives -> deterministic portfolio order;
21. urgent/critical obligation does not starve owner-interactive reasoning;
22. dependency-unblocking tie-break is deterministic;
23. malformed source digest -> fail closed;
24. unknown DesiredState rule version -> fail closed;
25. DesiredState generation changes -> stale evaluation cannot satisfy new generation;
26. old reconcile request token -> no duplicate processing;
27. downstream terminal WorkItem links to outcome without copying execution truth;
28. autonomously-created EngineeringChange still reaches owner architecture gate;
29. Authority remains unchanged and no self-approval occurs;
30. protected repo/production state unchanged in owner-machine acceptance harness.

Existing Phase 6/7/8/9/10 regression lanes must remain green.

## 28. Owner-machine acceptance boundary

Final Phase-10A owner-machine acceptance should be:

- isolated/non-destructive by default;
- exact-commit bound;
- Windows-compatible;
- restart/replay capable;
- able to prove clean shutdown/restart of reconciliation;
- able to prove no duplicate autonomous dispatch;
- able to prove no Authority expansion;
- able to prove production mode remains SHADOW unless separately owner-enabled;
- able to prove repository/protected-main remains unchanged.

Any live ASSISTED proof should use a harmless bounded diagnostic/research scenario and
must not perform the deferred Phase-9 physical-device lifecycle unless that separate
validation is intentionally scheduled.

## 29. Implementation sequence after owner approval

If the owner approves this architecture, implement as isolated slices:

### Phase 10A.1 — contracts + durable autonomy store

Objective, DesiredState, Finding, ActionCandidate, Attention, run identity and schema.

### Phase 10A.2 — SystemState aggregation

Read-only adapters, bounded snapshot/digest/freshness semantics.

### Phase 10A.3 — DesiredState evaluators + stabilization

Rule registry, fail-closed evaluation, generation binding, hysteresis/cooldowns.

### Phase 10A.4 — findings + action resolution

Finding lifecycle, ActionCandidate identity, deterministic resolver hierarchy.

### Phase 10A.5 — budgets + portfolio + owner attention

Activity throttles, deterministic priority mapping, durable attention
dedupe/group/inhibition/re-notify.

### Phase 10A.6 — shadow/assisted dispatch bridges

Existing controller / WorkItem / EngineeringChange / attention bridges with replay-safe
dispatch links. Production remains SHADOW initially.

### Phase 10A.7 — reconciliation runtime + final evaluation

Startup/state-hint/periodic triggers, restart-safe replay corpus, exact-head CI and
owner-machine acceptance.

No slice may bypass the accepted owner-approval boundary for this architecture.

## 30. Explicit non-goals

Phase 10A does not:

- autonomously discover general new capability gaps (Phase 11);
- autonomously run optimization experiments (Phase 12);
- choose specialist training/model curricula (Phase 13);
- autonomously change protected governance (Phase 14 never implies that either);
- add a generalized delegated AuthorityEnvelope;
- self-approve architecture, promotion or governance;
- replace existing deterministic repair/capability reconcilers;
- create a new work engine or durable workflow platform;
- adopt Kubernetes/Crossplane/Temporal;
- create a second operational health or knowledge truth;
- make an LLM the SystemState or DesiredState judge;
- silently enable broad production autonomy.

## 31. Owner approval decision

Approval of this document authorizes implementation of Phase 10A within the contracts
above, starting with Phase 10A.1 on a new isolated implementation branch.

Approval does **not**:

- enable ASSISTED or ACTIVE_BOUNDED production autonomy by itself;
- grant new Authority;
- approve any future Phase-11/12/13/14 architecture;
- waive owner-machine acceptance;
- waive protected-main governance;
- waive the deferred Phase-9 whole-system validation.
