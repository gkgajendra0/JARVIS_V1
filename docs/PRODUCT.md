# JARVIS V1 Product

## Vision

JARVIS V1 is a personal, voice-first intelligent assistant intended to feel like one coherent intelligence across conversation, memory, knowledge, local computer work, devices, communication, proactive assistance, and eventually tightly governed self-improvement.

The goal is not to reproduce the old JARVIS implementation. The goal is to preserve its worthwhile product intent and rebuild each active subsystem using the best suitable technology available when that subsystem becomes active.

Cloud technology is allowed when it gives the best experience. Local/offline capability should be added where it materially improves resilience, privacy, latency, cost, or availability.

## Permanent Behavioural Contract

1. **One coherent intelligence.** Internal modules may be many, but each responsibility has one authoritative owner.
2. **Preserve user intent.** A fallback must not silently answer a different question.
3. **No fake success.** JARVIS may claim an action completed only when the authoritative underlying system confirms it.
4. **Truth beats confidence.** JARVIS should distinguish known, remembered, current-verified, inferred, stale, and uncertain information when relevant.
5. **Explicit input outranks inference.** Current user instruction outranks passive context, model guesses, inferred mood, stale memory, or historical preference.
6. **Intelligence is not authority.** A model may recommend an action; permission and consequential execution remain JARVIS-owned.
7. **Graduated trust.** Ordinary conversation is frictionless; stronger identity/approval is required only as consequence increases.
8. **Aware but quiet.** Passive awareness should improve responses without becoming unsolicited noise.
9. **Memory is selective.** Not every sentence becomes durable memory. Corrections, provenance, confidence, supersession, and forgetting must be supported.
10. **Capability limits are stated plainly.** If JARVIS cannot access or verify something, it should say so rather than pretend.

Action state should distinguish at least: proposed, awaiting approval, approved, attempted, succeeded, failed, partially completed, and unverified.

## Personality and Interaction

JARVIS should be calm, composed, capable, concise, natural, respectful, and comfortable in spoken conversation. It should adapt naturally among English, Hindi, and Hinglish; avoid robotic command phrasing; handle corrections cleanly; ask clarification only when materially necessary; and never hide uncertainty merely to sound capable.

## Development Philosophy

For every major product slice:

1. Define the required JARVIS behaviour.
2. Research the best suitable technology available at that time.
3. Inspect only relevant old-JARVIS work for product intent, tests, failure lessons, and potentially reusable ideas.
4. Compare realistic candidates.
5. Make an explicit decision where useful: `KEEP_OURS`, `ADOPT`, `ADAPT`, `WRAP`, `REWRITE`, or `REJECT`.
6. Define one authoritative owner per responsibility.
7. Design only the active slice.
8. Implement the approved design.
9. Validate with automated tests and real human use.
10. Correct problems before activating the next slice.

No implementation is protected by sunk cost. Interesting new technology must not derail an active release unless it exposes a material architecture, security, privacy, licensing, reliability, or product-quality problem.

## Adopt Commodity Infrastructure, Own JARVIS Authority

Commodity mechanics should normally use strong existing technology when that is better than rebuilding them. Examples include realtime media plumbing, speech models, general LLM inference, search/retrieval mechanics, browser automation, provider SDKs, and external service integrations.

JARVIS retains authority over:

- identity and personality;
- canonical conversation truth;
- personal-context policy;
- memory-write authority;
- trust and authentication policy;
- permissions and consent;
- capability authorization;
- approvals;
- truthfulness policy;
- consequential action execution;
- durable audit state;
- self-modification authority.

## Privacy and Data Lifecycle Principles

Personal intelligence is only useful if the user can understand and control what is retained.

Permanent rules:

1. **Minimize by default.** Do not persist raw audio, provider payloads, full transcripts, secrets, or sensitive content merely because they are available.
2. **Separate session context from durable memory.** Conversation state may be short-lived without becoming long-term personal memory.
3. **Durable memory needs provenance.** Persisted personal/project facts should retain enough source/time/confidence information to support correction and supersession.
4. **Correction and forgetting are first-class.** The user must be able to correct, replace, or remove durable personal memory.
5. **Transient emotion stays transient.** Mood/emotional interpretations may shape the current interaction but should not become permanent identity labels by default.
6. **Provider data is not automatically JARVIS memory.** External operational history/caches do not become canonical personal memory merely because a provider retains them during a session.
7. **Sensitive capability access is bounded.** File, email, calendar, device, browser, credential-adjacent, and system access should request only what the active operation requires.
8. **Audit without surveillance.** Observability should capture state transitions, decisions, result status, and latency while avoiding unnecessary content capture.
9. **Secrets are never normal model context.** Credentials/tokens should remain in dedicated secret/config boundaries and should not be logged or inserted into prompts unless a provider protocol strictly requires the credential outside model-visible content.
10. **Deletion means deletion from JARVIS-owned stores.** Where provider-side retention cannot be controlled by JARVIS, that limitation must be understood rather than falsely claiming complete deletion.

Specific retention/storage technology is selected when the relevant memory/knowledge/observability step becomes active.

## Architectural Invariants

1. One authoritative owner per responsibility.
2. Provider SDKs stay behind JARVIS-owned adapters/contracts where practical.
3. Core domain/state should not depend on provider-specific SDK types.
4. Conversation, context, and memory must not have duplicate authoritative owners.
5. No giant `main.py`; composition belongs in a clear application root.
6. Models do not receive unrestricted system-execution authority.
7. Models do not write directly to persistent memory.
8. UI does not create backend authority.
9. Capabilities cannot grant themselves broader permission.
10. Legacy compatibility requires explicit approval.
11. Accepted replacements remove abandoned runtime implementations rather than preserving dead architecture indefinitely.
12. Git history is the archive; do not create `FINAL`, `V2`, or duplicated history documents.
13. Build only what the current product slice needs.
14. Future architecture is never represented as current architecture.
15. Replaceable providers must have a clear replacement boundary.
16. Development/repair tooling is not automatically part of normal user-facing runtime authority.
17. A shared capability boundary should exist before multiple action families expand, so notes/apps/browser/email/etc. do not each create separate execution architectures.

## Old JARVIS Policy

The old `gkgajendra0/JARVIS` repository is engineering evidence only. It is useful for discovering product requirements, recovering tests and acceptance scenarios, learning runtime failure modes, and understanding which abstractions caused duplication or drift.

JARVIS V1 must not import it at runtime, depend on its directory structure, copy whole old subsystems blindly, restore retired autonomous development agents, reproduce its documentation/control-plane sprawl, or preserve duplicated registries/context owners/note paths/routing stacks merely because they existed.

`docs/LEGACY_REQUIREMENTS_MAP.md` records the migration of old product intent into V1.

## Capability Catalogue

Presence here means **planned product intent**, not implementation authorization. Status values are deliberately simple: `DONE`, `ACTIVE`, `PLANNED`, `RETIRED`.

### Interaction, Voice, and Identity

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-001 | Natural Voice Conversation | Realtime continuous spoken conversation, multilingual use, natural turn-taking. | 1 | DONE |
| CAP-002 | Wake and Conversational Presence | Wake by name, enter follow-up conversation, return to idle naturally. | 2 | DONE |
| CAP-003 | Barge-In and Audio Robustness | User interruption, echo/noise/device handling, clean recovery from voice-state faults. | 2 | DONE |
| CAP-004 | Identity and Presence | Owner/session/presence evidence when identity actually matters. | 3 | ACTIVE |
| CAP-005 | JARVIS Personality | Stable natural identity, language adaptation, truthful capability framing. | 1 | DONE |

### Conversation, Context, and Memory

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-006 | Conversation Intelligence | Follow-ups, references, corrections, topic changes, clarification, goals, planning. | 1 | DONE |
| CAP-007 | Canonical Conversation State | One JARVIS-owned accepted record of live conversation turns/lifecycle. | 1 | DONE |
| CAP-008 | Live Session Context | Active task, goal, project, recent outcomes/issues/pending work. | 4 | PLANNED |
| CAP-009 | Long-Term Personal Memory | Durable useful personal/project facts with provenance and correction. | 4 | PLANNED |
| CAP-010 | Episodic Memory | Recall meaningful past events, sessions, failures, fixes, milestones. | 4 | PLANNED |
| CAP-011 | Semantic Memory | Durable facts/preferences/rules with conflict and supersession handling. | 4 | PLANNED |
| CAP-012 | Reflection and Session Learning | Achievements, issues, decisions, next steps, memory candidates. | 4 | PLANNED |
| CAP-013 | Emotional Interaction Context | Transient interaction signals that improve tone without becoming permanent identity facts. | 4 | PLANNED |

### Knowledge, Research, and Truth

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-014 | Knowledge and Source Routing | Select the right source: model, web, memory, project docs, local files, trusted domain data. | 6 | PLANNED |
| CAP-015 | Current Information and Deep Research | Fresh web/news/current information with sources and provenance. | 6 | PLANNED |
| CAP-016 | Trusted Domain Knowledge | Prefer appropriate authoritative sources for specialist/high-stakes domains. | 6 | PLANNED |
| CAP-017 | Fact Checking and Truthfulness | Verify when required; distinguish known/inferred/stale/unverified claims. | 6 | PLANNED |
| CAP-018 | Local Project and Document Intelligence | Search/reason over approved project files, code, docs, logs, notes, handovers. | 7 | PLANNED |
| CAP-019 | World Awareness | Maintain selected current context across world/user-interest domains. | 14 | PLANNED |
| CAP-020 | Aware-but-Quiet Context | Use passive awareness without unsolicited noise or hidden authority. | 14 | PLANNED |

### Local Computer, Files, Browser, and Devices

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-021 | Computer and System Awareness | Machine time, uptime, health, apps, approved files/devices. | 7 | PLANNED |
| CAP-022 | File and Computer Safe Reads | Bounded read-only access to approved local resources. | 7 | PLANNED |
| CAP-023 | Application Control | Open/focus and later manage approved desktop applications/windows. | 9 | PLANNED |
| CAP-024 | Device Control | Control approved local/network/smart devices and services. | 9 | PLANNED |
| CAP-025 | Browser and Web Interaction | Search/read first; later navigate/forms/downloads/uploads under authority controls. | 10 | PLANNED |
| CAP-026 | File and Document Actions | Create/edit/organize/move/rename and eventually delete with safeguards. | 12 | PLANNED |

### Personal Productivity and Communication

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-027 | Notes | Unified read/create/update/delete note lifecycle. | 8 | PLANNED |
| CAP-028 | Tasks, Reminders, and Scheduling | Explicit future tasks, reminders, recurring checks, routines. | 8 | PLANNED |
| CAP-029 | Calendar | Read availability/events, later approved calendar writes. | 11 | PLANNED |
| CAP-030 | Email and Communication | Search/read, draft/review, then explicitly approved sending. | 11 | PLANNED |
| CAP-031 | Coding and Project Engineering | Repositories, code, tests, diffs, validation, approved development work. | 12 | PLANNED |

### Capability Runtime and Authority

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-032 | Generic Capability Runtime | Discover/select/validate/execute capabilities through one common boundary. | 7 | PLANNED |
| CAP-033 | Extensible Skills and Plugins | Add/register/enable/disable/replace integrations without rebuilding core JARVIS. | 16 | PLANNED |
| CAP-034 | Authority, Permissions, and Consent | Decide whether reads/writes/external/destructive actions are permitted. | 3 | ACTIVE |
| CAP-035 | Graduated Trust | Scale identity/approval friction with consequence. | 3 | ACTIVE |
| CAP-036 | Auditable Action Execution | Proposal, approval, attempt, result, evidence, rollback state. | 3 | ACTIVE |

### Runtime Operations, UI, and Proactivity

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-037 | Runtime Observability | Trace sessions, turns, latency, provider/capability results, authority decisions safely. | 3 | ACTIVE |
| CAP-038 | Health and Diagnostics | Explain degraded audio/network/provider/capability/runtime state and recovery options. | 13 | PLANNED |
| CAP-039 | HUD and Visual Workspace | Present conversation, status, context, world feed, memory, skills, execution, diagnostics. | 13 | PLANNED |
| CAP-040 | Proactive Monitoring | Watch approved topics/conditions and surface meaningful changes. | 15 | PLANNED |
| CAP-041 | Background Work | Explicit scheduled research, recurring summaries, bounded workflows. | 15 | PLANNED |
| CAP-042 | Multi-Capability Workflows | Sequence mature capabilities to achieve goals without an uncontrolled second brain. | 17 | PLANNED |

### Learning, Repair, Resilience, and Development

| ID | Capability | Purpose | Step | Status |
| --- | --- | --- | ---: | --- |
| CAP-043 | Outcome Learning | Learn useful routing/recommendation patterns from confirmed results. | 18 | PLANNED |
| CAP-044 | Capability Gap Detection | Recognize missing abilities instead of hallucinating capability. | 18 | PLANNED |
| CAP-045 | Governed Skill Creation | Propose, generate, validate, test, stage, and approve new capabilities. | 18 | PLANNED |
| CAP-046 | Self-Diagnostics and Repair | Diagnose, propose, sandbox/dry-run, backup, approve, apply, verify, rollback. | 19 | PLANNED |
| CAP-047 | Governed Self-Improvement | Research and propose upgrades without silently rewriting itself or expanding authority. | 20 | PLANNED |
| CAP-048 | Local and Offline Survival | Preserve useful functionality during cloud/network/provider failure where practical. | 5 | PLANNED |
| CAP-049 | Provider and Model Replaceability | Keep speech/model/search/memory/browser providers replaceable. | all | PLANNED |
| CAP-050 | Development Health and Research-First Evolution | Tests, benchmarks, architecture checks, project health, research-first development. | all | ACTIVE |

## Definition of the Final Goal

JARVIS V1 reaches its intended product goal when it behaves as a **Personal Intelligence Runtime**, not merely when all capability rows have implementations.

The integrated end state should satisfy all of the following:

- conversation feels natural enough for daily voice use rather than command prompting;
- JARVIS can remain present across sessions while preserving correct context/memory boundaries;
- personal/project memory is selective, correctable, forgettable, and source-aware;
- JARVIS automatically chooses suitable knowledge/evidence paths without forcing the user to specify tools/providers;
- current and high-risk claims receive appropriate freshness/source verification;
- daily reads/actions across computer, files, apps, devices, browser, notes, calendar, email, and project work feel like parts of one assistant;
- consequential actions remain proportional, visible, auditable, and user-governed;
- proactive/background behaviour is useful, configured, cancellable, and quiet when nothing matters;
- multi-capability workflows use shared authority/execution boundaries rather than creating a second autonomous brain;
- cloud/local/provider failures degrade truthfully and recover without corrupting canonical JARVIS state;
- providers/models/frameworks remain replaceable as the ecosystem changes;
- JARVIS can diagnose and eventually improve itself only through explicit, reversible, evidence-backed governance;
- the user can understand what JARVIS knows, what it inferred, what it did, what failed, and what authority it currently has.

This definition is intentionally product-level. Exact technology should evolve over time while these behavioural outcomes remain stable.

## Documentation Authority

Active documentation stays intentionally small:

- `PRODUCT.md` — permanent product definition and capability catalogue.
- `ROADMAP.md` — implementation sequence and high-level slices.
- `CURRENT_PLAN.md` — active slice and its current stage.
- `CURRENT_ARCHITECTURE.md` — only architecture that actually exists and is accepted.
- `QUALITY_GATES.md` — universal completion/validation rules.
- `LEGACY_REQUIREMENTS_MAP.md` — one-time mapping from old JARVIS intent to V1.
- `research/` — bounded evidence for actual technology decisions.
- `decisions/` — short ADRs for major accepted architectural/technology decisions.

Temporary bugs, blockers, experiments, and deferred ideas should normally use GitHub Issues rather than permanent Markdown logs.
