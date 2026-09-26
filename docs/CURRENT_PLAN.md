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

**Phase 5 — Secure Autonomous Engineering Substrate**

Phase 4 Research + Diagnostic Model Router is **DONE / OWNER-MACHINE ACCEPTED 2026-09-26**. Its final evidence is recorded in `PHASE4_MODEL_ROUTER_ACCEPTANCE_2026-09-26.md`.

Phase-5 technology research is now complete and a concrete architecture/implementation plan is proposed. Canonical review documents are:

- `PHASE5_SECURE_ENGINEERING_SUBSTRATE_RESEARCH.md`;
- `PHASE5_SECURE_ENGINEERING_SUBSTRATE_ARCHITECTURE.md`;
- `PHASE5_SECURE_ENGINEERING_SUBSTRATE_IMPLEMENTATION_PLAN.md`.

The proposed design adds deterministic DependencyBroker, SecretBroker, declarative CapabilityManifest, bounded discovery, JARVIS-owned SandboxProfiles, provenance and hardware-acceptance evidence while preserving EngineeringChange and Authority as the only governance boundary.

**Current gate: OWNER ARCHITECTURE APPROVAL REQUIRED.** Do not implement Phase 5 until the architecture is explicitly approved.

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
Phase 5  Secure autonomous engineering substrate — ACTIVE / ARCHITECTURE PROPOSED; OWNER APPROVAL REQUIRED
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

They remain separate unless evidence shows that one directly blocks the active Phase 4 work.

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
- `PHASE2_ENGINEERING_KNOWLEDGE_IMPLEMENTATION_PLAN.md` — completed Phase-2 implementation sequence, gates and acceptance matrix.
- `PHASE2_ENGINEERING_KNOWLEDGE_ACCEPTANCE_2026-09-25.md` — canonical Phase-2 owner-machine acceptance record.
- `PHASE3_ENGINEERING_CHANGE_ACCEPTANCE_2026-09-25.md` — canonical Phase-3 owner-machine acceptance record.
- `PHASE4_MODEL_ROUTER_RESEARCH.md` — Phase-4 technology research and dispositions.
- `PHASE4_MODEL_ROUTER_ARCHITECTURE.md` — owner-approved stable Phase-4 routing contracts/invariants.
- `PHASE4_MODEL_ROUTER_IMPLEMENTATION_PLAN.md` — completed implementation sequence and acceptance gates.
- `PHASE4_MODEL_ROUTER_ACCEPTANCE_2026-09-26.md` — canonical Phase-4 owner-machine acceptance record.

Historical experiments, old acceptance transcripts and superseded research remain available through Git history rather than becoming competing planning truth.

## Immediate next action

**Review and approve/revise Phase 5 — Secure Autonomous Engineering Substrate architecture.**

Research is complete. The proposed architecture and ordered implementation slices are documented in the Phase-5 research, architecture and implementation-plan files. No implementation begins until explicit owner approval.
