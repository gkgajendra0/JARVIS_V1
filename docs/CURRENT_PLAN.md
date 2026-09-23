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
- Deterministic R1/R2 Self-Repair: accepted foundation.
- Self-Repair issue #65: CLOSED / COMPLETED.
- Open pull requests at reconciliation start: none.

The authoritative completed/deferred/superseded/rejected ledger is
`PROJECT_STATE.md`.

## Active cross-cutting program

The active development program is:

**Self-Repair / Self-Evolution Phase 2 — RepairKnowledge Foundation**

The full staged program is defined in
`SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md`.

Phase 2 is intentionally limited to:

1. canonical RepairKnowledge domain contracts;
2. durable persistence and provenance;
3. lifecycle states and transitions;
4. links to incidents, RepairAttempts and repository evidence;
5. deterministic retrieval by component/signature;
6. candidate knowledge creation from verified incidents;
7. proof that RepairKnowledge cannot execute, authorize or mutate RepairPolicy;
8. repository tests and owner-machine acceptance.

Do not start DiagnosticModelRouter, AI source repair or self-evolution in the same
implementation slice.

## Next numbered product slice

Step 8 — Notes, Tasks, Reminders and Scheduling — remains the next numbered product
slice when numbered roadmap work resumes.

The active Self-Repair/Evolution program is cross-cutting and does not renumber the
roadmap.

## Open deferred / parallel items

Current open/deferred items are tracked only in `PROJECT_STATE.md`. The important
open issues are #19, #44, #45, #46, #63 and #69.

They remain separate unless evidence shows that one directly blocks the active
RepairKnowledge slice.

## Documentation ownership

- `PRODUCT.md` — durable product intent and capability catalogue.
- `ROADMAP.md` — numbered sequence and high-level status.
- `CURRENT_ARCHITECTURE.md` — architecture that exists on protected `main`.
- `CURRENT_PLAN.md` — active work only.
- `PROJECT_STATE.md` — accepted/deferred/superseded/rejected repository ledger.
- `QUALITY_GATES.md` — universal validation and acceptance rules.
- `SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md` — active repair/evolution program.

Historical experiments, old acceptance transcripts and superseded ADR/research
documents are preserved by Git history rather than treated as current truth.

## Immediate next action

After this repository reconciliation is merged:

**begin Phase 2 — RepairKnowledge Foundation.**
