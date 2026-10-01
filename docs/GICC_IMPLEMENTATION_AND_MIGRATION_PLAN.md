# GICC - Implementation and Migration Plan

## Status

OWNER APPROVED / READY FOR IMPLEMENTATION - 2026-10-01

This plan implements GICC_GOAL_INTELLIGENCE_ARCHITECTURE.md without changing
production jarvis-voice behavior until owner-machine acceptance passes through jarvis-dev.

Owner approved this implementation/migration plan on 2026-10-01. The implementation is intentionally incremental. Existing JARVIS systems remain authoritative while each GICC stage is proven.

---

## 1. Delivery strategy

Use one isolated implementation branch and one development runtime lane.

High-level sequence:

~~~text
GICC-0  runtime lane + contracts + persistence
GICC-1  shadow goal interpretation
GICC-2  world/entity resolution + typed clarification
GICC-3  capability requirement graph + reusable gap analysis
GICC-4  Phase-9 V2 bridge + continuation
GICC-5  PlanGraph execution + observe/verify/replan
GICC-6  monitoring goals
GICC-7  full jarvis-dev owner acceptance
GICC-8  production promotion to jarvis-voice
~~~

No GICC stage before GICC-8 may enable production APPLY.

---

## 2. Branch and promotion model

Implementation branch naming:

~~~text
feat/gicc-goal-intelligence
~~~

Development runtime:

~~~powershell
$env:JARVIS_DEV_BRANCH = "feat/gicc-goal-intelligence"
jarvis-dev
~~~

Production runtime remains on main/LKG and is not used to test candidate behavior.

The final production activation is a separate governed promotion after owner acceptance
of the exact candidate SHA.

---

# GICC-0 - RUNTIME LANE, CONTRACTS, STORE

## 3. RuntimeLane and GiccMode

Add a small shared runtime-mode module, for example:

~~~text
src/jarvis/runtime_lane.py
~~~

Contracts:

~~~text
RuntimeLane.DEVELOPMENT
RuntimeLane.PRODUCTION

GiccMode.OFF
GiccMode.SHADOW
GiccMode.APPLY
~~~

Suggested environment/config:

~~~text
JARVIS_RUNTIME_LANE
JARVIS_GICC_MODE
~~~

Defaults:

~~~text
direct jarvis-voice:
  runtime_lane = production
  gicc_mode    = off initially

jarvis-supervisor:
  runtime_lane = production
  gicc_mode    = off initially

jarvis-dev:
  runtime_lane = development
  gicc_mode    = shadow initially
~~~

During owner acceptance we explicitly switch jarvis-dev to APPLY.

Hard guard:

~~~text
if runtime_lane == PRODUCTION and gicc_mode == APPLY and production_activation_not_approved:
    fail closed
~~~

For the first implementation, the simplest safe form is: production APPLY is not a
valid configuration at all. A later promotion commit intentionally enables it.

Required tests:

- direct jarvis-voice cannot silently enter development lane;
- jarvis-dev child receives development lane;
- production APPLY rejected;
- dev SHADOW/APPLY accepted.

---

## 4. Dev supervisor change

Modify src/jarvis/dev_supervisor.py so the child environment clearly identifies the lane.

The development entrypoint must inject:

~~~text
JARVIS_RUNTIME_LANE=development
~~~

The production supervisor path injects or defaults:

~~~text
JARVIS_RUNTIME_LANE=production
~~~

Do not infer lane from branch name.

This is necessary because both supervisors ultimately start
jarvis.voice.production_runtime.

---

## 5. Domain models

Create src/jarvis/goal_intelligence/models.py.

Implement frozen, validated, digest-bound dataclasses/enums for:

- OwnerGoalV2
- GoalInterpretationCandidateV1
- WorldEntityRefV1
- ResourceBindingV1
- InformationNeedV1
- CapabilityRequirementV1
- CapabilityRequirementGraphV1
- CapabilityGapV1
- PlanNodeV1
- PlanGraphV1
- GoalContinuationV1
- MonitorPredicateV1

Requirements:

- canonical JSON/digest helpers reuse existing engineering_substrate canonical helpers;
- enums are explicit;
- IDs are deterministic where replay semantics require them;
- no plaintext secrets;
- no model-generated numeric confidence as Authority/truth;
- validation fails closed.

---

## 6. GoalStore

Create src/jarvis/goal_intelligence/store.py.

Use the existing canonical local SQLite path and protected payload codec pattern.

Do not modify existing WorkStore row semantics.

GoalStore owns only its new tables and has explicit methods such as:

~~~text
create_goal
get_goal
update_goal_state
put_entity
get_entity
put_resource_binding
create_information_need
resolve_information_need
put_requirement_graph
put_gap
put_plan
put_continuation
put_monitor_predicate
~~~

Concurrency:

- SQLite transactions;
- compare-and-swap version/generation where state mutation matters;
- unique active-gap constraints;
- unique unresolved InformationNeed identities;
- idempotent continuation resume.

Tests must include DPAPI-protected payload round-trip on Windows-compatible abstraction.

---

# GICC-1 - SHADOW GOAL INTERPRETATION

## 7. GoalInterpreter

Create interpretation.py.

Add a strict structured-output model that receives:

- latest canonical user turn;
- bounded recent user turns;
- known entity summaries only;
- relevant active goals;
- no secret values.

Returns GoalInterpretationCandidateV1.

Prompt principles:

- interpret desired outcome, not command phrase;
- distinguish task-specific parameters from reusable capability;
- prefer unresolved over invented target;
- preserve natural Hinglish/English behavior;
- do not ask owner questions directly;
- do not claim success;
- do not create Authority.

---

## 8. Shadow observer

In GICC SHADOW mode:

- every accepted actionable-looking user turn may be interpreted;
- candidate interpretation is logged/persisted as shadow evidence;
- existing Jarvis routing remains authoritative;
- no new owner questions;
- no Phase-9 acquisition;
- no action changes.

We need comparison telemetry:

~~~text
original_user_turn
shadow_goal_kind
shadow_desired_outcome
shadow_entities
shadow_information_needs
shadow_capability_requirements
legacy_route/result
~~~

No sensitive values in logs.

Acceptance threshold before APPLY:

- no obvious task overfitting in TV test;
- no camera-specific hardcoding in gate test;
- ordinary chat is not turned into work;
- normal Hands requests are interpreted without changing behavior.

---

# GICC-2 - WORLD MODEL AND TYPED CLARIFICATION

## 9. Entity/resource registry

Create world.py.

Initial entity types should remain small and extensible:

- media_player
- camera
- computer
- application
- display
- room
- entrance
- person-reference only when explicitly supported
- generic external_resource

Do not create a giant ontology in this phase.

Adapters can project existing known resources into ResourceBindingV1.

Initial binding sources may include:

- existing CapabilityRuntime metadata;
- owner-configured resources;
- current machine devices;
- future Home Assistant/MCP adapter if separately approved.

---

## 10. Entity resolution

Resolution must follow architecture order and return one of:

~~~text
RESOLVED(entity_id, evidence)
AMBIGUOUS(candidate_entity_ids)
MISSING
~~~

No model-only entity ID may become canonical without evidence.

Tests:

- one known TV + "my TV" resolves;
- two TVs + "my TV" becomes InformationNeed;
- "main gate" relation resolves to gate entity;
- stale/nonexistent binding does not silently resolve.

---

## 11. InformationResolver

Create information.py.

Resolution strategy registry:

~~~text
conversation_context
world_registry
current_state_observation
bounded_local_discovery
research_retrieval
owner_input
secret_flow
~~~

Owner input is last.

InformationNeed must store what was tried before asking.

---

## 12. Owner-input binding redesign

Add a new exact interaction binding for GICC InformationNeed.

The owner-facing prompt carries:

~~~text
goal_id
information_need_id
expected answer schema
allowed candidate values if any
~~~

The voice interaction may accept a turn only while that exact interaction is active.

Do not reuse the current generic background-owner-input semantics for GICC.

This is intentionally designed so the GICC path does not reproduce BUG-001.

The existing BUG-001 path can remain unchanged until separately migrated.

Regression tests:

- unrelated user turn outside bound interaction does not resolve need;
- exact bound reply resolves once;
- restart restores pending need without consuming ambient speech;
- another WorkItem cannot receive the reply.

---

# GICC-3 - CAPABILITY REQUIREMENT GRAPH AND GAP ANALYSIS

## 13. Requirement derivation

Create requirements.py.

A reasoning worker proposes semantic requirements; deterministic validation confirms:

- operation name format;
- target entity binding;
- required preconditions;
- completion observation;
- no capability family derived from task-specific proper noun unless justified.

Examples:

TV request:

~~~text
goal:
watch media on living_room_tv

requirements:
media_player.control.launch_app
media_player.control.navigate_or_text_input
media_player.control.play
media_player.observe.playback_state
~~~

Gate request:

~~~text
camera.observe.read_live_stream(main_gate_camera)
vision.perceive.person_and_package
monitor.evaluate(predicate)
notification.owner.send
~~~

---

## 14. Capability semantic metadata

Extend CapabilityDescriptor metadata without breaking existing descriptors.

Add optional normalized metadata:

~~~text
semantic_capability_family
target_entity_types[]
operation_effects
observation_operations[]
idempotency hints
reversibility hints
acquisition_target_hints
~~~

Existing descriptors without new metadata continue to function through compatibility
mapping.

No broad automatic migration is required on day one.

---

## 15. CapabilityGraphResolver

Create capability_graph.py.

Algorithm:

1. load requirement graph;
2. load current CapabilityRuntime catalog and Phase-8 state;
3. match each requirement to executable/effective capability;
4. identify satisfied nodes;
5. group missing nodes by reusable capability family and compatible target type;
6. emit CapabilityGapV1;
7. deduplicate active gaps for same goal/family/target/minimum operations.

Important:

- current task data such as Transporter title must not affect reusable family identity;
- selected package may support more operations than minimum requirement;
- extra supported operations do not grant task Authority.

---

# GICC-4 - PHASE-9 V2 BRIDGE AND CONTINUATION

## 16. Phase9AcquisitionRequestV2

Add a new bridge contract in capability_acquisition or goal_intelligence integration.

It should convert CapabilityGapV1 to existing OwnerCapabilityGoalV1-compatible research
input without losing motivating-goal linkage.

Do not delete V1.

Suggested adapter:

~~~text
Phase9GoalBridge.admit_gap(gap, goal)
~~~

It:

- records motivating_goal_id and gap_id in acquisition artifacts;
- supplies reusable capability family;
- supplies minimum required operations;
- supplies target type/hints;
- explicitly excludes task-only parameters.

---

## 17. Acquisition completion callback

When Phase 9 reaches a verified/activated state required by the goal:

1. verify exact gap linkage;
2. refresh CapabilityRuntime catalog;
3. re-run CapabilityGraphResolver;
4. only if gap is now satisfied, resolve continuation;
5. resume original goal/plan.

No model statement "capability is ready" is sufficient.

---

## 18. Existing Transporter work

Do not automatically mutate the current work_093a4bd977fe43f5 record.

Treat it as historical validation evidence.

For the new GICC acceptance, start a clean owner goal after GICC APPLY is enabled in
jarvis-dev. Reuse trustworthy research/provenance only through normal evidence retrieval
if it is still applicable.

This avoids trying to reinterpret old V1 state in place.

---

# GICC-5 - PLANGRAPH EXECUTION

## 19. PlanGraph planner

Create planning.py.

The planner sees:

- canonical OwnerGoalV2;
- resolved entities;
- satisfied capability requirements;
- allowed semantic operations;
- current observations;
- prior plan result evidence.

It outputs a strict candidate graph.

Validation:

- DAG only;
- node/edge limits;
- every ACTION maps to existing capability operation;
- every ACQUIRE node maps to canonical gap;
- every CLARIFY node maps to canonical InformationNeed;
- every VERIFY node has an observable predicate;
- no arbitrary executable text.

---

## 20. Plan dispatcher

GoalOrchestrator dispatches nodes through existing systems:

| Plan node | Existing execution path |
| --- | --- |
| ACTION: computer | Hands |
| ACTION: capability | CapabilityRuntime |
| ACQUIRE_CAPABILITY | Phase 9 |
| CLARIFY | InformationNeed owner interaction |
| WAIT | Work waiting state |
| MONITOR | WorkType.MONITORING |
| OBSERVE | read-only capability / sensor |
| VERIFY | deterministic check or bounded reasoning over observation |
| SUBGOAL | child Goal/Work linkage when necessary |

Do not embed another scheduler.

---

## 21. Observe / verify / replan

After an action:

- capture canonical operation result;
- obtain required observation;
- evaluate postcondition;
- if satisfied, advance;
- if not satisfied and recoverable, produce new plan revision;
- if missing capability appears, derive new gap;
- if missing owner fact appears, derive InformationNeed;
- if blocked, report truthfully.

Add anti-loop controls:

- action+parameter+state fingerprint;
- reject exact no-progress repetition;
- bounded replan budget;
- explicit stagnation reason;
- owner escalation only after self-resolution is exhausted.

---

# GICC-6 - MONITORING

## 22. Monitoring planner

Create monitoring.py.

For conditional goals choose the cheapest trustworthy observation strategy:

~~~text
native event
-> state-change subscription
-> local detector
-> bounded polling
-> expensive perception/model analysis only when warranted
~~~

Example gate pipeline:

~~~text
camera/motion event
-> candidate frame/snapshot
-> person/package perception
-> semantic predicate verification
-> owner notification
~~~

Do not stream every frame to a cloud model.

---

## 23. Monitoring Work integration

Create/link WorkType.MONITORING item with:

- predicate ID;
- source entity IDs;
- trigger strategy;
- last observation digest;
- debounce/stability state;
- notification state;
- continuation/goal ID.

Restart restores exact monitor state.

Tests include duplicate-event suppression and notification idempotency.

---

# GICC-7 - DEV OWNER ACCEPTANCE

## 24. Automated acceptance suite

Add tests such as:

~~~text
tests/test_goal_intelligence_models.py
tests/test_goal_intelligence_store.py
tests/test_goal_interpretation.py
tests/test_information_need_resolution.py
tests/test_world_entity_resolution.py
tests/test_capability_gap_analysis.py
tests/test_phase9_goal_bridge.py
tests/test_goal_continuation.py
tests/test_plan_graph.py
tests/test_goal_replanning.py
tests/test_goal_monitoring.py
tests/test_gicc_runtime_lane.py
tests/test_gicc_owner_acceptance.py
~~~

Existing regression suites remain green.

---

## 25. Development interactive acceptance

Only jarvis-dev is used.

Required owner-machine conversational scenarios:

### Scenario 1 - TV

Say naturally:

~~~text
Jarvis, I want to watch Transporter on my TV.
~~~

Observe whether JARVIS:

- understands the outcome;
- resolves TV;
- discovers only reusable missing capability;
- does not ask movie edition/subscription/country during capability acquisition unless
  genuinely required at execution time;
- returns to original task after capability readiness.

### Scenario 2 - gate monitoring

~~~text
Jarvis, monitor my main gate and let me know once a delivery agent is standing at the door.
~~~

Observe whether JARVIS:

- understands conditional monitoring;
- resolves/accesses the camera or asks only necessary resource clarification;
- composes perception + monitor + notification;
- does not ask technical questions the system can solve itself;
- handles uncertainty honestly.

### Scenario 3 - existing Hands

Use ordinary PC action.

Pass if GICC does not make the experience slower or create unnecessary acquisition.

### Scenario 4 - ambiguity

Use a deliberately ambiguous resource.

Pass if one useful question is asked and the task resumes.

### Scenario 5 - restart

Restart jarvis-dev while waiting for clarification/acquisition/monitor.

Pass if state resumes correctly.

---

## 26. Acceptance telemetry

During dev APPLY, log structured events:

~~~text
gicc_goal_admitted
gicc_entity_resolved
gicc_information_need_created
gicc_information_need_resolved
gicc_requirement_graph_created
gicc_capability_gap_created
gicc_phase9_linked
gicc_plan_created
gicc_plan_node_dispatched
gicc_postcondition_verified
gicc_replan
gicc_monitor_triggered
gicc_goal_completed
~~~

Logs include IDs/digests and reason codes, not secrets.

---

## 27. Owner approval gate

Before GICC-8 the owner must explicitly approve:

- exact implementation SHA;
- acceptance report;
- known limitations;
- production activation.

No implicit merge/promotion from tests alone.

---

# GICC-8 - PRODUCTION PROMOTION

## 28. Separate production activation change

After development acceptance, prepare a small isolated production activation change.

It may:

- allow GICC APPLY in production runtime lane;
- set production composition default/config;
- update preflight to display GICC production state;
- add production rollback guard.

It should not contain major new GICC logic. Major logic was already tested in jarvis-dev.

---

## 29. Phase-7 promotion

Use existing governed promotion:

~~~text
accepted candidate SHA
-> PR / CI
-> promotion evidence
-> owner gate
-> merge
-> staged release
-> production startup readiness
-> observation samples
-> LKG close
~~~

If production observation fails, rollback to prior LKG.

---

## 30. Production observation

Minimum observation:

- startup/preflight healthy;
- GICC production mode identity logged;
- ordinary conversation still works;
- one low-risk existing-capability goal succeeds;
- no duplicate durable work;
- no unexpected owner-input prompt;
- no new crash/liveness degradation.

TV/gate physical tests may be repeated after promotion if safe.

---

# MIGRATION AND COMPATIBILITY

## 31. Existing Phase-9 compatibility

Keep:

- OwnerCapabilityGoalV1
- existing acquisition WorkItems
- existing source adapters
- resolver
- candidate verification
- EngineeringChange lifecycle
- Phase-7/8 promotion/package paths

Add V2 bridge rather than changing historical records.

---

## 32. Existing Hands compatibility

Keep existing Hands router/planner/executor.

GICC supplies goals/subtasks to Hands; it does not reimplement UIA/browser/visual control.

Fast-path benchmark must prove no material regression for common Hands commands.

---

## 33. Existing voice compatibility

Before production promotion:

- production tool list/behavior stays legacy;
- development GICC wiring is lane-gated;
- wake/voice/vision stack remains unchanged except for new goal intake integration;
- BUG-002 startup greeting remains deferred.

---

## 34. Existing Work/DBOS compatibility

No WorkType replacement.

Reuse current types, especially:

- RESEARCH
- DEVELOPMENT
- EXTERNAL_ACCEPTANCE
- HANDS
- MONITORING

Goal/Plan objects describe why and how; WorkItem remains committed durable execution.

---

## 35. Existing Authority compatibility

No GICC decision bypasses Authority.

Planner-created capability operation requests use the same action-origin and policy
evaluation as current requests.

Acquiring a package does not authorize executing all operations in it.

---

## 36. Data migration

No destructive migration.

New tables are additive.

Existing V1 Phase-9 records remain valid.

Historical V1 capability acquisition may be read as evidence but is not silently converted
into OwnerGoalV2.

---

# PERFORMANCE AND COST

## 37. Latency policy

Use intelligence proportionate to complexity.

Fast simple request:

~~~text
goal interpretation -> existing capability -> execute
~~~

Complex request:

~~~text
goal -> resolve -> requirements -> plan
~~~

Unknown capability:

~~~text
goal -> gap -> durable Phase-9 acquisition
~~~

Do not call the strongest model at every stage if deterministic logic can decide.

---

## 38. Model routing

Suggested roles:

- realtime model: natural conversation/presentation;
- goal interpretation/planning: ChatGPT Plan or configured reasoning target;
- deterministic resolver: no model;
- current research: existing research provider;
- perception: existing vision stack / task-specific provider;
- verification: deterministic when possible.

All roles remain behind existing model routing/provider configuration.

---

## 39. Cost controls

- cache stable capability/world metadata;
- avoid repeated research for same evidence digest;
- event-trigger monitoring;
- bounded planner/replan budgets;
- C6-style compact context after proven safe;
- do not send full Work history unnecessarily;
- record actual action/decision observability.

---

# IMPLEMENTATION STOP CONDITIONS

## 40. Stop and return to architecture review if

- implementation requires a second workflow engine;
- production APPLY is needed before dev acceptance;
- capability identity needs task-specific content to work generically;
- InformationNeed cannot be bound to exact interaction;
- replay can duplicate external effects;
- Authority would need to be weakened;
- World Model becomes an unbounded personal-memory duplicate;
- PlanGraph starts storing executable arbitrary code;
- Phase-9 evidence/provenance would be bypassed.

---

## 41. Definition of done

GICC is not done when unit tests pass.

It is done only when:

1. contracts/storage are deterministic and protected;
2. shadow interpretation is sensible;
3. jarvis-dev APPLY works in natural owner usage;
4. TV case produces reusable capability behavior;
5. gate case produces composed monitoring behavior;
6. genuine ambiguity produces one targeted clarification;
7. restart/replay preserves exact state;
8. ordinary Hands remains good;
9. production remains untouched until owner approval;
10. exact accepted SHA is promoted through existing Phase-7 controls;
11. production observation succeeds or rolls back safely.
