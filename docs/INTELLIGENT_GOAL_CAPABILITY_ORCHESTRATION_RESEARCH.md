# Intelligent Goal & Capability Orchestration Research

**Status:** Research complete; architecture review required before implementation  
**Date:** 2026-10-01

## Objective

JARVIS should behave as a goal-driven intelligent assistant rather than a command/intent bot or an LLM that directly maps the latest utterance to one tool. The model is a reasoning worker; JARVIS owns canonical goals, world state, capability truth, durable work, authority, verification, clarification state, monitoring state, and task continuation.

Target loop:

```text
owner request
-> understand desired outcome
-> resolve entities/context
-> check information sufficiency
-> self-resolve missing facts where possible
-> ask owner only for necessary unresolved facts
-> derive capability requirements
-> compare with current capability graph
-> acquire only missing reusable capabilities
-> compose plan
-> execute / observe / verify
-> replan when needed
-> resume motivating task after clarification/acquisition
-> complete owner goal
```

## Key conclusions from research

### 1. Do not build another Alexa/Siri-style fixed intent system

Traditional assistants provide useful ideas such as required parameters, disambiguation,
validation and confirmation, but they assume developer-defined intents/actions. JARVIS
must additionally detect capability gaps, discover or build reusable capabilities, and
resume the original task.

### 2. Keep JARVIS-native state and orchestration

Modern frameworks such as OpenAI Agents SDK, Semantic Kernel and LangGraph offer useful
patterns: typed tools, manager/specialist composition, durable interrupts, and
human-in-the-loop resume. JARVIS already has stronger project-specific foundations:
DBOS Work, WorkStore, CapabilityRuntime, CapabilityRegistry, Phase-9 acquisition,
EngineeringChange, Authority/OPA, Hands, model routing and Phase-10/10A.

Use the patterns, not another canonical workflow engine.

### 3. Use a BDI-like separation without adopting an academic BDI runtime

JARVIS already has natural equivalents:

```text
Beliefs    = canonical world/system/device state + verified knowledge
Desires    = owner goals/objectives
Intentions = selected plan + active durable Work
```

This separation prevents the active model from becoming the owner of truth or committed
state.

### 4. Clarification must be typed and last-resort

JARVIS should ask the owner only when:

1. the missing/ambiguous fact is necessary for correct or safe progress;
2. it cannot be resolved from trusted conversation context, world state, bounded
   discovery, retrieval, observation or existing knowledge;
3. choosing incorrectly would materially change outcome, authority, cost or target;
4. the owner is an appropriate source.

Clarification should be represented as durable task-bound information need, not generic
free-form "needs_owner" text.

### 5. Separate task from reusable capability

Example:

```text
Task: "Watch Transporter on my TV"

Reusable gap:
media_player.control for the referenced TV

Task-specific details:
which Transporter title, which streaming source, current catalog availability
```

Example:

```text
Task: "Tell me when a delivery agent reaches my main gate"

Possible reusable gaps:
camera.observe for the main-gate camera

Existing reusable pieces:
vision/perception
monitoring
notification
```

Do not create one-off capabilities such as "play Transporter on Hotstar" or
"detect delivery agent at my gate".

### 6. Separate semantic capability, provider adapter and resource instance

Target model:

```text
semantic capability: media_player.control
provider adapter:    VIDAA / Home Assistant / SDK
resource instance:   living_room_tv

semantic capability: camera.observe
provider adapter:    ONVIF / Home Assistant / vendor API
resource instance:   main_gate_camera
```

This enables reuse across future tasks.

### 7. Capability breadth and execution authority are different

A verified integration may support many operations. The current task may require only a
subset, and Authority may permit an even narrower subset.

Permanent invariant:

```text
supported operations != current task requirements != execution authority
```

### 8. Prefer composition over giant skills

Owner outcomes should be built by composing existing capabilities. Phase 9 should acquire
only missing graph nodes.

### 9. Monitoring is a first-class plan type

"Tell me when X happens" should use durable MONITORING Work and event/predicate-driven
observation where possible. Expensive model/perception calls should be triggered by
candidate events rather than continuous polling when a cheaper trusted trigger exists.

### 10. Add an operational world model

JARVIS needs canonical entities/resources and relationships such as:

```text
entrance.main_gate -> camera.main_gate
living_room -> media_player.living_room_tv
```

The model may propose reference resolution, but trusted adapters/world state establish
canonical identity.

## Recommended new layer

Working name: **Goal Intelligence & Capability Composition (GICC)**.

Responsibilities:

1. normalize an owner request into a durable goal;
2. resolve entities and context;
3. track unresolved information;
4. self-resolve what can be resolved;
5. create typed clarification only when required;
6. derive a capability requirement graph;
7. identify reusable capability gaps;
8. invoke Phase 9 only for missing capabilities;
9. compose available/acquired capabilities into a hierarchical plan;
10. execute through existing Work/Hands/capability runtimes;
11. observe and verify postconditions;
12. replan on changed state/failure;
13. resume the motivating task after clarification/acquisition;
14. support one-shot, long-running, conditional and monitoring goals.

## Candidate canonical contracts for architecture phase

- `OwnerGoalV2`
- `WorldEntityRefV1` / `ResourceBindingV1`
- `InformationNeedV1`
- `CapabilityRequirementV1`
- `CapabilityRequirementGraphV1`
- `CapabilityGapV1`
- `PlanGraphV1`
- `PlanNodeV1`
- `GoalContinuationV1`
- `MonitorPredicateV1`

Exact schemas are intentionally deferred to the architecture document.

## Acceptance scenarios

Implementation must be generic and pass at least:

1. **TV capability gap**
   - "I want to watch Transporter on my TV."
   - acquire reusable TV/media-player control if missing;
   - resume original task;
   - ask title/source questions only when task execution genuinely needs them.

2. **Gate monitoring**
   - "Monitor my main gate and let me know once a delivery agent is standing at the door."
   - resolve main-gate entity;
   - acquire camera access only if missing;
   - compose camera + perception + monitoring + notification;
   - clarify success criteria only when genuinely necessary.

3. **No acquisition**
   - a multi-step desktop task already covered by Hands;
   - execute without Phase-9 acquisition.

4. **Genuine ambiguity**
   - two plausible target devices;
   - ask one targeted clarification and resume the exact task.

5. **Restart/replay**
   - clarification or monitor survives restart;
   - no duplicate task;
   - unrelated speech cannot satisfy a pending information need.

## External research themes used

- Alexa dialog/slot collection and validation
- Siri/App Intents parameter resolution
- OpenAI Agents SDK manager/tools/HITL patterns
- Semantic Kernel function-calling planners
- LangGraph durable interrupts/resume
- DBOS durable AI/HITL workflows
- MCP typed tools / elicitation / tool annotations
- Home Assistant normalized device/entity/trigger abstractions
- BDI agent architecture
- hierarchical planning and reactive Behavior Tree concepts

## Recommendation

Proceed to an exact architecture and migration plan against the current repository. Do not
start production implementation until those contracts, integration points, rollout/shadow
strategy, compatibility plan and acceptance tests are owner-approved.
