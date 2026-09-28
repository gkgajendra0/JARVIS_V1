# Phase 10A — Autonomous Operations Control Plane Acceptance Record

Status: **IMPLEMENTATION CANDIDATE / OWNER-MACHINE ACCEPTANCE PENDING — 2026-09-28**

Phase 10A implements the owner-approved thin whole-JARVIS operations control plane
without making JARVIS its own source of Authority.

The implementation is being finalized in PR #219,
`Phase 10A.7: reconciliation runtime and final replay acceptance`.

## Implemented scope

The Phase-10A implementation now contains:

- durable Objective / DesiredState / Finding / ActionCandidate / OwnerAttention /
  Outcome / Reconcile contracts inside the existing WorkStore;
- immutable, provenance-bearing whole-JARVIS SystemState aggregation over canonical
  subsystem reads;
- exact-version deterministic DesiredState rules and anti-flapping stabilization;
- durable finding lifecycle and least-powerful action resolution;
- replay-safe shadow action intents and downstream dispatch links;
- deterministic autonomy budgets and portfolio prioritization;
- canonical owner-attention deduplication, grouping, inhibition and re-notification;
- governed SHADOW / isolated ASSISTED dispatch bridges over existing Work,
  EngineeringChange, deterministic-controller and owner-attention boundaries;
- bounded AutonomyReconciler execution with STARTUP, STATE_CHANGE_HINT, PERIODIC and
  MANUAL_TEST triggers;
- in-process single-run locking and durable handled-token replay semantics;
- a periodic safety-sweep wrapper with clean shutdown;
- optional WorkRuntime lifecycle attachment without automatic production activation;
- a locked 30-case replay corpus;
- an exact-commit Windows owner-machine acceptance harness.

## Governance boundary

The acceptance candidate preserves these invariants:

- production autonomy remains SHADOW by default;
- ACTIVE_BOUNDED cannot be enabled by the controller itself;
- budgets and modes do not grant Authority;
- no generic shell or arbitrary capability invocation was introduced;
- WorkItem execution remains canonical in WorkStore / DBOS;
- EngineeringChange retains existing research, architecture, owner-approval,
  verification, acceptance and promotion gates;
- canonical subsystem facts remain owned by their existing stores/registries;
- owner attention is durable control-plane truth while WorkDelivery is transport only;
- failed reconcile runs are retryable and are not marked handled;
- replay/restart must not duplicate findings, candidates or downstream execution;
- the Phase-9 full external physical-device lifecycle remains separately deferred.

## Locked replay corpus

The repository contains exactly 30 Phase-10A replay requirements in
`jarvis.autonomy.replay.PHASE10A_REPLAY_CORPUS_V1`.

The corpus covers:

1. quiet healthy state;
2. missing source;
3. stale evidence;
4. transient violation;
5. sustained violation;
6. snapshot/request replay;
7. restart replay;
8. stable recovery;
9. deterministic-controller preference;
10. bounded diagnostics path;
11. governed EngineeringChange path;
12. SHADOW zero downstream dispatch;
13. isolated ASSISTED exactly-once WorkItem;
14. existing Authority preservation;
15. owner-attention deduplication;
16. root-cause attention inhibition;
17. re-notify throttling;
18. budget exhaustion;
19. dispatch cooldown;
20. deterministic portfolio order;
21. owner-priority preservation;
22. dependency-unblocking tie-break;
23. malformed evidence;
24. unknown rule version;
25. DesiredState generation binding;
26. reconcile-token idempotency;
27. canonical downstream outcome linkage;
28. EngineeringChange owner gate preservation;
29. no self-approval / production-mode escalation;
30. protected checkout/main and production immutability in owner-machine acceptance.

The exact replay-corpus digest and owner-tested implementation SHA will be recorded here
only after the real owner-machine run.

## Owner-machine acceptance gate

Phase 10A is **not DONE** until all of the following are true:

1. PR #219 exact-head CI is green.
2. The owner runs the Windows acceptance harness against that exact head.
3. The returned evidence is PASS and digest-valid.
4. The evidence proves:
   - the checkout is unchanged;
   - the local protected-main ref is unchanged;
   - no Authority was granted;
   - production was not mutated;
   - no production autonomy mode was enabled;
   - all 30 locked replay requirements are represented.
5. The accepted evidence is recorded in this document.
6. Final documentation-only reconciliation passes CI and is merged.

The command is intentionally exact-commit bound:

```powershell
$repo = "C:\Users\gkgaj\Desktop\jarvis_v1"
$python = "$repo\.venv\Scripts\python.exe"
$expectedCommit = "<EXACT_GREEN_PR_219_HEAD_SHA>"
$acceptanceRepo = Join-Path $env:TEMP "jarvis-phase10a-owner-acceptance-$($expectedCommit.Substring(0,8))"
$output = Join-Path $env:TEMP "jarvis-phase10a-owner-acceptance.json"

Set-Location $repo
git fetch origin

if (Test-Path $acceptanceRepo) {
    git worktree remove --force $acceptanceRepo
}
git worktree add --detach $acceptanceRepo $expectedCommit

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$acceptanceRepo\src"
    Set-Location $acceptanceRepo

    & $python -m jarvis.autonomy.phase10a_acceptance `
        --repo-root $acceptanceRepo `
        --expected-commit $expectedCommit `
        --output $output

    Get-Content $output
}
finally {
    Set-Location $repo
    $env:PYTHONPATH = $previousPythonPath
    git worktree remove --force $acceptanceRepo
}
```

Do not substitute a different SHA. The final exact SHA will be supplied only after the
PR CI matrix is green.

## Current result

Implementation is at the final validation boundary.

No claim of owner-machine acceptance or Phase-10A completion is made yet.

The permanent rule remains:

> **JARVIS may manage JARVIS, but JARVIS must never become its own source of authority.**
