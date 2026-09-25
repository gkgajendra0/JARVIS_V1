# Phase 2 EngineeringKnowledge — Owner-Machine Acceptance

## Status

**PASS — OWNER-MACHINE ACCEPTED 2026-09-25**

Accepted protected-main baseline tested:

`3c5a2f732db171a9ad61a4531fecd66aed0d27c4`

Acceptance evidence file on the owner machine:

`C:\Users\gkgaj\AppData\Local\JARVIS\operations\acceptance\phase2-engineeringknowledge-20260925-104003.json`

## Final acceptance result

The integrated Phase-2J owner-machine runner completed with every required gate passing:

- `live-r2-independence` — PASS;
- `real-repair-projection` — PASS;
- `real-repair-exact-lexical-retrieval` — PASS;
- `real-repair-semantic-retrieval` — PASS;
- `poisoning-and-secret-gates` — PASS;
- `open-ended-facet-extensibility` — PASS;
- `qrel-lexical-safety` — PASS;
- `qrel-hybrid-baseline` — PASS.

Final console result:

`RESULT: PASS - all automated owner-machine gates passed.`

## What the pass proves

### R2 independence

A real bounded production runtime crash was injected while the production supervisor owned the runtime.

R2 recovered first, and the acceptance runner proved that no EngineeringKnowledge revision existed for that RepairAttempt before recovery completed.

This preserves the Phase-2 invariant:

> EngineeringKnowledge is advisory memory and is not a prerequisite for deterministic production Self-Repair.

### Real repair -> EngineeringKnowledge

The newly recovered production RepairAttempt was then projected into EngineeringKnowledge and moved through the allowed lifecycle.

Acceptance verified:

- deterministic candidate creation;
- promotion through the registered policy;
- canonical integrity;
- exact provenance to incident, RepairAttempt, trigger, policy and verifier;
- persisted revision identity.

### Retrieval

The accepted real repair was retrieved through:

- exact evidence lookup;
- lexical retrieval;
- wrong-component applicability exclusion;
- paraphrased semantic retrieval using the pinned local Qwen-256 baseline.

The final owner-machine qrel run passed both lexical and hybrid safety gates.

### Security and extensibility

Acceptance also proved:

- poisoned instruction-like evidence is quarantined/fails closed;
- secret-like evidence is rejected;
- unknown facets are preserved but cannot influence decisions;
- a reviewed future facet can register through the same shared registry without a new knowledge database or authority path.

## Findings discovered and corrected during acceptance

The owner-machine sequence intentionally exposed real integration defects. They were corrected before the final pass.

1. Existing virtual environments do not automatically acquire newly declared dependencies after `git pull`; owner-machine instructions now require editable-install refresh where needed.
2. A cold-process circular import existed between EngineeringKnowledge security/projector/incident imports; shared repair identifiers were moved into dependency-light contracts and fresh-process regression tests were added.
3. Unrestricted dense nearest-neighbor expansion caused false positives on explicit no-answer qrels; dense similarity is now grounded by exact/lexical candidates and may rerank but not invent an answer.
4. The original acceptance observer waited only 120 seconds, equal to one production startup-readiness timeout; the observer now covers the full bounded R2 recovery budget and reports detailed attempt/supervisor state.

These were acceptance-harness/integration corrections. They did not weaken R2 repair budgets, Authority, lifecycle, verification or production governance.

## Phase 2 closure

Phase 2 is accepted for its defined scope:

- canonical JARVIS-owned EngineeringKnowledge persistence;
- immutable revisions and provenance;
- registered versioned facets;
- deterministic REPAIR projection;
- lifecycle/promotion;
- applicability;
- local-first exact/FTS/Qwen/RRF retrieval with grounded dense ranking;
- integrity, poisoning and secret controls;
- evaluation/qrel infrastructure;
- open-ended facet/process extensibility;
- verified independence from deterministic R2 Self-Repair.

EngineeringKnowledge remains advisory. It does not mint RepairPolicy, execution permits, Authority, credentials, merge rights or deployment permission.

The next cross-cutting phase is:

**Phase 3 — EngineeringChange Lifecycle / Mission Orchestration.**
