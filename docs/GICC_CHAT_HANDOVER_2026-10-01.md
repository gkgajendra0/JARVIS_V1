# JARVIS GICC - Chat Handover

## Status

**READY TO START IMPLEMENTATION IN A NEW CHAT - 2026-10-01**

Owner approved the GICC research direction, architecture, implementation/migration plan,
and dev-first rollout on 2026-10-01.

No GICC runtime implementation has started yet.

The next chat should begin implementation from GICC-0 on an isolated feature branch.
Production `jarvis-voice` must remain unchanged until owner-machine acceptance passes
through `jarvis-dev` and the exact accepted candidate is promoted through the governed
promotion path.

---

# 1. Repository

Repository:

`gkgajendra0/JARVIS_V1`

Local owner machine:

`C:\Users\gkgaj\Desktop\jarvis_v1`

Documentation branch used for the completed design work:

`docs/intelligent-goal-capability-research`

Documentation PR:

`#248 - docs: define GICC intelligent goal orchestration`

The design PR contains three core documents:

1. `docs/INTELLIGENT_GOAL_CAPABILITY_ORCHESTRATION_RESEARCH.md`
2. `docs/GICC_GOAL_INTELLIGENCE_ARCHITECTURE.md`
3. `docs/GICC_IMPLEMENTATION_AND_MIGRATION_PLAN.md`

Architecture and implementation plan are OWNER APPROVED / READY FOR IMPLEMENTATION.

---

# 2. Why GICC is being built

The current JARVIS architecture contains strong foundations but interprets some owner
requests too directly as capability-acquisition requests.

Observed example:

`I want to watch Transporter on my TV.`

Current Phase-9 interpretation became approximately:

`requested_capability=media_control`
`required_operations=play_media`
`target=Hisense TV`

This led capability acquisition to ask task-specific questions such as:

- which Transporter movie;
- streaming source;
- Hotstar/subscription/catalog details.

Those can be valid later when actually executing the movie task, but they should not
define the reusable capability being acquired.

Desired reusable capability is closer to:

`media_player.control`

with a provider/resource binding such as:

`provider=VIDAA/Home Assistant/SDK`
`resource=living_room_tv`

The original task should resume after that reusable capability exists.

Second acceptance example:

`Monitor my main gate and let me know once a delivery agent is standing at the door.`

JARVIS should not build a one-off
`detect_delivery_agent_at_my_main_gate` capability.

It should decompose the goal into reusable pieces such as:

- `camera.observe`
- vision/perception
- condition monitoring
- owner notification

and acquire only whichever reusable capability is actually missing.

---

# 3. North-star behavior

JARVIS should behave as an intelligent goal-driven assistant, not a fixed Alexa/Siri
intent system and not merely an LLM with tools.

Permanent conceptual rule:

```text
MODEL = reasoning worker
JARVIS = intelligent system
```

The model may:

- interpret natural language;
- propose goals;
- propose entity resolution;
- propose information needs;
- decompose tasks;
- propose capability requirements;
- research options;
- propose plans;
- interpret uncertain observations.

JARVIS itself owns:

- canonical owner goals;
- canonical entity/resource identity;
- capability truth;
- missing-information state;
- durable work;
- continuation/resume state;
- Authority;
- verification;
- monitoring state;
- completion truth.

Target loop:

```text
owner request
-> understand desired outcome
-> resolve entities/context
-> check information sufficiency
-> self-resolve missing information where possible
-> ask owner only when genuinely necessary
-> derive capability requirements
-> compare with current reusable capabilities
-> acquire only missing reusable capabilities
-> compose plan
-> execute
-> observe
-> verify
-> replan when required
-> resume after clarification/acquisition
-> complete original owner goal
```

---

# 4. Critical concept separation

These concepts must never collapse into one another:

```text
owner task
!= reusable capability
!= provider/integration
!= physical/logical resource
!= execution Authority
```

Example:

```text
Task:
Watch Transporter

Semantic capability:
media_player.control

Provider:
VIDAA / Home Assistant / SDK

Resource:
living_room_tv

Authority:
only exact operations currently allowed for this task
```

Another permanent invariant:

```text
capability supported operations
!= current task required operations
!= current execution permission
```

A package may support power, launch_app, navigation, text input, volume, playback and
state observation. The current task may use only launch/search/play. Authority remains
narrow.

---

# 5. Intelligent clarification policy

JARVIS must not ask the owner a question merely because the model does not know the answer.

Ask only when all are true:

1. the missing/ambiguous fact is necessary;
2. JARVIS cannot safely resolve it from current conversation context, canonical world
   state, existing resources, bounded discovery, observation, retrieval or research;
3. choosing incorrectly would materially change the target, outcome, Authority, cost or
   success criteria;
4. the owner is an appropriate source.

Good questions:

- which of two genuinely ambiguous TVs/cameras;
- pairing PIN visible only to owner;
- explicit owner authorization;
- owner preference that cannot be inferred;
- what success criteria mean when semantic ambiguity matters.

Bad questions:

- camera brand when JARVIS can discover it;
- protocol when JARVIS can research it;
- movie edition while generic TV control is still being acquired;
- streaming country/subscription details before they are needed for task execution.

Clarification becomes typed canonical state rather than free-form model text.

---

# 6. Main new canonical contracts

Architecture specifies the following new Goal Intelligence contracts:

- `OwnerGoalV2`
- `GoalInterpretationCandidateV1`
- `WorldEntityRefV1`
- `ResourceBindingV1`
- `InformationNeedV1`
- `CapabilityRequirementV1`
- `CapabilityRequirementGraphV1`
- `CapabilityGapV1`
- `PlanNodeV1`
- `PlanGraphV1`
- `GoalContinuationV1`
- `MonitorPredicateV1`

New package boundary:

```text
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
```

This package does not replace Voice, Work, DBOS, Hands, Phase 9, CapabilityRuntime,
EngineeringChange, Authority, secrets, model routing or memory.

---

# 7. Canonical ownership

Keep these truth boundaries:

| Truth | Canonical owner |
| --- | --- |
| exact accepted USER text | ConversationSession |
| desired owner outcome | Goal Intelligence |
| stable resource/entity identity | Goal Intelligence resource registry |
| live device/system state | existing authoritative adapters/runtime observations |
| capability availability | CapabilityRuntime / CapabilityRegistry |
| acquisition lifecycle | Phase 9 + EngineeringChange |
| execution permission | Authority / OPA |
| durable committed execution | WorkStore / DBOS |
| plan structure | Goal Intelligence PlanGraph |
| promotion | Phase 7 |
| package lifecycle | Phase 8 |
| engineering learning | Phase 10 |
| general long-lived memory | existing Memory system |

Do not duplicate canonical truth in GICC.

---

# 8. Dev-first rollout is mandatory

Owner explicitly does **not** want GICC implemented directly into production
`jarvis-voice`.

Important current repository fact:

`jarvis-dev` currently supervises a child process that runs
`python -m jarvis.voice.production_runtime`.

Therefore implementation needs explicit runtime-lane separation.

Approved design:

```text
RuntimeLane
  DEVELOPMENT
  PRODUCTION

GiccMode
  OFF
  SHADOW
  APPLY
```

Rules:

- `jarvis-dev` injects `JARVIS_RUNTIME_LANE=development`.
- direct `jarvis-voice` defaults to `production`.
- `jarvis-supervisor`/governed release runtime uses production.
- GICC APPLY is initially valid only in DEVELOPMENT.
- production remains OFF or SHADOW until owner-machine acceptance.
- production APPLY requires a separate explicit promotion/activation change.
- direct `jarvis-voice` from a feature branch must not accidentally enable GICC APPLY.

Required lifecycle:

```text
implementation branch
-> automated tests
-> GICC SHADOW through jarvis-dev
-> GICC APPLY through jarvis-dev
-> owner uses JARVIS naturally
-> fix issues
-> exact candidate SHA owner accepted
-> governed promotion
-> jarvis-voice production activation
-> production observation
-> LKG or rollback
```

---

# 9. Implementation stages

Approved sequence:

## GICC-0 - Runtime lane + contracts + persistence

Implement:

- RuntimeLane / GiccMode;
- dev supervisor lane injection;
- production APPLY fail-closed;
- canonical models;
- GoalStore;
- additive SQLite tables;
- protected payload pattern;
- replay/idempotency foundations.

No behavior switch yet.

## GICC-1 - Shadow goal interpretation

- GoalInterpreter with strict structured output;
- observe accepted owner requests;
- existing Jarvis behavior remains authoritative;
- compare shadow goal understanding against current routing;
- no acquisition/action/question changes.

## GICC-2 - World/entity resolution + typed clarification

- entity/resource registry;
- entity resolver;
- InformationResolver;
- self-resolution before owner question;
- exact `InformationNeedV1` binding;
- owner response must bind to exact active need.

Do not reproduce the current generic owner-input behavior.

## GICC-3 - Capability graph + reusable gap analysis

- derive semantic requirements;
- extend optional semantic capability metadata;
- match current capabilities;
- emit only reusable gaps;
- task-specific content must not become capability-family identity.

## GICC-4 - Phase-9 V2 bridge + continuation

- preserve existing Phase 9;
- bridge `CapabilityGapV1` to acquisition;
- include motivating goal/gap lineage;
- after verified capability availability, re-check capability truth;
- resume exact original goal only if gap is actually satisfied.

## GICC-5 - PlanGraph execution

- typed DAG;
- nodes: ACTION, OBSERVE, VERIFY, SUBGOAL, CLARIFY,
  ACQUIRE_CAPABILITY, WAIT, MONITOR;
- dispatch to existing Hands/CapabilityRuntime/Work;
- observe -> verify -> advance/replan;
- anti-loop fingerprints and replan budget.

## GICC-6 - Monitoring

- use WorkType.MONITORING;
- event-first observation;
- cheap trigger before expensive vision/model reasoning where possible;
- survive restart;
- notification idempotency.

## GICC-7 - Full jarvis-dev owner acceptance

Run realistic natural usage, not only synthetic tests.

## GICC-8 - Separate production activation

Only after owner accepts exact dev candidate SHA.

---

# 10. Mandatory owner-machine acceptance scenarios

## TV

Owner says naturally:

`Jarvis, I want to watch Transporter on my TV.`

Expected:

- understand desired outcome;
- resolve TV;
- identify reusable missing TV/media capability;
- no movie-specific capability;
- no premature movie/service/country questions during generic acquisition;
- resume original media task after capability is ready;
- ask task-specific clarification only when actually necessary;
- execute and verify playback.

## Main gate

Owner says:

`Jarvis, monitor my main gate and let me know once a delivery agent is standing at the door.`

Expected:

- resolve main gate;
- determine existing camera/perception/monitoring/notification abilities;
- acquire only missing reusable camera/resource capability;
- do not ask technical questions JARVIS can solve;
- treat "delivery agent" uncertainty truthfully;
- create durable monitor;
- notify after verified condition;
- survive restart.

## Existing Hands

Normal supported PC action.

Expected:

- no unnecessary Phase-9 acquisition;
- no unnecessary owner question;
- no major latency regression.

## Genuine ambiguity

Two valid resources fit the request.

Expected:

- exactly useful targeted clarification;
- owner answer attaches to exact InformationNeed;
- original task resumes.

## Restart

Restart jarvis-dev during:

- owner clarification;
- capability acquisition;
- monitor wait.

Expected:

- no duplicate work;
- exact goal/need resumes;
- unrelated speech does not resolve pending need.

---

# 11. Current Transporter acquisition

Existing Work ID:

`work_093a4bd977fe43f5`

This work was useful for discovering the current design weakness.

Observed useful behavior:

- ChatGPT Plan was active;
- Phase-9 research/discovery/provenance verification worked;
- resolver did not blindly trust unverified packages;
- package/SDK claims were treated conservatively.

Observed design weakness:

- immediate task became too tightly bound to acquisition;
- system asked task-specific movie/service questions too early.

Decision:

**Do not mutate this old WorkItem into GICC state.**

Keep it as historical/evidence material. Once GICC APPLY is ready in jarvis-dev, start a
clean natural owner request and test the new architecture from scratch.

---

# 12. Current known bugs to preserve

## BUG-001 - background owner-input routing

A pending Transporter background WorkItem opened a proactive owner-input session and
consumed unrelated owner speech from an HR call about email as if it belonged to the
Transporter task.

This is logged/deferred separately in PR #247.

Root architecture issue includes:

- background owner-input can temporarily own following speech;
- owner identity and task-interaction identity are different problems.

GICC InformationNeed input binding is explicitly designed not to reproduce this behavior.

Do not start a quick BUG-001 patch before GICC input binding unless owner reprioritizes.

## BUG-002 - startup greeting time mismatch

Startup time-of-day is chosen deterministically, but Gemini receives the greeting as a
cue and can paraphrase it incorrectly, e.g. saying "Good morning" during afternoon.

This bug is logged/deferred separately.

Do not mix BUG-002 remediation into GICC implementation.

---

# 13. Existing audio/video owner-confirmation status

JARVIS has the vision/audio processing stack running, including camera, speaker shadow
and LR-ASD active-speaker diagnostics, but active-speaker confirmation is intentionally
not conversation Authority yet.

Current code has active-speaker promotion disabled and diagnostics can report
`active_speaker_confirmed=False`.

Do not enable it casually as part of GICC.

Owner identity answers "who is speaking"; GICC InformationNeed binding answers
"which active task/interaction does this speech belong to". They are separate gates.

---

# 14. Existing Phase-9 pieces to preserve

Do not rewrite the following concepts:

- Phase-9 source adapters;
- candidate evidence;
- resolver;
- exact dependency/provenance verification;
- EngineeringChange architecture gate;
- isolated development;
- Phase-7 promotion;
- Phase-8 package lifecycle;
- external acceptance;
- rollback/disable.

GICC adds a better reusable-gap input and continuation layer above Phase 9.

Current resolver already checks requested operations against candidate supported
operations; this is reusable.

---

# 15. Existing Hands pieces to preserve

Hands already has useful generic behavior:

- semantic route selection;
- typed operations;
- observe/act/observe/verify loop;
- UIA/browser/visual fallbacks;
- clarification when a safe action truly lacks required information.

GICC should call Hands as a specialist for computer-control plan nodes, not reimplement it.

---

# 16. Research conclusions to remember

External research compared patterns from:

- Alexa dialog/slot collection;
- Siri/App Intents parameter resolution;
- OpenAI Agents SDK manager/tools/HITL;
- Semantic Kernel function-calling planning;
- LangGraph interrupts/resume;
- DBOS durable AI/HITL;
- MCP typed tools, annotations and elicitation;
- Home Assistant normalized devices/entities/triggers;
- BDI agent architecture;
- hierarchical planning / reactive Behavior Tree concepts.

Decision:

**Do not replace JARVIS with another agent framework.**

Reuse patterns while keeping JARVIS-native canonical Work, Authority, capability,
promotion and lifecycle systems.

Home Assistant may later be an optional capability provider, not a mandatory brain.

---

# 17. First actions in the next chat

The new chat should:

1. read the three GICC design documents from the repository;
2. confirm latest `main` and PR #248 state;
3. make sure approved documentation is on main before implementation;
4. create isolated branch:
   `feat/gicc-goal-intelligence`;
5. begin only GICC-0;
6. inspect current config/dev_supervisor/runtime composition/store/canonical helper code
   before editing;
7. implement runtime lane first;
8. add tests before enabling any GICC behavior;
9. keep production `jarvis-voice` OFF for GICC;
10. report progress before moving from GICC-0 to GICC-1.

Do not jump directly to TV integration or camera integration.

The purpose of GICC is to make those examples fall out of one generic architecture.

---

# 18. Owner-machine dev rule

When the implementation branch is ready for interactive testing, the expected style is:

~~~powershell
$env:JARVIS_DEV_BRANCH = "feat/gicc-goal-intelligence"
jarvis-dev
~~~

The exact command may evolve if GICC mode requires an additional environment/config
setting. The implementation must make the development lane explicit and must not depend
on branch-name inference.

Owner wants to actually use JARVIS conversationally in jarvis-dev before any promotion to
jarvis-voice.

---

# 19. Definition of success

GICC is successful only when JARVIS feels like one intelligent assistant that:

- understands what the owner is trying to accomplish;
- figures out what it already knows and can do;
- discovers missing information itself where possible;
- asks only useful clarification;
- detects missing reusable abilities;
- acquires them safely;
- composes abilities;
- continues the original task;
- observes real outcomes;
- replans when necessary;
- handles one-shot and monitoring goals;
- survives restart;
- remains governed by owner Authority.

The TV and gate-camera cases are acceptance scenarios, not hard-coded product features.
