# JARVIS Self-Repair and Self-Evolution Program

## Status

**SPECIALIZED PROGRAM ENTRYPOINT — governed by the autonomous-engineering subsystem under the whole-JARVIS autonomous self-management north star**

Established: 2026-09-23  
Reconciled: 2026-09-24  
North-star hierarchy reconciled: 2026-09-26

This document is the canonical entrypoint for JARVIS Self-Repair and Self-Evolution.

The whole-JARVIS product north star is owned by:

- `AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md`

The long-term autonomous-engineering architecture and engineering phase sequence are owned by:

- `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`

The authoritative current active phase is owned by:

- `CURRENT_PLAN.md`

The detailed pre-reconciliation Self-Repair technical plan is preserved without loss at:

- `SELF_REPAIR_AND_EVOLUTION_TECHNICAL_PLAN.md`

That technical plan remains valuable design evidence for deterministic repair, RepairKnowledge semantics, diagnostics, source repair, curriculum, verification and evolution. Its legacy Phase 2–12 numbering is **superseded wherever it conflicts** with the current cross-cutting sequence below.

No production behavior changes merely because this planning hierarchy changed.

---

## 1. Accepted foundation remains unchanged

### Phase 0 — prerequisites

**DONE**

Self-Awareness, health/evidence, Authority, persistent WorkItems, isolated development worktrees, sandboxed tests, protected-main governance and the deployment/readiness boundary remain accepted prerequisites.

### Phase 1 — deterministic repair framework + bounded R2 runtime Self-Repair

**DONE / OWNER-MACHINE ACCEPTED 2026-09-23**

The accepted foundation remains the deterministic repair framework plus bounded R2 runtime crash/hang recovery with registered policies, durable attempts, budgets/cooldowns, startup readiness, authenticated liveness and verification before recovery.

R1 remains part of the typed risk/action vocabulary but has no owner-accepted automatic production policy yet.

### Phase 1H — Self-Repair foundation hardening

**DONE / OWNER-MACHINE ACCEPTED 2026-09-24**

Phase 1H is accepted. Its hardening contract and owner-machine evidence are recorded in `SELF_REPAIR_PHASE1H_HARDENING.md`.

Accepted hardening includes sustained rolling restart history, one target/action circuit breaker across crash/liveness failures, typed execution preconditions and verifier proof, immutable repair provenance, versioned engineering-DB migrations, Windows Job Object runtime ownership, a local-only production supervisor, and a bounded Windows outer guardian.

Owner-machine acceptance proved crash/hang recovery, launcher/interpreter/supervisor failure handling, no accepted duplicate/orphan runtime, shared mixed-fault restart history, and a clean 3-of-3 rolling budget followed by a fourth crash that created zero new RepairAttempts and left zero guardian/supervisor/runtime processes.

Automatic logon startup was also observed. A temporarily unavailable configured Pocket 3 microphone correctly caused fail-closed preflight; once Windows enumerated the device, the same production path started normally. Bounded hardware-readiness retry is a non-blocking future resilience improvement.

Do not reopen the accepted Phase-1/R2 or Phase-1H architecture without new concrete evidence.

---

## 2. Canonical forward sequence

With Phases 2, 3 and 4 owner-machine accepted, the cross-cutting program proceeds as follows:

```text
Phase 2   EngineeringKnowledge Foundation — DONE / OWNER-MACHINE ACCEPTED 2026-09-25
Phase 3   EngineeringChange Lifecycle / Mission Orchestration — DONE / OWNER-MACHINE ACCEPTED 2026-09-25
Phase 4   Research + Diagnostic Model Router — DONE / OWNER-MACHINE ACCEPTED 2026-09-26
Phase 5   Secure Autonomous Engineering Substrate — ACTIVE / IMPLEMENTATION; 5A–5F merged, 5G underway
Phase 6   Unknown-Incident Investigation + Source Repair
Phase 7   Governed Promotion / Production Verification / Rollback
Phase 8   Capability Package + Registry Lifecycle
Phase 9   Owner-Requested Capability Acquisition
Phase 10  Closed-Loop Engineering Learning
Phase 10A Autonomous Operations Control Plane — whole-JARVIS integration point
Phase 11  Autonomous Capability-Gap / Weakness Detection
Phase 12  Shadow Improvement + Baseline Benchmarking
Phase 13  Engineering Curriculum + Specialist Model Evaluation
Phase 14  Governed Self-Evolution
```

The full requirements, objects, entry/exit gates and permanent governance invariants for these phases are defined in `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`.

Phase-4 implementation details are preserved in `PHASE4_MODEL_ROUTER_RESEARCH.md`, `PHASE4_MODEL_ROUTER_ARCHITECTURE.md`, and `PHASE4_MODEL_ROUTER_IMPLEMENTATION_PLAN.md`; final owner-machine evidence is in `PHASE4_MODEL_ROUTER_ACCEPTANCE_2026-09-26.md`. Jev remains deferred to a separate later optimization experiment.

---

## 3. Mapping from the original Self-Repair plan

The preserved technical plan used a narrower repair-centric sequence. Its technical content maps forward as follows:

| Original technical concept | Canonical forward home |
| --- | --- |
| RepairKnowledge | Phase 2 `EngineeringKnowledge`, `REPAIR` vertical |
| DiagnosticModelRouter | Phase 4 |
| AI-assisted diagnostics | Phase 4 / Phase 6 |
| Sandboxed source repair | Phase 6 |
| Governed deployment / rollback | Phase 7 |
| Closed-loop repair learning | Phase 10 |
| Repair Curriculum | Phase 13 |
| Specialist repair-model evaluation | Phase 13 |
| Capability-gap / weakness detection | Phase 11 |
| Shadow self-improvement | Phase 12 |
| Governed self-evolution | Phase 14 |

The original repair-specific semantics are not discarded. They are generalized under shared engineering primitives so repair, unknown investigation and new-capability engineering do not create parallel autonomous systems.

---

## 4. Self-Repair remains one of three governed loops

### Loop A — deterministic production repair

Known accepted low-risk faults may recover through registered deterministic policy, bounded execution and independent verification.

### Loop B — unknown-problem investigation and repair engineering

Unknown faults become durable evidence-driven investigation and, when justified, isolated source-repair work.

### Loop C — capability evolution

Direct owner requests for missing capabilities, and later autonomously detected gaps, use the same governed engineering substrate rather than a separate skill-building brain.

Self-Repair therefore remains a first-class specialization, but it no longer owns the complete JARVIS engineering north star by itself.

---

## 5. Governance remains unchanged

The permanent engineering lifecycle is:

```text
research thoroughly
-> architecture
-> owner approval
-> isolated implementation / PR
-> CI
-> owner-machine acceptance where required
-> documentation reconciliation
-> explicit owner merge approval
-> protected-main merge
```

JARVIS may increasingly perform the research, coding, debugging, testing and candidate preparation inside that lifecycle. It does not gain permission to self-authorize, weaken protected controls, expand credentials, merge protected main or silently deploy.

For detailed historical design rationale and repair-specific schemas, use `SELF_REPAIR_AND_EVOLUTION_TECHNICAL_PLAN.md`. For current status, use `CURRENT_PLAN.md`. For the integrated future architecture and phase sequence, use `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`.
