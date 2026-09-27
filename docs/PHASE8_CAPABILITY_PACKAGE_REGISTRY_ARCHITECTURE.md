# Phase 8 — Capability Package + Registry Lifecycle Architecture

## Status

**ARCHITECTURE REVISED AFTER IMPLEMENTATION RESEARCH — OWNER APPROVAL REQUIRED — 2026-09-27**

No Phase-8 runtime implementation is authorized until the owner approves this architecture.

## 1. Purpose

Phase 8 creates durable lifecycle truth for capability packages while preserving the accepted JARVIS execution and Authority boundaries.

It answers:

- what capability package versions exist;
- what exact manifest/evidence each version binds;
- which version is selected;
- whether the owner/system desires it enabled;
- whether the current JARVIS release can actually run it;
- whether required health evidence is currently acceptable;
- why a lifecycle transition occurred;
- what older package version remains available for bounded rollback.

Phase 8 does **not** research/build an arbitrary new capability. That is Phase 9.

## 2. Architectural rule

```text
package metadata
      |
      v
admission + exact evidence
      |
      v
durable registry desired state/generation
      |
      +----------------------+------------------+
      |                      |                  |
      v                      v                  v
compatibility truth     HealthRegistry    active release truth
      |                      |                  |
      +----------+-----------+------------------+
                 |
                 v
      CapabilityLifecycleReconciler
                 |
                 v
     generation-fenced effective snapshot
                 |
                 v
       CapabilityRegistryProjection
                 |
                 v
       existing CapabilityRuntime
resolve -> validate -> Authority -> execute -> audit
```

The registry filters trusted executors. It never manufactures execution code.

## 3. New package contract

Introduce immutable `CapabilityPackageV1`.

Required concepts:

- `package_id` — stable normalized package identity;
- `package_version` — strict SemVer;
- `capability_id` — stable product capability identity;
- `package_kind` — initially `core_source` or `extension_source`; extensible later;
- `manifest_id`;
- `manifest_version` — Phase-5 manifest contract version, currently 1;
- `manifest_digest`;
- `runtime_api_id` — initially `jarvis.capability_runtime`;
- `runtime_api_version` — exact supported contract version, initially 1;
- package artifact references;
- optional attestation/SBOM evidence refs;
- package-schema version.

### 3.1 Package artifact descriptor

Each external artifact reference is typed:

- role;
- SHA-256;
- byte size;
- media type;
- provenance reference(s).

The descriptor follows OCI-style content-identity principles but uses the existing local ArtifactStore.

### 3.2 Source code binding

Source-backed packages do not need to duplicate the whole JARVIS source tree into ArtifactStore.

On admission, the durable installed/admitted record additionally binds:

- exact active `release_sha`;
- exact package descriptor digest;
- exact manifest digest.

A version may be selected only if its exact descriptor is present in the current release package inventory and its trusted executor/provider remains available.

This prevents an old package descriptor from silently running against incompatible newer code.

## 4. Package immutability

The pair:

`(package_id, package_version)`

is immutable.

If a later release presents the same pair with a different package digest, admission fails closed with `VERSION_REUSE_CONFLICT`.

A changed package requires a new SemVer.

## 5. Trusted provider boundary

Introduce a release-owned `CapabilityProviderRegistry`.

A trusted provider registration binds:

- Phase-5 `executor_id`;
- Phase-5 `adapter_id`;
- actual `CapabilityExecutor` factory/object;
- runtime `CapabilityDescriptor` identity;
- supported runtime API version;
- optional deterministic health probe implementations.

Rules:

- package JSON cannot contain module/import/executable paths;
- the provider registry is code, not data;
- a package can activate only when its manifest references a trusted provider already present in the active accepted release;
- future Phase-9 changes may add provider code through EngineeringChange + Phase 7;
- provider-registry code is a protected engineering surface;
- persistent package metadata never selects an arbitrary execution backend;
- v1 providers may be trusted in-process Python implementations, but the provider abstraction must remain execution-model neutral so a later reviewed WASM/AppContainer/subprocess executor can implement the same trusted CapabilityExecutor boundary without redesigning package lifecycle truth.

## 6. Release package source

Introduce `CapabilityPackageSource` protocol.

Phase-8 v1 production implementation:

`ReleaseCapabilityPackageSource`

reads deterministic package JSON files from one fixed trusted directory inside the exact active release.

It:

- refuses symlinks/path escape;
- uses JSON Schema 2020-12;
- canonicalizes and digests every descriptor;
- never imports code;
- never installs dependencies;
- never makes network calls.

Future OCI/TUF sources can implement the protocol later.

## 7. Durable registry store

Introduce `CapabilityRegistryStore` with dedicated versioned SQLite persistence.

Default Windows path:

`%LOCALAPPDATA%\JARVIS\capabilities\registry.sqlite3`

### 7.1 Tables

Conceptually:

#### capability_packages

Immutable admitted package records:

- package identity/version/digest;
- capability ID;
- manifest identity/digest;
- admitted release SHA;
- package disposition;
- admitted timestamp;
- evidence digest.

#### capability_registry

One mutable CAS row per managed capability:

- capability ID;
- selected package identity/version/digest;
- desired activation state;
- generation;
- updated timestamp.

#### capability_lifecycle_events

Append-only:

- event ID;
- capability ID;
- package identity/version/digest;
- event kind;
- previous/new generation;
- reason code;
- Authority/evidence refs where applicable;
- timestamp;
- canonical event digest.

### 7.2 Package disposition

Keep package eligibility separate from activation:

- `AVAILABLE`;
- `RETIRED`;
- `QUARANTINED`.

`QUARANTINED` is terminal in v1. Recovery uses a new package version rather than mutating rejected history.

“Superseded” is represented by version-selection history, not a terminal package state, so an older AVAILABLE version can remain rollback-eligible.

### 7.3 Desired activation

Exactly:

- `ENABLED`;
- `DISABLED`.

This is durable owner/system intent, not proof the package can run.

### 7.4 Transaction and concurrency rule

Lifecycle mutation uses explicit transactional CAS. The registry row mutation and its lifecycle event are one atomic SQLite transaction.

Recommended v1 mutation boundary:

```text
BEGIN IMMEDIATE
-> verify expected generation
-> verify exact package identity/digest/disposition
-> update selected version / desired state
-> append lifecycle event for the resulting generation
COMMIT
```

A transaction may not commit lifecycle state without its event, and an event may not claim a transition whose CAS failed. Concurrent writers for one expected generation must produce one winner and a deterministic stale-generation rejection.

SQLite remains canonical domain truth. DBOS may orchestrate future long-running lifecycle work, but DBOS workflow state is never the capability registry.

## 8. Compatibility truth

Introduce immutable `CapabilityCompatibilityReportV1` evaluated against:

- package descriptor/digest;
- current release SHA;
- runtime API id/version;
- current platform;
- Phase-5 manifest validation;
- trusted provider presence;
- exact executor/adapter identity;
- referenced ArtifactStore objects and integrity;
- dependency/provenance references;
- trusted health-probe registrations;
- package disposition.

Verdicts:

- `READY`;
- `RESTART_REQUIRED`;
- `BLOCKED`.

Reason codes remain deterministic and machine-readable.

A report is evidence. It does not enable a package.

## 9. Effective execution state

For package-managed capability C:

```text
effective_enabled(C) =
    desired_state == ENABLED
    AND selected package == AVAILABLE
    AND current-release descriptor is exact
    AND compatibility == READY
    AND trusted provider exists
    AND required health is acceptable
    AND transition_fence == CLEAR
    AND applied_projection_generation == current_registry_generation
```

If any term becomes false, new capability routing fails closed.

Desired state is not silently rewritten when runtime reality changes.

## 10. Health integration

Use existing `HealthState`; do not create package-specific health enums.

For each package-managed capability expose a deterministic self-model component such as:

`capability.package:<capability_id>`

Required probe IDs in the Phase-5 manifest map only to trusted release-owned health probe implementations.

Rules:

- package data cannot provide executable probe code;
- required missing/stale health evidence blocks effective execution;
- DISABLED desired state projects `HealthState.DISABLED`;
- failed/incompatible state is visible to the future Autonomy Control Plane;
- model output cannot directly write HealthRegistry state.

## 11. Runtime integration

Existing `CapabilityRuntime` remains the execution engine.

Introduce two components between durable lifecycle truth and `CapabilityCatalog`:

- `CapabilityLifecycleReconciler`;
- `CapabilityRegistryProjection`.

The reconciler is deterministic, idempotent and Authority-free. It reads the exact active release, release package inventory, durable selected/desired state and generation, manifest/provider/artifact/provenance compatibility and current HealthRegistry evidence. It produces an immutable effective-state snapshot with deterministic reason codes.

The reconciler may make execution less permissive when evidence is missing/stale/invalid. It may not create desired state, grant Authority, lower package disposition or make execution more permissive than authorized durable intent.

Reconciliation runs at least on startup, package admission/rescan, successful lifecycle mutation, active-release identity change, relevant health change where practical, and a bounded periodic safety sweep.

The projection:

- produces execution-enabled descriptors only for effectively enabled packages;
- carries the applied registry generation;
- fails closed for PACKAGE_MANAGED routing while a capability is transition-fenced or the applied generation is stale;
- preserves discovery-only descriptors as execution-disabled;
- preserves current core built-ins that have not yet migrated;
- marks inventory management mode:
  - `CORE_PINNED`;
  - `PACKAGE_MANAGED`.

The hot routing path should use an atomic in-process registry/effective snapshot rather than querying SQLite for every invocation. Canonical SQLite truth is loaded/reconciled into that snapshot.

Existing Hands semantic operations remain owned by `HandsCapabilityRegistry`.

A package may implement an existing semantic operation only when its trusted provider is registered for that operation. Phase 8 does not permit package metadata to invent new Hands semantics.

## 12. Enable / disable behavior

### Transition fence

Every state-changing PACKAGE_MANAGED lifecycle operation uses a per-capability transition fence.

Before the durable mutation, the in-process projection makes that capability temporarily non-routable for new work. This closes the failure window where durable truth changes but a crash or projection-refresh failure leaves stale routing active.

General transition shape:

```text
acquire per-capability transition fence
-> remove new routing for that capability
-> compute exact current compatibility
-> obtain/consume required Authority
-> atomic registry CAS + lifecycle-event commit
-> reconcile from committed durable truth
-> verify effective routing/health
-> release transition fence
```

If validation, Authority or DB commit fails, durable desired state remains unchanged and reconciliation restores the prior effective truth.

If DB commit succeeds but runtime reconciliation fails, desired state remains committed but effective routing stays blocked until reconciliation succeeds.

### Disable

Disable is a routing decision, not Python unloading.

- new resolutions stop before/through the durable transition, not after a best-effort refresh;
- in-flight operations may finish unless a trusted cancellation contract exists;
- loaded Python objects may remain resident until normal process restart.

### Enable

Enable is allowed only after exact package admission and a current READY compatibility report.

If the trusted provider is already present in the current runtime, reconciliation can make it routable without Python re-import/reload after the authorized registry commit.

If code/provider presence changed, activation reports `RESTART_REQUIRED` and uses the normal supervisor/release-start boundary; Phase 8 never hot-reloads code.

## 13. Version selection and rollback

Only one package version may be selected per capability.

Registering a new version never auto-selects or auto-enables it.

Version switch:

1. acquire the capability transition fence and stop new routing;
2. verify candidate package is AVAILABLE;
3. verify exact descriptor/provider exists in the current release;
4. produce a current compatibility report;
5. obtain/consume required Authority bound to exact package, compatibility digest and expected generation;
6. atomically CAS selected package generation **and append the lifecycle event in the same SQLite transaction**;
7. reconcile runtime projection from committed durable truth;
8. verify health/routing and applied generation;
9. release the transition fence.

Rollback to an older version uses the same path.

If the old descriptor/provider is not shipped by the current accepted release, package-level rollback is **BLOCKED**. Returning to older code then requires normal EngineeringChange/Phase-7 production rollback/change.

## 14. Registry lifecycle Authority

Do not build another approval system.

### Admission

Deterministic admission of package metadata already present in an accepted release is non-executing validation and may occur automatically.

### State-changing operations

These go through existing Authority with an exact proposal binding:

- capability ID;
- package ID/version/digest;
- current registry generation;
- requested selected version / enable / disable action;
- compatibility-report digest;
- manifest risk floor;
- source owner turn or approved EngineeringChange artifact.

Authority risk must be at least the manifest's accepted floor plus persistent-system-change semantics.

Automatic safety quarantine may make execution less permissive immediately without waiting for owner approval, but it must create durable evidence/incident state.

## 15. Phase-9 integration

Phase 9 will create new capability code/package descriptors through the existing engineering lifecycle.

Expected flow:

```text
owner capability goal
-> discovery/research
-> owner-approved architecture
-> isolated implementation
-> Phase-5 manifest/dependency/provenance
-> package descriptor
-> verification / hardware acceptance
-> Phase-7 promotion
-> new release starts
-> package admission
-> approved activation intent
-> registry enable/select
-> health verification
```

No Phase-9 path may bypass Phase-8 package admission.

## 16. Artifact retention

Use Phase-5 `ArtifactRetentionReferences`.

Artifacts remain retained while referenced by:

- any AVAILABLE package shipped by the current release;
- selected package;
- bounded rollback history;
- unresolved lifecycle/incident evidence.

Retirement does not immediately delete bytes.

Garbage collection is deterministic and separate from lifecycle mutation.

## 17. Core migration

Phase 8 does not force every existing built-in executor into the new registry.

Initial behavior:

- current built-ins remain `CORE_PINNED`;
- package-managed capabilities can coexist;
- inventory APIs show both;
- Phase 9 requires new capabilities to be PACKAGE_MANAGED.

Later existing core capabilities can migrate individually by adding reviewed Phase-5 manifests/package descriptors/providers without changing the registry architecture.

## 18. Protected surfaces

Add at minimum:

- `src/jarvis/capability_registry/`;
- package schema/descriptor definitions;
- capability provider registry;
- registry migrations;
- runtime projection/effective-enable policy;
- package lifecycle Authority bridge;
- lifecycle acceptance/evaluation tests.

Ordinary Phase-6 source repair may not silently modify these surfaces.

## 19. Restart / crash reconciliation

Every mutation is idempotent by:

- package digest;
- registry generation;
- lifecycle event key.

On restart, PACKAGE_MANAGED routing begins fail-closed and startup reconciliation runs before those packages become routable:

- verify the exact active Phase-7 release identity using the existing release boundary;
- re-scan exact release package descriptors;
- revalidate selected package;
- re-evaluate compatibility;
- restore durable desired state;
- regenerate current health/effective-state snapshot;
- publish one generation-consistent runtime projection;
- never replay an already committed generation transition.

Crash cases are intentionally asymmetric and safe:

- crash before DB commit -> canonical lifecycle truth did not change;
- crash after DB commit but before projection update -> no process remains to route stale work, and startup reconciliation rebuilds from committed truth;
- projection/reconcile failure while process remains alive -> affected PACKAGE_MANAGED capability stays blocked.

No mutable “half enabled” permission state may outlive the generation-fenced projection.

## 20. Acceptance matrix

Phase 8 must deterministically test at least:

1. package schema validation;
2. strict SemVer;
3. same version / changed digest rejected;
4. unknown manifest version rejected;
5. manifest digest mismatch rejected;
6. untrusted executor/provider rejected;
7. raw import/module/command fields structurally impossible;
8. missing/corrupt artifact rejected/quarantined;
9. unsupported runtime API blocked;
10. platform mismatch blocked;
11. registration does not enable execution;
12. enable requires exact READY compatibility;
13. stale generation/CAS rejected;
14. exactly one selected version;
15. disable immediately removes new routing;
16. disabled code is not falsely claimed unloaded;
17. new version registration does not auto-switch;
18. version switch records exact event;
19. rollback to current-release-supported old version succeeds;
20. old version absent from current release cannot activate;
21. RETIRED cannot select;
22. QUARANTINED cannot select;
23. required missing/failed health blocks execution;
24. desired enabled remains distinct from observed blocked;
25. registry survives process restart;
26. newer unsupported registry schema fails closed;
27. installed Python entry point without trusted provider cannot execute;
28. artifact retention includes selected/rollback references;
29. existing CORE_PINNED capabilities remain unaffected;
30. existing Authority/Phase5/Phase7 regressions remain green;
31. disable commit cannot leave the old package routable;
32. version-switch commit cannot leave the previous generation routable;
33. reconciler is idempotent;
34. crash after registry commit but before projection refresh recovers correctly on startup;
35. registry generation mutation and lifecycle event append are atomic;
36. reconciler never grants Authority or silently changes desired state;
37. DBOS unavailability does not invalidate or replace canonical capability-registry truth;
38. concurrent mutations with one expected generation produce one winner and one stale-CAS rejection;
39. stale in-process projection generation fails closed for PACKAGE_MANAGED routing;
40. startup with corrupt/unknown selected package remains blocked rather than falling back;
41. active release SHA change invalidates incompatible package projection until exact new-release support passes;
42. package metadata cannot select an arbitrary execution model;
43. CORE_PINNED routing remains unaffected by package-registry generation fencing;
44. Windows file/restart test proves registry handles close cleanly and the database can be reopened/replaced by the test harness;
45. safety quarantine removes new routing even while durable desired state remains ENABLED.

Windows CI must exercise registry file handles/restart behavior. Final owner-machine acceptance should use a harmless disposable representative package and one consolidated PowerShell block.

## 21. Exit criteria

Phase 8 is complete when JARVIS can truthfully report and govern:

- immutable package versions;
- exact manifest/evidence;
- selected version;
- desired enabled/disabled state;
- compatibility verdict;
- live health/effective availability;
- lifecycle history;
- safe version rollback eligibility;

and when a package cannot gain execution merely from metadata, installation or discovery.

## 22. Non-goals

Phase 8 does not:

- autonomously research/build a requested new capability;
- browse public plugin marketplaces;
- install arbitrary wheels into production;
- auto-load Python entry points;
- introduce OCI/TUF infrastructure;
- introduce WASI/Wasmtime/Extism;
- introduce Windows AppContainer/LPAC execution as part of v1;
- introduce Kubernetes, Dapr, Nix or another external lifecycle control plane;
- hot-reload Python code;
- replace Hands;
- replace CapabilityRuntime;
- replace EngineeringChange;
- change owner promotion Authority.
