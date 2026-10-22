# JARVIS V1 Product

## Vision

JARVIS V1 is a personal, voice-first intelligent assistant intended to mature into one coherent **governed autonomous self-managing personal intelligence runtime** across conversation, memory, knowledge, local computer work, devices, communication, proactive assistance, operations, self-repair and self-evolution.

The end-state owner relationship is:

> **The owner defines intent, priorities, boundaries, budgets and protected decisions. JARVIS continuously understands itself and its environment, determines what work is necessary, operates and maintains itself, repairs failures, optimizes performance and cost, acquires missing capabilities, executes long-running goals, verifies its own results, learns from outcomes, and progressively improves itself. Authority remains with the owner.**

The owner should not need to act as JARVIS's full-time operator, project manager, debugger or release engineer. Mature JARVIS should increasingly determine what work needs to exist from owner goals, accepted system obligations and evidence from its own current state, rather than waiting for the owner to manually create every task.

When JARVIS cannot currently satisfy a goal, it should identify the capability or engineering gap truthfully and use the governed engineering lifecycle to research, architect, implement, test, diagnose failed attempts, prepare evidence and promotion artifacts, and involve the owner only at genuine authority, secret/physical-input, acceptance or protected-promotion gates.

The permanent constitutional rule is:

> **JARVIS may manage JARVIS, but JARVIS must never become its own source of authority.**

The complete top-level operating architecture is defined in `AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md`. The autonomous-engineering system is one major subsystem beneath that product north star.

The goal is not to reproduce the old JARVIS implementation. Preserve worthwhile product intent, research the best suitable current technology for each active slice, and keep JARVIS-owned truth/authority around commodity technology.

## Owner-Centered Personal Intelligence Contract

Candidate update (22 October 2026): automatic conversational learning is implemented and software-verified on its dedicated branch/draft PR#295 (all7CI on c03666b7 passed). The owner chose to advance development and defer extended quota-bound provider qualification. Learning remains OFF by default and unpromoted; multilingual quality/resource and normal-app acceptance are still open, not passed by this decision. CAP-053stays PARTIAL. See the [handoff](research/PERSONAL_AUTO_LEARNING_IMPLEMENTED_HANDOFF_2026-10-22.md) and [immutable qualification](research/PERSONAL_AUTO_LEARNING_QUALIFICATION_2026-10-22.md).

Implementation update (21 October 2026): PR #294 supplies the first opt-in active
read slice with fresh exact-request Hello, natural existing-memory changes and
provider-session retirement after each personal answer. The owner confirmed
saved-preference recall/correction/restart/restoration and authorized checked
promotion. See the [bounded acceptance](acceptance/PERSONAL_MEMORY_OWNER_ACCEPTANCE_2026-10-21.md).
CAP-053 is PARTIAL; broader advice quality and automatic learning remain open.

**Owner goal clarified 2026-10-18; desired product behavior, NOT accepted production
capability.** The distinctive point of building JARVIS is a movie-inspired,
deeply contextual, dedicated personal assistant—not a generic cloud chatbot
with a voice, a repository-aware coding agent, or an autonomous repair daemon.

JARVIS should reliably know, where supported and authorized, **who the owner
is in context**: preferences, goals, commitments, routines, possessions,
relationships, constraints, decisions, experiences and what has changed
over time. This knowledge should improve ordinary advice, follow-ups,
recommendations and permitted actions without requiring the owner to
re-introduce already known and still-valid facts.

**The core interaction loop:**

```text
owner's request + current permitted situation
  -> determine whether personal context changes the answer or action
  -> retrieve relevant owner facts, episodes, preferences and current context
  -> check provenance, freshness, corrections, ambiguity, sensitivity
  -> assemble the smallest safe, useful context for the model
  -> give personalized, grounded guidance or perform an authorized action
  -> record verified outcomes / allowed memory candidates (separate consent gate)
  -> improve subsequent interactions without pretending guesses are facts
```

**Required experience:**

- Ask "What should I eat?" and receive a response taking account of current
  authorized dietary preferences, goals and constraints—not generic advice.
- Ask "Which tyres should I choose?" and have JARVIS connect the right owned
  vehicle, previous decisions and current conditions before answering.
- Ask "What did we decide?" after a new session and receive the applicable
  past decision, with temporal and source grounding, or a focused clarification
  only if genuinely ambiguous.
- Ask "Can I afford this?" and have JARVIS respect current authorized budgets,
  existing commitments and uncertainty without using stale numbers as fact.
- Change a preference and see the current answer update while legitimate
  historical context remains properly time-scoped.
- Request help with a real-world situation and receive context-aware reasoning
  using only actually connected, permitted, sufficiently fresh observations.
- Opt into proactive help without creating intrusive surveillance,
  unnecessary notifications or unauthorized actions.

**Permanent product boundaries:**

- "Know me" means useful, correct, privacy-respecting, owner-controlled
  continuity—not indiscriminate or perfect retention of every utterance.
- An inference about the owner is not a verified fact; a retrieved document
  is not a command; remembered information is not action authority.
- Separate automatic **retrieval** from automatic **memory writes**, and keep
  sensitive-data access, source trust and deletion controls enforceable.
- Personal memories should remain JARVIS-owned canonical state with
  provenance, correction, time validity, visibility and revocability.
- Model providers, indexing engines and retrieval frameworks remain
  replaceable. Avoid building a parallel memory or work source of truth.
- Movie J.A.R.V.I.S. is a **behavioral inspiration**, not an assertion of
  omniscience, sentience, continuous perfect understanding or guaranteed
  fictional functionality.
- Engineering, self-management, broad knowledge and self-evolution support
  this personal intelligence experience; they do not substitute for it.

**Success is measured by personalized outcomes, not the number of integrations:**
on representative held-out, multi-session life-domain tasks JARVIS must
retrieve and *correctly use* relevant history, honor corrections and
uncertainty, reduce repeated questions, protect sensitive context, and act
only with permission. High fact-retrieval accuracy without better assistant
behavior is insufficient.

Implementation is subject to the existing research -> architecture ->
owner approval -> isolated implementation -> automated/owner-machine
validation -> protected promotion lifecycle. No new memory admission,
provider-context injection or production autonomy is authorized merely by
this goal statement.

**Authoritative detailed specification:** Section 17,
`AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md`. This user experience is the
primary user-facing value proposition within the existing constitutional
autonomy North Star; it does not create a competing North Star.

## Permanent Behavioural Contract

1. **One coherent intelligence.** Each responsibility has one authoritative owner.
2. **Preserve user intent.** A fallback must not silently answer or perform a different task.
3. **No fake success.** Completion requires authoritative result evidence where verification is possible.
4. **Truth beats confidence.** Distinguish known, remembered, verified-current, inferred, stale, unavailable, and uncertain information when relevant.
5. **Explicit input outranks inference.** Current user instruction outranks passive context/model guesses/stale preferences.
6. **Intelligence is not authority.** Models may reason, research and propose; JARVIS owns permissions and consequential execution.
7. **Graduated trust.** Strong verification is proportional to consequence.
8. **Aware but quiet.** Passive context improves relevance without creating unsolicited noise or hidden authority.
9. **Memory is selective.** Durable memory supports provenance, correction, supersession, and forgetting.
10. **Capability limits are explicit.** JARVIS fails truthfully rather than hallucinating access or completion.
11. **Owner intent can create engineering work.** A missing capability may become a governed durable EngineeringChange rather than a dead-end response.
12. **Autonomy never implies self-authorization.** Research/coding/testing autonomy does not remove owner approval, security, verification or protected-main promotion gates.
13. **JARVIS owns operations, not constitutional authority.** Mature JARVIS may create and prioritize work from accepted goals/system obligations and may operate itself inside delegated bounds; it may not create new authority for itself.
14. **Desired state drives autonomy.** Autonomous work must be traceable to accepted owner intent, registered system obligations, measurable desired state or evidence-backed operational findings.
15. **Deterministic before agentic.** Predictable maintenance/recovery should use deterministic controllers or workflows when they are safer and sufficient; model reasoning is reserved for ambiguity, diagnosis, research, planning and novel work.

Action state should distinguish proposed, awaiting approval, approved, attempted, succeeded, failed, partially completed, unverified and rolled back where applicable.

## Owner-Directed Engineering Contract

Mature JARVIS should support three kinds of governed autonomous engineering through one shared platform:

1. **Known production repair** — deterministic bounded recovery for accepted failure signatures.
2. **Unknown-problem investigation and repair engineering** — evidence-driven diagnosis, isolated source repair, verification and promotion preparation.
3. **Capability evolution** — direct owner-requested capability acquisition and, later, autonomous gap/weakness proposals.

For a high-level owner request such as:

> "JARVIS, I want to control this TV through you. Get that capability."

or:

> "JARVIS, integrate the gate camera and tell me when a person is there."

mature behavior should be:

```text
owner goal
-> truthful capability check
-> research / discovery
-> technology comparison
-> architecture
-> owner approval
-> isolated implementation
-> governed dependency / credential handling
-> automated tests / simulation / replay
-> diagnose and retry failed attempts
-> real-world owner acceptance where required
-> PR / CI / documentation
-> explicit owner merge/promotion approval
-> production observation
-> verified engineering learning
```

The owner may be asked to provide information only the owner can provide, such as a pairing PIN, credential through a trusted local secret-entry path, physical device observation or explicit governance approval.

Every device/service is not guaranteed to be automatable. Vendor restrictions, closed protocols, unsupported firmware, cloud-only access or missing local permissions may make a requested operation impossible. JARVIS must report the blocker and alternatives truthfully rather than inventing success.

The detailed cross-cutting architecture is owned by `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`.

## Personality and Interaction

JARVIS should be calm, composed, capable, concise, natural, respectful, and comfortable in spoken English, Hindi, and Hinglish. It should handle corrections and topic shifts cleanly, clarify only when materially necessary, and never hide uncertainty merely to sound capable.

During autonomous engineering it should keep the owner informed at meaningful transitions, not narrate every tool call. Useful owner interactions include architecture decisions, genuine blockers, secure credential/pairing requests, bounded physical acceptance steps and promotion approvals.

## Development Philosophy

For every major slice: define behavior -> inspect accepted boundaries -> research current mature technology -> compare candidates -> decide (`KEEP_OURS`, `ADOPT`, `ADAPT`, `WRAP`, `REWRITE`, `REJECT`) -> design the smallest active slice -> obtain approval -> implement in isolation -> automate validation -> use it on the real owner machine when required -> correct failures -> reconcile documentation -> review/CI -> obtain explicit merge approval -> merge.

The same lifecycle applies when JARVIS itself becomes the engineering worker. Autonomous execution may reduce manual owner engineering effort; it does not remove architecture, verification, acceptance or promotion governance.

No implementation is protected by sunk cost. Historical branches are evidence, not automatic merge candidates.

## Architectural and Privacy Invariants

- JARVIS identity/personality, canonical conversation truth, personal-context policy, memory mutation, trust/authentication, permissions, risk floors, approvals, truthfulness policy, consequential execution, audit, verification and self-modification authority remain JARVIS-owned.
- Provider-specific SDKs stay behind replaceable adapters where practical.
- Models do not receive unrestricted system-execution, package-installation, network-discovery, credential or persistent-memory authority.
- UI/provider/retrieved content cannot create backend authority.
- Retrieved web/local/UI content is untrusted data.
- Secrets are not ordinary model context or ordinary logs; future capability engineering uses a governed secret broker/opaque references when credentials are needed.
- Session context and durable memory remain separate.
- Durable personal memory is correctable/removable; raw audio/full transcripts/provider payloads are not retained by default without a concrete reason.
- Observability records operational evidence without becoming hidden surveillance.
- Accepted replacements remove dead production architecture; Git history remains the archive.
- Future architecture is never represented as current architecture.
- A shared capability/authority boundary is reused rather than creating separate permission systems per feature.
- Repair, capability acquisition and self-improvement reuse shared durable work, engineering-change, knowledge and verification primitives rather than independent autonomous brains.
- Development/repair tooling does not automatically gain normal user-facing runtime authority.
- Development sandboxes remain least-privilege; new dependencies/SDKs are acquired through governed provenance-aware mechanisms rather than arbitrary shell authority.
- Protected-main merge and protected governance mutation never become implicit consequences of a model-generated candidate.

The old `gkgajendra0/JARVIS` repository remains engineering reference only. Any migrated intent that still matters is represented in this capability catalogue or `PROJECT_STATE.md`; Git history is the archive for obsolete migration notes.

## Capability Status Vocabulary

- `DONE` — accepted production capability for its defined scope.
- `BOUNDED` — accepted useful production subset with an explicit unresolved/deferred remainder.
- `PARTIAL` — accepted production foundation exists, but its later formal roadmap slice is not complete.
- `ACTIVE` — current work/research or intentionally ongoing cross-cutting capability.
- `PLANNED` — product intent exists but the formal capability is not accepted as complete.
- `RETIRED` — intentionally removed/rejected product behavior.

Presence in this catalogue is product intent, not permission to implement or execute.

## Capability Catalogue

### Interaction, Voice, Identity

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-001 | Natural Voice Conversation | Realtime continuous spoken conversation, multilingual use, natural turn-taking. | 1 | DONE |
| CAP-002 | Wake and Conversational Presence | Wake by name, enter follow-up conversation, return to idle naturally. | 2 | DONE |
| CAP-003 | Barge-In and Audio Robustness | User interruption, echo/noise/device handling, clean recovery from voice-state faults. | 2 | DONE |
| CAP-004 | Identity and Presence | Owner/session/presence evidence when identity actually matters. | 3 | DONE |
| CAP-005 | JARVIS Personality | Stable natural identity, language adaptation, truthful capability framing. | 1 | DONE |

Turn-specific spoken actor binding remains a Step-3 deferral. CAM++/LR-ASD remain shadow evidence. Hands may use bounded post-Windows-Hello same-session T2 convenience, but face/voice evidence does not independently mint authority.

### Conversation, Context, Memory

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-006 | Conversation Intelligence | Follow-ups, references, corrections, topic changes, clarification, goals, planning. | 1 | DONE |
| CAP-007 | Canonical Conversation State | One JARVIS-owned accepted record of live conversation turns/lifecycle. | 1 | DONE |
| CAP-008 | Live Session Context | Active task, goal, project, recent outcomes/issues/pending work. | 4 | BOUNDED |
| CAP-009 | Long-Term Personal Memory | Durable useful personal/project facts with provenance and correction. | 4 | BOUNDED |
| CAP-010 | Episodic Memory | Recall meaningful past events, sessions, failures, fixes, milestones. | 4 | BOUNDED |
| CAP-011 | Semantic Memory | Durable facts/preferences/rules with conflict and supersession handling. | 4 | BOUNDED |
| CAP-012 | Reflection and Session Learning | Achievements, issues, decisions, next steps, memory candidates. | 4 | BOUNDED |
| CAP-013 | Emotional Interaction Context | Transient interaction signals that improve tone without permanent identity labels. | 4 | BOUNDED |
| CAP-053 | Personal Intelligence and Automatic Context Use | Owner-centered, safe multi-session personal understanding and relevant use of authorized facts, episodes, corrections, preferences, and situation in actual assistance. | cross-cutting | PARTIAL — opt-in saved-preference recall/correction/restart owner-confirmed; broader advice, natural learning and seamless speaker follow-ups open |

Step-4 bounded status reflects accepted encrypted lifecycle/retrieval/explicit recall while the strict independent semantic verifier and automatic Phase-4.5E memory injection remain deferred.

CAP-053 is the primary owner-facing outcome and uses CAP-006–013 plus source-aware knowledge, voice, permitted devices, context assembly, and governed actions. Its partial status distinguishes the accepted bounded flow from the broader intended assistant.

### Knowledge, Research, Truth

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-014 | Knowledge and Source Routing | Select the right source: model, web, memory, project docs, local files, trusted domain data. | 6 | BOUNDED |
| CAP-015 | Current Information and Deep Research | Fresh web/news/current information with sources/provenance. | 6 | BOUNDED |
| CAP-016 | Trusted Domain Knowledge | Prefer appropriate authoritative sources for specialist/high-stakes domains. | 6 | BOUNDED |
| CAP-017 | Fact Checking and Truthfulness | Verify when required; distinguish known/inferred/stale/unverified claims. | 6 | BOUNDED |
| CAP-018 | Local Project and Document Intelligence | Search/reason over approved project files, code, docs, logs, notes, handovers. | 7 | DONE |
| CAP-019 | World Awareness | Maintain selected current context across world/user-interest domains. | 14 | PLANNED |
| CAP-020 | Aware-but-Quiet Context | Use passive awareness without unsolicited noise or hidden authority. | 14 | PLANNED |

The Step-6 source-aware research slice remains bounded. PR #55 adds accepted durable background research execution and concurrent work truth, but proactive/event-driven monitoring and scheduled/recurring product behavior remain later Step-15 work.

### Local Computer, Files, Browser, Devices

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-021 | Computer and System Awareness | Machine time, uptime, health, apps, approved files/devices. | 7 | DONE |
| CAP-022 | File and Computer Safe Reads | Bounded read-only access to approved local resources. | 7 | DONE |
| CAP-023 | Application Control | Open/focus/manage approved desktop applications/windows. | 9 | PARTIAL |
| CAP-024 | Device Control | Control approved local/network/smart devices and services. | 9 | PARTIAL |
| CAP-025 | Browser and Web Interaction | Navigate/forms/downloads/uploads under authority controls. | 10 | PARTIAL |
| CAP-026 | File and Document Actions | Create/edit/organize/move/rename and eventually delete with safeguards. | 12 | PARTIAL |

`PARTIAL` records owner-accepted Hands foundations pulled forward after Step 7. It does not mark Steps 9/10/12 complete.

### Productivity and Communication

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-027 | Notes | Unified read/create/update/delete note lifecycle. | 8 | PLANNED |
| CAP-028 | Tasks, Reminders, Scheduling | Explicit future tasks, reminders, recurring checks and routines. | 8 | PLANNED |
| CAP-029 | Calendar | Read availability/events, later approved calendar writes. | 11 | PLANNED |
| CAP-030 | Email and Communication | Search/read, draft/review, then explicitly approved sending. | 11 | PLANNED |
| CAP-031 | Coding and Project Engineering | Repositories, code, tests, diffs, validation, approved development work. | 12 | PARTIAL |

CAP-031 is partial because bounded Git/project operations exist through Hands; the formal coding/project-engineering slice remains future work and arbitrary shell authority remains blocked.

### Capability Runtime and Authority

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-032 | Generic Capability Runtime | Discover/select/validate/execute capabilities through one common boundary. | 7 | DONE |
| CAP-033 | Extensible Skills and Plugins | Add/register/enable/disable/replace integrations without rebuilding core. | 16 | PLANNED |
| CAP-034 | Authority, Permissions, Consent | Decide whether reads/writes/external/destructive actions are permitted. | 3 | DONE |
| CAP-035 | Graduated Trust | Scale identity/approval friction with consequence. | 3 | DONE |
| CAP-036 | Auditable Action Execution | Proposal, approval, attempt, result, evidence, rollback state. | 3 | DONE |
| CAP-037 | Runtime Observability | Trace sessions, turns, latency, capability/provider/authority outcomes safely. | 3 | DONE |

### Runtime Operations, UI, Proactivity

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-038 | Health and Diagnostics | Explain degraded audio/network/provider/capability/runtime state and recovery options. | 13 | PARTIAL |
| CAP-039 | HUD and Visual Workspace | Present conversation, status, context, world feed, memory, skills, execution, diagnostics. | 13 | PLANNED |
| CAP-040 | Proactive Monitoring | Watch approved topics/conditions and surface meaningful changes. | 15 | PLANNED |
| CAP-041 | Background Work | Explicit scheduled research, recurring summaries, bounded workflows. | 15 | PARTIAL |
| CAP-042 | Multi-Capability Workflows | Sequence mature capabilities to achieve goals without an uncontrolled second brain. | 17 | PLANNED |

CAP-038 is partial because provider-failure diagnostics, runtime telemetry/profiling, and bounded recovery already exist; the full user-facing diagnostics product slice does not.

CAP-041 is partial because PR #55 now provides accepted persistent concurrent WorkItems, restart recovery, bounded research/development workers, owner controls, progress/status and durable delivery. Step 15 still owns proactive monitoring, event-driven triggers, scheduled/recurring background behavior and broader workflow productization.

### Learning, Repair, Resilience, Development

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-043 | Outcome Learning | Learn useful routing/recommendation/engineering patterns from confirmed results. | 18 | PLANNED |
| CAP-044 | Capability Gap Detection | Recognize missing abilities instead of hallucinating capability. | 18 | PLANNED |
| CAP-045 | Governed Skill Creation | Research, propose, generate, validate, test, stage and approve new capabilities. | 18 | PLANNED |
| CAP-046 | Self-Diagnostics and Repair | Diagnose, propose, sandbox/dry-run, backup, approve, apply, verify, rollback. | 19 | PARTIAL |
| CAP-047 | Governed Self-Improvement | Research/propose/build/benchmark upgrades without silently rewriting itself or expanding authority. | 20 | PLANNED |
| CAP-048 | Local and Offline Survival | Preserve useful functionality during cloud/network/provider failure where practical. | 5 | BOUNDED |
| CAP-049 | Provider and Model Replaceability | Keep speech/model/search/memory/browser providers replaceable. | all | BOUNDED |
| CAP-050 | Development Health and Research-First Evolution | Tests, benchmarks, architecture checks, project health, research-first development. | all | ACTIVE |
| CAP-051 | Governed Autonomous Engineering | Turn an approved owner goal/incident/gap into durable research, architecture, isolated development, verification and promotion-ready evidence without transferring owner authority. | cross-cutting | PLANNED — foundational pieces exist |
| CAP-052 | Autonomous Self-Management Control Plane | Maintain owner-approved desired state, reconcile whole-JARVIS actual state, create/prioritize necessary work, operate/heal/configure/optimize/protect/extend JARVIS within delegated authority, and escalate only genuine owner-attention boundaries. | cross-cutting | PLANNED — north star approved 2026-09-26 |

CAP-046 is partial because the deterministic repair framework, bounded R2 production Self-Repair foundation and generalized EngineeringKnowledge foundation are owner accepted. Registered repair policies, durable RepairAttempts, external crash/hang supervision, budgets/cooldowns, startup readiness, authenticated liveness verification, Windows process-tree recovery, verified-repair knowledge projection, lifecycle/provenance/applicability and grounded local retrieval are production proven. AI-assisted diagnostics, sandboxed source repair, closed-loop engineering learning and later self-evolution layers remain incomplete.

CAP-047 remains planned. No current capability may silently rewrite protected main, weaken Authority/governance, expand permissions or self-declare an improvement successful.

CAP-051 is the explicit autonomous-engineering capability. Existing durable WorkItems, bounded research/development workers, Authority, self-awareness, isolated worktrees and deterministic R2 repair are foundations, not completion. The staged engineering sequence is defined in `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`.

CAP-052 is the top-level autonomy capability and does **not** mean an unrestricted super-agent. Its future control plane must reuse Self Model, Health, WorkItems, EngineeringChange, EngineeringKnowledge, Authority and verification as canonical truth. It introduces durable objectives/desired state, whole-system reconciliation, autonomous finding/work creation, portfolio prioritization, meaningful owner-attention escalation and later separately approved delegated-authority envelopes. The authoritative design is `AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md`.

CAP-048 is bounded because truthful local failure survival exists but full offline conversation does not. CAP-049 is bounded because major provider boundaries are replaceable while complete replaceability across future capabilities remains ongoing.

## Final Goal — Autonomous Self-Managing Personal Intelligence Runtime

The product is not complete merely because every catalogue row has code or because JARVIS can autonomously execute an engineering project. The end state requires whole-JARVIS self-management under owner authority.

The end state is one coherent personal intelligence runtime where:

- mature capabilities cooperate through shared conversation, context, memory, truthfulness, authority, observability and execution boundaries;
- current/high-risk claims receive appropriate evidence;
- proactive behavior is configured/cancellable/quiet;
- failures degrade truthfully;
- providers remain replaceable;
- JARVIS can understand its own health/capability state;
- known faults can recover through accepted deterministic policy;
- unknown faults can become governed investigation/repair work;
- an explicit owner request for a missing capability can become governed autonomous engineering work;
- research, architecture, implementation, testing, debugging, PR preparation and evidence gathering can increasingly be handled by JARVIS;
- owner involvement is concentrated at real authority, secret/physical-input, acceptance and promotion gates;
- self-diagnosis/improvement occurs only through explicit governed evidence-backed processes;
- protected Authority/security/governance cannot be silently relaxed by the system improving itself;
- JARVIS maintains an owner-approved desired-state/objective model distinct from observed actual state;
- JARVIS can detect meaningful gaps between desired and actual state and decide when new work should exist;
- JARVIS can manage and prioritize its own operational, repair, capability, maintenance and improvement portfolio;
- predictable self-management uses deterministic controllers/workflows before invoking agentic reasoning;
- owner attention becomes a scarce explicit resource reserved for true authority, judgment, secret/physical-input, acceptance or protected-promotion boundaries.

The owner should be able to understand what JARVIS knows, what it inferred, what it did, what failed, what it changed or proposes to change, how it verified the result, and what authority it currently has.

The target experience is therefore not "the owner programs every new capability into JARVIS" and not merely "JARVIS manages projects for the owner." It is:

> **The owner defines intent and the constitution; JARVIS manages JARVIS and its work inside that constitution, continuously moving actual state toward the owner-approved desired state and involving the owner only when owner authority is genuinely required.**

The engineering subsystem remains essential because it gives the autonomy control plane a governed way to repair, extend and improve the system rather than merely detect problems.

## Documentation Authority

- `PRODUCT.md` — durable product identity, behavioral contract and capability catalogue.
- `AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md` — authoritative whole-JARVIS operating north star.
- `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md` — autonomous-engineering subsystem under the product north star.
- `SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md` — specialized staged repair/evolution program under the engineering subsystem.
- `ROADMAP.md` — numbered product sequence/high-level status and approved cross-cutting sequencing.
- `CURRENT_PLAN.md` — active slice and work disposition; authoritative current phase.
- `CURRENT_ARCHITECTURE.md` — accepted running architecture only; future north-star behavior must never be represented here as current production truth.
- `QUALITY_GATES.md` — universal completion/validation/promotion rules.
- `PROJECT_STATE.md` — canonical accepted/deferred/superseded/rejected repository ledger.

For accepted, deferred, superseded and rejected repository state, see `PROJECT_STATE.md`.
