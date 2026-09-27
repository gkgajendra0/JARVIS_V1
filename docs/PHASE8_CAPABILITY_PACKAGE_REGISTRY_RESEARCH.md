# Phase 8 — Capability Package + Registry Lifecycle Research

## Status

**RESEARCH COMPLETE / ARCHITECTURE PROPOSED — OWNER APPROVAL REQUIRED BEFORE IMPLEMENTATION**

Research date: 2026-09-27

Protected-main baseline inspected:

`0c1822907c133cf16b261515c443d2487c733922`

## 1. Phase-8 purpose

Phase 8 is the lifecycle substrate that Phase 9 will later use when the owner asks JARVIS to acquire a new capability.

Phase 8 does **not** autonomously research/build new capabilities. It makes capability identity, package provenance, compatibility, activation, health, disable and rollback deterministic enough that Phase 9 can safely compose them.

The target is:

```text
accepted capability implementation
        ↓
immutable manifest/package identity
        ↓
durable registry
        ↓
compatibility + verification
        ↓
accepted version
        ↓
governed enable
        ↓
runtime projection + health truth
        ↓
disable / rollback / retire
```

Normal per-action Authority remains mandatory after a capability is enabled.

## 2. Repository findings

### 2.1 Phase 5 already implemented the capability manifest substrate

Phase 5 already contains:

- `CapabilityManifest` in `engineering_substrate/contracts.py`;
- exact schema registration in `engineering_substrate/registry.py`;
- deterministic JSON-schema generation;
- `CapabilityManifestRegistry` admission/activation validation in `engineering_substrate/manifest.py`;
- trusted executor and adapter registrations;
- dependency/provenance/sandbox/discovery digest binding;
- Authority risk-floor validation;
- secret-scope validation;
- health-probe IDs;
- verification and hardware-acceptance contract IDs;
- disable/rollback contract identity.

The Phase-5 manifest validator intentionally **does not import or execute capability code**. That separation is correct and should remain.

Phase 8 therefore must not create a competing manifest format.

### 2.2 Existing runtime catalog is intentionally ephemeral

`jarvis.capabilities.CapabilityRuntime` currently:

- constructs executor objects at process startup;
- merges built-in descriptors with read-only discovery results;
- resolves semantic operations through `HandsCapabilityRegistry`;
- authorizes every action through canonical Authority;
- audits execution results.

`CapabilityDescriptor` is a useful runtime projection, but it does not represent package lifecycle truth.

Current gaps:

- no durable accepted package/version registry;
- no persistent enable/disable state;
- no version/supersession/retirement history;
- no atomic active-version pointer;
- no crash-safe activation attempt;
- no immutable implementation-content binding;
- no accepted-version rollback target;
- no durable package acceptance lineage.

### 2.3 Hands semantic operation truth already exists

`HandsCapabilityRegistry` owns semantic operations and substrate preference independently of concrete executors.

Phase 8 should not create another semantic-operation registry.

Package lifecycle should map accepted implementations onto existing semantic operations.

### 2.4 Existing Self Model/Health Registry is the correct health plane

The Self Model already declares `capability_runtime` as a health surface.

`HealthRegistry` already supports:

- UNKNOWN;
- STARTING;
- HEALTHY;
- DEGRADED;
- FAILED;
- RECOVERING;
- DISABLED.

`SelfAwareness.observe()` already records deterministic health transitions and can create engineering incidents.

Phase 8 should publish package/runtime health into this existing system rather than create a competing health database.

### 2.5 Existing supply-chain foundations are sufficient

Phase 5 already provides:

- immutable content-addressed `ArtifactStore`;
- trusted `uv` dependency resolution;
- strict PEP-751 `pylock.toml` inspection;
- wheel-only acquisition for the current Python dependency path;
- exact SHA-256 admission and verify-on-read;
- PyPI PEP-740 attestation verification through `pypi-attestations` / Sigstore;
- SecretBroker;
- sandbox profiles;
- hardware acceptance contracts.

Phase 8 should compose these rather than become another package manager.

## 3. External technology research

### 3.1 PyPA entry points — ADOPT AS OPTIONAL DISTRIBUTION METADATA, NOT TRUST

Python entry points are the standard mechanism for an installed distribution to advertise a plugin/component. PyPA documents entry points as portable package metadata discoverable through `importlib.metadata`.

Disposition:

- reserve a future group such as `jarvis.capability_adapters.v1`;
- an accepted package may declare an exact entry-point name/value;
- never auto-load every discovered entry point;
- an entry point is discovery metadata, not acceptance, enablement, or Authority;
- Phase-8 v1 does not require external plugin execution.

Sources:

- https://packaging.python.org/en/latest/specifications/entry-points/
- https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/

### 3.2 Pluggy — DO NOT ADOPT FOR PHASE-8 V1

Pluggy is mature and powers pytest's plugin system. It is optimized for in-process hook registration and 1:N hook calling.

JARVIS already has:

- typed CapabilityExecutor contracts;
- semantic Hands operations;
- canonical Authority;
- explicit result auditing.

Adopting Pluggy now would create a second extension abstraction and would encourage third-party code to run inside the core JARVIS process.

Disposition: do not add Pluggy in Phase 8. Reconsider only if a future use case genuinely needs multi-provider in-process hooks rather than governed capability execution.

Source:

- https://pluggy.readthedocs.io/en/latest/

### 3.3 PEP 440 / PyPA version specifiers — ADOPT

Capability versions should be normalized and ordered using the Python packaging version rules rather than custom string comparison.

Disposition:

- Phase-8 registry admission requires `CapabilityManifest.capability_version` to be a valid normalized PEP-440 version;
- add `packaging` as a direct dependency rather than relying on a transitive install;
- this dependency change is itself governed by the accepted dependency/provenance path and Phase-7 high-risk compatibility rules.

Source:

- https://packaging.python.org/en/latest/specifications/version-specifiers/

### 3.4 Wheels + pylock.toml — KEEP

For Python dependencies, the existing wheel + PEP-751 lock path is already the correct deterministic substrate.

Disposition: reuse DependencyBroker, pylock and ArtifactStore. No pip/raw shell acquisition path is added.

Source:

- https://packaging.python.org/en/latest/specifications/

### 3.5 CycloneDX — OPTIONAL EVIDENCE, NOT THE JARVIS MANIFEST

CycloneDX can represent software, hardware, services, dependencies and lifecycle BOMs, including operational inventories.

Disposition:

- allow an optional CycloneDX SBOM/OBOM artifact reference in package evidence;
- do not replace `CapabilityManifest` with CycloneDX;
- SBOM generation/verification may be added when it materially improves dependency transparency.

Source:

- https://cyclonedx.org/specification/overview/
- https://cyclonedx.org/docs/1.7/json/

### 3.6 OCI artifacts / ORAS-style registry — DEFER

OCI 1.1 supports non-container artifacts through `artifactType`, `subject`, and referrers. Helm, OPA and Wasm already use OCI registries for non-image artifacts.

This is attractive if JARVIS later distributes capabilities between machines or publishes a private capability registry.

For the current single-owner/local runtime, JARVIS already has a content-addressed local ArtifactStore. Adding an OCI registry now would add network, auth and lifecycle complexity without solving the current core gap.

Disposition:

- define package records so they can later be exported to OCI;
- do not require an OCI registry in Phase-8 v1.

Source:

- https://opencontainers.org/posts/blog/2024-03-13-image-and-distribution-1-1/

### 3.7 Sigstore — KEEP EXISTING INTEGRATION; DEFER STANDALONE PACKAGE SIGNING

Sigstore bundles contain the verification material required to verify signed artifacts.

JARVIS already consumes Sigstore-backed PyPI attestations through the Phase-5 provenance service.

Disposition:

- keep existing PEP-740/Sigstore verification for acquired Python artifacts;
- exact Git/source/promotion evidence is sufficient for first-party source-integrated capability packages in Phase-8 v1;
- standalone capability-artifact signing can be added when separately distributed capability packages become executable.

Source:

- https://docs.sigstore.dev/about/bundle/

### 3.8 TUF — BORROW SECURITY INVARIANTS; DEFER FULL REMOTE UPDATE FRAMEWORK

TUF provides signed Root/Targets/Snapshot/Timestamp metadata, target hashes/sizes, consistent repository views, expiration/freshness, and rollback/freeze resistance.

These properties become important when JARVIS fetches independently distributed capability packages from a remote registry.

Disposition:

- Phase 8 adopts monotonic version/history, exact digest binding and stale/superseded rejection principles;
- do not add TUF keys/repository metadata in local-registry v1;
- require a new architecture decision before remote capability distribution is enabled.

Sources:

- https://theupdateframework.io/docs/metadata/
- https://theupdateframework.io/docs/security/

### 3.9 Python virtual environments — FUTURE EXTERNAL-PACKAGE BOUNDARY

Python documents venvs as disposable and not movable/copyable; they should be recreated.

Disposition:

- if future separately installed Python capability packages use isolated environments, build/rebuild them from exact locks/artifacts;
- never copy an existing venv between package versions/machines;
- Phase-8 v1 does not make arbitrary external Python packages executable.

Source:

- https://docs.python.org/3.11/library/venv.html

## 4. Core design conclusion

The best Phase-8 v1 is **not a new plugin framework or marketplace**.

It is a durable operational lifecycle around the accepted Phase-5 manifest validator and current CapabilityRuntime:

```text
Phase-5 CapabilityManifest
        +
trusted executor/adapter registrations
        +
implementation-content evidence
        +
acceptance/provenance evidence
        ↓
CapabilityPackageRecord
        ↓
durable CapabilityRegistry
        ↓
compatibility verification
        ↓
ACCEPTED / ENABLED / DISABLED / RETIRED
        ↓
CapabilityRuntime projection
        ↓
existing Authority per action
        ↓
existing Self Model / Health Registry
```

## 5. Important scope decision: first-party source-integrated execution in v1

Phase-8 v1 should support execution of **first-party/source-integrated capability implementations that have already passed the governed engineering + Phase-7 source promotion path**.

It should not make arbitrary third-party wheel/plugin code executable merely because a package is installed or an entry point exists.

This gives Phase 9 a safe path:

```text
owner asks for capability
→ EngineeringChange
→ research/architecture
→ develop capability in isolation
→ Phase-5 manifest/dependency/provenance verification
→ Phase-6/normal source verification
→ Phase-7 protected promotion/deploy
→ Phase-8 package registration
→ governed enable
```

A future independently distributed plugin host can be designed later if it produces a real benefit.

## 6. Research verdict

Phase-8 research is sufficient to proceed to architecture.

No large new framework is justified.

Keep and extend:

- Phase-5 `CapabilityManifest` + validator;
- CapabilityRuntime;
- Hands semantic registry;
- ArtifactStore;
- DependencyBroker / pylock;
- provenance/Sigstore integration;
- SecretBroker;
- Self Model / Health Registry;
- SQLite migration patterns;
- Authority.

Add:

- durable package/registration lifecycle;
- exact implementation-content binding;
- PEP-440 capability version validation;
- compatibility evidence;
- atomic enable/disable/version rollback;
- runtime registry projection;
- health projection;
- acceptance/replay.

Defer:

- public/private capability marketplace;
- OCI registry;
- TUF remote updater;
- generic third-party plugin loader;
- automatic entry-point import;
- Pluggy;
- standalone package signing beyond existing provenance;
- autonomous owner-requested acquisition (Phase 9).
