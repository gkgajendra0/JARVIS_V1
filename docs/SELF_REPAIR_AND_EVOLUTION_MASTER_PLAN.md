# JARVIS Self-Repair and Self-Evolution Program

## Status

**SPECIALIZED PROGRAM ENTRYPOINT — governed by the JARVIS autonomous-engineering north star**

Established: 2026-09-23  
Reconciled: 2026-09-24

This document is the canonical entrypoint for JARVIS Self-Repair and Self-Evolution.

The long-term cross-cutting architecture and future phase sequence are owned by:

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

**ACTIVE**

Phase 1H remains the active acceptance gate. Its detailed contract is `SELF_REPAIR_PHASE1H_HARDENING.md`.

Do not reopen the accepted Phase-1/R2 architecture merely because later program scope is broader. Runtime changes require concrete hardening evidence.

---

## 2. Canonical forward sequence

After Phase 1H owner-machine acceptance, the cross-cutting program proceeds as follows:

```text
Phase 2   EngineeringKnowledge Foundation
Phase 3   EngineeringChange Lifecycle / Mission Orchestration
Phase 4   Research + Diagnostic Model Router
Phase 5   Secure Autonomous Engineering Substrate
Phase 6   Unknown-Incident Investigation + Source Repair
Phase 7   Governed Promotion / Production Verification / Rollback
Phase 8   Capability Package + Registry Lifecycle
Phase 9   Owner-Requested Capability Acquisition
Phase 10  Closed-Loop Engineering Learning
Phase 11  Autonomous Capability-Gap / Weakness Detection
Phase 12  Shadow Improvement + Baseline Benchmarking
Phase 13  Engineering Curriculum + Specialist Model Evaluation
Phase 14  Governed Self-Evolution
```

The full requirements, objects, entry/exit gates and permanent governance invariants for these phases are defined in `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`.

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
