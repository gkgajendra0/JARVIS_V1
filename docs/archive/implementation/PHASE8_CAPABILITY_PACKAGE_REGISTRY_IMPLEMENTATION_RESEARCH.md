# Phase 8 — Capability Package + Registry Lifecycle Implementation Research

## Status

**IMPLEMENTATION-FOCUSED RESEARCH COMPLETE — ARCHITECTURE REVISION REQUIRED — NO RUNTIME IMPLEMENTATION AUTHORIZED — 2026-09-27**

This is the second Phase-8 research pass. The original research established the package/lifecycle direction. This pass answers a narrower question before implementation:

> Is JARVIS about to build lifecycle infrastructure that an existing mature technology already solves better, and what implementation patterns should be adopted before Phase 8A–8F begin?

The answer is:

> **No existing framework replaces Phase 8 as a whole. JARVIS still needs a small JARVIS-owned lifecycle registry because its trust boundary combines accepted-release identity, Phase-5 manifest/provenance evidence, existing Authority, health truth, desired/effective state and runtime routing. However, several mature systems provide patterns that should materially change the implementation design.**

The most important change is to make Phase 8 explicitly **reconciliation-driven and generation-fenced**, rather than treating lifecycle mutation as “database write followed by best-effort catalog refresh”.

No runtime code should be written until the architecture document incorporates the conclusions below and receives owner approval.

---

## 1. Repository facts constraining the design

Current protected-main behavior was re-inspected before this research.

### CapabilityRuntime already owns execution

`src/jarvis/capabilities/runtime.py` already performs:

```text
resolve
-> validate descriptor / operation
-> Authority authorize
-> consume Authority
-> execute trusted executor
-> audit
```

It maintains trusted executor objects separately from the catalog. Phase 8 therefore needs to control **which trusted descriptors are routable**, not replace execution.

### Phase 5 already owns package-security primitives

Existing accepted code already supplies:

- strict `CapabilityManifest` admission;
- trusted executor/adapter identities;
- immutable SHA-256 ArtifactStore with verify-on-read and quarantine;
- provenance and dependency evidence;
- versioned SandboxProfiles;
- secret scopes and leases;
- bounded discovery;
- canonical RFC-8785-style digests.

Phase 8 must remain a lifecycle layer around this substrate.

### HealthRegistry already owns observed health

`src/jarvis/self_model/health.py` already supplies deterministic, freshness-aware health truth and explicitly prevents model-authored health state.

No parallel package-health system is justified.

### Phase 7 already owns exact active-release identity

`src/jarvis/promotion/release.py` already verifies the active immutable release slot and exposes exact:

- release SHA;
- release root;
- promotion attempt;
- configuration digest.

`load_active_release_for_startup()` verifies that the release root is under the managed releases directory, is not a symlink, matches the recorded Git SHA and has no tracked source mutation.

Phase 8 package-source identity should reuse this exact boundary instead of reimplementing release verification.

### JARVIS already separates canonical truth from durable execution

Current Work architecture deliberately keeps:

- `SQLiteWorkStore` = canonical JARVIS domain truth;
- DBOS = durable execution mechanics.

`WorkOrchestrator.reconcile_active()` already demonstrates the desired architecture: canonical state is read and durable execution is reconciled toward it.

Phase 8 should repeat this separation rather than put package truth in DBOS.

---

## 2. Technology decision matrix

| Technology / pattern | Decision for Phase 8 | Why |
|---|---|---|
| Kubernetes controller/reconciliation pattern | **ADOPT PATTERN, NOT KUBERNETES** | Desired state and observed/current state are explicitly separate; deterministic controllers continuously reconcile them. This maps directly to desired ENABLED/DISABLED versus effective READY/BLOCKED. |
| Nix immutable store/profile generations | **BORROW PRINCIPLES** | Immutable versions and generation-based rollback validate the package immutability/rollback model. JARVIS already has ArtifactStore and accepted release slots, so deploying Nix would duplicate infrastructure. |
| SQLite WAL | **ADOPT** | Correct fit for one local JARVIS runtime: transactional canonical truth, concurrent readers, one serialized writer, no server dependency. |
| DBOS | **REUSE FOR DURABLE OPERATIONS WHEN NEEDED; NOT REGISTRY TRUTH** | DBOS persists workflow/step execution and recovery. Package lifecycle state is domain truth and must survive independently of workflow machinery. |
| Python PyPA entry points | **REJECT AS EXECUTION AUTHORITY** | Entry points advertise importable Python objects and loading them imports modules. “Installed” must never imply trusted/routable. |
| Pluggy | **DO NOT ADOPT IN V1** | Mature hook registration but in-process plugin code still executes as host code; it adds little beyond JARVIS’s existing trusted executor/provider model. |
| HashiCorp go-plugin | **BORROW DESIGN PRINCIPLES, DO NOT DEPLOY** | Good protocol-version negotiation, checksum verification and subprocess lifecycle isolation, but it is executable-plugin infrastructure and does not solve JARVIS Authority/provenance/registry semantics. |
| Dapr pluggable components | **REJECT FOR PHASE 8** | Separate-process gRPC model is useful, but Dapr is a distributed sidecar/building-block runtime and native Windows pluggable-component development relies on WSL/Unix sockets. Too much unrelated infrastructure. |
| WebAssembly Component Model / WASI | **DEFER, PRESERVE COMPATIBILITY** | Strong long-term portable isolation/interface model. Phase 8 should not force a new execution runtime into the accepted source-backed lifecycle. |
| Extism | **DEFER; PREFERRED FUTURE WASM PROVIDER CANDIDATE** | Concrete Python host SDK, SHA-bound Wasm, memory constraints, host/path allowlists and opt-in WASI. Strong candidate for future generated/third-party capabilities behind the provider boundary. |
| Windows AppContainer / LPAC | **DEFER AS FUTURE NATIVE-PROCESS BACKEND** | Real least-privilege filesystem/network/process/window isolation on Windows, but it is an execution sandbox, not lifecycle/package truth. |
| Windows Sandbox | **REJECT FOR NORMAL CAPABILITY EXECUTION** | Strong VM isolation but disposable and heavyweight; useful for testing unknown software, not normal low-latency JARVIS capabilities. |
| OCI content descriptors | **ADOPT DESCRIPTOR SEMANTICS** | mediaType + digest + size is a mature interoperable external-artifact identity model. |
| OCI registry / ORAS | **DEFER** | Useful future remote artifact/source transport. Local Phase-8 packages already originate from exact accepted releases and ArtifactStore. |
| TUF | **DEFER** | Solves remote repository metadata/key rotation/freeze/rollback/consistent-view attacks. There is no remote capability repository in Phase-8 v1. |
| Sigstore / in-toto | **REUSE THROUGH PHASE 5** | Verification/attestation evidence should remain part of existing provenance rather than creating a second signing system. |
| SLSA | **REUSE AS PROVENANCE VOCABULARY** | Current SLSA 1.2 describes source/build provenance and verified supply-chain properties. Do not claim a SLSA level unless independently demonstrated. |
| CycloneDX | **KEEP OPTIONAL SBOM EVIDENCE** | Mature interoperable BOM/evidence format; no reason to create JARVIS SBOM semantics. |
| OPA | **REUSE EXISTING AUTHORITY POLICY PATH** | OPA is a policy decision point, not a lifecycle control plane. Phase 8 must not create a competing approval system. |
| VS Code extension model | **BORROW MANIFEST/ACTIVATION IDEAS ONLY** | VS Code extensions run with host-equivalent permissions; it is explicitly not an isolation model suitable for autonomous JARVIS capability acquisition. |
| SemVer 2.0.0 | **ADOPT** | Released contents are immutable and changed contents require a new version; exact match for package version-reuse policy. |
| JSON Schema Draft 2020-12 | **ADOPT** | Still the current published JSON Schema specification as of this research. |

---

## 3. External evidence behind the major decisions

### Kubernetes reconciliation

Kubernetes controllers operate control loops that compare desired state with current state and act to bring them closer.

Reference:

- https://kubernetes.io/docs/concepts/architecture/controller/

This is a better model for Phase 8 than direct imperative lifecycle mutations because compatibility, health and release identity can change after the owner’s desired state was recorded.

### Nix generation model

Nix stores package outputs immutably and profile changes create generations rather than mutating prior packages. Earlier generations remain rollback targets.

References:

- https://wiki.nixos.org/wiki/Nix_store
- https://wiki.nixos.org/wiki/Generation

JARVIS does not need Nix itself. Its accepted release slots, ArtifactStore, immutable package rows, registry generation and lifecycle history already provide the primitives needed to borrow this behavior.

### SQLite transaction model

SQLite WAL permits readers while one writer appends to WAL, while writes remain serialized.

`BEGIN IMMEDIATE` obtains the write transaction before mutation, avoiding a read snapshot later failing to upgrade because another writer moved ahead.

References:

- https://www.sqlite.org/wal.html
- https://www.sqlite.org/isolation.html
- https://www.sqlite.org/atomiccommit.html

This supports a dedicated local capability registry with explicit transactional CAS.

### DBOS

DBOS workflows durably checkpoint workflow and step execution and resume after interruptions. DBOS’s system database is explicitly workflow/step state.

References:

- https://docs.dbos.dev/python/tutorials/workflow-tutorial
- https://docs.dbos.dev/python/tutorials/database-connection

Therefore:

> **CapabilityRegistryStore is canonical capability domain truth. DBOS may durably orchestrate a future multi-step lifecycle operation, but DBOS is not the registry.**

This matches JARVIS’s existing WorkStore/DBOS architecture.

### Python entry points and Pluggy

PyPA entry points point to importable Python objects; resolution uses module import.

Reference:

- https://packaging.python.org/en/latest/specifications/entry-points/

Pluggy is a mature in-process hook/plugin registry.

Reference:

- https://pluggy.readthedocs.io/en/latest/

Neither creates the JARVIS trust boundary. Automatic discovery/loading would weaken it.

### Out-of-process / portable plugin candidates

HashiCorp go-plugin demonstrates:

- executable checksum verification;
- protocol/version negotiation;
- subprocess lifecycle isolation;
- RPC/gRPC boundaries.

Reference:

- https://github.com/hashicorp/go-plugin

Dapr demonstrates language-neutral pluggable gRPC components, but its component model is oriented to Dapr building-block APIs and pluggable components commonly communicate over Unix Domain Sockets.

References:

- https://docs.dapr.io/developing-applications/develop-components/pluggable-components/pluggable-components-overview/
- https://docs.dapr.io/operations/components/pluggable-components-registration/

The WebAssembly Component Model/WASI is a more promising long-term generic capability boundary.

Extism is a concrete host framework offering a Python SDK and a manifest that can constrain Wasm hash, memory, allowed network hosts and allowed paths.

References:

- https://component-model.bytecodealliance.org/
- https://docs.wasmtime.dev/
- https://extism.org/docs/concepts/manifest/

Phase-8 v1 should **not** add these runtimes. Its provider contract should simply avoid assuming that all future providers are Python in-process implementations.

### Windows-native isolation

AppContainer/LPAC isolates processes from files, registry, network, other processes/windows, devices and credentials unless access is granted.

Reference:

- https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation

Windows Sandbox provides hardware-virtualized disposable isolation, but is designed for isolated application/testing sessions and is not an embedded plugin substrate.

Reference:

- https://learn.microsoft.com/en-us/windows/security/threat-protection/windows-sandbox/windows-sandbox-overview

### OCI/TUF/Sigstore/SLSA/CycloneDX

OCI descriptors define the useful external-artifact identity tuple:

- media type;
- digest;
- byte size.

Reference:

- https://specs.opencontainers.org/image-spec/descriptor/?v=v1.1.1

ORAS demonstrates arbitrary artifact/referrer transport over OCI registries:

- https://oras.land/docs/commands/oras_attach/

TUF’s Root/Targets/Snapshot/Timestamp roles solve remote repository trust and freshness/consistent-view problems:

- https://theupdateframework.io/docs/metadata/

Sigstore/Cosign provides signature and attestation verification:

- https://docs.sigstore.dev/cosign/verifying/verify/

SLSA 1.2 is the current approved SLSA specification during this research:

- https://slsa.dev/spec/v1.2/

CycloneDX provides interoperable BOM/component/evidence representation:

- https://cyclonedx.org/specification/overview/

These are evidence/distribution technologies, not a replacement for the JARVIS lifecycle registry.

### OPA

OPA decouples policy evaluation from application code and provides decision/audit interfaces, but explicitly does not ship a complete lifecycle control plane.

References:

- https://www.openpolicyagent.org/docs/integration
- https://www.openpolicyagent.org/docs/management-introduction

Existing JARVIS Authority/OPA remains the policy boundary.

---

## 4. Central implementation change: add a lifecycle reconciler

The original architecture correctly separated desired state from effective execution, but it did not make reconciliation a first-class component.

Add:

`CapabilityLifecycleReconciler`

Conceptually:

```text
exact active release
        +
release package inventory
        +
durable registry desired state/generation
        +
manifest/provider/artifact/provenance truth
        +
fresh HealthRegistry evidence
        |
        v
CapabilityLifecycleReconciler
        |
        v
immutable effective-state snapshot
        |
        v
CapabilityRegistryProjection
        |
        v
existing CapabilityCatalog / CapabilityRuntime
```

### Reconciler properties

It must be:

- deterministic;
- idempotent;
- Authority-free;
- unable to invent desired state;
- unable to lower package disposition;
- unable to make execution more permissive than durable authorized intent;
- allowed to make execution **less permissive** when current evidence is missing, stale or invalid;
- explicit about deterministic reason codes.

### Reconcile triggers

At minimum:

1. runtime startup;
2. package admission/rescan;
3. successful lifecycle registry mutation;
4. active release identity change;
5. relevant health-state change where practical;
6. bounded periodic safety sweep.

Periodic reconciliation is a safety net, not the primary activation mechanism.

---

## 5. Critical race found in the original design

The original sequence effectively allowed:

```text
commit desired DISABLED
-> refresh runtime projection
```

That contains an unacceptable failure window:

> The durable registry can say DISABLED while a crash/refresh failure leaves the previous package routable in the still-running process.

The implementation needs a generation-aware transition fence.

### Required transition semantics

For a package-managed lifecycle mutation:

```text
acquire per-capability transition fence
-> make that capability temporarily non-routable in the in-process projection
-> compute current exact compatibility
-> obtain/consume required Authority for the exact proposal
-> BEGIN IMMEDIATE registry transaction
     CAS expected generation
     mutate selected version / desired state
     append exact lifecycle event
   COMMIT
-> reconcile projection from committed durable truth
-> verify effective routing/health
-> release transition fence
```

If validation/Authority/DB commit fails:

- canonical desired state is unchanged;
- projection is restored by reconciliation from existing durable truth.

If the DB commit succeeds but projection update fails:

- desired truth remains committed;
- **effective execution stays blocked**;
- the reconciler repairs the projection later.

If the process crashes after commit:

- there is no live process left routing stale work;
- startup reconciliation rebuilds projection from durable truth before package-managed routing becomes available.

---

## 6. Generation-aware runtime projection

The projection needs an applied registry generation.

For PACKAGE_MANAGED capabilities, new routing must fail closed when:

- the capability is under a transition fence;
- projection generation is stale relative to the current in-process registry generation/epoch;
- compatibility evidence no longer matches current release/package;
- required health is stale or unacceptable.

Do not perform a SQLite query for every capability invocation solely to discover the generation. Maintain an atomic in-process registry snapshot rebuilt from canonical storage; lifecycle commits and reconciler swaps update that snapshot.

This creates a cheap routing check while preserving fail-closed behavior.

CORE_PINNED capabilities remain outside this new lifecycle gate during initial migration.

---

## 7. Transaction boundary

A lifecycle state change and its durable lifecycle event are **one transaction**.

Required atomicity:

```text
registry CAS row update
+
append lifecycle event
=
one SQLite commit
```

Never allow:

- state changed with no event;
- event claiming state changed when CAS failed.

Recommended mutation transaction:

- `BEGIN IMMEDIATE`;
- verify expected generation;
- verify exact selected package identity/digest/disposition;
- update one registry row;
- append lifecycle event using the resulting generation;
- commit.

Concurrent mutations for one capability should produce exactly one winner for a given expected generation.

---

## 8. Package/schema implementation guidance

### Keep package data allowlisted, not blacklist-driven

The package JSON schema should use a closed object model, including `additionalProperties: false` or the equivalent at package-owned object layers.

That is better than scanning recursively for suspicious words such as “command”, because legitimate evidence metadata could contain those words.

### Keep the three version dimensions

1. package schema version;
2. Phase-5 manifest contract version;
3. capability package release SemVer.

Do not introduce implicit “latest schema” fallback.

### SemVer

SemVer 2.0.0 explicitly says released contents must not be modified and changes require a new version.

Reference:

- https://semver.org/

No new runtime dependency is justified solely for basic strict SemVer validation. A small deterministic implementation derived from the specification, with exhaustive precedence/invalid-input tests, is acceptable.

### JSON Schema

JSON Schema’s official specification page still identifies Draft 2020-12 as the current published version.

Reference:

- https://json-schema.org/specification

If an implementation library is added, it must be pinned and pass Phase-5 dependency/provenance controls. Do not add a validator dependency merely because the format exists; a repository-owned schema plus deterministic contract parser may be enough if it can be shown to enforce the same accepted contract.

---

## 9. Provider boundary must remain execution-model neutral

The Phase-8 package descriptor must continue to reference only trusted logical identities, not import paths or executable paths.

The release-owned provider registry can internally map a trusted provider to an implementation.

V1 may support only trusted in-process Python providers.

The provider abstraction must not make “Python object in this process” part of the persistent package contract. This preserves a future path to:

- isolated WASM/Extism provider;
- Windows AppContainer/LPAC subprocess provider;
- another reviewed executor substrate.

Adding one of those execution models later remains a governed source/architecture/security change. Package metadata cannot select an arbitrary runtime backend.

---

## 10. No off-the-shelf registry should replace the JARVIS registry

The examined systems each solve only a subset:

- Nix: immutable builds/generations, not JARVIS Authority/health/routing;
- Kubernetes: reconciliation, not local package provenance/Authority;
- DBOS: durable operations, not canonical package domain state;
- Pluggy/PyPA: plugin registration/import, not trust;
- go-plugin/Dapr/Extism: execution boundaries, not JARVIS lifecycle governance;
- OCI/TUF/Sigstore: artifact distribution/trust evidence, not activation state;
- OPA: policy decisions, not package lifecycle state.

Therefore the custom Phase-8 layer is justified **only if it stays thin**:

1. immutable package identity/evidence;
2. selected version + desired state;
3. generation/CAS;
4. append-only lifecycle evidence;
5. deterministic compatibility;
6. deterministic reconciliation into existing runtime routing.

Anything beyond those responsibilities should be delegated to existing JARVIS systems or standards.

---

## 11. Revised implementation boundary

The research recommends Phase 8 own exactly these new components:

```text
CapabilityPackageV1
PackageArtifactDescriptorV1
ReleaseCapabilityPackageSource
CapabilityProviderRegistry
CapabilityRegistryStore
CapabilityCompatibilityEvaluator
CapabilityLifecycleService
CapabilityLifecycleReconciler
CapabilityRegistryProjection
```

Where:

- `CapabilityLifecycleService` owns Authority-bound mutation + transition fencing;
- `CapabilityLifecycleReconciler` owns idempotent convergence from durable truth to effective runtime projection;
- `CapabilityRegistryStore` owns domain truth only;
- `CapabilityProviderRegistry` contains trusted release-owned executable bindings;
- existing `CapabilityRuntime` remains execution;
- existing `HealthRegistry` remains health;
- existing Authority/OPA remains permission;
- existing Phase-5 substrate remains dependency/provenance/sandbox/secret/artifact truth;
- Phase 7 remains source release promotion/rollback.

---

## 12. Additional acceptance tests required by this research

Add to the original Phase-8 acceptance matrix:

31. disable commit cannot leave the old package routable;
32. version-switch commit cannot leave the previous generation routable;
33. reconciler is idempotent;
34. crash after registry commit but before projection refresh recovers correctly on startup;
35. registry generation mutation and lifecycle event append are atomic;
36. reconciler never grants Authority or silently changes desired state;
37. DBOS unavailable does not invalidate or replace canonical capability-registry truth;
38. concurrent mutations with one expected generation produce one winner and one stale-CAS rejection;
39. stale in-process projection generation fails closed for package-managed routing;
40. startup with corrupt/unknown selected package remains blocked rather than falling back;
41. active release SHA change invalidates incompatible package projection until exact new-release support passes;
42. package metadata cannot select an arbitrary execution model;
43. CORE_PINNED routing remains unaffected by package-registry generation fencing;
44. Windows process/file restart test proves registry handles are closed and the database can be reopened/replaced by the test harness;
45. safety quarantine removes new routing even if desired state remains ENABLED.

---

## 13. Deferred future investigations

These are deliberately not Phase-8 v1 dependencies:

### Isolated generated/third-party capability execution

When Phase 9 or later first needs code that should not share JARVIS process privileges, perform a separate security/performance evaluation of:

1. Extism/WASI;
2. direct Wasmtime Component Model;
3. Windows AppContainer/LPAC subprocess;
4. hardened ordinary subprocess + Job Object only as a lower-isolation fallback.

The choice should be benchmarked on the actual Windows owner machine.

### Remote capability repository

Only when packages come from outside the accepted local release, evaluate together:

- OCI/ORAS transport;
- TUF repository metadata;
- Sigstore bundle verification;
- SLSA/in-toto provenance;
- CycloneDX SBOM.

Do not pre-deploy that infrastructure now.

---

## 14. Final research conclusion

The original Phase-8 direction is fundamentally correct, but implementation should **not** start from the original document unchanged.

The architecture should be revised to add:

1. an explicit `CapabilityLifecycleReconciler`;
2. a fail-closed lifecycle transition fence;
3. generation-aware projection/routing;
4. one-transaction CAS + lifecycle-event atomicity;
5. explicit DBOS/domain-store separation;
6. execution-model-neutral trusted provider registration;
7. the expanded crash/concurrency acceptance matrix.

Once those changes are incorporated into the Phase-8 architecture/implementation plan and CI is green, the owner can make the Phase-8 architecture decision with substantially less implementation risk.
