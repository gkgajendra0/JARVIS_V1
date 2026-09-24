# Phase 1H — Self-Repair Foundation Hardening

## Status

**ACTIVE — REQUIRED BEFORE PHASE 2 REPAIRKNOWLEDGE IMPLEMENTATION**

Established: 2026-09-24  
Baseline: protected `main` at `7cd4ab241d4706130a82636657da25eaf639d961`

This hardening slice follows a repository/code audit and comparison against mature
supervision/auto-remediation patterns. The accepted Phase-1 crash/hang recovery is
real and remains valuable, but several system-level invariants need strengthening
before RepairKnowledge is allowed to learn from repair history.

## Invariants that remain accepted

- process-external deterministic supervision;
- exact registered RepairPolicy matching;
- unknown triggers fail closed;
- provider/dependency degradation does not imply process death;
- startup readiness and authenticated liveness are separate;
- repeated liveness failure plus confirmation is required before restart;
- same-revision runtime restart;
- durable RepairAttempt history;
- post-restart stabilization before RECOVERED;
- full Windows venv runtime-tree cleanup from the current psutil implementation;
- owner-machine crash/hang acceptance as evidence for the existing R2 path.

## Hardening findings

### H1 — restart budget must not reset immediately after RECOVERED

A short stabilization window proves one repair attempt worked. It must not forgive
crash-loop history.

Required:

- all restart attempts remain counted for the rolling-window circuit breaker;
- only expiry from the configured sustained healthy window resets rate history;
- attempt numbering remains monotonic.

### H2 — add target/action-level restart circuit breaker

Crash and liveness policies currently have independent budgets and crash fingerprints
may differ by exit code.

Required:

```text
voice_runtime + RESTART_RUNTIME_CHILD
-> shared rolling-window ceiling
-> applies across policies, reasons, incidents and exit-code fingerprints
```

The stricter policy/target limit wins.

### H3 — typed deterministic verification proof

A free-form verifier string must not be enough to justify RECOVERED.

Required future shape:

- verifier_id/version;
- verification contract identity;
- PASS / FAIL / INCONCLUSIVE;
- evidence references;
- observation time;
- RECOVERED constructible only from matching PASS proof.

### H4 — deterministic precondition evaluation

Execution authorization must not trust caller-supplied strings such as
`same_local_revision`.

Required:

- deterministic execution context;
- gate computes preconditions from actual state;
- model/worker cannot assert its own authorization facts.

### H5 — immutable trigger/policy provenance

RepairAttempt must eventually preserve enough immutable evidence to reconstruct what
was authorized historically.

Required:

- trigger snapshot;
- policy snapshot or canonical digest;
- verification-contract identity;
- policy version plus digest;
- provenance usable safely by RepairKnowledge.

### H6 — engineering DB migrations

The operational incident/repair DB currently relies on CREATE TABLE IF NOT EXISTS.

Required:

- versioned migration ledger;
- checksums;
- schema version;
- deterministic upgrade path before adding RepairKnowledge tables.

### H7 — authoritative Windows runtime process ownership

psutil tree snapshots fixed the real Windows venv launcher/interpreter bug but remain
race-prone.

Target:

- Windows Job Object owns runtime tree;
- no breakaway by default;
- authoritative whole-job termination;
- psutil retained for diagnostics/fallback/tests where useful.

### H8 — production supervisor boundary

Production Self-Repair should not depend on a Git-development wrapper.

Target:

```text
jarvis-supervisor
  process ownership
  watchdog
  repair policies/budgets
  verification

jarvis-dev
  optional development/update layer
  owner-approved Git update handling
```

### H9 — supervisor survivability

If the process-external supervisor dies, runtime Self-Repair disappears.

Target on Windows:

- bounded outer guardian using Task Scheduler restart-on-failure semantics;
- interactive JARVIS runtime remains in the logged-in user session;
- no migration of interactive JARVIS itself into Session-0 service UI.

### H10 — truthfulness of R1/R2 status

The framework contains R1/R2 contracts, but current accepted automatic production
repair is R2 runtime restart.

Docs should distinguish:

- R1/R2 deterministic framework;
- currently owner-accepted R2 crash/hang runtime repair;
- future R1 policies only after an actual policy/effector/verifier is implemented and
  accepted.

## Implementation order

1. H1 restart-budget semantics.
2. H2 target/action circuit breaker.
3. H3 typed verification.
4. H4 deterministic precondition gate.
5. H5 immutable trigger/policy provenance.
6. H6 engineering DB migrations.
7. H7 Windows Job Object ownership.
8. H8 extract production supervisor from jarvis-dev.
9. H9 outer supervisor guardian.
10. H10 documentation truth reconciliation.
11. full automated tests.
12. owner-machine fault matrix.

## Required owner-machine acceptance matrix

Before Phase 1H is accepted, exercise at minimum:

- full runtime crash;
- full runtime hang;
- launcher-only death;
- interpreter-only death;
- supervisor death;
- alternating crash/liveness faults;
- different exit-code fingerprints;
- recover -> crash -> recover loop within rolling window;
- budget survives supervisor restart;
- persistence unavailable;
- revision changes during cooldown;
- provider quota/degradation negative control;
- no duplicate/orphan runtime survives cleanup;
- normal healthy runtime does not false-trigger repair.

## Exit condition

Phase 1H is accepted only when the repair foundation can safely serve as trusted
input to RepairKnowledge. Phase 2 implementation remains blocked until then.
