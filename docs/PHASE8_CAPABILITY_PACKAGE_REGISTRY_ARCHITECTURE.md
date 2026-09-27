# Phase 8 — Capability Package + Registry Lifecycle Architecture

## Status

**PROPOSED ARCHITECTURE — OWNER APPROVAL REQUIRED BEFORE IMPLEMENTATION**

Baseline:

`0c1822907c133cf16b261515c443d2487c733922`

This architecture preserves all accepted Phase-1 through Phase-7 Authority, governance, provenance, sandbox and promotion boundaries.

## 1. Architectural objective

Make capability identity and operational lifecycle durable and deterministic without creating a second capability runtime or transferring Authority to package metadata.

Phase 8 must answer:

- exactly what capability/version is accepted?
- exactly what implementation bytes/source does it represent?
- what manifest/provenance/verification accepted it?
- is it compatible with this machine/runtime?
- is it enabled?
- what version was previously enabled?
- what health evidence exists?
- can it be disabled/rolled back safely?
- can restart recover without duplicate or ambiguous activation?

## 2. Permanent invariants

1. `CapabilityManifest` from Phase 5 remains the canonical declarative capability contract.
2. Manifest/package metadata is never executable Authority.
3. Normal CapabilityRuntime per-action Authority remains mandatory.
4. Registration does not imply enablement.
5. Acceptance does not imply enablement.
6. At most one version of a capability ID may be ENABLED on the ordinary path.
7. Enable/rollback is digest-bound and crash-recoverable.
8. Runtime descriptors are projections, not lifecycle truth.
9. Live health is evidence, not a model assertion.
10. Disabled capability code cannot become executable through discovery alone.
11. Arbitrary package entry points are never auto-imported.
12. A stale/superseded package cannot silently become active.
13. Package/dependency/artifact integrity is always re-verifiable from canonical digests.
14. Existing protected-main/Phase-7 source promotion remains the route for source-integrated capability code.

## 3. Reuse, do not replace

### Keep Phase-5 CapabilityManifest

Do not create `CapabilityManifestV2` merely for lifecycle state.

The existing manifest already covers:

- capability ID/version/purpose;
- adapter and executor identity;
- operations;
- dependencies;
- secret scopes;
- Authority attributes;
- sandbox/discovery scopes;
- platform/resource constraints;
- health probes;
- verification/hardware contracts;
- provenance;
- disable/rollback contract.

Phase 8 adds operational records around that immutable digest.

### Keep CapabilityRuntime

`CapabilityRuntime` remains the execution boundary:

`resolve → prepare → Authority → consume → execute → audit`.

Phase 8 controls which accepted implementations can project into that runtime.

### Keep HandsCapabilityRegistry

Hands remains semantic operation truth. Package registry maps implementations to those operations; it does not redefine them.

### Keep Self Model / Health Registry

Phase-8 health observations are published to the existing health plane.

## 4. New Phase-8 domain objects

### 4.1 CapabilityPackageRecord

Immutable package identity.

Required fields:

- `package_id`;
- `capability_id`;
- normalized PEP-440 `capability_version`;
- `manifest_id`;
- `manifest_version`;
- `manifest_digest`;
- `implementation_kind`;
- `implementation_paths`;
- `implementation_digest`;
- trusted executor-registration digest;
- trusted adapter-registration digest;
- source revision / EngineeringChange / promotion evidence lineage;
- dependency/provenance artifact references;
- optional SBOM artifact reference;
- verification evidence digest;
- owner acceptance evidence digest;
- creation timestamp;
- canonical `package_digest`.

Phase-8 v1 supports:

`implementation_kind = builtin_source_v1`

This means implementation code is already part of a governed JARVIS release and passed source promotion.

Externally installed executable Python distributions are out of scope for v1.

### 4.2 CapabilityRegistration

Durable operational record for one package version.

Lifecycle:

```text
STAGED
  ├─> VERIFIED
  │     ├─> ACCEPTED
  │     │     ├─> ENABLED
  │     │     │     ├─> DISABLED
  │     │     │     │     ├─> ENABLED
  │     │     │     │     └─> RETIRED
  │     │     │     └─> DISABLED
  │     │     └─> RETIRED
  │     └─> REJECTED
  └─> REJECTED
```

Rules:

- `REJECTED` and `RETIRED` are terminal for new activation;
- only `ACCEPTED` or `DISABLED` can become ENABLED;
- ENABLED must be disabled/superseded before retirement;
- one ENABLED registration per capability ID;
- older accepted/disabled versions may be retained as rollback targets;
- package lifecycle state is separate from live health.

### 4.3 CapabilityCompatibilityEvidence

Immutable evaluation output binding:

- package/manifest digest;
- current implementation-content digest;
- current trusted executor/adapter registration digests;
- manifest schema support;
- capability version validity;
- platform constraint results;
- required dependency/provenance availability;
- required secret-scope registration, never secret values;
- sandbox/discovery contract availability;
- verification/hardware/rollback contract availability;
- operation mapping to trusted executor/adapter and Hands semantics;
- current runtime contract version;
- verdict `COMPATIBLE | REVIEW_REQUIRED | INCOMPATIBLE`;
- reason codes;
- evidence digest and time.

Enable requires `COMPATIBLE`.

### 4.4 CapabilityActivationAttempt

Crash-safe operational record for enable/disable/rollback.

States:

`PREPARED → APPLYING → VERIFYING → COMPLETED`

Failure states:

`ROLLED_BACK | BLOCKED | FAILED`

Binds:

- capability ID;
- from registration/package;
- to registration/package;
- compatibility digest;
- owner/Authority decision identity where required;
- pre-activation active pointer;
- activation generation;
- health/readiness evidence;
- recovery reason.

It is idempotent across restart.

## 5. Exact implementation-content binding

A full Git release SHA is too broad for package identity: a docs-only commit should not invalidate unchanged capability code.

For `builtin_source_v1` packages:

1. the package declares a fixed allowlisted set of implementation source paths;
2. each regular file is SHA-256 hashed;
3. a canonical sorted `path → sha256` payload is hashed into `implementation_digest`;
4. symlinks and path escapes fail closed;
5. runtime activation recomputes the digest from the current verified release root;
6. mismatch = INCOMPATIBLE until a new package version/registration is verified.

Source revision/PR/promotion evidence remains provenance, while implementation digest is runtime compatibility identity.

## 6. Trusted implementation catalog

Add a version-controlled `CapabilityImplementationCatalog`.

It maps exact IDs to trusted factories/contracts:

- executor ID;
- adapter ID;
- supported operations;
- source paths;
- Authority attribute floor;
- allowed secret scopes;
- allowed sandbox profiles;
- discovery scopes;
- health-probe contract;
- runtime adapter contract version.

The Phase-5 `TrustedExecutorRegistration` and `TrustedAdapterRegistration` remain the validation data model.

Phase 8 adds deterministic digests for these registrations and binds them into each package.

No model-provided import path, module path, class name, command or executable is accepted.

## 7. Durable registry store

Use a dedicated SQLite database:

`%LOCALAPPDATA%\JARVIS\capabilities\registry.sqlite3`

Reasons:

- capability lifecycle is durable runtime/configuration truth, not WorkItem lifecycle;
- existing JARVIS SQLite migration/checksum conventions can be reused;
- transactional active-version switching is straightforward;
- local single-owner runtime does not justify a new database service.

Tables conceptually:

- `capability_packages` — immutable package rows;
- `capability_registrations` — current lifecycle state + optimistic version;
- `capability_lifecycle_events` — append-only transition evidence;
- `capability_active_versions` — one active package per capability;
- `capability_activation_attempts` — restart-safe enable/disable/rollback operations;
- `capability_schema` — version/checksum ledger.

Use foreign keys, WAL, explicit migrations, checksum ledger and too-new-schema rejection.

## 8. Version semantics

Phase-8 registry admission requires `capability_version` to parse under PEP 440.

Use the maintained `packaging` library as a **direct dependency**, not a transitive assumption.

No custom version comparator.

Do not use JARVIS's current package version `0.1.0` as host compatibility identity because it is not yet a per-release semantic version.

Host compatibility in v1 is instead bound to:

- manifest schema version;
- exact trusted adapter/executor contract IDs/digests;
- runtime adapter contract version;
- current Python/platform constraints;
- implementation digest.

A later project-versioning phase may add a JARVIS version specifier without breaking this model.

## 9. Registration/admission flow

```text
CapabilityManifest + package lineage
        ↓
Phase-5 manifest validation
        ↓
implementation path/digest verification
        ↓
dependency / provenance verification
        ↓
CapabilityPackageRecord STAGED
        ↓
compatibility + declared verification contracts
        ↓
VERIFIED
        ↓
acceptance evidence / owner boundary where required
        ↓
ACCEPTED
```

Registration never makes the capability executable.

## 10. Enable flow

```text
ACCEPTED or DISABLED package
        ↓
recompute current compatibility
        ↓
prepare CapabilityActivationAttempt
        ↓
Authority decision for capability-management effect
        ↓
atomic active-version transaction
        ↓
construct runtime projection
        ↓
run declared health/readiness probes
        ↓
publish Self Model health
        ↓
COMPLETED / ENABLED
```

If readiness fails:

- restore prior active pointer in the same governed recovery path;
- verify previous version compatibility/health;
- mark failed attempt with exact evidence;
- do not delete the candidate package.

## 11. Disable flow

Disable is a containment operation:

- remove/replace active pointer transactionally;
- stop exposing the implementation through CapabilityRuntime projection;
- publish `HealthState.DISABLED`;
- preserve package, provenance, acceptance and prior history;
- audit reason and owner/automatic-containment provenance.

Automatic disable may be allowed only under a deterministic owner-approved containment policy.

Automatic enable is never inferred from health recovery.

## 12. Version switch / rollback

Enabling a new version is an atomic switch:

```text
v1 ENABLED + v2 ACCEPTED
        ↓
verify v2
        ↓
activation attempt
        ↓
v1 DISABLED + v2 ENABLED in one transaction
        ↓
v2 readiness/health
        ↓
success
   or
rollback pointer:
v2 DISABLED + v1 ENABLED
```

Rollback requires:

- exact previous package still ACCEPTED/DISABLED;
- implementation/dependencies still available and intact;
- compatibility still passes;
- rollback contract permits the switch;
- one bounded automatic rollback attempt for one activation incident.

## 13. Runtime projection

Add a registry-backed projection layer between durable package truth and current `CapabilityRuntime`.

The runtime sees only packages that are:

- ENABLED;
- current;
- compatible;
- implementation-digest verified;
- mapped to a trusted executor/adapter factory;
- not blocked by current deterministic health/readiness policy.

`CapabilityDescriptor` remains the runtime/discovery projection.

Discovery-only services remain discovery-only until an accepted enabled implementation exists.

## 14. Health integration

Do not create a second health database.

For each enabled capability:

- execute registered deterministic probe(s);
- publish observations into existing `SelfAwareness/HealthRegistry`;
- use existing HEALTHY/DEGRADED/FAILED/RECOVERING/DISABLED states;
- preserve TTL/freshness semantics;
- allow existing incident creation on meaningful transitions.

Registry lifecycle and health remain separate:

- `ENABLED` means owner/runtime intent says this version is active;
- `FAILED` health means the active capability is currently unhealthy;
- deterministic policy may disable/rollback it, but an LLM cannot directly write health state.

## 15. Authority model

Capability package metadata never grants permission.

Management actions are typed:

- stage/register;
- accept;
- enable;
- disable;
- switch version;
- rollback;
- retire.

Risk is derived from the manifest and management effect.

Rules:

- enabling new executable/secret/network/device scope requires owner-governed Authority proportional to risk;
- manifest Authority attributes can only maintain/increase the deterministic executor floor;
- disable can use a lower-friction containment policy where explicitly owner-approved;
- rollback can be automatic only when it restores a previously accepted version without increasing permission scope and all safety contracts pass;
- every ordinary capability operation still passes through current CapabilityRuntime Authority.

## 16. Existing capability migration

Phase 8 cannot be accepted with two untracked operational truths.

Implementation must bootstrap today's default runtime capabilities into the durable registry.

For each current built-in executor:

1. define a checked-in Phase-5 CapabilityManifest and trusted implementation registration;
2. bind its exact source paths/implementation digest;
3. bind existing verification/provenance/health/rollback contracts;
4. create an accepted bootstrap CapabilityPackageRecord;
5. mark currently exposed capabilities ENABLED through deterministic migration evidence;
6. compare the registry-backed runtime catalog against the pre-Phase-8 catalog;
7. fail acceptance on unexpected operation loss, duplicate resolution or Authority weakening.

No bootstrap step may auto-enable a capability that is currently execution-disabled.

## 17. Protected surfaces

Add at minimum:

- `src/jarvis/capability_registry/`;
- package/implementation catalog definitions;
- registry migrations;
- registry-backed runtime projection;
- activation/rollback controller;
- capability-management Authority bridge;
- Phase-8 acceptance/evaluation tests.

Existing `engineering_substrate/manifest.py`, Authority, secrets, sandbox, promotion, Self Model and WorkStore protections remain.

## 18. Technology dispositions

### Adopt now

- existing CapabilityManifest validator;
- SQLite durable registry;
- existing ArtifactStore/DependencyBroker/provenance;
- direct `packaging` dependency for PEP-440 capability versions;
- existing CapabilityRuntime + Hands semantic registry;
- existing Self Model/Health Registry.

### Define compatibility for later, but do not activate now

- PyPA entry-point identity for future external Python distributions;
- optional CycloneDX SBOM references;
- future OCI export mapping.

### Defer

- Pluggy;
- arbitrary third-party in-process plugins;
- remote OCI capability registry;
- TUF remote updater;
- marketplace;
- standalone capability signing beyond accepted provenance;
- copied/movable venvs;
- Phase-9 autonomous capability acquisition.

## 19. Restart/recovery matrix

- crash after STAGED: package remains non-executable;
- crash during verification: rerun exact verification, do not advance implicitly;
- crash after ACCEPTED: remains disabled unless prior active pointer says otherwise;
- crash before active-pointer transaction: old version remains active;
- crash after pointer transaction but before health verification: activation attempt resumes VERIFYING;
- crash after readiness success but before completion record: reconcile active pointer + health evidence and complete idempotently;
- crash during rollback: reconcile exact current/previous pointers before acting;
- multiple incomplete activation attempts for one capability: fail closed for owner investigation.

## 20. Acceptance matrix

Phase-8 deterministic acceptance must include:

- manifest digest mismatch;
- unknown schema/manifest version;
- invalid/non-PEP440 capability version;
- stale dependency/provenance/sandbox/discovery digest;
- Authority-floor reduction attempt;
- unknown executor/adapter;
- implementation source mutation/digest mismatch;
- platform incompatibility;
- undeclared semantic operation;
- missing health/verification/rollback contract;
- missing secret-scope registration;
- duplicate capability version;
- duplicate ENABLED version prevention;
- enable of unaccepted package rejection;
- disabled capability absent from runtime projection;
- healthy enabled capability present exactly once;
- version switch transaction;
- crash before/after active-pointer switch;
- readiness failure rollback;
- restart during rollback;
- rollback budget exhaustion;
- retired/rejected package cannot enable;
- artifact corruption rejection;
- no automatic entry-point import;
- runtime operation still requires normal Authority;
- Self Model receives DISABLED/HEALTHY/FAILED evidence correctly;
- bootstrap catalog equivalence for current built-ins.

Windows-specific activation/restart behavior must run in Windows CI where applicable.

Final owner-machine acceptance should remain non-destructive and use one consolidated PowerShell block.

## 21. Proposed implementation slices

### 8A — Durable package/registry domain

- package record;
- lifecycle states;
- SQLite registry + migrations;
- immutable/event evidence;
- PEP-440 version validation.

### 8B — Trusted implementation/content binding

- implementation catalog;
- source-path digest;
- executor/adapter registration digests;
- compatibility evaluator;
- existing Phase-5 manifest validation integration.

### 8C — Runtime projection + health

- registry-backed CapabilityRuntime projection;
- deterministic health probe registry;
- Self Model/Health Registry publication;
- disabled/unhealthy behavior.

### 8D — Enable / disable / version switch / rollback

- activation attempt;
- atomic active pointer;
- Authority bridge;
- crash recovery;
- bounded rollback.

### 8E — Existing capability bootstrap

- checked-in manifests/implementation registrations for current default executors;
- migration to accepted/enabled registry truth;
- pre/post catalog equivalence validation.

### 8F — End-to-end acceptance

- deterministic replay/fault injection;
- Linux + Windows CI;
- registry corruption/compatibility negative controls;
- non-destructive owner-machine acceptance;
- documentation reconciliation.

## 22. Exit criteria

Phase 8 is complete only when:

- every default executable capability exposed by the runtime has durable registry identity;
- exact package/implementation/provenance evidence is queryable;
- one active version per capability is enforced;
- enable/disable/version rollback is durable and restart-safe;
- registry projection cannot bypass CapabilityRuntime Authority;
- health truth reaches the existing Self Model;
- current built-in behavior is preserved without silent capability loss;
- deterministic replay and real owner-machine acceptance pass.

## 23. Owner approval boundary

No Phase-8 implementation code may begin until the owner explicitly approves this architecture.

Approval authorizes implementation of this architecture only. It does not authorize:

- arbitrary external plugin execution;
- a marketplace;
- remote package registry/TUF rollout;
- automatic capability acquisition;
- weakening per-action Authority;
- Phase-9 implementation.
