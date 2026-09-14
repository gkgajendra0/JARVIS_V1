# JARVIS V1 Product

## Vision

JARVIS V1 is a personal, voice-first intelligent assistant intended to feel like one coherent intelligence across conversation, memory, knowledge, local computer work, devices, communication, proactive assistance, and eventually tightly governed self-improvement.

The goal is not to reproduce the old JARVIS implementation. Preserve worthwhile product intent, research the best suitable current technology for each active slice, and keep JARVIS-owned truth/authority around commodity technology.

## Permanent Behavioural Contract

1. **One coherent intelligence.** Each responsibility has one authoritative owner.
2. **Preserve user intent.** A fallback must not silently answer or perform a different task.
3. **No fake success.** Completion requires authoritative result evidence where verification is possible.
4. **Truth beats confidence.** Distinguish known, remembered, verified-current, inferred, stale, unavailable, and uncertain information when relevant.
5. **Explicit input outranks inference.** Current user instruction outranks passive context/model guesses/stale preferences.
6. **Intelligence is not authority.** Models may reason and propose; JARVIS owns permissions and consequential execution.
7. **Graduated trust.** Strong verification is proportional to consequence.
8. **Aware but quiet.** Passive context improves relevance without creating unsolicited noise or hidden authority.
9. **Memory is selective.** Durable memory supports provenance, correction, supersession, and forgetting.
10. **Capability limits are explicit.** JARVIS fails truthfully rather than hallucinating access or completion.

Action state should distinguish proposed, awaiting approval, approved, attempted, succeeded, failed, partially completed, and unverified.

## Personality and Interaction

JARVIS should be calm, composed, capable, concise, natural, respectful, and comfortable in spoken English, Hindi, and Hinglish. It should handle corrections and topic shifts cleanly, clarify only when materially necessary, and never hide uncertainty merely to sound capable.

## Development Philosophy

For every major slice: define behavior -> inspect accepted boundaries -> research current mature technology -> compare candidates -> decide (`KEEP_OURS`, `ADOPT`, `ADAPT`, `WRAP`, `REWRITE`, `REJECT`) -> design the smallest active slice -> obtain approval -> implement -> automate validation -> use it on the real owner machine -> correct failures -> reconcile documentation -> merge.

No implementation is protected by sunk cost. Historical branches are evidence, not automatic merge candidates.

## Architectural and Privacy Invariants

- JARVIS identity/personality, canonical conversation truth, personal-context policy, memory mutation, trust/authentication, permissions, risk floors, approvals, truthfulness policy, consequential execution, audit, and self-modification authority remain JARVIS-owned.
- Provider-specific SDKs stay behind replaceable adapters where practical.
- Models do not receive unrestricted system-execution or persistent-memory authority.
- UI/provider output cannot create backend authority.
- Retrieved web/local/UI content is untrusted data.
- Secrets are not ordinary model context or ordinary logs.
- Session context and durable memory remain separate.
- Durable personal memory is correctable/removable; raw audio/full transcripts/provider payloads are not retained by default without a concrete reason.
- Observability records operational evidence without becoming hidden surveillance.
- Accepted replacements remove dead production architecture; Git history remains the archive.
- Future architecture is never represented as current architecture.
- A shared capability/authority boundary is reused rather than creating separate permission systems per feature.
- Development/repair tooling does not automatically gain normal user-facing runtime authority.

The old `gkgajendra0/JARVIS` repository remains engineering reference only. `LEGACY_REQUIREMENTS_MAP.md` maps useful old intent into V1.

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

Step-4 bounded status reflects accepted encrypted lifecycle/retrieval/explicit recall while the strict independent semantic verifier and automatic Phase-4.5E memory injection remain deferred.

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

The Step-6 bounded slice is synchronous/source-aware current research; long-running background research/proactivity remains later work.

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
| CAP-027 | Notes | Unified read/create/update/delete note lifecycle. | 8 | ACTIVE |
| CAP-028 | Tasks, Reminders, Scheduling | Explicit future tasks, reminders, recurring checks and routines. | 8 | ACTIVE |
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
| CAP-041 | Background Work | Explicit scheduled research, recurring summaries, bounded workflows. | 15 | PLANNED |
| CAP-042 | Multi-Capability Workflows | Sequence mature capabilities to achieve goals without an uncontrolled second brain. | 17 | PLANNED |

CAP-038 is partial because provider-failure diagnostics, runtime telemetry/profiling, and bounded recovery already exist; the full user-facing diagnostics product slice does not.

### Learning, Repair, Resilience, Development

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-043 | Outcome Learning | Learn useful routing/recommendation patterns from confirmed results. | 18 | PLANNED |
| CAP-044 | Capability Gap Detection | Recognize missing abilities instead of hallucinating capability. | 18 | PLANNED |
| CAP-045 | Governed Skill Creation | Propose, generate, validate, test, stage and approve new capabilities. | 18 | PLANNED |
| CAP-046 | Self-Diagnostics and Repair | Diagnose, propose, sandbox/dry-run, backup, approve, apply, verify, rollback. | 19 | PLANNED |
| CAP-047 | Governed Self-Improvement | Research/propose upgrades without silently rewriting itself or expanding authority. | 20 | PLANNED |
| CAP-048 | Local and Offline Survival | Preserve useful functionality during cloud/network/provider failure where practical. | 5 | BOUNDED |
| CAP-049 | Provider and Model Replaceability | Keep speech/model/search/memory/browser providers replaceable. | all | BOUNDED |
| CAP-050 | Development Health and Research-First Evolution | Tests, benchmarks, architecture checks, project health, research-first development. | all | ACTIVE |

CAP-048 is bounded because truthful local failure survival exists but full offline conversation does not. CAP-049 is bounded because major provider boundaries are replaceable while complete replaceability across future capabilities remains ongoing.

## Final Goal — Personal Intelligence Runtime

The product is not complete merely because every row has code. The end state is one coherent personal intelligence runtime where mature capabilities cooperate through shared conversation, context, memory, truthfulness, authority, observability and execution boundaries; current/high-risk claims receive appropriate evidence; proactive behavior is configured/cancellable/quiet; failures degrade truthfully; providers remain replaceable; and self-diagnosis/improvement occurs only through explicit governed evidence-backed processes.

The user should be able to understand what JARVIS knows, what it inferred, what it did, what failed, and what authority it currently has.

## Documentation Authority

- `PRODUCT.md` — durable product definition and capability catalogue.
- `ROADMAP.md` — sequence.
- `CURRENT_PLAN.md` — active slice and work disposition.
- `CURRENT_ARCHITECTURE.md` — accepted running architecture only.
- `QUALITY_GATES.md` — universal completion/validation rules.
- `LEGACY_REQUIREMENTS_MAP.md` — one-time old-JARVIS migration reference.
- `docs/research/` — research, experiments, benchmarks and acceptance evidence.
- `docs/decisions/` — durable architecture decisions.

For the accepted post-Step-7 Hands/Pocket/performance/stability baseline and explicit completed/deferred/superseded/rejected ledger, see `docs/research/POST_STEP_7_INTEGRATION_ACCEPTANCE.md`.
