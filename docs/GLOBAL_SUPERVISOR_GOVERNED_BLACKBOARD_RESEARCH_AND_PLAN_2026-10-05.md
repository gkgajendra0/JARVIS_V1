# JARVIS Global Supervisor / Governed Blackboard Architecture

**Status:** S1-S12 implemented and system-hardened; S13 live owner-machine acceptance pending  
**Date:** 2026-10-05  
**Branch:** `feat/development-engine-control-plane`  
**Baseline before this documentation change:** `d88906e209e40ea09827b12413d987f7d0052a51`  
**PR:** #252 — draft / unmerged

## Implementation status

The governed Blackboard / Global Supervisor implementation is now integrated through
controlled cutover and protected by cross-lifecycle invariants, replay coverage,
manager-only owner communication, canonical retry semantics, exact-generation
activation/external-acceptance lineage, and same-goal continuation fencing.

S13 remains intentionally open until the preserved D8 owner-machine lineage completes a
real external acceptance and the original goal resumes. The live acceptance must use the
existing goal/gap/EngineeringChange; it is not valid to prove S13 by creating a fresh TV
objective.

## 1. Decision

Do **not** replace JARVIS with a generic multi-agent framework and do **not** continue
patching the Phase-9/D8 TV path one isolated failure at a time.

Upgrade the supervisor/control-plane architecture JARVIS already has.

Target operating model:

```text
                           OWNER
                             |
                             v
                     JARVIS SUPERVISOR
                  one conversational voice
                             |
             +---------------+---------------+
             |                               |
        TASK LEDGER                    PROGRESS LEDGER
             |                               |
             +---------------+---------------+
                             |
                    GOVERNED BLACKBOARD
                 one shared system reality
                             |
       +---------------------+---------------------+
       |                     |                     |
       v                     v                     v
   Research              Architecture          Development
 specialist              specialist          DevelopmentEngine
       |                     |                     |
       +---------------------+---------------------+
                             |
                             v
                         Verification
                             |
                             v
                    Supervisor evaluates
                             |
                             v
                 deterministic JARVIS control
         GICC / Work / EngineeringChange / DBOS /
           Authority / Gates / Registry / Promotion
```

The specialists are internal contributors. **JARVIS is the manager, orchestrator,
memory of the whole objective, and only owner-facing conversational interface.**

## 2. Why this change is needed

The recent TV capability run exposed a recurring pattern:

```text
problem
-> diagnose one subsystem
-> patch it
-> test it
-> restart
-> discover another cross-system inconsistency
```

Many individual fixes were correct, but the system was repeatedly reasoning too locally.
The missing capability is not simply "more agents". It is a continuously active
system-level supervisor that understands the full owner objective and the relationship
between every specialist's result.

Two owner requirements are now architectural requirements:

1. JARVIS must not become so focused on the immediate Research/Development failure that
   it loses sight of the complete system objective.
2. Research, Architecture, Development, Verification and other specialists must behave
   like contributors to **one JARVIS system with shared current truth**, not disconnected
   components with separate realities.

## 3. Existing architecture should be reused

JARVIS already contains most of the correct foundations:

- GICC / Goal Intelligence owns owner-level objectives;
- `GoalOrchestrator` already routes validated work to specialist subsystems;
- WorkEngine / WorkOrchestrator provide durable WorkItem, WorkStep and WorkDelivery truth;
- DBOS provides durable execution and restart recovery;
- EngineeringChange provides governed lifecycle, versioned artifacts and gates;
- capability acquisition provides research, candidate evaluation and architecture handoff;
- DevelopmentEngine / Codex is already a bounded development specialist;
- Authority / OPA / Windows Hello remain execution and approval boundaries;
- verification, promotion, capability registry and external acceptance already exist;
- GICC already contains plan revision, continuation, no-progress and supersession concepts.

Therefore this is an **upgrade of the existing supervisor**, not a second orchestration
stack.

## 4. Research findings

### 4.1 Centralized supervision is safer than free agent-to-agent orchestration

Current production guidance and research consistently favor deterministic workflow
control for sequential, stateful work.

OpenAI's Agents SDK guidance explicitly distinguishes LLM-driven orchestration from
code-driven orchestration and notes that code orchestration is more deterministic and
predictable in speed, cost and performance.

Reference:
https://openai.github.io/openai-agents-python/multi_agent/

Google Research evaluated 180 agent configurations and reported that multi-agent systems
can improve parallelizable tasks while performing substantially worse on sequential
planning tasks; centralized orchestration also contained error propagation better than
independent agents.

Reference:
https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/

This matters because JARVIS capability acquisition is largely sequential:

```text
goal
-> research
-> architecture
-> approval
-> development
-> verification
-> promotion
-> activation
-> external acceptance
-> resume original goal
```

Conclusion: do not build a free-running swarm.

### 4.2 Magentic-One validates the Supervisor + Ledger concept

Microsoft Magentic-One is a strong architectural precedent for the owner's intended
model. Its Orchestrator maintains a Task Ledger and Progress Ledger, assigns specialists,
monitors progress and replans when progress stalls.

Reference:
https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/

Use this as an architectural pattern only. Do **not** migrate JARVIS to Magentic-One or
Microsoft Agent Framework as canonical runtime.

### 4.3 Anthropic validates orchestrator/worker separation and artifact handoffs

Anthropic's production multi-agent research architecture uses a lead orchestrator with
bounded subagents. Their engineering guidance emphasizes clear delegation, persistent
artifacts and careful context management rather than passing every detail through every
agent.

Reference:
https://www.anthropic.com/engineering/multi-agent-research-system

Anthropic's context-engineering guidance also reinforces that more context is not always
better; irrelevant context can degrade behavior even when the context window is large.

Reference:
https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

Conclusion: specialists should share one system reality, but receive role-specific
projections rather than the entire history.

### 4.4 Shared memory must be governed

A naive global mutable memory would create new failure classes:

- stale facts propagating as current truth;
- contradictory records;
- one specialist's wrong assumption poisoning everyone else;
- provenance loss;
- uncontrolled scope leakage.

Therefore the target is a **governed Blackboard / Objective Workspace**, not one large
mutable memory object.

Every important fact should preserve:

- source/provenance;
- evidence references;
- scope;
- generation/revision;
- validity;
- current/historical status;
- supersession relationship.

### 4.5 External frameworks do not remove orchestration bugs

Recent real-world issue reports in agent frameworks include:

- lost context during handoffs;
- repeated or duplicated history;
- looping managers;
- shared-state races;
- repeated side effects after retries;
- malformed ledger/manager outputs;
- worker delegation problems.

This is a reason to keep JARVIS-owned DBOS, GICC, Work, EngineeringChange and Authority
as canonical truth rather than replacing them with a generic orchestration framework.

## 5. Critical UX rule: only JARVIS speaks to the owner

All owner-facing communication must flow through the Supervisor.

Forbidden conceptual flow:

```text
Researcher -> Owner
Developer  -> Owner
Verifier   -> Owner
```

Required flow:

```text
Specialist
    |
    v
Supervisor
    |
    v
natural owner-level explanation
    |
    v
Owner
```

Specialists return typed machine reports. They do not generate owner-facing progress or
failure messages directly.

The Supervisor decides:

- whether the owner needs to know;
- whether owner action is required;
- how much technical detail is useful;
- how to explain the situation naturally;
- whether an internal problem should remain silent and retry automatically.

Example internal event:

```text
Development:
NEEDS_RESEARCH
question = "Confirm VIDAA pairing/certificate behaviour."
```

Normal owner-facing wording:

```text
I'm still working on the TV capability. The implementation needs one technical detail
confirmed before I can safely continue, so I'm checking that now. You don't need to do
anything.
```

If the owner asks "why?", the Supervisor should explain the real reason naturally from
shared state.

### Owner-facing invariants

- one personality;
- one conversation;
- one understanding of the objective;
- technical IDs/errors hidden by default;
- internal specialist failure must not sound like entire JARVIS failure;
- JARVIS can answer:
  - what are you doing?
  - why?
  - what failed?
  - is it serious?
  - what happens next?
  - do I need to do anything?

## 6. Governed Blackboard / Objective Workspace

The Blackboard is not a new competing source of truth.

It should be a materialized projection over canonical JARVIS state plus narrowly typed
Supervisor events.

Primary existing inputs:

- OwnerGoalV2;
- PlanGraphV1;
- plan-node results;
- goal continuations;
- capability gaps;
- EngineeringChange;
- EngineeringChange events;
- versioned artifacts;
- gates/decisions;
- WorkItems;
- WorkSteps;
- DevelopmentResultV1;
- capability registry/lifecycle;
- verification;
- external acceptance.

Candidate projection:

```text
ObjectiveWorkspaceV1
  objective
  success_criteria
  canonical_targets
  accepted_facts
  assumptions
  rejected_facts
  current_strategy
  current_architecture
  active_assignments
  current_attempts
  historical_attempts
  supersession_relations
  blockers
  open_questions
  specialist_outputs
  approvals
  verification_state
  progress_state
  next_legal_actions
```

The Blackboard should preserve history while making "what is authoritative now" explicit.

Example:

```text
claim:
  samsungtvws supports television control

source:
  research attempt 2

target_compatibility:
  rejected

reason:
  Samsung-specific; owner target is Hisense/VIDAA

status:
  historical
```

The record remains visible but can never silently become current truth.

## 7. Task Ledger

The Task Ledger is the stable mission view.

It should answer:

- What did the owner actually ask for?
- What outcome counts as success?
- What exact entity/device/resource is involved?
- What constraints and authority boundaries exist?
- What strategy is currently accepted?
- What important facts are accepted?
- What assumptions remain?
- What alternatives were rejected and why?

For the current TV case the ledger should retain, among other facts:

```text
objective:
  acquire/use TV control and ultimately execute the owner's requested playback outcome

target:
  Hisense U7N / VIDAA

success:
  real governed TV operation and verified owner outcome

constraints:
  no unsafe bypasses
  architecture/promotion approvals remain artifact-bound
```

## 8. Progress Ledger

The Progress Ledger is the current operational picture.

It should answer:

- Which phase are we in?
- Which specialist currently owns the next bounded assignment?
- What did that specialist last produce?
- Are we making progress?
- What is the active blocker?
- Is the blocker temporary, superseded, owner-only or terminal?
- Is another specialist needed?
- Is the current plan still valid?
- What is the next legal system action?

Example:

```text
phase:
  development

active_specialist:
  DevelopmentEngine

current_assignment:
  implement approved VIDAA architecture

latest_progress:
  dependency evidence requested

blocker:
  pairing behaviour insufficiently evidenced

owner_action_required:
  false

supervisor_decision:
  ask Research the exact bounded question

next_action:
  resume Development when accepted evidence is available
```

## 9. Specialist model

Start with specialists JARVIS effectively already has.

### Research specialist

Responsible for:

- current-source research;
- bounded technical questions;
- candidate discovery;
- evidence and provenance.

Returns typed research findings.

### Architecture specialist

Responsible for:

- synthesizing accepted evidence;
- proposing an architecture;
- dependencies;
- assumptions;
- verification plan;
- risks.

It cannot approve its own proposal.

### Development specialist

Use existing DevelopmentEngine / Codex.

Responsible for:

- implementing the exact approved architecture;
- bounded repository inspection/editing;
- governed dependency requests;
- tests;
- candidate commit;
- typed blocker/completion outcome.

### Verification specialist

Responsible for:

- independent verification against approved architecture and success conditions.

Deterministic tests and policy remain authoritative.

## 10. Specialist communication rule

Do not allow hidden free-form specialist-to-specialist conversations.

Required pattern:

```text
Developer
   |
   | structured information request
   v
Supervisor
   |
   | bounded assignment
   v
Research
   |
   | structured finding
   v
Supervisor
   |
   | accept/reject + Blackboard update
   v
Developer resumes
```

This keeps JARVIS aware of every meaningful handoff.

## 11. Current concrete architecture gaps

### 11.1 Stage attempts lack first-class supersession authority

GICC already models superseded plan states, but EngineeringChange stage attempts do not
fully express current/superseded authority.

The recent TV sequence was approximately:

```text
research attempt 1 -> completed
research attempt 2 -> failed
research attempt 3 -> completed replacement
```

Attempt 3 semantically replaced attempt 2.

However Development currently builds dependencies from every source-stage WorkItem in
the EngineeringChange. WorkEngine then fails a WorkItem if any dependency is FAILED or
CANCELLED.

Result: historical failed attempt 2 poisoned the new development attempt even though
attempt 3 had replaced it and produced the new approved architecture.

Required semantics:

```text
attempt 2:
  FAILED
  HISTORICAL
  SUPERSEDED_BY = attempt 3

attempt 3:
  CURRENT
  ACCEPTED
```

History remains immutable; only authority changes.

### 11.2 Dependency ownership is too historical

Development should depend on the **current approved architecture/source generation**, not
every research WorkItem ever created for the change.

The existing architecture artifact is already:

- versioned;
- digest-bound;
- provenance-bound;
- bound to the selected candidate/plan;
- owner-approved before Development admission.

The DevelopmentTicketBuilder already consumes the exact architecture artifact.

Therefore raw historical source WorkItems should not continue acting as active
dependencies after replacement.

### 11.3 Failure propagation is too mechanical

A WorkStep failure, WorkItem failure, EngineeringChange failure and owner-goal failure are
not semantically equivalent.

Introduce system-level typed outcomes such as:

```text
TEMPORARY_RESOURCE
RETRYABLE
EVIDENCE_INSUFFICIENT
NEEDS_RESEARCH
NEEDS_ARCHITECTURE_REVISION
NEEDS_DEPENDENCY
NEEDS_OWNER
SUPERSEDED
TERMINAL
```

Only a genuinely terminal system decision should normally terminate the governing owner
objective.

Example:

```text
provider overloaded
!= capability failed
!= owner goal failed
```

### 11.4 Recovery logic has become too incident-specific

Compatibility recovery functions are valid migrations for already-persisted bad states,
but future normal behavior should be driven by generic failure/supersession semantics
rather than accumulating one recovery function per discovered edge case.

### 11.5 Target compatibility needs a deterministic boundary

Research is allowed to discover irrelevant candidates.

Selection is not allowed to treat them as valid for the current target.

Add a generic target-compatibility contract between a candidate and the canonical target
entity/platform.

For the current objective:

```text
Samsung-only SDK
vs
Hisense / VIDAA target
=> TARGET_INCOMPATIBLE
=> NOT_SELECTABLE
```

### 11.6 Testing is too component-focused

The repository contains strong subsystem tests, but cross-lifecycle combinations have
still escaped.

The next test layer must replay complete system stories.

## 12. Implementation sequence

### S0 — Freeze current D8 state

Do not create a new TV goal or another parallel EngineeringChange.

Preserve the current messy history as test evidence.

Do not merge PR #252 without explicit owner instruction.

### S1 — Build system scenario replay/fault harness first

Before changing Supervisor behavior, encode the failures already observed.

Minimum scenarios:

1. provider overload during Research;
2. provider overload during DevelopmentEngine;
3. malformed model structured output;
4. DevelopmentEngine response-contract repair;
5. temporary resource waiting;
6. failed research replaced by successful research;
7. superseded WorkItem cannot poison current dependency;
8. incompatible Samsung candidate against Hisense/VIDAA target;
9. PyPI project URL passed where distribution name is required;
10. architecture revision;
11. changed architecture requires a new exact approval;
12. restart during Research;
13. restart during Development;
14. restart after approval;
15. duplicate/replayed durable execution;
16. Developer requests a bounded Research answer;
17. Research returns accepted evidence and Development resumes;
18. Verification rejects candidate;
19. genuine owner input required;
20. full existing TV goal from acquisition through external result.

The replay harness is the acceptance gate for every following supervisor change.

### S2 — ObjectiveWorkspaceV1 projection

Build the governed Blackboard projection over existing canonical stores.

Do not create a competing mutable truth database.

### S3 — attempt/supersession semantics

Make current vs historical authority explicit for EngineeringChange stages and their
produced artifacts.

### S4 — authoritative dependency semantics

Bind downstream work to current accepted artifacts/generations rather than all historical
WorkItems.

### S5 — typed system failure semantics

Normalize child outcomes into system-meaningful classes and prevent automatic upward
terminal propagation.

### S6 — target compatibility

Add deterministic candidate-target compatibility before candidate selection.

### S7 — Task Ledger + Progress Ledger

Derive stable mission state and current operational state from ObjectiveWorkspace.

### S8 — Global Supervisor

Add bounded system-level reasoning over:

- Task Ledger;
- Progress Ledger;
- relevant Blackboard projection;
- allowed Supervisor actions.

Candidate typed actions:

```text
CONTINUE
WAIT_RESOURCE
RETRY
REQUEST_RESEARCH
REQUEST_ARCHITECTURE
RESUME_DEVELOPMENT
VERIFY_ASSUMPTION
SUPERSEDE_ATTEMPT
REPLAN
ASK_OWNER
TERMINAL
```

The Supervisor proposes. Deterministic JARVIS code validates and performs the transition.

### S9 — role-specific context projections

Create bounded views such as:

- ResearchContextV1;
- ArchitectureContextV1;
- DevelopmentContextV1;
- VerificationContextV1.

All views derive from the same ObjectiveWorkspace.

### S10 — Manager-only conversation

Route all progress, questions, blockers, approvals and explanations through the
Supervisor.

Specialists produce machine contracts only.

### S11 — shadow mode

Run Supervisor reasoning against replayed and live state without granting mutation
authority.

Compare proposed actions against expected system actions.

Inject:

- provider outages;
- malformed responses;
- stale artifacts;
- duplicate events;
- process crashes;
- irrelevant candidates;
- specialist loops;
- failed dependencies.

### S12 — controlled cutover

Allow the Supervisor to coordinate Research, Architecture, DevelopmentEngine and
Verification while deterministic state/control remains authoritative.

### S13 — resume the same D8 TV objective

Do not create a new TV goal.

Use the existing lineage as the first real acceptance case.

Expected conceptual flow:

```text
Supervisor
-> reconstruct current TV ObjectiveWorkspace
-> recognize historical/superseded attempts
-> identify current approved architecture
-> create/resume valid Development assignment
-> coordinate bounded Research questions as required
-> Development completion
-> Verification
-> owner acceptance
-> promotion
-> activation
-> real Hisense/VIDAA acceptance
-> resume motivating GICC goal
-> execute requested playback outcome
-> verify result
```

## 13. Acceptance invariants

### Goal safety

- specialist failure does not automatically equal owner-goal failure;
- superseded work cannot block current work;
- original owner objective remains stable across replanning.

### State consistency

- exactly one authoritative current attempt/generation where required;
- current architecture is explicit;
- active dependencies bind to current authority;
- historical state remains auditable.

### Security

- Supervisor cannot bypass gates;
- specialists cannot self-authorize;
- OPA/Authority remain final policy owners;
- Windows Hello remains required where current policy requires it.

### Context

- all specialists derive from one ObjectiveWorkspace;
- role projections cannot silently contradict current Blackboard truth;
- superseded/stale facts are explicit.

### UX

- only JARVIS Supervisor communicates with owner;
- internal technical IDs/errors hidden by default;
- Supervisor can explain current status and reasons naturally;
- owner is interrupted only when owner action is genuinely required.

### Durability

- restart reconstructs the same canonical state;
- no duplicate side effects;
- no duplicate goals;
- no duplicate EngineeringChanges.

## 14. Framework decision

Keep:

- GICC;
- GoalOrchestrator;
- WorkEngine / WorkOrchestrator;
- DBOS;
- EngineeringChange;
- DevelopmentEngine / Codex;
- capability acquisition;
- Authority / OPA / Windows Hello;
- capability registry;
- verification;
- promotion;
- existing model routing.

Borrow patterns from:

- Microsoft Magentic-One: Supervisor, Task Ledger, Progress Ledger, stall detection;
- Anthropic: bounded orchestrator/worker assignments, artifact handoffs, context
  engineering;
- governed shared-memory research: provenance, scope and supersession;
- event-sourced systems: append history, derive current state.

Do not add at this stage:

- CrewAI;
- LangGraph as canonical runtime;
- Microsoft Agent Framework as canonical runtime;
- Magentic-One runtime;
- Google ADK as canonical runtime;
- Pydantic AI as a new orchestration dependency.

These may remain future specialist-runtime options if later evaluation proves a specific
benefit.

## 15. Existing TV lineage must be preserved

Do not create a new TV objective.

Known canonical lineage includes:

```text
GICC owner goal:
  goal_a42ef045757a59bf3b3f

capability family:
  media_player.control

capability gap:
  capability_gap_e1e27710f5381984a0f8

EngineeringChange:
  change_8b21e503c5c04a3e

original architecture:
  artifact_6131ca86672f4fe2

original architecture approval gate:
  gate_3343fc849a0644a0
```

Historical WorkItems include:

```text
work_e86849d954194bd1
work_8b7df65cf55e4363
work_70d026fbb52d49af
work_a367c67637084ffa
work_d87bfb2033274577
```

The current owner-machine DB must be re-read before relying on any latest-attempt ID
created after those records.

## 16. Engineering rule going forward

Continue using:

```text
symptom
-> invariant
-> whole architecture
-> canonical state
-> external research / existing technology
-> fix owning abstraction
-> regression
-> owner-machine proof
```

Add two permanent rules:

> Before fixing a local failure, determine what that failure means to the complete owner
> objective.

> A specialist result is evidence. The Supervisor plus deterministic policy determines
> system meaning.

## 17. Next-chat starting point

Do not immediately modify Supervisor behavior.

Start with **S1 — System Scenario Replay / Fault Harness**.

Before implementation:

1. verify current branch/head;
2. re-read current TV canonical state if owner-machine evidence is supplied;
3. inspect GICC / GoalOrchestrator / WorkEngine / EngineeringChange against this document;
4. encode system replay scenarios;
5. keep the existing D8 TV objective frozen;
6. do not create a new TV goal;
7. do not merge PR #252.

The replay suite must become the safety net before S2–S12 are implemented.
