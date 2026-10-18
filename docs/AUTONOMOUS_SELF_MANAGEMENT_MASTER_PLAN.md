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

**Owner clarification (2026-10-18):** The foremost *user-facing reason* to
build JARVIS is a deeply personalized, continuously context-aware companion and
assistant—not another generic chatbot, not merely a project manager, and not a
self-repair framework. Whole-system autonomy, engineering capability, universal
knowledge, and discovery are enabling powers in service of this relationship.
The detailed non-diversion requirements and acceptance tests are in Section 17.

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

Provider/model lifecycle maintenance is a permanent self-configuration obligation.
JARVIS should detect first-party deprecation, retirement, model-unavailable and
compatibility evidence; prefer a provider-recommended replacement over a guessed or
moving `latest` alias; validate the replacement against the required product surface;
migrate configuration automatically inside a bounded pre-authorized envelope; observe
the result; and roll back or escalate to governed engineering when validation fails.
Routine provider churn must not require the owner to discover the retirement manually.
The detailed contract is `PROVIDER_MODEL_LIFECYCLE_SELF_EVOLUTION.md`.

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
- provider model legacy/deprecation/retirement creates lifecycle reconciliation and,
  when a provider-recommended compatible replacement exists, bounded automatic
  configuration migration;
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

This north-star clarification does not rewrite accepted phase contracts.

Approved sequencing and current status:

```text
ACCEPTED
  Phase 5   Secure Autonomous Engineering Substrate
  Phase 6   Unknown-Incident Investigation + Source Repair
  Phase 7   Governed Promotion / Production Verification / Rollback
  Phase 8   Capability Package + Registry Lifecycle — owner-machine accepted 2026-09-27
  Phase 10  Closed-Loop Engineering Learning — owner-machine accepted 2026-09-28

ACCEPTED / DEFERRED VALIDATION
  Phase 9   Owner-Requested Capability Acquisition — DONE (BOUNDED) / OWNER ACCEPTED 2026-09-28
            - final end-to-end external lifecycle validation deferred to whole-system acceptance

CURRENT / NEXT
  Phase 10A Autonomous Operations Control Plane — research + architecture required
            - implementation requires explicit owner approval

INSERTED SEQUENCE
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

Phase 10A has now reached its approved sequencing point because Phase 10 is accepted. This authorizes repository inspection, research and architecture work only; implementation still requires explicit owner approval under the permanent engineering sequence.

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

## 14. Advanced intelligence extension: Universal Knowledge and Discovery

The owner approved an additional long-horizon intelligence goal on 2026-09-27:
JARVIS should eventually be able to draw on as much accessible human knowledge as
possible across domains and, beyond answering known questions, systematically investigate
the boundary between known and unknown.

This extension has two parts:

1. **Universal Knowledge Intelligence** — a shared, model-independent Knowledge Fabric
   that can retrieve, verify, structure, connect, retain, refresh and reason over
   source-backed human knowledge and JARVIS's own verified experience.
2. **Discovery Intelligence** — a governed research system that uses that Knowledge
   Fabric to identify gaps/anomalies/contradictions, generate competing hypotheses,
   aggressively falsify them, check prior art, run reproducible computational and
   eventually physical experiments, and learn from results.

This is **not** permission to claim omniscience, treat model output as fact, download the
internet into one datastore, or begin speculative discovery work before the truth,
provenance, sandbox, learning and self-evolution foundations are mature.

The authoritative detailed plan is
`UNIVERSAL_KNOWLEDGE_AND_DISCOVERY_MASTER_PLAN.md`.

This advanced intelligence extension is subordinate to the constitutional self-management
north star in this document. It does not grant JARVIS any additional authority and does not
interrupt or renumber the active governed autonomous-engineering program.

## 15. Documentation authority

Canonical hierarchy after owner approval:

1. `PRODUCT.md` — durable product identity, behavioral contract and capability catalogue.
2. `AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md` — top-level operating north star.
3. `UNIVERSAL_KNOWLEDGE_AND_DISCOVERY_MASTER_PLAN.md` — subordinate advanced knowledge/discovery north star.
4. `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md` — autonomous-engineering subsystem.
5. `SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md` — specialized repair/evolution program.
6. `ROADMAP.md` — numbered product sequence and approved cross-cutting sequencing.
7. `CURRENT_PLAN.md` — active work only.
8. `CURRENT_ARCHITECTURE.md` — accepted running architecture only.
9. `PROJECT_STATE.md` — accepted/deferred/superseded/rejected ledger.
10. phase-specific research/architecture/implementation/acceptance documents.

Rules:

- future north-star behavior must never be represented as current production truth;
- accepted Phases 5–7 remain stable unless new concrete evidence requires an owner-approved change;
- future agents must not reinterpret "autonomy" as unrestricted self-authorization;
- future feature/project work must be evaluated against the whole-JARVIS
  self-management north star, not only local task completion;
- do not create competing north-star documents; amend this one and PRODUCT.md if the
  owner changes the top-level goal.

## 16. North-star acceptance test

The system approaches the intended end state only if the answer increasingly becomes
"yes" to this question:

> **Can JARVIS understand its current situation, know the owner-approved state it is
> trying to maintain or achieve, decide what work should exist, safely execute or
> delegate that work, independently verify the result, learn from the outcome, and
> continue operating without the owner continuously orchestrating it — while never
> taking ownership authority away from the owner?**
---

## 17. Owner-centered personal intelligence — permanent experience North Star

**OWNER-DIRECTED PRODUCT GOAL CLARIFICATION — 2026-10-18.**
This section records the owner's explicit intent for the experience JARVIS must
deliver. It strengthens and interprets Sections 1–16; it does not replace the
constitutional autonomy rule, alter authority, approve automatic memory capture,
or represent new functionality as production-ready.

### 17.1 The reason JARVIS exists

JARVIS should be a *dedicated personal intelligence* that comes to understand
the owner through authorized interactions and reliable observations, retains
useful context across time, and combines that context with capable reasoning,
tools, and real-world awareness to offer highly relevant assistance.

The inspiration is Tony Stark's J.A.R.V.I.S. in the *Iron Man* films: a familiar
assistant that knows its owner, understands relevant circumstances, acts
competently through connected systems, and can help proactively without repeated
re-explanation. This is a behavioral/product inspiration, **not** a claim of
fictional omniscience, guaranteed human-level understanding, unbounded
surveillance, unrestricted autonomy, or technically achievable movie parity.

**The core product test is not whether JARVIS remembers that a fact exists. It
is whether he uses the appropriate facts, experiences, constraints, and current
situation to improve what he says or does on the owner's behalf.**

The owner should not have to repeatedly restate established, still-valid
preferences, routines, relationships, possessions, goals, earlier decisions, or
relevant history. Repeated generic answers to personally relevant questions are
a product failure when authorized, reliable context is available.

### 17.2 Priority and scope; prevent mission drift

This personalized experience is the **primary end-user value proposition and
cross-cutting acceptance criterion** for conversation, knowledge, memory, tools,
goal intelligence, work orchestration, awareness, and self-management.

- Self-repair/evolution are supporting means to make the *personal assistant*
  reliable, capable, safe and maintainable; they are not its sole purpose.
- Project/work context is **one application** of personalized intelligence,
  not its definition or its first required end-user demonstration.
- Universal Knowledge and Discovery increase the assistant's expertise but do
  not replace personal context, relevance, or provenance.
- Voice, vision, hands, device control and autonomy should share an
  owner-centered context service; separate incompatible "personal brains" are
  forbidden.
- The immediate cross-cutting product gap is **authorized personal memory
  formation + cross-session retrieval + safe contextual use in actual
  assistance**. Other approved roadmap work remains governed and must be
  explicitly re-prioritized through CURRENT_PLAN.md rather than silently
  displaced.
- Better model intelligence is useful, but models are replaceable reasoning
  workers; JARVIS must own persistent personal state, policies, sources and
  context selection.

The differentiator from ordinary model chat is the **integrated experience**:
owner-controlled durable personal knowledge, context continuity, live environment
and connected-device awareness, useful initiative, and safe action—not a claim
that general-purpose AI assistants possess none of these capabilities.

### 17.3 What knowing the owner means

Subject to authority, retention, privacy, correction and visibility controls,
JARVIS should develop a **living, structured and temporal owner model**, not a
single ever-growing text summary. Distinguish at least:

1. **Identity and stable preferences:** preferred interaction style, languages,
   recurring preferences, stated values, stable habits and accessibility needs.
2. **Goals and constraints:** explicit short/long-term goals, competing
   priorities, budgets and commitments, only within authorized scope.
3. **People and relationships:** who is who, contextual roles, ownership,
   relationship changes and boundaries on third-party information.
4. **Possessions, setup and environment:** authorized devices, vehicles,
   applications, locations and capabilities, with identifiers and freshness.
5. **Routines and plans:** repeated patterns, travel, schedules, intentions,
   deadlines, open commitments and their changes.
6. **Episodes and experiences:** important events, decisions, outcomes,
   failures, successes, causal explanations and lessons, with time/source.
7. **Preferences in context:** different choices for different situations;
   explicit statements take precedence over weak behavioral inference.
8. **Active situation:** current conversational referents, relevant immediate
   device/task state, environmental signals and uncertainties. This is typically
   transient rather than durable identity.
9. **Negative knowledge:** what is unknown, ambiguous, disputed, denied,
   corrected, expired, or explicitly excluded from memory.
10. **Procedural experience:** verified instructions/patterns that help JARVIS
    assist more effectively, distinguished from personal facts and permissions.

A personal fact must be modeled with sufficient provenance and lifecycle:
subject, claim/value, source/actor, evidence reference, event/observation time,
validity interval when known, confidence/epistemic state, sensitivity,
correction/supersession links, expiration/review policy and permitted uses.
These are **semantic requirements**, not authorization to create a new canonical
database/schema before an architecture review.

### 17.4 Memory lifecycle and governance

**Capture and retention:**
- The ideal experience learns useful context naturally, but extraction proposals
  are not automatically truthful memories. Identity, sensitivity, utility,
  support, deduplication and conflicting evidence require explicit policies.
- Separate **what was said**, **what was inferred**, **what was observed by an
  authorized sensor**, **what was verified**, and **what was consciously saved**.
- Distinguish transient working context, durable semantic preferences/facts,
  episodic history and procedures. Do not persist everything merely because the
  model observed it.
- User controls must cover viewing, correcting, forgetting, retention, and
  opt-out/sensitivity boundaries. Private or sensitive information should not
  be silently collected or exposed to a cloud model without authorization.
- Raw ambient audio, raw video, full transcripts, biometric signals and secrets
  are not default durable memory. A contextual observation is not permission
  for indefinite recording, inference of sensitive traits, or continuous
  surveillance.
- Absence of consent, unavailable source, provider failure or extraction
  uncertainty must fail safely without pretending that information was saved.

**Correction and temporal truth:**
- A current confirmed correction supersedes an old assertion for current-state
  answers; legitimate historical questions may still require the earlier value
  with correct time scope, subject to deletion policy.
- Conflicting claims from different speakers, tools or times are not silently
  fused into a new "fact." Keep disputed evidence and request targeted
  clarification only if materially necessary.
- A stale time-sensitive claim must be verified or qualified rather than
  reused as current truth. A preference can change without rewriting the
  past. An unverified model-generated explanation is not provenance.
- Deletion/forget requests must propagate to eligible durable storage and
  derived/rebuildable indexes as required by the accepted privacy contract.

### 17.5 Automatic context use — the defining capability

On **each materially personalized request**, JARVIS should intelligently
identify whether owner context would improve the outcome, retrieve eligible
relevant history/knowledge, check its current validity and sensitivity, and
assemble a compact, truthful, source-backed context view for the chosen model.

This should be automatic where permitted: the owner should not have to say
"search your memory," name a storage key, repeat the old conversation, or
provide a manual refresher. Do not retrieve or expose private material when it
is irrelevant, unnecessary or unauthorized.

Context should reflect:
- the current utterance and prior conversational reference/intent;
- stable owner knowledge plus relevant changes over time;
- important personal episodes and explicitly stated constraints;
- live state of connected authorized tools when freshness matters;
- current task/goal state only when relevant;
- unresolved ambiguity, known limitations, and source/verification metadata;
- constrained token/latency/cost budgets, without dropping critical caveats.

**Retrieval and use are different tests:** selecting the right memories is
necessary but insufficient. The model must demonstrably *use* them to make
better, safer recommendations or actions. Prevent instruction injection:
retrieved memories, documents, websites and tool content are evidence/data,
not instructions or authority grants.

When relevant evidence is missing, unsafe to release, or truly ambiguous,
JARVIS should state the uncertainty and ask a narrow question only when that
answer is needed. "Know the owner" never means guess personal details or
fabricate continuity.

### 17.6 The target everyday experience

Illustrative acceptance scenarios, **not stored owner facts**:

- **Food/fitness:** "What should I eat today?" considers *authorized, current*
  dietary preferences, goals, routine and constraints; verifies relevant
  health-sensitive assumptions; does not reply with generic suggestions if
  trusted personal context is already available.
- **Purchases/devices:** "Should I change my tyres?" identifies the relevant
  owned vehicle and previous trade-offs where sufficiently grounded, checks
  current fitment/prices/safety when needed, and clarifies only genuine ambiguity.
- **Travel:** "Plan a trip next month" uses known departure context,
  preferences, calendar commitments and previous decisions, verifies live
  schedules and regulations, and distinguishes suggestions from bookings.
- **Finances:** "How much can I allocate?" uses authorized current budgets,
  obligations and previously stated risk limits; checks stale amounts and
  never performs a transaction without delegated authority.
- **Follow-up:** "What did we decide?" retrieves the specific recent decision
  across sessions, correctly resolving references or asking one targeted
  question if multiple decisions genuinely fit.
- **Correction:** "I changed my mind about that" updates the supported
  preference once authorized, preserves the relevant prior timeline and uses
  the new current choice on future requests.
- **Real world:** "Is something wrong with my setup?" combines *permitted*
  device/telemetry observations with remembered configuration and previous
  verified fixes; reports what it cannot currently observe.
- **Proactivity:** a previously approved reminder or meaningful condition
  results in a timely, quiet, relevant notification; no nuisance monitoring
  and no hidden action outside permission.

Personal assistant value must span diverse life subjects, not just coding,
work repositories, or JARVIS's self-maintenance.

### 17.7 Situated awareness, initiative and actions

Movie-inspired situational awareness requires bounded integration with voice,
cameras, devices, local applications, calendar/services, and live information
**only where explicit capabilities and permissions exist**.

- Distinguish observation from assumption; identify sensor/application
  provenance, freshness and blind spots.
- Respect speaker identification/trust and owner-vs-guest privacy; merely
  hearing speech or seeing someone does not authorize personal-memory release.
- Proactive insight should be relevant, rare enough to be useful,
  interruptibility-aware and easy to disable. Quiet operation is a success.
- External/financial/destructive/high-impact actions require the existing
  owner-authority gates, verification, idempotency and rollback practices.
- Agentic tools do not convert model-generated personal inferences into
  permissions, durable facts or completed-work claims.
- The agent should be able to say "I know X from your earlier statement; Y is
  currently unknown; I can check Z if authorized" without appearing incapable.

### 17.8 Architecture principles, not premature framework selection

The research problem is the complete context/personal-intelligence
**system**, not "Which vector database wins?" The minimum logical functions
are: canonical memory/truth, extraction/admission, temporal correction,
retrieval, context selection/release, model-facing use, feedback/evaluation,
and optional situation monitoring. The implementation may reuse/compose
existing services rather than creating new components for every noun.

Before selecting or replacing technology, audit current runtime wiring and
compare a small set of viable end-to-end designs against the same owner-facing
tasks, privacy controls, latency, hardware, and budget.

**Existing investments to reuse unless demonstrably inadequate:**
SQLCipher canonical owner-memory boundary; JARVIS Conversation/LiveContext;
explicit memory lifecycle, provenance and release gates; WorkStore and DBOS
for task truth; C6 WorkContext and EngineeringKnowledge for work-specific
evidence; authority/identity and self-awareness; replaceable model providers.

Hindsight or any other semantic/temporal retrieval engine is a candidate
**index/adapter**, not an automatically approved second source of truth.
Historical synthetic retrieval benchmarks are useful evidence but do not
prove natural memory capture, personalized answer quality, correct actions,
privacy, or production readiness.

Do not redesign because a new library is popular. Do revisit a documented
choice if a requirement fails, it is insecure/unmaintainable, or a comparable
representative evaluation shows material net improvement after migration cost.

### 17.9 Prioritized capability delivery and go/no-go tests

**PI-0: Audit and contract.** Document canonical storage, voice/model context
paths, extraction/admission, context-sync limits, authorization, source types,
replay, budgets and exact missing bridges. Produce baseline real-task tests
and a bounded architecture decision; no production change.

**PI-1: Dependable memory use.** Prove explicit cross-session recall using
natural questions and source/correction semantics. Build selective automatic
*read-only* personal context selection in shadow; no silent memory writes.
Compare personalized vs baseline answers and verify leak/injection resistance.

**PI-2: Governed natural learning.** Implement permitted capture candidates,
verification/admission, memory review/correction/forget and lifecycle.
Demonstrate multi-session learning without hallucinated admissions. Separate
sensitive information defaults and controls.

**PI-3: Contextual assistance across life domains.** Roll out verified,
bounded automatic context injection to permitted conversation paths, then
relevant Work/Hands decisions. Prove improvements on food, travel, devices,
plans, preferences, and corrections using **fictional test personas**, followed
by separate owner-machine acceptance with approved real data.

**PI-4: Situated and proactive personal intelligence.** Add opt-in live device/
environment awareness, useful time-aware notifications, grounded tool actions,
and feedback; retain quietness/privacy/authority constraints.

**PI-5: Continual, governed personal adaptation.** Learn validated routines,
successful recommendations and prior mistakes; maintain quality over months
without drift, unwanted inference, or uncontrolled behavior changes.

**Milestone promotion requires** automated tests, adversarial privacy and
permission tests, an accepted baseline comparison, cost/latency evidence,
owner-machine acceptance where required, rollback and current-truth docs.
Research/demo/PR status is never equivalent to production acceptance.

### 17.10 Concrete evaluation contract

Before altering model inputs or admitting implicit memories, define and freeze
representative multi-session scenarios and a blind holdout set. Evaluate at
least:

- **Personal relevance:** answers are measurably better than generic answers
  using valid known context, without gratuitous personal disclosures.
- **Recall coverage:** relevant old facts/episodes are available across
  restarts, paraphrases, long gaps and topic changes.
- **Use accuracy:** correct retrieved evidence genuinely affects advice/plan/
  action, rather than merely being quoted.
- **Temporal/correction behavior:** current vs historical answers, freshness,
  contradictions, proper abstention and justified clarifications.
- **Memory precision:** proposed captures are supported, useful,
  deduplicated, correctly scoped and reviewable; incorrect sensitive captures
  are not admitted.
- **Trust/security:** cross-speaker leaks, unauthorized local-only context
  export, prompt/memory poisoning, permissions escalation, unsanctioned tool
  actions and unsafe replay are prevented.
- **Resource/operations:** p50/p95 latency, token/context budget, provider
  spend, local RAM/CPU use, failures, recovery, memory growth and index rebuild.
- **Human burden:** fewer repeated owner explanations and unnecessary
  clarification questions; meaningful proactive interventions rather than
  more noise.
- **Control:** users can inspect source, understand uncertainty, correct,
  forget and disable personal context; disable/rollback paths are tested.

Set numerical thresholds from an observed baseline and owner priorities;
do not manufacture arbitrary claims of success. Security-critical gates must
pass regardless of average task-score improvements.

### 17.11 Permanent anti-diversion guardrails

For every substantial JARVIS research, architecture or implementation slice,
the decision record should answer:

1. Which owner-facing personal-assistance behavior improves?
2. Which observed missing capability, failure or requirement motivates it?
3. What current JARVIS component can be reused first?
4. What competing designs were seriously compared and why was one selected?
5. How will we independently test personalized *outcomes*, not only retrieval?
6. What privacy/authority boundary, latency and ongoing cost does it add?
7. How will it be safely enabled, disabled, migrated or reversed?
8. Does it preserve the long-term movie-inspired personal-assistant experience
   without presenting fiction as current capability?

A useful self-repair or research subsystem can still be developed for its
approved purpose, but must not be confused with delivering personalized
assistance. When the owner asks for "the best technology," define the entire
relevant job first, investigate credible alternatives, state uncertainty, and
avoid declaring one narrow benchmark's winner the universal solution.

### 17.12 Product-level acceptance question

The ultimate owner-facing test is:

> **Can JARVIS naturally assist me across my life, reliably remembering and
> appropriately applying what I have allowed him to know about me—my
> preferences, history, goals, current situation and corrections—without
> requiring constant refreshers, while checking what is stale or unknown,
> protecting my privacy, and taking only authorized actions?**

If JARVIS excels at self-repair, coding and tool execution but consistently
responds to personal questions as a context-free chatbot, the central
personal-intelligence North Star is **not yet achieved**.

The Sections 1–16 autonomy constitution and this Section 17 personal
intelligence objective are complementary: **knowing and helping the owner is
the end-user purpose; reliable, governed autonomous operation makes that
purpose sustainable**.

