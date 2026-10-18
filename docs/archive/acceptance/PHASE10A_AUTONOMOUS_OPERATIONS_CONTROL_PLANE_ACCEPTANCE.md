# Phase 10A — Autonomous Operations Control Plane Acceptance Record

Status: **DONE / OWNER-MACHINE ACCEPTED — 2026-09-28**

Phase 10A implements the owner-approved thin whole-JARVIS operations control plane
without making JARVIS its own source of Authority.

PR #219, `Phase 10A.7: reconciliation runtime and final replay acceptance`,
squash-merged the accepted implementation to protected `main` as
`3d9289aafd371484fe22023bf57279d6101d6b16`.

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

## Accepted owner-machine evidence

The real Windows owner-machine acceptance passed against exact implementation head
`4d1cb077cf3b0c5d9271edf05b47a5012ca14695`.

Accepted evidence:

- status: `PASS`;
- tested implementation head: `4d1cb077cf3b0c5d9271edf05b47a5012ca14695`;
- locked replay cases: `30`;
- pytest evidence nodes executed: `18`;
- replay-corpus digest: `2a8205a1a84165effd813aee088d298c5c25ba290585d20753f17e750be77258`;
- acceptance evidence digest: `fa85ee31a0d63609167be4556f8cab587c980d20311de88396bbf70e16b9bae3`;
- pytest stdout digest: `341d5dca33250b815baddbafb6001e174c20bf1716bb74f3d612e77777db8938`;
- pytest stderr digest: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
- tested repository status digest: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
- owner-machine local protected-main ref observed during the isolated worktree run:
  `369178c2a8b2d59d3593e3260528708e6f6cac23`;
- recorded at: `2026-09-28T17:24:48.389499+00:00`;
- repository unchanged: `true`;
- local protected-main ref unchanged: `true`;
- Authority granted: `false`;
- production mutated: `false`;
- production autonomy mode enabled: `false`.

The evidence digest was independently recomputed from the canonical evidence body and
matches the recorded digest exactly.

## Owner-machine acceptance gate

Phase 10A is **DONE** because all of the following acceptance conditions are true:

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
$expectedCommit = "4d1cb077cf3b0c5d9271edf05b47a5012ca14695"
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

This command records the exact owner-tested implementation SHA. The accepted run used
`4d1cb077cf3b0c5d9271edf05b47a5012ca14695`; PR #219 later merged the evidence-recording head to protected
`main` as `3d9289aafd371484fe22023bf57279d6101d6b16`.

## Current result

The owner-machine acceptance gate has passed for exact head
`4d1cb077cf3b0c5d9271edf05b47a5012ca14695`.

Phase 10A is DONE / OWNER-MACHINE ACCEPTED. PR #219 merged the accepted implementation
and evidence record to protected `main` as `3d9289aafd371484fe22023bf57279d6101d6b16`.

The owner-tested implementation head remains `4d1cb077cf3b0c5d9271edf05b47a5012ca14695`, with replay digest
`2a8205a1a84165effd813aee088d298c5c25ba290585d20753f17e750be77258` and evidence digest `fa85ee31a0d63609167be4556f8cab587c980d20311de88396bbf70e16b9bae3`.

Production autonomy remains SHADOW, Authority is unchanged, and the Phase-9 full external
physical-device lifecycle remains separately deferred.

The permanent rule remains:

> **JARVIS may manage JARVIS, but JARVIS must never become its own source of authority.**
