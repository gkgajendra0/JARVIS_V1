# Phase 10 — Closed-Loop Engineering Learning Acceptance Runbook

Status: **IMPLEMENTATION COMPLETE — OWNER-MACHINE ACCEPTANCE PENDING**

Phase 10 closes the engineering learning loop without granting JARVIS new
Authority. Verified engineering outcomes can be normalized, admitted by a
deterministic policy, projected into immutable EngineeringKnowledge, promoted,
superseded by newer verified evidence, replayed after restart, and retrieved as
advisory evidence by existing engineering workflows.

## What automated CI already proves

The Phase-10.7 replay matrix contains exactly 15 locked cases:

1. verified production success becomes accepted learning;
2. candidate-local regression becomes negative evidence;
3. external-provider failure does not become candidate causal truth;
4. external-hardware failure does not become candidate causal truth;
5. unknown-attribution failure remains inconclusive;
6. compatibility READY becomes scoped compatibility learning;
7. compatibility BLOCKED becomes scoped compatibility learning;
8. contradictory newer evidence creates a successor and supersedes the prior revision;
9. restart replay creates no duplicate knowledge;
10. accepted-successor / not-yet-superseded crash gap is recovered;
11. missing learning attestation blocks promotion;
12. unknown future facet schema blocks promotion;
13. rejected learning is never resurrected;
14. Phase-6 can retrieve learned repair knowledge only as advisory evidence;
15. malformed claimed integrity evidence fails closed.

The repository CI additionally reruns the existing Ruff, full pytest, Windows
Hello, Windows DPAPI/security, Phase-6, Phase-7, Phase-8, Phase-9 and promotion
policy gates.

## Owner-machine acceptance boundary

The final acceptance harness is intentionally non-destructive.

It:

- runs only on Windows;
- creates its replay databases beneath an isolated temporary directory;
- binds evidence to the exact Git commit being tested;
- records the pre-run repository status digest;
- proves the repository checkout is unchanged after the replay matrix;
- refuses to write its JSON evidence inside the tested repository;
- grants no Authority;
- mutates no production state.

It does **not** deploy code, create engineering projects, alter protected main,
change capability/runtime state, or perform the deferred Phase-9 physical-device
end-to-end validation.

## Required owner-machine command

Run from PowerShell in the local repository after checking out the exact
Phase-10.7 implementation/acceptance-harness head supplied during acceptance:

~~~powershell
$repo = "C:\Users\gkgaj\Desktop\jarvis_v1"
$python = "$repo\.venv\Scripts\python.exe"
$output = Join-Path $env:TEMP "jarvis-phase10-owner-acceptance.json"

Set-Location $repo
& $python -m jarvis.engineering_learning.phase10_acceptance --repo-root $repo --output $output

if ($LASTEXITCODE -ne 0) {
    throw "Phase 10 owner-machine acceptance failed."
}

Get-Content $output
~~~

The evidence must report:

- status = PASS;
- suite_status = PASS;
- the exact tested commit;
- exactly the locked 15 case IDs;
- authority_granted = false;
- production_mutated = false;
- repo_unchanged = true;
- a valid suite_digest;
- a valid evidence_digest.

## Completion rule

Phase 10 may be marked **DONE** only after:

1. PR #201 automated CI is green on the exact Phase-10.7 implementation/acceptance head;
2. the owner-machine harness passes against that exact implementation head;
3. returned evidence validates against that exact tested commit;
4. a documentation-only acceptance record/status update records the tested commit and evidence digests;
5. the accepted documentation/code PR is revalidated and merged to protected main.

The implementation head remains the owner-tested runtime identity even though the final
merge may contain a later documentation-only acceptance-record commit.

The deferred Phase-9 full physical-device lifecycle validation remains a separate
whole-system acceptance item and is not silently claimed by Phase 10.
