# JARVIS Autonomous Self-Management Master Plan

## Status

**AUTHORITATIVE OWNER-APPROVED PRODUCT NORTH STAR — approved 2026-09-26**

This document defines the top-level operating goal for JARVIS V1. It sits above the
governed autonomous-engineering, self-repair/self-evolution, numbered product-roadmap,
and individual phase plans.

It does **not** claim that the end state is implemented today. Current production
truth remains in `CURRENT_ARCHITECTURE.md`, `CURRENT_PLAN.md`, and
`PROJECT_STATE.md`.

## 1. North-star definition

JARVIS is intended to become a **governed autonomous self-managing personal
intelligence runtime**.

> **The owner defines intent, priorities, boundaries, budgets and protected
> decisions. JARVIS continuously understands itself and its environment,
> determines what work is necessary, operates and maintains itself, repairs
> failures, optimizes performance and cost, acquires missing capabilities,
> executes long-running goals, verifies its own results, learns from outcomes,
> and progressively improves itself. JARVIS involves the owner only when a
> decision exceeds delegated authority or requires information, judgment,
> credentials, acceptance or physical action that only the owner can provide.**

The target relationship is:

```text
OWNER
  |
  | intent / priorities / boundaries / budgets / protected approvals
  v
JARVIS
  |
  +-- understands itself and its environment
  +-- maintains and operates itself
  +-- manages goals and work
  +-- detects and repairs failures
  +-- configures and optimizes itself
  +-- protects itself
  +-- acquires missing capabilities
  +-- improves and evolves through governed evidence
  |
  +--> escalates only when owner authority or uniquely human input is required
```

The owner should not need to act as JARVIS's full-time operator, project manager,
debugger or release engineer.

## 2. Permanent constitutional rule

> **JARVIS may manage JARVIS, but JARVIS must never become its own source of
> authority.**

Autonomy is the ability to decide and perform work inside accepted boundaries.
Authority is the right to define or change those boundaries.

JARVIS may eventually decide that it should investigate a failure, restart an
approved component, clean expired resources, benchmark an alternative, create an
EngineeringChange, propose a dependency upgrade, research a capability gap, or
prepare an improvement candidate.

JARVIS does not gain implicit permission to:

- grant itself broader filesystem, network, credential, device or administrator scope;
- weaken Authority, sandbox, CI, test, verification or provenance requirements;
- redefine success criteria merely to make a candidate pass;
- silently alter protected governance or protected-main rules;
- expose secrets to model context or ordinary logs;
- self-approve protected promotion merely because its own model judges a change good;
- convert model confidence into verified operational truth.

Any future delegated-authority mechanism must itself be owner-approved, explicit,
bounded, auditable, revocable and fail closed.

## 3. Operating model: desired state versus actual state

The missing top-level concept is a durable difference between:

1. **Desired state** — what JARVIS and its services are expected to achieve or
   preserve under owner-approved goals, objectives, policies, service levels,
   budgets and constraints.
2. **Actual state** — current health, capabilities, work, incidents, versions,
   resources, dependencies, performance, cost, provider availability, security
   posture and observed outcomes.

JARVIS should continuously reconcile the two.

```text
OWNER INTENT / POLICIES / OBJECTIVES
                 |
                 v
          DESIRED JARVIS STATE
                 |
              compare
                 |
                 v
           ACTUAL STATE
                 |
                 v
        AUTONOMY CONTROLLER
                 |
       no gap -> remain quiet
                 |
       gap -> decide response
                 |
        +--------+--------+---------+---------+---------+
        |        |        |         |         |         |
      operate  heal   configure  optimize  protect  extend
        |        |        |         |         |         |
        +--------+--------+---------+---------+---------+
                           |
                           v
                canonical Work / Engineering
                           |
                           v
                    independent verify
                           |
                           v
                     observe + learn
                           |
                           +----> reconcile again
```

This is a control-plane pattern, not a requirement to use Kubernetes. Kubernetes is
a useful reference because its controllers continually move actual state toward
desired state. IBM autonomic-computing work is a useful reference for the
self-configure, self-heal, self-optimize and self-protect properties. JARVIS adapts
those principles to a personal intelligence runtime with explicit human authority.

## 4. Six permanent self-management loops

### 4.1 Operate

Keep accepted services, work, schedules, resources and dependencies functioning.
Routine deterministic lifecycle work should not require an LLM when a safer
deterministic controller can do it.

Examples:

- keep required runtime components alive;
- resume durable work after restart;
- manage queues, leases, schedules and resource cleanup;
- maintain accepted local services within policy;
- surface only meaningful owner attention.

### 4.2 Self-heal

Detect failure, classify known faults, recover through accepted deterministic policy,
and escalate unknown faults into evidence-driven investigation and source-repair work.

Existing deterministic R2 repair is the first production slice of this loop.

### 4.3 Self-configure

Keep configuration, integrations, versions, capabilities and dependencies aligned
with accepted desired state.

Configuration autonomy must not become privilege autonomy. A configuration change
outside delegated scope becomes an owner-gated EngineeringChange.

### 4.4 Self-optimize

Observe measurable latency, reliability, resource use, cost, quality and other
accepted objectives. Detect meaningful degradation or improvement opportunities,
experiment in isolation, compare against the accepted baseline, and keep production
unchanged unless evidence and governance support promotion.

"Tests pass" is not evidence that an optimization is better.

### 4.5 Self-protect

Continuously preserve accepted security, privacy, provenance, dependency integrity,
credential handling, least privilege and protected-governance boundaries.

Security controls are not merely blockers around autonomy; they are part of the
autonomous operating goal.

### 4.6 Self-extend and evolve

Recognize missing capabilities or repeated weaknesses, research options, architect,
build in isolation, verify, benchmark, prepare promotion, observe production results
and retain verified engineering knowledge.

Direct owner-requested capability acquisition comes before autonomous capability-gap
creation. Later autonomous gap detection creates a proposal or EngineeringChange;
it does not silently expand authority.

## 5. Autonomy Control Plane

The Autonomy Control Plane is the future top-level coordinator above individual
WorkItems and EngineeringChanges. It must **reuse** accepted JARVIS primitives rather
than become a second uncontrolled agent stack.

### 5.1 Canonical future objects

The exact schemas require phase-specific research and owner approval, but the
top-level semantics are fixed:

- **Objective** — durable owner or system goal, priority, success measures, horizon
  and constraints.
- **DesiredState** — measurable or checkable target condition derived only from
  accepted owner intent/policy and registered system contracts.
- **SystemState** — bounded aggregate view derived from Self Model, Health Registry,
  capability state, work state, incidents, resources, model/provider state,
  performance/cost telemetry and accepted observations.
- **AutonomyFinding** — evidence-backed difference, weakness, opportunity or required
  maintenance action discovered by reconciliation.
- **ActionCandidate** — typed proposed response with expected benefit, risk,
  reversibility, cost, dependencies and required authority.
- **AuthorityEnvelope** — owner-defined delegated scope for classes of actions.
  This is a future governance capability; it is not implied by this document.
- **OwnerAttentionItem** — a durable escalation that explains what JARVIS needs,
  why it cannot proceed autonomously, available options and consequence of waiting.
- **OutcomeRecord** — evidence describing attempted action, verification result,
  operational observation and learning/provenance links.

These objects must not duplicate canonical WorkItem, EngineeringChange,
EngineeringKnowledge, Authority, CapabilityManifest or Self Model truth.

### 5.2 Decision hierarchy

The controller should prefer the least-powerful reliable mechanism:

```text
deterministic policy
-> deterministic workflow/controller
-> bounded existing capability
-> durable WorkItem
-> EngineeringChange / research / agentic reasoning
-> owner escalation
```

AI reasoning is used for ambiguity, research, diagnosis, planning and novel work.
Predictable maintenance stays deterministic.

### 5.3 Work creation

The major behavioral change is that mature JARVIS may create work because the system
state requires it, not only because the owner explicitly issued a task.

Examples:

- repeated provider failures create a reliability investigation;
- rising voice latency creates a performance diagnosis;
- a vulnerable dependency creates a remediation candidate;
- repeated owner manual intervention creates a capability-gap proposal;
- growing expired sandbox usage triggers deterministic cleanup;
- a production regression creates rollback/investigation work.

Every autonomous work item must have a traceable trigger, evidence, policy basis,
priority and authority classification.

## 6. Goal and portfolio management

Projects are subordinate to JARVIS autonomy; they are not the top-level product
identity.

JARVIS should eventually maintain a durable portfolio of:

- owner objectives;
- operational obligations;
- incidents;
- engineering changes;
- capability work;
- maintenance work;
- scheduled/recurring work;
- improvement candidates;
- blocked/waiting work.

It should prioritize with explicit rules considering owner priority, urgency,
dependency, impact, risk, resource contention, cost and deadlines.

Examples of correct priority behavior:

- production voice failure outranks a cosmetic improvement;
- a security remediation may outrank feature research;
- owner conversation always preempts background model reasoning;
- a blocked low-priority experiment should not starve urgent repair work.

## 7. Owner attention should become scarce and meaningful

The end state is not "ask permission for every tiny step."

The target is to concentrate owner involvement around genuine boundaries:

- new or changed architecture when policy requires it;
- authority/permission expansion;
- secret or pairing input that JARVIS cannot obtain;
- financial/spending decisions outside a delegated budget;
- irreversible or high-impact external actions;
- physical-world acceptance that software cannot independently verify;
- protected governance changes;
- protected promotion/merge unless a separately approved future policy delegates
  some bounded class.

Future authority envelopes may reduce repetitive prompts for low-risk reversible
operations, but only through a separate owner-approved governance phase.

## 8. Relationship to current JARVIS foundations

The current work is not discarded. It is the substrate of this north star.

| Existing foundation | North-star role |
| --- | --- |
| Self Model / Self Awareness / Health Registry | actual-state understanding |
| Authority / OPA / approvals / audit | constitutional boundary |
| WorkItem / DBOS | durable execution |
| BrainCoordinator | bounded reasoning coordination |
| EngineeringChange | governed multi-stage change lifecycle |
| EngineeringKnowledge | verified engineering learning |
| deterministic Self-Repair | first self-healing controller |
| Model Router | reasoning-resource selection |
| Phase-5 engineering substrate | secure dependencies, secrets, sandbox/provenance |
| Capability runtime / Hands | governed effectors |
| memory/context | owner/project/context continuity |

The missing future layer is primarily the DesiredState/Objectives model,
system-level reconciliation, autonomous finding/work creation, portfolio
prioritization and eventually delegated authority envelopes.

## 9. Approved implementation sequence

This north-star clarification **does not interrupt or rewrite Phase 5**.

Approved sequencing:

```text
CURRENT
  Phase 5   Secure Autonomous Engineering Substrate — continue

THEN
  Phase 6   Unknown-Incident Investigation + Source Repair
  Phase 7   Governed Promotion / Production Verification / Rollback
  Phase 8   Capability Package + Registry Lifecycle
  Phase 9   Owner-Requested Capability Acquisition
  Phase 10  Closed-Loop Engineering Learning

INSERT
  Phase 10A Autonomous Operations Control Plane
            - Objective / DesiredState contracts
            - SystemState aggregation
            - reconciliation loop
            - AutonomyFinding + ActionCandidate
            - autonomous work creation
            - goal/portfolio prioritization
            - owner-attention queue
            - autonomy budgets / anti-thrash controls
            - evaluation and shadow mode before live authority

THEN CONTINUE
  Phase 11  Autonomous Capability-Gap / Weakness Detection
  Phase 12  Shadow Improvement + Baseline Benchmarking
  Phase 13  Engineering Curriculum + Specialist Model Evaluation
  Phase 14  Governed Self-Evolution
```

Phase 10A is deliberately placed after JARVIS can repair, promote, package, acquire
and learn through the governed engineering lifecycle. The top-level controller
should not receive broad responsibility before its effectors and verification
substrate are mature.

Phase 10A is a planning commitment, not permission to implement it during active
Phase 5.

## 10. Autonomy evaluation

Autonomy must be measured by outcomes, not feature count or model confidence.

The future evaluation suite should track at least:

- owner interventions per completed goal;
- autonomous goal/task completion rate;
- longest reliable end-to-end task/goal horizon;
- mean time to detect meaningful degradation;
- mean time to recover from accepted failure classes;
- false-positive autonomous intervention rate;
- unnecessary owner-attention rate;
- rollback success and recovery rate;
- post-change regression rate;
- cost/resource use per completed goal;
- percentage of recurring manual operations eliminated;
- percentage of autonomous changes with complete provenance and independent evidence;
- uninterrupted operating duration without human maintenance.

Metrics must be segmented by task/risk class. A high success rate on trivial work
must not be presented as evidence of reliable high-impact autonomy.

## 11. Anti-goals

The north star explicitly rejects:

- one unrestricted super-agent with arbitrary shell/network/credential access;
- multiple independent "brains" with competing task, authority or memory truth;
- self-modification directly in production;
- autonomous lowering of safeguards;
- hidden goals not traceable to owner policy or registered system obligations;
- endless self-improvement loops without measurable utility;
- model-generated success claims without independent evidence;
- constant unsolicited activity merely to appear proactive;
- replacing deterministic reliable automation with LLM calls unnecessarily;
- architecture rewrites caused only by framework fashion.

## 12. Technology strategy

JARVIS owns the control plane. External frameworks may provide replaceable workers,
adapters or implementation patterns.

Current disposition:

- DBOS durable execution — **KEEP**;
- JARVIS WorkItem / EngineeringChange / EngineeringKnowledge — **KEEP AND EXPAND**;
- Self Model / Health Registry — **KEEP AND EXPAND**;
- Authority / OPA / audit / verification boundaries — **KEEP**;
- isolated worktrees / sandboxes — **KEEP**;
- Kubernetes desired-state reconciliation pattern — **ADAPT, do not adopt Kubernetes
  as the JARVIS control plane**;
- IBM autonomic self-configure/heal/optimize/protect pattern — **ADAPT**;
- external agent frameworks — **evaluate as replaceable workers/pattern sources,
  never as canonical JARVIS authority**;
- SLSA provenance concepts — **KEEP/EXPAND**;
- TUF-style secure-update concepts — **evaluate for future promotion/update
  hardening**.

No external framework is permitted to become the canonical source of JARVIS
identity, goals, Authority, memory, capability truth, work truth or promotion truth.

## 13. Research basis

This architecture adapts established ideas rather than inventing autonomy as
"give an LLM more permissions":

- IBM autonomic-computing architecture: systems manage themselves according to
  high-level human objectives and pursue self-configuration, self-optimization,
  self-healing and self-protection.
  https://research.ibm.com/publications/an-architectural-approach-to-autonomic-computing
- Kubernetes controller pattern: a control loop observes current state and acts to
  move it toward desired state.
  https://kubernetes.io/docs/concepts/architecture/controller/
- NIST SP 800-218 SSDF: secure-development practices should be integrated into the
  lifecycle and should address root causes, not merely symptoms.
  https://csrc.nist.gov/pubs/sp/800/218/final
- SLSA v1.2 provenance: verifiable information should track where, when and how
  artifacts were produced.
  https://slsa.dev/spec/v1.2/provenance
- The Update Framework: secure update systems should defend against arbitrary,
  rollback, freeze and key-compromise attacks.
  https://theupdateframework.io/docs/security/
- DBOS durable workflows: interrupted workflows can recover from persisted execution
  state rather than restarting the entire logical job from scratch.
  https://docs.dbos.dev/production/workflow-recovery

These references guide principles. They are not claims that current JARVIS
implements every control in those systems.

## 14. Documentation authority

Canonical hierarchy after owner approval:

1. `PRODUCT.md` — durable product identity, behavioral contract and capability catalogue.
2. `AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md` — top-level operating north star.
3. `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md` — autonomous-engineering subsystem.
4. `SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md` — specialized repair/evolution program.
5. `ROADMAP.md` — numbered product sequence and approved cross-cutting sequencing.
6. `CURRENT_PLAN.md` — active work only.
7. `CURRENT_ARCHITECTURE.md` — accepted running architecture only.
8. `PROJECT_STATE.md` — accepted/deferred/superseded/rejected ledger.
9. phase-specific research/architecture/implementation/acceptance documents.

Rules:

- future north-star behavior must never be represented as current production truth;
- Phase 5 continues unchanged unless new evidence requires an owner-approved change;
- future agents must not reinterpret "autonomy" as unrestricted self-authorization;
- future feature/project work must be evaluated against the whole-JARVIS
  self-management north star, not only local task completion;
- do not create competing north-star documents; amend this one and PRODUCT.md if the
  owner changes the top-level goal.

## 15. North-star acceptance test

The system approaches the intended end state only if the answer increasingly becomes
"yes" to this question:

> **Can JARVIS understand its current situation, know the owner-approved state it is
> trying to maintain or achieve, decide what work should exist, safely execute or
> delegate that work, independently verify the result, learn from the outcome, and
> continue operating without the owner continuously orchestrating it — while never
> taking ownership authority away from the owner?**
