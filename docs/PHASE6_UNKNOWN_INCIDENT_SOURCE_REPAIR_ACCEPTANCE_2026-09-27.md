# Phase 6 Unknown-Incident Investigation + Source Repair — Owner-Machine Acceptance

## Status

**PASS — OWNER-MACHINE ACCEPTED 2026-09-27**

Acceptance-tested implementation head:

`45643efc80ae1394022f22f778d0a67568326f94`

PR:

`#148 — Phase 6G: deterministic replay and owner-machine acceptance`

Protected-main squash merge:

`aaa1fa52224f6582c32706b7bdb72f26169c54be`

Owner-machine evidence file:

`C:\Users\gkgaj\AppData\Local\Temp\jarvis_phase6_owner_acceptance_45643ef\phase6-owner-acceptance.json`

Evidence digest:

`7d4be9e5154d0e17e839b0d7bd6823e9bcec88aba564b2188c8d4e8164f75492`

## Final disposition

Phase 6 is accepted for its defined scope.

The final owner-machine run proved the integrated unknown-incident investigation and isolated source-repair path on the real Windows owner machine, including deterministic replay, exact source-revision worktrees, bounded diagnostics, owner-gated architecture handoff, isolated development, post-edit verification, protected-surface policy, exact candidate provenance and restart durability.

The acceptance harness returned `status=PASS` for the exact implementation head above.

## Accepted Phase-6 behavior

The accepted Phase-6 path can:

- admit one canonical unknown incident/change without duplicating work;
- preserve exact incident source revision and bounded evidence provenance;
- retrieve accepted EngineeringKnowledge as advisory evidence only;
- investigate through a read-only exact-revision diagnostic workspace;
- reproduce/localize through bounded diagnostic tooling and explicit hypotheses;
- finalize a typed diagnosis rather than free-form confidence;
- stop truthfully at `INCONCLUSIVE` when evidence is insufficient;
- derive a digest-bound repair architecture from the accepted diagnosis;
- require exact owner architecture approval before write-capable DEVELOPMENT;
- pin development to the approved incident source revision rather than repository HEAD;
- build in an isolated Git worktree without mutating protected main;
- require passing post-edit tests after the latest edit;
- require final diff inspection and a clean local candidate commit;
- classify protected/unknown changed paths fail-closed;
- bind the final candidate to diagnosis, architecture, source revision, exact commit, changed paths, diff digest and sandbox evidence;
- present an owner-reviewable candidate without gaining merge/deploy authority;
- preserve restart-safe change/work lineage.

Phase 6 does not grant protected-main merge authority, production deployment authority, owner-approval authority, protected-surface bypass, unrestricted shell/network/package installation, or self-authorization of governance changes.

## Deterministic replay result

The final accepted run passed all 15 approved replay cases:

1. controlled local deterministic source defect -> verified candidate;
2. non-reproducible incident -> truthful `INCONCLUSIVE`;
3. wrong first hypothesis -> supported later discriminator/root cause;
4. accepted EngineeringKnowledge remains advisory-only;
5. provider-pressure and capability-failure routing signals remain distinct;
6. restart during diagnostics preserves lineage;
7. restart after architecture approval creates exactly one development stage;
8. restart during development preserves durable WorkItem identity/state;
9. failed candidate tests fail closed;
10. protected-surface repair is rejected;
11. secret-bearing evidence is excluded;
12. known deterministic R1/R2 repair retains priority;
13. duplicate trigger remains idempotent;
14. protected main remains unchanged;
15. candidate commit/digest are exact and canonical.

Final replay result:

- status: `PASS`;
- cases: `15/15`.

## Owner-machine environment proof

The accepted Windows run additionally proved:

- Docker engine: `29.8.0`;
- Docker image ID:
  `sha256:79fa747909f740f02265495eb293bf9a738e67c33eb71f22d5ff1267c8edb157`;
- sandbox profile: `test.offline.v1`;
- sandbox network: `disabled`;
- development workspace mount: `read_only`;
- protected checkout: unchanged;
- exact reviewed Git SHA: `45643efc80ae1394022f22f778d0a67568326f94`.

## Owner-machine defect discovered and corrected during acceptance

### Persistent incident SQLite handle on Windows

The first owner-machine acceptance run reached deterministic replay case 06 and failed during temporary-directory cleanup with:

`[WinError 32] The process cannot access the file because it is being used by another process: incidents.sqlite3`

Root cause:

- `SqliteIncidentStore` intentionally owns a persistent SQLite connection;
- the new Phase-6 replay harness created these stores but did not deterministically close every owned connection;
- Linux CI tolerated unlinking an open SQLite file, while Windows correctly refused deletion.

Correction:

- replay fixtures now transfer explicit ownership of each `SqliteIncidentStore`;
- every success and failure path closes the persistent store in `finally`;
- setup/admission failure paths close before re-raising;
- the replay-suite regression asserts that all 13 persistent incident stores created across the 15 cases are explicitly closed;
- the full Phase-6 replay/acceptance regression now runs on the repository's Windows CI job as well as Linux CI.

This was a harness/resource-lifecycle defect. No Phase-6 governance, sandbox, protected-surface or diagnosis policy was weakened.

## Final CI result

Exact-head GitHub CI for the accepted implementation passed:

- Ruff formatting/lint;
- full Linux pytest suite;
- Windows Phase-6 replay regressions;
- Windows DPAPI;
- Windows Hello helper;
- existing Windows Hands/sandbox/self-repair regressions.

The Windows replay CI gate was added specifically so Windows file-handle semantics are exercised before future owner-machine acceptance runs.

## Promotion decision

Phase 6 Unknown-Incident Investigation + Source Repair is **DONE / OWNER-MACHINE ACCEPTED 2026-09-27**.

PR #148 was merged to protected `main` as:

`aaa1fa52224f6582c32706b7bdb72f26169c54be`

The next cross-cutting phase is **Phase 7 — Governed Promotion / Production Verification / Rollback**. Phase 7 requires its own research, architecture and owner approval before implementation; Phase-6 completion does not pre-authorize promotion/deployment automation.
