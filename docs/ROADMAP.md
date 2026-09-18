# JARVIS V1 Roadmap

This roadmap owns **sequence only**. It does not select technology, define current architecture, or authorize implementation. `CURRENT_PLAN.md` owns the active slice.

| Step | Product slice | Major capabilities | Status |
| ---: | --- | --- | --- |
| 0 | Clean Foundation | lifecycle, package/config/logging/tests | DONE |
| 1 | Natural Conversational Core | CAP-001, CAP-005, CAP-006, CAP-007 | DONE |
| 2 | Wake, Voice Session, Audio Robustness | CAP-002, CAP-003 | DONE |
| 2.5 | Vision Sensor & Active Target Tracking Foundation | camera/PTZ, detection/tracking, following | DONE |
| 3 | Identity, Graduated Trust, Authority, Observability | CAP-004, CAP-034–037 | DONE; spoken actor binding deferred |
| 4 | Live Context and Personal Memory | CAP-008–013 | DONE (BOUNDED); strict 4.5D + automatic 4.5E deferred |
| 5 | Local/Offline Survival and Provider Resilience | CAP-048, CAP-049 | DONE (BOUNDED); full offline conversation deferred |
| 6 | Knowledge, Current Research, Truthfulness | CAP-014–017 | DONE (BOUNDED) |
| 7 | Governed Capability Runtime + Safe Local Reads | CAP-018, CAP-021, CAP-022, CAP-032 | DONE — OWNER ACCEPTED 2026-09-09 |
| 8 | Notes, Tasks, Reminders, Scheduling | CAP-027, CAP-028 | QUEUED AFTER CONCURRENT-WORK FOUNDATION |
| 9 | Computer, Application, Device Control | CAP-023, CAP-024 | PLANNED — PARTIAL HANDS FOUNDATION EXISTS |
| 10 | Browser and Web Interaction | CAP-025 | PLANNED — PARTIAL PLAYWRIGHT FOUNDATION EXISTS |
| 11 | Calendar, Email, External Communication | CAP-029, CAP-030 | PLANNED |
| 12 | Documents, File Writes, Coding/Project Operations | CAP-026, CAP-031 | PLANNED — PARTIAL HANDS FOUNDATION EXISTS |
| 13 | HUD, Visual Workspace, Health, Diagnostics | CAP-038, CAP-039 | PLANNED |
| 14 | Passive World Awareness | CAP-019, CAP-020 | PLANNED |
| 15 | Proactive Monitoring and Event-Driven Background Work | CAP-040, CAP-041 | PLANNED — REUSES CONCURRENT-WORK FOUNDATION |
| 16 | Extensibility and Plugin/Skill Lifecycle | CAP-033 | PLANNED |
| 17 | Daily Assistant and Multi-Capability Workflows | CAP-042 | PLANNED |
| 18 | Learning, Gap Detection, Governed Skill Creation | CAP-043–045 | PLANNED |
| 19 | Governed Self-Diagnostics and Repair | CAP-046 | PLANNED |
| 20 | Governed Self-Improvement and Advanced Autonomy | CAP-047 | PLANNED |

## Accepted interludes that do not renumber the roadmap

### Step 2.5 visual interlude

The Pocket 3 visual sensor/PTZ foundation was deliberately inserted before Step 3 so identity/awareness work had a real visual substrate.

### Development supervisor

`jarvis-dev` is accepted development infrastructure, not a product step. It can detect a protected-main update, ask the owner, fast-forward/restart, verify readiness and restore the last-known-good revision on failed readiness. Normal `jarvis-voice` does not gain autonomous Git/self-update authority from this.

### Self-Awareness Foundation

PR #41 is owner-accepted and merged to protected `main` (2026-09-18) as a bounded read-only foundation: hierarchical whole-JARVIS Self Model, deterministic health/dependency/blast-radius reasoning, redacted local operational evidence, incident engineering memory and typed governed Self-Awareness reads. Autonomous diagnosis/repair remains later work.

Detailed acceptance: `docs/research/SELF_AWARENESS_ACCEPTANCE_2026-09-18.md`.

### Persistent Concurrent Work Orchestration foundation

Owner-approved sequence change on 2026-09-18: durable concurrent work orchestration is pulled forward as the **architecture foundation before Step 8 implementation**. This does not renumber the roadmap.

Draft PR #55 now contains the implementation: provider-neutral durable WorkItems, explicit lifecycle/state, DBOS restart recovery, single-brain live-voice priority, priorities/dependencies/resource leases, pause/resume/cancel/owner-input semantics, persisted deferred delivery, bounded research work, and isolated sandboxed development work. It remains **not production-accepted** until exact-head automated validation and the real owner-machine acceptance matrix pass.

Step 8 tasks/reminders/scheduling and later Step 15 proactive/event-driven work must reuse this foundation rather than create separate task/background systems.

### Post-Step-7 production integration interlude

After Step 7, owner-approved work intentionally pulled forward **bounded foundations** needed for real daily usability and stability without declaring later roadmap slices complete:

- **JARVIS Hands (PR #30):** native Windows semantics, Microsoft `winapp` UI Automation, Playwright browser execution, bounded file/document/device/Git operations, multilingual grounding, fast-path execution and window-scoped visual Computer Use under canonical authority.
- **Pocket 3 native OWNER tracking (PRs #33–#35, #38):** native DJI targeting/evidence, reacquisition, recenter, adaptive perception and resilient session recovery.
- **Runtime performance (PR #36):** selective accepted OPT-1 scheduling/wake/profiling work.
- **Runtime stabilization (PR #38):** canonical USER-generation cleanup, silent-audio recovery, immediate standby and Hands/Pocket reliability corrections.

These foundations are current production architecture. Steps 9, 10 and 12 remain roadmap slices because their full product requirements and completion boundaries have not yet been executed as formal steps.

Detailed evidence: `docs/research/POST_STEP_7_INTEGRATION_ACCEPTANCE.md`.

## Bounded/deferred rule

A step may close bounded when an independently useful subset is accepted and continuing would require weakening an important safety/reliability boundary or building speculative scope.

Current major deferrals:

- Step 3 turn-specific spoken actor binding and general biometric/voice-derived T2 promotion;
- strict independent Step-4 semantic-memory verifier;
- Phase-4.5E automatic memory injection;
- full Step-5 offline conversation/provider failover;
- long-running/background Step-6 research until the new concurrent-work foundation is accepted;
- later proactive monitoring/plugin/self-repair/self-improvement capabilities.

A deferred capability is not a hidden failure and must not be represented as working.

## Superseded/rejected work rule

Historical branches/PRs remain evidence but are not automatically integration candidates.

Current notable dispositions:

- PR #13 superseded by Step-3 PR #15;
- PR #27 superseded by accepted Step-7 PR #28;
- PRs #31/#32 superseded by selective recovery in PR #36 plus later Pocket/stability PRs;
- PR #37 retained only through its consolidated fix inside PR #38;
- the automatic Windows workstation-lock experiment was rejected and explicitly excluded from production recovery.

Open PR #18 is historical/unmerged Step-3 hardening work. Its spoken-actor-binding problem remains valid future work, but that branch is not the current production source of truth and must not be merged wholesale into modern main.

## Universal step lifecycle

```text
REQUIREMENTS
-> RESEARCH
-> TECHNOLOGY DECISION
-> ARCHITECTURE
-> HUMAN APPROVAL
-> IMPLEMENTATION
-> AUTOMATED VALIDATION
-> REAL HUMAN USE
-> CORRECTION IF NEEDED
-> HUMAN ACCEPTANCE
-> DOCUMENTATION RECONCILIATION
-> PROTECTED-MAIN MERGE
-> DONE
```

Research for future slices is intentionally deferred until that slice becomes active unless a demonstrated blocker requires an owner-approved interlude.

## Strategic milestones

1. Conversational Presence — Steps 1–2.
2. Perception Foundation — Step 2.5.
3. Governed Personal Foundation — Steps 3–5.
4. Source-Aware Intelligence — Steps 6–7.
5. Reliable Daily Actions — Steps 8–12.
6. Visible and Aware Assistant — Steps 13–15.
7. Extensible Daily Assistant — Steps 16–17.
8. Governed Learning and Improvement — Steps 18–20.
9. Personal Intelligence Runtime — integrated end state.

## Current next step

Persistent Concurrent Work Orchestration (issue #53) is the active **requirements / research** foundation. It must reuse conversation, lifecycle, Authority, capability runtime, Hands, Self-Awareness and observability while defining durable work truth, bounded concurrency, dependencies/resources, restart recovery, progress/status and non-blocking result delivery.

After that foundation is accepted, Step 8 begins formal tasks/reminders/scheduling requirements and implementation on top of the same work model.

## Roadmap change rule

A future idea may be added when it represents real product intent, but it does not automatically interrupt the active step. Sequence changes require deliberate planning and owner approval.
