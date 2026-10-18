# Phase 8 Capability Package + Registry Lifecycle — Owner-Machine Acceptance

## Status

**PASS — OWNER-MACHINE ACCEPTED 2026-09-27**

Accepted protected-main implementation SHA:

`1eda461be022ee30753b3d981e33290442f38a80`

Implementation PR:

`#161 — Phase 8F: deterministic evaluation and Windows acceptance`

Phase-8 implementation slices:

- 8A package contracts/schema;
- 8B durable registry;
- 8C release admission/compatibility;
- 8D runtime projection/health;
- 8E Authority-bound lifecycle/version rollback;
- 8F deterministic evaluation/acceptance.

Owner-machine evidence file:

`C:\Users\gkgaj\AppData\Local\Temp\jarvis_phase8_owner_acceptance_1eda461\phase8-owner-acceptance.json`

Owner-machine evidence digest:

`16de093d87b12bd9918e87fd160f9efa25c3787fe30fca2fbc0c630089893900`

Deterministic replay digest:

`7e20c17d2a94567b051a92366987100b76e439afa48252f456aa738fd00c7a0c`

## Final disposition

Phase 8 is accepted for its defined scope.

The accepted implementation provides a governed capability-package and lifecycle-registry layer that extends the existing Phase-5 manifest/provenance/sandbox/secret/Authority substrate and Phase-7 exact release identity rather than creating a parallel trust system.

The real Windows owner-machine run returned `status=PASS` against the exact protected-main SHA above. The run was non-destructive and verified that protected repository state was unchanged.

## Accepted Phase-8 behavior

The accepted Phase-8 path can:

- parse immutable closed `CapabilityPackageV1` descriptors with strict SemVer 2.0.0 release identity;
- keep package-schema version, manifest-contract version and package release version separate;
- structurally forbid package metadata from naming arbitrary imports, executables, shell commands, argv or plaintext secrets;
- generate Draft-2020-12 JSON Schema and canonical SHA-256 package/schema digests;
- persist canonical capability lifecycle truth in a dedicated checksummed SQLite registry;
- keep package admission rows immutable;
- persist one selected package version, desired activation state and optimistic generation per managed capability;
- atomically commit registry CAS state changes and append-only lifecycle events under `BEGIN IMMEDIATE`;
- fail closed on stale generations, corrupt persisted package identity or unsupported registry schema;
- bind package descriptors to the exact Phase-7 active release SHA;
- reuse the accepted Phase-5 CapabilityManifest validator, ArtifactStore integrity/provenance checks and Authority boundaries;
- require source-owned trusted provider registrations rather than allowing package metadata to manufacture executable code;
- produce deterministic `READY`, `RESTART_REQUIRED` and `BLOCKED` compatibility evidence;
- quarantine deterministic integrity/security failures without treating ordinary incompatibility as a security quarantine;
- keep existing built-in capabilities `CORE_PINNED` while new package-managed capabilities use `PACKAGE_MANAGED` lifecycle truth;
- reconcile durable desired state to immutable generation-bearing effective runtime state;
- fence package-managed capability transitions before mutation so stale routing fails closed;
- avoid a SQLite read on every normal invocation by using reconciled in-memory generation snapshots;
- reuse the existing CapabilityRuntime Authority -> execute -> audit path rather than replacing it;
- map trusted release-owned health probes into the existing Self Model HealthRegistry;
- force desired-disabled package-managed capabilities to effective `DISABLED` health even after prior failed probe evidence;
- require existing Authority for enable, disable, select-version, rollback and owner-approved disposition changes;
- bind Authority proposals to exact package identity/version/digest, compatibility digest and registry generation;
- keep gate approval separate from one-shot executable Authority;
- support rollback to an older package version only when that exact descriptor/provider remains supported by the current accepted release and compatibility is `READY`;
- block fake package rollback when old source/provider code is not present in the current release;
- retain selected and bounded rollback package artifacts independently of retirement;
- keep DBOS outside canonical package-registry truth;
- recover after restart/crash by rebuilding effective routing from durable registry + exact release + compatibility/health truth;
- preserve ordinary source-repair protected boundaries around the entire capability-registry lifecycle surface.

## Deterministic replay result

The owner-machine run passed all 45 approved Phase-8 replay cases.

Final replay result:

- status: `PASS`;
- cases: `45/45`;
- suite digest: `7e20c17d2a94567b051a92366987100b76e439afa48252f456aa738fd00c7a0c`.

The replay covers package schema/SemVer rules, same-version content conflict, unknown/mismatched manifests, untrusted provider execution, impossible raw executable metadata, artifact corruption/provenance, runtime API/platform compatibility, registration without enablement, READY-gated activation, stale CAS, single selected version, immediate disable routing, no false unload, no automatic version switch, exact switch events, supported/unsupported rollback, retired/quarantined packages, health blocking, desired/effective-state separation, restart recovery, newer-schema fail-closed behavior, untrusted entry points, artifact retention, CORE_PINNED isolation, prior governance regressions, stale-routing prevention, reconciler idempotency, crash-after-commit recovery, CAS/event atomicity, Authority-free reconciliation, DBOS independence, concurrent mutation single-winner semantics, stale projection fail-closed behavior, corrupt-selected no-fallback behavior, release-SHA invalidation, execution-model neutrality, CORE_PINNED fence isolation, Windows registry handle restart, and safety quarantine routing removal without rewriting desired intent.

## Owner-machine environment proof

The real Windows owner-machine run additionally proved:

- exact tested protected-main SHA: `1eda461be022ee30753b3d981e33290442f38a80`;
- platform: `win32`;
- Python: `3.11.9`;
- registry schema version: `1`;
- registry file replace roundtrip: `true`;
- registry reopen after replace: `true`;
- protected repository unchanged: `true`;
- protected-surface policy: `repair.protected_surfaces` version `4`;
- protected-surface verdict: `protected_change_required`;
- protected Phase-8 control-surface count: `4`.

## Final CI result

The final Phase-8 implementation head passed GitHub Code Quality workflow run:

`36318315504`

The final head passed:

- Ruff formatting/lint;
- full Linux pytest suite;
- Windows Hello helper contract;
- Windows Hands/sandbox/DPAPI/self-repair regressions;
- Phase-6 replay regressions;
- Phase-7 release/promotion regressions;
- non-destructive Windows Phase-7 acceptance;
- all Phase-8 capability-registry regressions;
- non-destructive Windows Phase-8 acceptance;
- aggregate `promotion-policy`.

A prior Windows 8F acceptance run correctly exposed an open SQLite handle during registry file replacement. The acceptance harness and replay mutation paths were corrected to explicitly close SQLite connections; the final run above passed the exact Windows file-handle/reopen proof.

## Authority and operational boundary

Phase-8 acceptance does **not** grant JARVIS ownership authority.

The accepted capability lifecycle preserves:

- owner-defined Authority boundaries;
- exact evidence/digest binding;
- Phase-7 protected-main promotion governance;
- Phase-5 dependency/provenance/sandbox/secret constraints;
- fail-closed package-managed routing;
- source-owned provider implementations;
- protected lifecycle/reconciler/runtime/acceptance surfaces;
- no automatic plugin import;
- no production package installation from registry metadata;
- no Python hot reload;
- no remote capability marketplace trust;
- no silent conversion of existing CORE_PINNED capabilities.

Phase 8 intentionally does not implement arbitrary owner-requested capability acquisition. That is Phase 9.

## Closure

Phase 8 Capability Package + Registry Lifecycle is:

**DONE / OWNER-MACHINE ACCEPTED 2026-09-27**

The next cross-cutting phase is:

**Phase 9 — Owner-Requested Capability Acquisition**

Phase 9 must begin with repository inspection, technology research and architecture against the accepted Phase-8 package/lifecycle boundary. Phase-8 completion does not pre-authorize Phase-9 implementation.
