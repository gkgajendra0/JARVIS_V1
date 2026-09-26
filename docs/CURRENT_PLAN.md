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

The owner-approved **whole-JARVIS product north star** is defined by:

`AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md`

JARVIS is intended to become a governed autonomous self-managing personal intelligence runtime: the owner defines intent, priorities, boundaries, budgets and protected decisions; JARVIS increasingly understands desired versus actual state, determines what work should exist, operates/manages itself, repairs failures, optimizes, protects, acquires capabilities and learns while remaining inside owner authority.

The permanent rule is: **JARVIS may manage JARVIS, but JARVIS must never become its own source of authority.**

The governed engineering subsystem is defined by:

`GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`

It remains the mechanism JARVIS uses when self-management requires research, diagnosis, source repair, capability acquisition or improvement. Its architecture uses one shared governed platform with three trigger loops:

1. deterministic production repair;
2. unknown-problem investigation and repair engineering;
3. owner-requested or later autonomously detected capability evolution.

These loops must reuse canonical WorkItems, Authority, research, development, verification, knowledge, acceptance and promotion boundaries rather than create parallel autonomous systems.

## Active cross-cutting program

The active development slice is now:

**Phase 6 — Unknown-Incident Investigation + Source Repair**

Phase 5 Secure Autonomous Engineering Substrate is **DONE / OWNER-MACHINE ACCEPTED 2026-09-27**. Its final evidence is recorded in `PHASE5_SECURE_ENGINEERING_SUBSTRATE_ACCEPTANCE_2026-09-27.md`. PR #133 merged to protected main at `78f25fb192b926ee30a028cfc02c829e1197cc9e`.

Phase-6 research is complete and the architecture/implementation plan is proposed on the dedicated design branch. Canonical review documents are:

- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_RESEARCH.md`;
- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_ARCHITECTURE.md`;
- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_IMPLEMENTATION_PLAN.md`.

The proposed design composes the accepted Incident, EngineeringKnowledge, EngineeringChange, WorkItem/DBOS, Model Router, Phase-5 sandbox/dependency/provenance and isolated DEVELOPMENT primitives. It adds bounded read-only diagnostics, typed diagnosis evidence, incident-to-change admission, exact architecture-gated development handoff and protected-surface candidate verification. It deliberately does not embed OpenHands, SWE-agent or another control plane.

**Current state: RESEARCH COMPLETE / ARCHITECTURE PROPOSED — WAITING OWNER APPROVAL.** Runtime/source implementation must not begin until the Phase-6 architecture is explicitly owner-approved.

Phase 3 EngineeringChange Lifecycle / Mission Orchestration is **DONE / OWNER-MACHINE ACCEPTED 2026-09-25**. Its final evidence is recorded in `PHASE3_ENGINEERING_CHANGE_ACCEPTANCE_2026-09-25.md`. The live run proved canonical idempotency, owner-input resume, Exa research, PostgreSQL DBOS identity and full Windows cold-boot recovery. Persistent Gemini HTTP 429 provider pressure prevented the same run from naturally reaching downstream architecture/Windows-Hello/development gates; the owner accepted that external limitation without weakening any gate.

Phase 1H is **DONE / OWNER-MACHINE ACCEPTED 2026-09-24**. Its final contract and evidence are recorded in `SELF_REPAIR_PHASE1H_HARDENING.md`.

Phase 2 EngineeringKnowledge is **DONE / OWNER-MACHINE ACCEPTED 2026-09-25** on protected-main baseline `3c5a2f732db171a9ad61a4531fecd66aed0d27c4`. Its final integrated evidence is recorded in `PHASE2_ENGINEERING_KNOWLEDGE_ACCEPTANCE_2026-09-25.md`.

The accepted Phase-2 scope includes immutable EngineeringKnowledge revisions, registered facets, deterministic REPAIR projection, lifecycle/promotion, provenance, applicability, grounded local hybrid retrieval, poisoning/secret controls and an open-ended extension model.

Do not reopen accepted Phase-1/R2, Phase-1H or Phase-2 architecture without new concrete evidence.

## Phase 2 accepted result

Phase 2 EngineeringKnowledge is now implemented and accepted.

Accepted behavior includes:

- canonical engineering SQLite persistence with immutable revisions;
- registered versioned facets with fail-closed unknown semantics;
- deterministic REPAIR projection from verified RepairAttempts;
- lifecycle/promotion, provenance, applicability and integrity contracts;
- exact + FTS5 + pinned local Qwen retrieval with grounded dense reranking and RRF;
- poisoning/secret admission controls and sensitivity filtering;
- JARVIS-specific qrel evaluation and owner-machine benchmark evidence;
- open-ended future facet/process extensibility without parallel knowledge or authority systems.

EngineeringKnowledge remains advisory and cannot create execution authority.

The final owner-machine negative control proved deterministic R2 recovery before EngineeringKnowledge existed for the new repair.

## Next cross-cutting sequence

Continue with the phased sequence in `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`:

```text
Phase 2  EngineeringKnowledge — DONE / OWNER-MACHINE ACCEPTED 2026-09-25
Phase 3  EngineeringChange lifecycle / mission orchestration — DONE / OWNER-MACHINE ACCEPTED 2026-09-25
Phase 4  Research + Diagnostic Model Router — DONE / OWNER-MACHINE ACCEPTED 2026-09-26
Phase 5  Secure autonomous engineering substrate — DONE / OWNER-MACHINE ACCEPTED 2026-09-27
Phase 6  Unknown-incident investigation + source repair — ACTIVE / ARCHITECTURE PROPOSED; WAITING OWNER APPROVAL
Phase 7  Governed promotion / production verification / rollback
Phase 8  Capability package + registry lifecycle
Phase 9  Owner-requested capability acquisition
Phase 10 Closed-loop engineering learning
Phase 10A Autonomous Operations Control Plane — approved future integration point; not active during Phase 5
Phase 11 Autonomous capability-gap / weakness detection
Phase 12 Shadow improvement + baseline benchmarking
Phase 13 Engineering curriculum + specialist model evaluation
Phase 14 Governed self-evolution
```

Owner-requested capability acquisition intentionally precedes autonomous gap detection: an explicit owner request to acquire a capability must not wait for repeated failures or repeated requests.

The owner-approved 2026-09-26 sequencing clarification inserts Phase 10A before Phase 11. Phase 10A will add the Objective/DesiredState model, whole-JARVIS SystemState reconciliation, evidence-backed autonomous work creation, portfolio prioritization, owner-attention handling and autonomy evaluation. It does not interrupt or broaden authority during active Phase 6.

## Next numbered product slice

Step 8 — Notes, Tasks, Reminders and Scheduling — remains the next numbered product slice when numbered roadmap work resumes.

The active Self-Repair/Evolution/Autonomous-Engineering program is cross-cutting and does not renumber the product roadmap.

## Open deferred / parallel items

Current open/deferred items are tracked only in `PROJECT_STATE.md`. The important open issues are #19, #44, #45, #46, #63 and #69.

They remain separate unless evidence shows that one directly blocks the active Phase 6 work.

## Documentation ownership

- `PRODUCT.md` — durable product intent and capability catalogue.
- `ROADMAP.md` — numbered sequence and high-level status.
- `CURRENT_ARCHITECTURE.md` — architecture accepted on protected `main`; future design must not be written here as current truth.
- `CURRENT_PLAN.md` — active work only and authoritative current phase.
- `PROJECT_STATE.md` — accepted/deferred/superseded/rejected repository ledger.
- `QUALITY_GATES.md` — universal validation, acceptance and promotion rules.
- `AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md` — authoritative whole-JARVIS product/operating north star.
- `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md` — autonomous-engineering subsystem under that north star.
- `SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md` — specialized repair/evolution program under the engineering subsystem.
- `SELF_REPAIR_PHASE1H_HARDENING.md` — current hardening gate.
- `PHASE2_ENGINEERING_KNOWLEDGE_RESEARCH.md` — consolidated Phase-2 research findings and technology dispositions.
- `PHASE2_ENGINEERING_KNOWLEDGE_ARCHITECTURE.md` — owner-approved Phase-2 architecture and invariants.
- `PHASE2_ENGINEERING_KNOWLEDGE_IMPLEMENTATION_PLAN.md` — completed Phase-2 implementation sequence, gates and acceptance matrix.
- `PHASE2_ENGINEERING_KNOWLEDGE_ACCEPTANCE_2026-09-25.md` — canonical Phase-2 owner-machine acceptance record.
- `PHASE3_ENGINEERING_CHANGE_ACCEPTANCE_2026-09-25.md` — canonical Phase-3 owner-machine acceptance record.
- `PHASE4_MODEL_ROUTER_RESEARCH.md` — Phase-4 technology research and dispositions.
- `PHASE4_MODEL_ROUTER_ARCHITECTURE.md` — owner-approved stable Phase-4 routing contracts/invariants.
- `PHASE4_MODEL_ROUTER_IMPLEMENTATION_PLAN.md` — completed implementation sequence and acceptance gates.
- `PHASE4_MODEL_ROUTER_ACCEPTANCE_2026-09-26.md` — canonical Phase-4 owner-machine acceptance record.
- `PHASE5_SECURE_ENGINEERING_SUBSTRATE_ACCEPTANCE_2026-09-27.md` — canonical Phase-5 owner-machine acceptance record.
- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_RESEARCH.md` — Phase-6 technology/repository research and framework dispositions.
- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_ARCHITECTURE.md` — proposed Phase-6 stable contracts/invariants, pending owner approval.
- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_IMPLEMENTATION_PLAN.md` — proposed Phase-6 implementation slices and acceptance matrix.

Historical experiments, old acceptance transcripts and superseded research remain available through Git history rather than becoming competing planning truth.

## Immediate next action

**Owner review/approval of the proposed Phase-6 Unknown-Incident Investigation + Source Repair architecture.** After explicit approval, create the isolated Phase-6 implementation branch/PR and begin Phase 6A contracts + process registration. Do not implement runtime/source behavior before that architecture gate.
