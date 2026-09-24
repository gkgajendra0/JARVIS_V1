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
- Automatic production Self-Repair currently accepted: bounded R2 runtime crash/hang
  recovery.
- R1 exists in the typed repair vocabulary but has no owner-accepted automatic
  production policy yet.
- Self-Repair issue #65: CLOSED / COMPLETED for the original R2 acceptance scope.

The authoritative completed/deferred/superseded/rejected ledger is
`PROJECT_STATE.md`.

## Active cross-cutting program

The active development slice is:

**Self-Repair / Self-Evolution Phase 1H — Self-Repair Foundation Hardening**

The hardening contract is defined in `SELF_REPAIR_PHASE1H_HARDENING.md`.

Phase 1H is intentionally focused on foundations required before repair history can
be trusted as learned engineering knowledge:

1. sustained restart-budget semantics;
2. target/action-level restart circuit breaking;
3. typed deterministic verifier proof;
4. deterministic execution-precondition evaluation;
5. immutable trigger/policy provenance and digests;
6. versioned engineering-database migrations;
7. Windows Job Object runtime ownership;
8. local-only production supervisor separation from Git/network update polling;
9. bounded Windows outer-supervisor guardian;
10. truthful R1/R2 documentation and expanded acceptance.

Phase-2 RepairKnowledge technology research/design is preserved in
`REPAIR_KNOWLEDGE_RESEARCH_AND_DESIGN.md`, but Phase-2 implementation remains
blocked until Phase 1H is independently accepted.

Do not start DiagnosticModelRouter, AI source repair or self-evolution in the same
slice.

## Next numbered product slice

Step 8 — Notes, Tasks, Reminders and Scheduling — remains the next numbered product
slice when numbered roadmap work resumes.

The active Self-Repair/Evolution program is cross-cutting and does not renumber the
roadmap.

## Open deferred / parallel items

Current open/deferred items are tracked only in `PROJECT_STATE.md`. The important
open issues are #19, #44, #45, #46, #63 and #69.

They remain separate unless evidence shows that one directly blocks Phase 1H.

## Documentation ownership

- `PRODUCT.md` — durable product intent and capability catalogue.
- `ROADMAP.md` — numbered sequence and high-level status.
- `CURRENT_ARCHITECTURE.md` — architecture accepted on protected `main`.
- `CURRENT_PLAN.md` — active work only.
- `PROJECT_STATE.md` — accepted/deferred/superseded/rejected repository ledger.
- `QUALITY_GATES.md` — universal validation and acceptance rules.
- `SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md` — active repair/evolution program.
- `SELF_REPAIR_PHASE1H_HARDENING.md` — current hardening gate.
- `REPAIR_KNOWLEDGE_RESEARCH_AND_DESIGN.md` — completed Phase-2 research/design.

Historical experiments, old acceptance transcripts and superseded ADR/research
documents are preserved by Git history rather than treated as current truth.

## Immediate next action

**Complete Phase 1H automated and owner-machine acceptance.**

Only after Phase 1H is accepted should implementation begin for
**Phase 2 — RepairKnowledge Foundation**.
