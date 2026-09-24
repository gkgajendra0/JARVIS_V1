# JARVIS V1 Current Plan

## Current state

The repository is reconciled around one accepted production baseline.

- Steps 0–3: DONE.
- Step 4 memory/context: BOUNDED.
- Step 5 provider resilience: BOUNDED.
- Step 6 current research/truthfulness: BOUNDED.
- Step 7 governed capability runtime: DONE.
- JARVIS Hands / browser / file / device foundations: PARTIAL for later Steps 9/10/12.
- Self-Awareness: accepted foundation.
- Persistent Concurrent Work Orchestration: accepted foundation.
- Deterministic repair framework: accepted foundation.
- Automatic production Self-Repair currently accepted: bounded R2 runtime crash/hang recovery.
- R1 exists in the typed repair vocabulary but has no owner-accepted automatic production policy yet.
- Self-Repair issue #65: CLOSED / COMPLETED for the original R2 acceptance scope.

The authoritative completed/deferred/superseded/rejected ledger is `PROJECT_STATE.md`.

## North-star program architecture

The owner-approved long-term engineering direction is defined by:

`GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`

The target is not merely self-repair. JARVIS should ultimately accept owner intent and autonomously perform the governed engineering needed to investigate failures, repair itself and acquire missing capabilities, while owner authority remains explicit at architecture, secrets/physical-input, acceptance and promotion gates.

The architecture uses one shared governed platform with three trigger loops:

1. deterministic production repair;
2. unknown-problem investigation and repair engineering;
3. owner-requested or later autonomously detected capability evolution.

These loops must reuse canonical WorkItems, Authority, research, development, verification, knowledge, acceptance and promotion boundaries rather than create parallel autonomous systems.

## Active cross-cutting program

The active development slice is now:

**Phase 2 — EngineeringKnowledge Foundation**

Phase 1H is **DONE / OWNER-MACHINE ACCEPTED 2026-09-24**. Its final contract and evidence are recorded in `SELF_REPAIR_PHASE1H_HARDENING.md`.

The accepted hardening covers sustained restart budgets, shared target/action circuit breaking, typed verification/preconditions, immutable repair provenance, versioned engineering persistence, Windows Job Object runtime ownership, local-only production supervision and the bounded Windows outer guardian.

The final owner-machine breaker proof established three verified recent repairs and then blocked the fourth restart with zero new RepairAttempts and zero remaining guardian/supervisor/runtime processes. Automatic logon startup was also observed; temporary Pocket 3 device-enumeration timing remains a non-blocking resilience follow-up.

Do not reopen the accepted Phase-1/R2 or Phase-1H architecture without new concrete evidence.

## Phase 2 definition

Phase 2 implementation is **UNBLOCKED** by completed Phase 1H owner-machine acceptance.

The previous RepairKnowledge research/design remains useful evidence, but Phase 2 should now be implemented as:

**Phase 2 — EngineeringKnowledge Foundation**

`REPAIR` is the first vertical, preserving all RepairKnowledge requirements for provenance, lifecycle, supersession and retrieval, but the underlying storage/schema should be able to represent later `DIAGNOSTIC`, `CAPABILITY`, `INTEGRATION`, `ARCHITECTURE`, `EVALUATION` and `OPERATIONS` engineering knowledge without creating parallel silos.

This is a forward architecture correction before implementation, not a claim that generalized EngineeringKnowledge already exists in production.

## Next cross-cutting sequence

Continue with the phased sequence in `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`:

```text
Phase 2  EngineeringKnowledge
Phase 3  EngineeringChange lifecycle / mission orchestration
Phase 4  Research + Diagnostic Model Router
Phase 5  Secure autonomous engineering substrate
Phase 6  Unknown-incident investigation + source repair
Phase 7  Governed promotion / production verification / rollback
Phase 8  Capability package + registry lifecycle
Phase 9  Owner-requested capability acquisition
Phase 10 Closed-loop engineering learning
Phase 11 Autonomous capability-gap / weakness detection
Phase 12 Shadow improvement + baseline benchmarking
Phase 13 Engineering curriculum + specialist model evaluation
Phase 14 Governed self-evolution
```

Owner-requested capability acquisition intentionally precedes autonomous gap detection: an explicit owner request to acquire a capability must not wait for repeated failures or repeated requests.

## Next numbered product slice

Step 8 — Notes, Tasks, Reminders and Scheduling — remains the next numbered product slice when numbered roadmap work resumes.

The active Self-Repair/Evolution/Autonomous-Engineering program is cross-cutting and does not renumber the product roadmap.

## Open deferred / parallel items

Current open/deferred items are tracked only in `PROJECT_STATE.md`. The important open issues are #19, #44, #45, #46, #63 and #69.

They remain separate unless evidence shows that one directly blocks the active Phase 2 work.

## Documentation ownership

- `PRODUCT.md` — durable product intent and capability catalogue.
- `ROADMAP.md` — numbered sequence and high-level status.
- `CURRENT_ARCHITECTURE.md` — architecture accepted on protected `main`; future design must not be written here as current truth.
- `CURRENT_PLAN.md` — active work only and authoritative current phase.
- `PROJECT_STATE.md` — accepted/deferred/superseded/rejected repository ledger.
- `QUALITY_GATES.md` — universal validation, acceptance and promotion rules.
- `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md` — north-star architecture for autonomous governed engineering.
- `SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md` — specialized repair/evolution program aligned under the north-star plan.
- `SELF_REPAIR_PHASE1H_HARDENING.md` — current hardening gate.
- `PHASE2_ENGINEERING_KNOWLEDGE_RESEARCH.md` — consolidated Phase-2 research findings and technology dispositions.
- `PHASE2_ENGINEERING_KNOWLEDGE_ARCHITECTURE.md` — owner-approved Phase-2 architecture and invariants.
- `PHASE2_ENGINEERING_KNOWLEDGE_IMPLEMENTATION_PLAN.md` — exact implementation sequence, gates and acceptance matrix.

Historical experiments, old acceptance transcripts and superseded research remain available through Git history rather than becoming competing planning truth.

## Immediate next action

**Execute Phase 2 — EngineeringKnowledge Foundation from the owner-approved architecture.**

First reconcile and merge the Phase-2 research/architecture/implementation documentation. Then implement from protected `main` on isolated Phase-2 branches, beginning with the stable EngineeringKnowledge core and REPAIR as the first deterministic vertical.

Preserve the open-ended extension contract: today's repair, investigation and capability-acquisition processes are initial consumers, not a closed enumeration. EngineeringKnowledge remains advisory and can never become executable Authority merely by being stored, retrieved or accepted.