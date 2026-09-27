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

The active cross-cutting engineering boundary is now:

**Phase 8 — Capability Package + Registry Lifecycle — OWNER-APPROVED / IMPLEMENTATION ACTIVE (8F)**

Phase 5 Secure Autonomous Engineering Substrate is **DONE / OWNER-MACHINE ACCEPTED 2026-09-27**. Its final evidence is recorded in `PHASE5_SECURE_ENGINEERING_SUBSTRATE_ACCEPTANCE_2026-09-27.md`. PR #133 merged to protected main at `78f25fb192b926ee30a028cfc02c829e1197cc9e`.

Phase 6 Unknown-Incident Investigation + Source Repair is **DONE / OWNER-MACHINE ACCEPTED 2026-09-27**.

Canonical Phase-6 documents are:

- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_RESEARCH.md`;
- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_ARCHITECTURE.md`;
- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_IMPLEMENTATION_PLAN.md`;
- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_ACCEPTANCE_2026-09-27.md`.

Accepted implementation head: `45643efc80ae1394022f22f778d0a67568326f94`.

Owner-machine evidence digest: `7d4be9e5154d0e17e839b0d7bd6823e9bcec88aba564b2188c8d4e8164f75492`.

PR #148 merged the accepted Phase-6 implementation to protected `main` as `aaa1fa52224f6582c32706b7bdb72f26169c54be`.

The accepted Phase-6 path adds bounded read-only diagnostics, typed diagnosis evidence, exact owner-gated architecture handoff, source-revision-pinned isolated development, post-edit verification, protected-surface fail-closed policy, exact candidate provenance and deterministic replay/Windows acceptance. It deliberately stops before protected-main promotion/deployment.

Phase 7 Governed Promotion / Production Verification / Rollback is **DONE / OWNER-MACHINE ACCEPTED 2026-09-27**.

Canonical Phase-7 documents are:

- `PHASE7_GOVERNED_PROMOTION_RESEARCH.md`;
- `PHASE7_GOVERNED_PROMOTION_ARCHITECTURE.md`;
- `PHASE7_GOVERNED_PROMOTION_IMPLEMENTATION_PLAN.md`;
- `PHASE7_GOVERNED_PROMOTION_ACCEPTANCE_2026-09-27.md`.

Accepted implementation head: `19beb542295fa4e3ab23407564847a82d8621258`.

Owner-machine evidence digest: `9fb2bb940a855c1d0ab32e444e00d7e922bd66d5edd7915c31efe6dd5fa77a9b`.

Replay digest: `07f53707a42760f53b6dadb4fc8740ea4553437d33551038b2ba0f726c0356ae`.

PR #150 was explicitly owner-approved and merged to protected `main` as `d2c7dc360386dab22bff6406d405b298601bff81`.

The accepted Phase-7 path adds exact candidate/PR/CI binding, digest-bound owner promotion, one-shot Authority execution, exact-head protected merge, immutable Windows release staging, runtime release identity verification, bounded observation and compatibility-safe rollback. It does not grant JARVIS ownership authority.

**Current state: Phase 8 architecture is owner-approved; 8A package contracts/schema, 8B durable registry, 8C release admission/compatibility, 8D runtime projection/health, and 8E Authority-bound lifecycle/version rollback are complete. 8F deterministic evaluation and non-destructive acceptance is active.** The second research pass found a stale-routing/crash failure window in the original commit-then-refresh design and closes it with deterministic lifecycle reconciliation, per-capability transition fencing, generation-aware runtime projection and atomic registry-CAS/lifecycle-event transactions.

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
Phase 6  Unknown-incident investigation + source repair — DONE / OWNER-MACHINE ACCEPTED 2026-09-27
Phase 7  Governed promotion / production verification / rollback — DONE / OWNER-MACHINE ACCEPTED 2026-09-27
Phase 8  Capability package + registry lifecycle — IMPLEMENTATION ACTIVE / 8F
Phase 9  Owner-requested capability acquisition
Phase 10 Closed-loop engineering learning
Phase 10A Autonomous Operations Control Plane — approved future integration point; not active yet
Phase 11 Autonomous capability-gap / weakness detection
Phase 12 Shadow improvement + baseline benchmarking
Phase 13 Engineering curriculum + specialist model evaluation
Phase 14 Governed self-evolution
```

Owner-requested capability acquisition intentionally precedes autonomous gap detection: an explicit owner request to acquire a capability must not wait for repeated failures or repeated requests.

The owner-approved 2026-09-26 sequencing clarification inserts Phase 10A before Phase 11. Phase 10A will add the Objective/DesiredState model, whole-JARVIS SystemState reconciliation, evidence-backed autonomous work creation, portfolio prioritization, owner-attention handling and autonomy evaluation. It does not interrupt or broaden authority during the current Phase-8 architecture gate.

## Next numbered product slice

Step 8 — Notes, Tasks, Reminders and Scheduling — remains the next numbered product slice when numbered roadmap work resumes.

The active Self-Repair/Evolution/Autonomous-Engineering program is cross-cutting and does not renumber the product roadmap.

## Open deferred / parallel items

Current open/deferred items are tracked only in `PROJECT_STATE.md`. The important open issues are #19, #44, #45, #46, #63 and #69.

They remain separate unless evidence shows that one directly blocks the current Phase-8 research/architecture work.

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
- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_ARCHITECTURE.md` — owner-approved Phase-6 stable contracts/invariants.
- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_IMPLEMENTATION_PLAN.md` — completed Phase-6 implementation slices and acceptance matrix.
- `PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_ACCEPTANCE_2026-09-27.md` — canonical Phase-6 owner-machine acceptance record.
- `PHASE7_GOVERNED_PROMOTION_RESEARCH.md` — Phase-7 technology/repository research and dispositions.
- `PHASE7_GOVERNED_PROMOTION_ARCHITECTURE.md` — owner-approved Phase-7 stable contracts/invariants.
- `PHASE7_GOVERNED_PROMOTION_IMPLEMENTATION_PLAN.md` — completed Phase-7 implementation slices and acceptance matrix.
- `PHASE7_GOVERNED_PROMOTION_ACCEPTANCE_2026-09-27.md` — canonical Phase-7 owner-machine acceptance record.
- `PHASE8_CAPABILITY_PACKAGE_REGISTRY_RESEARCH.md` — Phase-8 foundation repository/technology research and initial dispositions.
- `PHASE8_CAPABILITY_PACKAGE_REGISTRY_IMPLEMENTATION_RESEARCH.md` — implementation-focused comparison of mature lifecycle/plugin/package technologies and the research basis for the revised reconciler/generation-fenced design.
- `PHASE8_CAPABILITY_PACKAGE_REGISTRY_ARCHITECTURE.md` — revised Phase-8 architecture awaiting explicit owner approval.
- `PHASE8_CAPABILITY_PACKAGE_REGISTRY_IMPLEMENTATION_PLAN.md` — revised Phase-8 implementation slices and acceptance gates; not yet implementation-authorized.

Historical experiments, old acceptance transcripts and superseded research remain available through Git history rather than becoming competing planning truth.

## Immediate next action

**Implement Phase 8 in approved slices 8A–8F. Continue without weakening Authority/security/governance; stop only for required owner-machine input or a genuinely new architecture/security decision.**
