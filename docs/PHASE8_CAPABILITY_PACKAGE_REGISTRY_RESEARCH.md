# Phase 8 — Capability Package + Registry Lifecycle Research

## Status

**FOUNDATION RESEARCH COMPLETE — IMPLEMENTATION RESEARCH V2 COMPLETE — SEE `PHASE8_CAPABILITY_PACKAGE_REGISTRY_IMPLEMENTATION_RESEARCH.md` — 2026-09-27**

Phase 8 turns the accepted Phase-5 manifest/security primitives into durable capability lifecycle truth. It does not acquire arbitrary new capabilities; Phase 9 owns owner-requested capability acquisition.

## 1. Repository findings

Protected `main` already contains the foundations Phase 8 must extend:

- `jarvis.capabilities` has provider-neutral `CapabilityDescriptor`, discovery snapshots/catalogs, a governed runtime, and static trusted executors.
- `HandsCapabilityRegistry` owns semantic operation definitions independently of concrete executors.
- Phase 5 already defines immutable `CapabilityManifest` and `CapabilityManifestRegistry`.
- Phase-5 manifest admission already validates exact trusted executor/adapter IDs, operation subsets, dependency/provenance digests, secret scopes, SandboxProfiles, discovery scopes, Authority floors, verification contracts, hardware acceptance, health probe IDs, resource requirements and platform constraints.
- the manifest is declarative evidence; it never imports or executes code.
- `ArtifactStore` already provides immutable SHA-256 content-addressed storage, quarantine, verify-on-read and retention references.
- dependency acquisition already uses governed uv/PEP-751, exact wheel hashes and provenance rather than arbitrary package installation.
- bounded discovery intentionally projects newly found services as execution-disabled.
- `HealthRegistry` already owns deterministic health states and explicitly prevents model-authored health truth.
- existing durable stores use SQLite/WAL, versioned migrations, deterministic conflict handling and fail-closed schema checks.
- Phase 7 now provides exact promotion, immutable Windows release slots, runtime release identity and rollback.

The missing capability is therefore not another execution engine. The missing layer is durable package identity, selected version, enable/disable intent, compatibility truth, lifecycle history and safe runtime projection.

## 2. Important versioning distinction

Phase-5 `CapabilityManifest.manifest_version` is the manifest contract version. The current trusted validator accepts only manifest version 1.

It must not be overloaded as a package release version.

Phase 8 therefore needs three distinct version dimensions:

1. **package schema version** — the Phase-8 contract format;
2. **manifest contract version** — currently Phase-5 manifest v1;
3. **capability package release version** — semantic release identity such as `1.2.0`.

Mixing these would make compatibility and migration ambiguous.

## 3. External technology research

### 3.1 Semantic Versioning

SemVer 2.0.0 provides the right human-facing capability release language: MAJOR/MINOR/PATCH and immutable released contents.

Disposition: **ADOPT strict SemVer for capability package release versions.**

JARVIS does not need a new dependency merely to parse the v1 subset; the parser can be a small trusted deterministic contract implementation with exhaustive tests.

### 3.2 JSON Schema

JSON Schema Draft 2020-12 remains the current published JSON Schema specification and is already used by Phase-5 manifests.

Disposition: **KEEP Draft 2020-12 for Phase-8 package interchange schema.**

### 3.3 Python entry points / importlib.metadata

PyPA entry points are a standard way for an installed distribution to advertise plugin components. Loading an entry point resolves/imports Python code.

Disposition: **DO NOT use installed entry points as automatic execution authority.**

A future source adapter may inspect entry-point metadata as candidate evidence, but an entry point is executable only after it maps to an already trusted release-owned provider/executor and passes normal package admission. Merely being installed must never make a capability runnable.

### 3.4 Installed Python distribution metadata

`.dist-info` provides METADATA, RECORD, optional entry-point/direct-url metadata and an SBOM directory. RECORD can provide installed-file hash/size evidence when present.

Disposition: **USE as supporting evidence where useful, never as JARVIS canonical lifecycle truth.**

### 3.5 CycloneDX

CycloneDX provides interoperable component/service/dependency BOM representation and an official attestation predicate.

Disposition: **KEEP CycloneDX SBOM references as package evidence.**

Do not invent a JARVIS-specific SBOM format.

### 3.6 OCI artifacts

OCI descriptors provide strong content-addressed identity using media type, digest and size, with artifact/subject relationships.

Disposition: **BORROW descriptor principles, DEFER an OCI registry.**

JARVIS already has a local content-addressed ArtifactStore. Running an OCI registry for a single-owner local Phase-8 lifecycle would add infrastructure without improving the immediate trust boundary. A future remote `CapabilityPackageSource` may use OCI without changing the registry model.

### 3.7 TUF

TUF Root/Targets/Snapshot/Timestamp metadata solves remote repository key rotation, target integrity, consistent views and stale/freeze attacks.

Disposition: **DEFER until JARVIS consumes a remote capability repository.**

Phase 8's first source is the exact accepted local release, so a TUF repository is unnecessary now. The package-source boundary should remain compatible with a future TUF-backed implementation.

### 3.8 Sigstore / attestations

Sigstore bundles can carry signature verification material and transparency-log evidence. JARVIS already consumes high-grade attestation/provenance through Phase 5.

Disposition: **REUSE existing provenance fields; allow future package attestation refs.**

Do not add another mandatory signing ceremony for source code already admitted through protected-main Phase-7 promotion.

### 3.9 WebAssembly Component Model / WASI

The Component Model/WASI provides strong typed host/guest interfaces and a promising future boundary for third-party/untrusted portable capabilities.

As of this research, WASI 0.3 is the current stable WASI line; WASI 0.3.0 was released 2026-06-11 and 0.3.1 on 2026-08-11. Runtime/toolchain adoption is still uneven across languages, and JARVIS does not currently use a WASM component runtime.

Disposition: **DEFER AS AN EXECUTION BACKEND, PRESERVE PROVIDER COMPATIBILITY.**

Do not encode Python in-process execution into the persistent package contract. A future reviewed WASM provider should be able to implement the same trusted executor boundary without changing package lifecycle semantics.

## 4. Dynamic loading / hot reload research conclusion

Python runtime reload is not a reliable unload/version-switch primitive: old object references are not rebound, extension modules may not support repeated initialization, and reload is not thread-safe.

Therefore Phase 8 must not claim that package disable/version selection unloads Python code.

- **disable** means immediately stop routing new requests to the package;
- in-flight operations are allowed to finish unless their trusted executor exposes a separate cancellation contract;
- source/provider code changes enter production only through Phase 7 and a normal process restart/release switch;
- no `importlib.reload`-based production lifecycle.

## 5. Package-source decision

Phase-8 v1 begins with one trusted source:

**ReleaseCapabilityPackageSource**

It reads declarative package descriptors shipped inside the exact immutable active JARVIS release.

Rules:

- no arbitrary filesystem scanning outside the active release;
- no package descriptor may contain shell commands, argv, executable paths, Python import paths, raw secrets or installer flags;
- a package descriptor references the existing Phase-5 manifest and trusted IDs only;
- actual executor/provider code must already exist in the accepted release;
- the same `(package_id, package_version)` may never be reused with different content.

Future sources can include OCI/TUF or trusted installed-distribution metadata, but they must produce the same normalized package contract.

## 6. Persistent-registry decision

Capability lifecycle is operational product state, not a WorkItem and not transient discovery.

Use a dedicated durable SQLite registry under:

`%LOCALAPPDATA%\JARVIS\capabilities\registry.sqlite3`

on Windows, with the equivalent XDG state location elsewhere.

Use:

- WAL;
- versioned/checksummed migrations;
- immutable admitted-package rows;
- optimistic generation/CAS for selected version and desired state;
- append-only lifecycle events;
- exact package/manifest/artifact digests;
- no secret plaintext.

Artifact bytes remain in the Phase-5 ArtifactStore; the registry stores identity/reference truth only.

## 7. Health decision

Do not create another health language.

Phase 8 reuses `self_model.health.HealthState`.

The durable registry owns desired state and selected version. Live deterministic health probes own observed health.

If a package declares required health probes, effective execution remains disabled until required current health evidence is acceptable. A package marked desired-enabled with missing/failed health stays desired-enabled but **effectively unavailable**, preserving the distinction between intent and reality.

## 8. Core capability migration decision

Phase 8 must not destabilize all current production capabilities simply to retrofit packaging.

Existing built-ins remain release-pinned core capabilities during the first implementation. Phase 8 adds a registry/inventory projection that distinguishes:

- `CORE_PINNED` — current trusted built-ins not yet lifecycle-managed;
- `PACKAGE_MANAGED` — capabilities governed by the new package registry.

All capabilities created through Phase 9 must be `PACKAGE_MANAGED`.

Migration of older core capabilities can happen incrementally without blocking Phase 8.

## 9. Security conclusions

Permanent Phase-8 rules:

1. package metadata is never execution Authority;
2. a package cannot name arbitrary imports/commands;
3. installed software does not become a JARVIS capability merely by advertising an entry point;
4. package admission cannot lower Phase-5 Authority/secret/sandbox/discovery constraints;
5. registration alone never enables execution;
6. only one selected version exists per managed capability;
7. package version contents are immutable;
8. integrity failure quarantines and fail-closes execution;
9. remote capability installation is Phase 9+, not Phase 8;
10. registry lifecycle code/migrations/provider maps are protected surfaces;
11. enabling/disabling/version selection goes through existing Authority, not a new approval system;
12. code-version mutation still uses EngineeringChange + Phase 7.

## 10. Technology selection

### Adopt now

- existing Phase-5 CapabilityManifest and validator;
- strict SemVer release identity;
- JSON Schema Draft 2020-12;
- RFC-8785-style canonical digest already used by JARVIS;
- existing SHA-256 ArtifactStore;
- existing dependency/provenance/SecretBroker/SandboxProfile contracts;
- dedicated SQLite durable registry;
- existing HealthRegistry;
- existing Authority;
- active-release-owned declarative package descriptors.

### Defer

- OCI remote registry;
- TUF repository;
- automatic PyPA entry-point plugin loading;
- standalone wheel/plugin installation into production;
- WASI/Wasmtime capability runtime;
- hot Python module reload/unload;
- Kubernetes/Argo/Spinnaker-style deployment infrastructure.

## 11. Research readiness

The foundation research was sufficient to choose the package/registry direction, but implementation-focused research found an important missing lifecycle-control detail: direct “commit then refresh” mutation can leave stale routing if reconciliation fails.

The authoritative implementation-focused conclusions now live in:

`PHASE8_CAPABILITY_PACKAGE_REGISTRY_IMPLEMENTATION_RESEARCH.md`

That second pass compares Kubernetes reconciliation, Nix generations, SQLite/DBOS roles, PyPA/Pluggy, go-plugin, Dapr, WASI/Extism, Windows AppContainer/Sandbox, OCI/ORAS, TUF, Sigstore/SLSA/CycloneDX and OPA, and requires the architecture to add deterministic reconciliation plus generation-fenced transitions before implementation approval.
