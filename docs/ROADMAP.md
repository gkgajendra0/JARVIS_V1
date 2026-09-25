# JARVIS V1 Roadmap

This roadmap owns **numbered product sequence only**. It does not select technology, define current architecture, or authorize implementation. `CURRENT_PLAN.md` owns the active slice. `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md` owns the long-term cross-cutting architecture for autonomous governed engineering.

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
| 8 | Notes, Tasks, Reminders, Scheduling | CAP-027, CAP-028 | NEXT NUMBERED PRODUCT SLICE — currently paused behind owner-approved cross-cutting program |
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
| 19 | Governed Self-Diagnostics and Repair | CAP-046 | PARTIAL — deterministic R1/R2 + Phase 1H + Phase 2 EngineeringKnowledge accepted; Phase 3 EngineeringChange active |
| 20 | Governed Self-Improvement and Advanced Autonomy | CAP-047 | PLANNED |

## Accepted interludes that do not renumber the roadmap

### Step 2.5 visual interlude

The Pocket 3 visual sensor/PTZ foundation was deliberately inserted before Step 3 so identity/awareness work had a real visual substrate.

### Development supervisor

`jarvis-dev` is accepted development infrastructure, not a product step. It can detect a protected-main update, ask the owner, fast-forward/restart, verify readiness and restore the last-known-good revision on failed readiness. Normal `jarvis-voice` does not gain autonomous Git/self-update authority from this.

### Self-Awareness Foundation

PR #41 is owner-accepted and merged to protected `main` (2026-09-18) as a bounded read-only foundation: hierarchical whole-JARVIS Self Model, deterministic health/dependency/blast-radius reasoning, redacted local operational evidence, incident engineering memory and typed governed Self-Awareness reads. Autonomous diagnosis/repair remains later work.

Accepted status and merge history are summarized in `PROJECT_STATE.md`.

### Persistent Concurrent Work Orchestration foundation

Owner-approved sequence change on 2026-09-18: durable concurrent work orchestration was pulled forward as an architecture foundation before Step 8 implementation. This does not renumber the roadmap.

PR #55 contains the owner-accepted implementation: provider-neutral durable WorkItems, explicit lifecycle/state, DBOS restart recovery, single-brain live-voice priority, priorities/dependencies/resource leases, pause/resume/cancel/owner-input semantics, persisted deferred delivery, structured progress/ETA facts, bounded research work, and isolated sandboxed development work. Owner-machine acceptance passed on 2026-09-20 and the owner approved protected-main merge.

Step 8 tasks/reminders/scheduling, later Step 15 proactive/event-driven work and the autonomous-engineering program must reuse this foundation rather than create separate task/background systems.

### Governed autonomous engineering / Self-Repair / Self-Evolution cross-cutting program

The 2026-09-20 Self-Repair Foundation interlude completed on 2026-09-23 with owner-machine acceptance of the deterministic repair framework and bounded R2 runtime crash/hang recovery. Issue #65 is closed.

Accepted early Step-19 foundation includes deterministic repair contracts, durable RepairAttempts, external crash/hang supervision, restart budgets/cooldowns, startup readiness, authenticated liveness stabilization, provider-degradation separation and Windows runtime-process-tree handling.

A 2026-09-24 architecture review confirmed that Phase 1/R2 remains the correct foundation for the longer JARVIS goal. The program is now explicitly governed by `docs/GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`: JARVIS should eventually accept owner intent and autonomously perform the required governed research, engineering, testing, diagnosis and candidate preparation while the owner retains architecture, secret/physical-input, acceptance and protected-main promotion authority.

The shared program has three trigger loops:

1. deterministic production repair;
2. unknown-problem investigation and repair engineering;
3. owner-requested or later autonomously detected capability evolution.

The current exact sequence is:

```text
Phase 1   deterministic repair + accepted R2 recovery — DONE
Phase 1H  foundation hardening — DONE / OWNER-MACHINE ACCEPTED 2026-09-24
Phase 2   EngineeringKnowledge — DONE / OWNER-MACHINE ACCEPTED 2026-09-25
Phase 3   EngineeringChange lifecycle / mission orchestration — ACTIVE / NEXT
Phase 4   Research + Diagnostic Model Router
Phase 5   Secure autonomous engineering substrate
Phase 6   Unknown-incident investigation + source repair
Phase 7   Governed promotion / production verification / rollback
Phase 8   Capability package + registry lifecycle
Phase 9   Owner-requested capability acquisition
Phase 10  Closed-loop engineering learning
Phase 11  Autonomous capability-gap / weakness detection
Phase 12  Shadow improvement + baseline benchmarking
Phase 13  Engineering curriculum + specialist model evaluation
Phase 14  Governed self-evolution
```

Phase 2 generalized the earlier RepairKnowledge design into shared `EngineeringKnowledge`, with `REPAIR` as the first implemented vertical. Owner-machine acceptance passed on 2026-09-25, including R2-independence, real repair projection/promotion/retrieval, poisoning/secret gates, future-facet extensibility, and lexical/hybrid qrel safety.

Phase 3 is now the active cross-cutting slice and will add the durable `EngineeringChange` mission lifecycle above existing WorkItems.

Owner-requested capability acquisition intentionally comes before autonomous gap detection. If the owner explicitly says "get this capability", JARVIS should not need repeated failures or repeated requests before it can run the governed acquisition lifecycle.

This continuation does not renumber Steps 8–20. It builds cross-cutting foundations that later Steps 16, 18, 19 and 20 consume.

The program never inherits automatic permission to weaken Authority, CI/rulesets, sandbox/evaluator policy, protected-main governance, credentials or permissions.

### Post-Step-7 production integration interlude

After Step 7, owner-approved work intentionally pulled forward bounded foundations needed for real daily usability and stability without declaring later roadmap slices complete:

- **JARVIS Hands (PR #30):** native Windows semantics, Microsoft `winapp` UI Automation, Playwright browser execution, bounded file/document/device/Git operations, multilingual grounding, fast-path execution and window-scoped visual Computer Use under canonical authority.
- **Pocket 3 native OWNER tracking (PRs #33–#35, #38):** native DJI targeting/evidence, reacquisition, recenter, adaptive perception and resilient session recovery.
- **Runtime performance (PR #36):** selective accepted OPT-1 scheduling/wake/profiling work.
- **Runtime stabilization (PR #38):** canonical USER-generation cleanup, silent-audio recovery, immediate standby and Hands/Pocket reliability corrections.

These foundations are current production architecture. Steps 9, 10 and 12 remain roadmap slices because their full product requirements and completion boundaries have not yet been executed as formal steps.

Accepted production status and superseded/rejected history are summarized in `PROJECT_STATE.md`.

## Relationship between numbered product work and autonomous engineering

The numbered roadmap defines what JARVIS can do for the owner. The autonomous-engineering program defines how JARVIS can eventually repair, extend and improve those abilities itself under governance.

Key relationships:

- Step 9 defines stable device-control semantics that future device adapters reuse.
- Step 12 matures coding/project-engineering capability rather than granting arbitrary shell authority.
- Step 16 defines extensible skill/plugin lifecycle and registration.
- Step 18 uses EngineeringKnowledge, capability-gap detection and governed skill creation.
- Step 19 uses deterministic repair plus unknown-problem investigation/source repair.
- Step 20 integrates learning, benchmarking and governed self-evolution.

The existence of a future autonomous-engineering phase does not mark the corresponding numbered product step complete.

## Bounded/deferred rule

A step may close bounded when an independently useful subset is accepted and continuing would require weakening an important safety/reliability boundary or building speculative scope.

Current major deferrals include:

- Step 3 turn-specific spoken actor binding and general biometric/voice-derived T2 promotion;
- strict independent Step-4 semantic-memory verifier;
- Phase-4.5E automatic memory injection;
- full Step-5 offline conversation/provider failover;
- later proactive monitoring/plugin capabilities;
- AI-assisted/full Step-19 repair and Step-20 self-improvement beyond the accepted deterministic repair/R2 foundation.

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
-> OWNER APPROVAL
-> ISOLATED IMPLEMENTATION
-> AUTOMATED VALIDATION
-> REAL HUMAN / HARDWARE ACCEPTANCE WHERE REQUIRED
-> CORRECTION IF NEEDED
-> OWNER ACCEPTANCE
-> DOCUMENTATION RECONCILIATION
-> PR / EXACT-HEAD REQUIRED CHECKS
-> EXPLICIT MERGE APPROVAL
-> PROTECTED-MAIN MERGE
-> DONE
```

The same lifecycle applies to JARVIS-generated engineering candidates; autonomy does not remove governance gates.

## Strategic milestones

1. Conversational Presence — Steps 1–2.
2. Perception Foundation — Step 2.5.
3. Governed Personal Foundation — Steps 3–5.
4. Source-Aware Intelligence — Steps 6–7.
5. Reliable Daily Actions — Steps 8–12.
6. Visible and Aware Assistant — Steps 13–15.
7. Extensible Daily Assistant — Steps 16–17.
8. Governed Learning and Improvement — Steps 18–20 plus the cross-cutting autonomous-engineering program.
9. Personal Intelligence Runtime — integrated end state where owner intent can drive governed autonomous engineering.

## Current next step

Persistent Concurrent Work Orchestration and the deterministic repair/R2 foundation are owner accepted.

**Current active cross-cutting work is Phase 3 — EngineeringChange Lifecycle / Mission Orchestration.**

Phase 2 EngineeringKnowledge is DONE / OWNER-MACHINE ACCEPTED 2026-09-25. Its accepted foundation is now available to Phase 3 and later autonomous-engineering phases.

Step 8 remains the next numbered product slice when numbered roadmap work resumes.

## Roadmap change rule

A future idea may be added when it represents real product intent, but it does not automatically interrupt the active step. Sequence changes require deliberate planning and owner approval. `CURRENT_PLAN.md` wins if any roadmap status summary becomes stale.