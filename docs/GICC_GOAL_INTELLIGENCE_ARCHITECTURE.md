# GICC - Goal Intelligence & Capability Composition Architecture

## Status

OWNER APPROVED / READY FOR IMPLEMENTATION - 2026-10-01

This architecture is based on INTELLIGENT_GOAL_CAPABILITY_ORCHESTRATION_RESEARCH.md.
Owner approved this architecture on 2026-10-01. Implementation may begin only through the documented dev-first lifecycle; production jarvis-voice remains protected until owner-machine acceptance and governed promotion.

## 1. Objective

JARVIS must treat an owner utterance as evidence of a desired outcome, not as a fixed
command name or a one-off capability specification.

Target behavior:

~~~text
owner request
-> understand desired outcome
-> resolve references/world context
-> determine whether more information is actually required
-> self-resolve missing facts where possible
-> ask one targeted owner question only when necessary
-> derive semantic capability requirements
-> match them against reusable existing capabilities
-> acquire only missing reusable capabilities
-> compose a plan
-> execute / observe / verify
-> replan when reality changes
-> resume the original goal after clarification/acquisition
-> complete the owner outcome
~~~

The active model is a reasoning worker. JARVIS owns canonical state.

## 2. Permanent invariants

1. Model output is not canonical truth. A model may propose an interpretation, plan,
   clarification, entity match or capability gap; JARVIS validates and persists it.
2. Owner request is not unrestricted Authority.
3. Task, capability, provider, resource and Authority are separate concepts.
4. Capability support, current task requirement and execution permission are separate.
5. Clarification is last resort; safe self-resolution comes first.
6. Clarification is task-bound; unrelated speech cannot satisfy a pending information need.
7. Capability acquisition is reusable; Phase 9 receives a reusable semantic gap.
8. DBOS plus WorkStore remain the durable execution substrate.
9. Existing Authority / OPA remains the only action-permission boundary.
10. Existing CapabilityRuntime / CapabilityRegistry remain capability truth.
11. Success requires observed evidence or a postcondition, not model text.
12. Monitoring is durable and event-first where practical.
13. Production behavior remains unchanged until owner-machine acceptance passes in jarvis-dev.
14. GICC APPLY must not run in jarvis-voice before explicit production promotion.

## 3. Runtime lane separation

Current repository fact: jarvis-dev supervises a child that runs
python -m jarvis.voice.production_runtime. Therefore development and production behavior
cannot rely on different Python runtime modules; an explicit runtime lane is required.

Introduce:

~~~text
RuntimeLane
  DEVELOPMENT
  PRODUCTION

GiccMode
  OFF
  SHADOW
  APPLY
~~~

Rules:

- jarvis-dev injects JARVIS_RUNTIME_LANE=development into its child.
- direct jarvis-voice defaults to production.
- jarvis-supervisor / governed release runtime uses production.
- before owner acceptance, GiccMode.APPLY is allowed only in DEVELOPMENT.
- production may run OFF or SHADOW while development testing is active.
- enabling production APPLY requires a separate owner-approved promotion tied to the
  accepted branch/SHA/release.
- accidentally running jarvis-voice directly from a feature branch must not activate GICC APPLY.

Required rollout:

~~~text
feature branch
-> jarvis-dev interactive use
-> full owner acceptance
-> governed promotion
-> jarvis-voice production activation
~~~

## 4. New package boundary

Introduce:

~~~text
src/jarvis/goal_intelligence/
  __init__.py
  models.py
  store.py
  interpretation.py
  world.py
  information.py
  requirements.py
  capability_graph.py
  planning.py
  continuation.py
  monitoring.py
  service.py
  composition.py
  evaluation.py
~~~

This package owns goal-intelligence state and orchestration only.

It does not own voice transport, capability execution, capability package lifecycle,
EngineeringChange, DBOS execution, Authority, secrets, model routing, or general memory.

## 5. Canonical ownership map

| Truth | Canonical owner |
| --- | --- |
| exact user text | ConversationSession |
| desired owner outcome | Goal Intelligence |
| stable resource/entity identity | Goal Intelligence resource registry |
| live device/system state | authoritative adapters / runtime snapshots |
| capability availability | CapabilityRuntime / CapabilityRegistry |
| capability acquisition lifecycle | Phase 9 + EngineeringChange |
| execution permission | Authority / OPA |
| committed durable execution | WorkStore / DBOS |
| plan intent/structure | Goal Intelligence PlanGraph |
| engineering promotion | Phase 7 |
| package enable/disable | Phase 8 |
| learned engineering precedent | Phase 10 |
| long-lived personal memory | existing Memory subsystem |

Goal Intelligence references external canonical stores by stable ID/digest instead of
copying their truth.

# PART I - DOMAIN CONTRACTS

## 6. OwnerGoalV2

Suggested fields:

~~~text
goal_id
goal_revision
source_session_id
source_turn_id
exact_owner_request
goal_kind
desired_outcome
completion_predicates[]
referenced_entity_ids[]
state
priority
created_at
updated_at
interpretation_evidence[]
digest
~~~

Initial goal_kind values:

- ONE_SHOT
- CONDITIONAL
- MONITORING
- LONG_RUNNING

These are execution-shape classes, not hard-coded intent domains such as TV or camera.

Lifecycle:

~~~text
RECEIVED
 -> RESOLVING
 -> WAITING_INFORMATION
 -> REQUIREMENTS_READY
 -> WAITING_CAPABILITY
 -> PLANNED
 -> EXECUTING
 -> MONITORING
 -> VERIFYING
 -> COMPLETED

PAUSED / FAILED / CANCELLED are side control or terminal states.
~~~

No model may directly mark COMPLETED.

## 7. GoalInterpretationCandidateV1

Model-generated and non-authoritative.

Suggested fields:

~~~text
desired_outcome
goal_kind
candidate_entities[]
candidate_completion_predicates[]
candidate_information_needs[]
reasoning_evidence_refs[]
~~~

Every consequential entity/condition must be grounded to owner text, recent context, or
trusted world evidence. Unsupported interpretation remains unresolved.

## 8. WorldEntityRefV1 and ResourceBindingV1

Stable operational identity, not general memory.

~~~text
WorldEntityRefV1
  entity_id
  entity_type
  canonical_name
  aliases[]
  relation_ids[]
  provenance_refs[]
  lifecycle_state

ResourceBindingV1
  entity_id
  provider_id
  provider_resource_id
  capability_keys[]
  evidence_refs[]
  last_verified_at
  binding_digest
~~~

Examples:

~~~text
living_room_tv       type=media_player
main_gate_camera     type=camera
main_gate --observed_by--> main_gate_camera
~~~

Dynamic facts such as "TV currently on" come from fresh adapter observations rather than
becoming stale registry truth.

## 9. InformationNeedV1

Typed clarification / missing-information contract.

~~~text
information_need_id
goal_id
plan_node_id optional
category
subject
required_fact
why_required
candidate_values[]
allowed_resolution_sources[]
self_resolution_attempts[]
owner_question optional
answer_schema
state
created_at
resolved_at
evidence_refs[]
digest
~~~

Initial categories:

- MISSING_VALUE
- AMBIGUOUS_REFERENCE
- DISAMBIGUATION
- OWNER_PREFERENCE
- OWNER_SECRET
- AUTHORIZATION
- SUCCESS_CRITERIA
- PHYSICAL_OBSERVATION

Lifecycle:

~~~text
OPEN
 -> SELF_RESOLVING
 -> RESOLVED

OPEN
 -> SELF_RESOLVING
 -> WAITING_FOR_OWNER
 -> RESOLVED

OPEN -> CANCELLED
~~~

An InformationNeed may enter WAITING_FOR_OWNER only if:

1. the fact is necessary;
2. safe self-resolution was attempted or is inapplicable;
3. choosing incorrectly materially affects outcome, target, Authority or cost;
4. the owner is an appropriate source.

Owner answers bind to the exact information_need_id and goal interaction. A generic
committed user turn is not sufficient.

Secrets and credentials remain in the existing secret subsystem and are referenced, not
stored as ordinary answers.

## 10. CapabilityRequirementV1

Represents one semantic ability required by a goal.

~~~text
requirement_id
goal_id
semantic_capability
operation
target_entity_id optional
target_entity_type optional
required_parameters_schema
preconditions[]
expected_postconditions[]
observation_requirements[]
reason
digest
~~~

Examples:

~~~text
semantic_capability = media_player.control
operation           = launch_app
target_entity_id    = living_room_tv

semantic_capability = camera.observe
operation           = read_live_stream
target_entity_id    = main_gate_camera
~~~

## 11. CapabilityRequirementGraphV1

A DAG of required semantic abilities and dependencies.

Node classes:

- capability requirement
- information requirement
- world-state precondition
- completion predicate

Example:

~~~text
camera.observe(read_live_stream)
        |
        v
vision.observe(person/package)
        |
        v
monitor(predicate)
        |
        v
notify(owner)
~~~

The graph describes requirements; it does not execute actions.

## 12. CapabilityGapV1

Derived from the requirement graph plus current capability truth.

~~~text
gap_id
goal_id
requirement_ids[]
reusable_capability_family
target_entity_type
target_entity_id optional
minimum_required_operations[]
matching_capability_keys[]
missing_reason_codes[]
motivating_goal_id
digest
~~~

Good reusable families:

~~~text
media_player.control
camera.observe
smart_lock.control
email.search
calendar.write
~~~

Bad task-specific families:

~~~text
play_transporter_2002_on_hotstar
notify_when_amazon_agent_stands_at_my_gate
~~~

## 13. Phase-9 bridge V2

Do not replace Phase 9.

Add a bridge:

~~~text
OwnerGoalV2
   |
CapabilityGapV1
   |
Phase9AcquisitionRequestV2
   |
existing Phase-9 source discovery / resolver / provenance / EngineeringChange
~~~

Phase9AcquisitionRequestV2 carries:

~~~text
motivating_goal_id
gap_id
reusable_capability_family
minimum_required_operations
target_entity_type
target_hints
~~~

A selected integration may expose a broader verified supported-operation set. That is
recorded as capability truth. The current task receives Authority only for operations it
actually requires.

## 14. PlanGraphV1

Canonical plan structure; DBOS Work remains execution.

~~~text
plan_id
goal_id
goal_revision
nodes[]
edges[]
root_node_ids[]
completion_node_ids[]
state
created_at
updated_at
digest
~~~

Node types:

- ACTION
- OBSERVE
- VERIFY
- SUBGOAL
- CLARIFY
- ACQUIRE_CAPABILITY
- WAIT
- MONITOR

Executable nodes reference existing capability operations or WorkItems and never contain
arbitrary executable code.

Plan node state:

~~~text
PENDING
READY
RUNNING
WAITING
SUCCEEDED
FAILED
SUPERSEDED
CANCELLED
~~~

A model may propose a new plan revision after observation/failure. Old revisions remain
auditable.

## 15. GoalContinuationV1

Restart-safe continuation link.

~~~text
continuation_id
goal_id
plan_id
blocked_by_type
blocked_by_id
resume_node_id
work_ids[]
goal_revision
state
created_at
resumed_at
digest
~~~

Blocker kinds include information need, capability acquisition, external acceptance,
time/event wait and dependency WorkItem.

This is how JARVIS returns to the original task after learning a capability or receiving
clarification.

## 16. MonitorPredicateV1

Typed monitoring condition.

~~~text
predicate_id
goal_id
source_entity_ids[]
observation_capabilities[]
semantic_condition
candidate_trigger_strategy
stability_window
cooldown
timeout optional
completion_policy
notification_policy
verification_requirement
digest
~~~

Monitoring rules:

- prefer deterministic/event triggers where available;
- use model/perception only on candidate events when practical;
- do not continuously spend cloud inference just because a stream exists;
- persist monitoring as WorkType.MONITORING;
- restart must resume without duplicating monitors or notifications.

# PART II - SERVICES

## 17. GoalInterpreter

Input:

- latest canonical USER turn
- bounded recent conversation
- current world/entity summary
- relevant active goals

Output: GoalInterpretationCandidateV1.

It may use the configured reasoning provider but does not write canonical goal state.

## 18. EntityResolver

Resolution order:

1. exact entity ID/name
2. explicit recent conversational referent
3. unique alias/relation match
4. trusted current world observation
5. bounded discovery when allowed
6. InformationNeed if still ambiguous

Do not ask the owner when exactly one trustworthy candidate exists.

## 19. InformationResolver

For each missing fact:

1. inspect canonical recent context;
2. query entity/resource registry;
3. invoke safe read-only discovery;
4. perform warranted retrieval/research;
5. observe current state when permitted;
6. only then create an owner-facing question if policy allows it.

## 20. CapabilityGraphResolver

Input:

- requirement graph
- CapabilityRuntime catalog
- Phase-8 effective package state
- world/resource bindings

Output:

- satisfied requirements
- reusable gaps
- blocked requirements

Matching is semantic and typed rather than simple string matching.

## 21. GoalPlanner

Planner rules:

- use existing capability operations only;
- no arbitrary shell/code;
- preserve owner-grounded targets/parameters;
- include observation and verification;
- add acquisition nodes for missing reusable capabilities;
- add clarification nodes only for admitted InformationNeeds;
- use MONITOR nodes for conditional goals;
- stop and replan when postconditions fail.

The existing Hands planner remains the computer-action specialist behind relevant plan nodes.

## 22. GoalOrchestrator

Conceptual flow:

~~~text
admit_goal()
resolve_context()
resolve_information()
derive_requirements()
resolve_capability_graph()

if gaps:
    start/link Phase-9 acquisitions
    persist continuation
    wait
else:
    build plan
    dispatch plan nodes to Work / Hands / CapabilityRuntime

on observation:
    verify
    advance or replan

on blocker resolved:
    resume exact continuation
~~~

It coordinates state but does not execute raw actions itself.

# PART III - VOICE INTEGRATION

## 23. Conversational model role

Realtime Gemini/OpenAI remains responsible for natural conversation, presenting
clarifications, status summaries and translating structured outcomes into speech.

It does not own capability-gap identity, goal state, InformationNeed state, completion
truth or task resumption.

## 24. Goal intake

Introduce one high-level voice tool conceptually named pursue_owner_goal.

It binds to the latest canonical USER turn and submits it to Goal Intelligence.

In GICC APPLY mode, the realtime model should not directly start ordinary Phase-9
capability acquisition. Phase-9 acquisition becomes an internal GoalOrchestrator action.

Legacy direct tools remain during shadow/migration so existing behavior is not broken.

## 25. Fast path

Not every request becomes heavyweight work.

When target is unambiguous, all capabilities exist, no long-running dependency exists,
no clarification is needed and Authority permits the action, Goal Intelligence may hand
the action directly to existing Hands/capability execution.

This preserves conversational latency.

# PART IV - PERSISTENCE

## 26. Storage design

Use the existing local canonical SQLite root rather than introducing another database
service.

Add independent Goal Intelligence tables through a dedicated GoalStore:

- owner_goals_v2
- world_entities_v1
- resource_bindings_v1
- information_needs_v1
- capability_requirement_graphs_v1
- capability_gaps_v1
- plan_graphs_v1
- goal_continuations_v1
- monitor_predicates_v1

Protected payloads use the same DPAPI-backed payload protection pattern as WorkStore.
Secret plaintext is never stored here.

## 27. Replay and idempotency

Requirements:

- restarting GoalOrchestrator cannot duplicate an active acquisition for the same gap;
- resolving the same InformationNeed twice is idempotent;
- plan action replay cannot duplicate an external side effect unless the operation is
  explicitly idempotent and policy permits;
- WorkItem IDs are persisted on PlanNodes/Continuations;
- completed goals stay completed after restart;
- monitor restoration does not duplicate notifications.

# PART V - DEV-FIRST ROLLOUT

## 28. Development-only APPLY invariant

The owner requires interactive testing in jarvis-dev before production behavior changes.

~~~text
GICC code exists
        |
        +-- jarvis-dev / DEVELOPMENT
        |      SHADOW -> APPLY allowed
        |
        +-- jarvis-voice / PRODUCTION
               OFF or SHADOW only
               APPLY rejected before promotion
~~~

The initial implementation must not enable production APPLY.

## 29. Development acceptance

Use a dedicated implementation branch.

Owner runs jarvis-dev on that exact branch. The dev supervisor injects the development
runtime lane and runs the normal microphone, realtime model, camera/vision, Work/DBOS,
Hands and capability stack.

Acceptance is conversational and realistic, not merely synthetic tests.

## 30. Production promotion

Only after:

1. automated tests pass;
2. deterministic replay passes;
3. owner-machine jarvis-dev acceptance passes;
4. existing Hands/Work/Phase-9/voice regressions pass;
5. exact accepted SHA is recorded;
6. owner explicitly approves production promotion;

may a separate promotion change enable production GICC APPLY for jarvis-voice.

Phase-7 promotion, production observation and rollback remain required.

# PART VI - ACCEPTANCE

## 31. Mandatory scenarios

### A. TV reusable capability

Owner: "I want to watch Transporter on my TV."

Pass:

- no movie-specific capability;
- TV entity resolved;
- reusable media/device-control gap identified;
- only acquisition-relevant questions during capability acquisition;
- original movie task resumes after capability readiness;
- title/source clarification only when execution genuinely needs it;
- playback observed and verified.

### B. Main-gate monitoring

Owner: "Monitor my main gate and let me know once a delivery agent is standing at the door."

Pass:

- generic main-gate entity resolution;
- perception/monitoring/notification reused when available;
- only missing camera/resource access acquired;
- "delivery agent" uncertainty represented truthfully;
- clarification only if event criteria cannot be safely operationalized;
- monitor survives restart;
- notification occurs only after verification.

### C. No acquisition

A multi-step desktop request already covered by Hands.

Pass: no Phase-9 acquisition and no needless clarification.

### D. Genuine ambiguity

Two valid resources fit "the gate camera" or "the TV".

Pass: one targeted InformationNeed, exact answer binding and automatic goal resume.

### E. Restart during owner wait

Pass: exact InformationNeed restored, no duplicate spam, unrelated speech rejected and
task resumes correctly.

### F. Restart during capability acquisition

Pass: no duplicate acquisition, original goal remains linked and capability completion
returns control to the original plan.

### G. Replanning

External state changes after planning.

Pass: failed postcondition cannot become false success; JARVIS observes and replans or
truthfully reports the blocker.

## 32. Non-goals for first implementation

- no academic/general BDI runtime;
- no mandatory Home Assistant dependency;
- no LangGraph/Semantic Kernel/OpenAI Agents runtime migration;
- no universal ontology;
- no unrestricted autonomous LAN/device discovery;
- no production voice activation before dev acceptance;
- no BUG-002 startup greeting fix inside GICC;
- no quick promotion of active-speaker shadow to Authority.

## 33. Architecture decision

Proceed by adding GICC above the existing stack:

~~~text
                  Realtime conversation
                           |
                     Goal Intelligence
                           |
        +------------------+------------------+
        |                  |                  |
      Hands             Phase 9           Work / DBOS
        |                  |                  |
        +------------ Capability Runtime -----+
                           |
                        Authority
~~~

This preserves the existing foundation while adding the missing goal/intelligence layer.
