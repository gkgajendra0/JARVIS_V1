# Phase 5 Secure Autonomous Engineering Substrate — Architecture

Status: **OWNER-APPROVED / FROZEN FOR IMPLEMENTATION**

Owner approval recorded: 2026-09-26

Date: 2026-09-26

Research basis: PHASE5_SECURE_ENGINEERING_SUBSTRATE_RESEARCH.md

## 1. Objective

Phase 5 adds the minimum trusted substrate later autonomous-engineering phases need to acquire dependencies, use owner-provided secrets, discover bounded devices/services, describe capabilities, run least-privilege verification, preserve provenance and collect hardware evidence.

It increases safe engineering reach without increasing model authority.

~~~text
canonical owner request
        |
 EngineeringChange
        |
 research / architecture / owner gate
        |
     WorkItems
        |
Model Router / reasoner
        |
 typed broker intent
        |
 +------+--------------------+-------------------+
 |                           |                   |
DependencyBroker        SecretBroker       DiscoveryBroker
 |                           |                   |
trusted adapters        opaque handles      scoped adapters
 +-------------+-------------+----------+--------+
               |                        |
         SandboxRegistry          CapabilityManifest
               |                        |
               +------------+-----------+
                            |
                  deterministic verification
                            |
                    provenance evidence
                            |
             HardwareAcceptance if required
                            |
         existing EngineeringChange acceptance
                            |
              existing promotion gate
~~~

No new Phase-5 component can issue an Authority permit, approve an EngineeringChange gate, merge protected main, deploy production code or turn discovered metadata into executable permission.

## 2. Non-goals

Phase 5 does not:

- perform autonomous unknown-failure source repair; that remains Phase 6;
- add autonomous rollback/observation for source repair; Phase 7;
- add self-improvement scoring/curriculum; Phase 8;
- autonomously acquire arbitrary capabilities; Phase 9;
- replace CapabilityRuntime, Authority, EngineeringChange or WorkItem;
- expose arbitrary shell, package-manager, Docker or network-scanner arguments to models;
- install packages into protected-main .venv;
- introduce a mandatory cloud vault, package proxy or paid security control plane;
- silently run source distributions/build scripts;
- let hardware observation waive failed automated verification or security.

## 3. Hard invariants

### P5-I1 — Brokers never grant Authority

DependencyBroker, SecretBroker, DiscoveryBroker, SandboxRegistry, ManifestRegistry and HardwareAcceptanceService enforce policy and produce evidence. State-changing execution still uses canonical CapabilityRuntime/Authority or EngineeringChange gates.

### P5-I2 — Raw secrets never enter model-visible state

Models may see opaque secret identity, provider/service class, availability, scope labels, lease status and expiry. They must never receive plaintext, DPAPI blobs, secret-bearing argv, environment dumps or credential file contents.

### P5-I3 — No production dependency mutation

DependencyBroker may write only to a content-addressed staging store, isolated candidate environment and EngineeringChange development worktree. It never syncs or installs into protected-main .venv or system Python.

### P5-I4 — Trusted adapters build dangerous commands

Model output is typed intent only. Trusted JARVIS code constructs package-manager, Docker, subprocess and discovery arguments from registered contracts. Raw model-authored flags/shell strings are rejected.

### P5-I5 — Artifact identity is content-bound

Every admitted artifact has mandatory SHA-256 identity. Name/version alone is insufficient.

### P5-I6 — Source builds deny by default

Wheels/prebuilt artifacts are the default. An sdist/build path requires a separately reviewed future policy, isolated build profile, source/build-dependency provenance and owner-approved exception.

### P5-I7 — Discovery is read-only and bounded

No arbitrary subnet or port scan. Every request uses a registered adapter and immutable DiscoveryScope. Discovery evidence never authorizes control.

### P5-I8 — Sandbox profiles are JARVIS-owned

Models cannot author or relax sandbox security settings. Unknown profile ID/version/digest fails closed.

### P5-I9 — CapabilityManifest is declarative

A manifest cannot load arbitrary code, specify a shell command, create an executor dynamically, lower Authority risk or grant secret access. It references registered trusted adapters/executors and evidence.

### P5-I10 — Hardware evidence cannot override software evidence

A hardware PASS cannot turn failed CI, failed security checks or missing required provenance into success.

### P5-I11 — Existing promotion governance remains unchanged

Phase 5 supplies evidence to EngineeringChange. It does not make architecture/acceptance/promotion decisions or auto-merge after approval.

### P5-I12 — Unknown schema/version fails closed

All new contracts are explicitly versioned. Unknown versions require a registered migration/adapter.

## 4. Proposed module boundary

~~~text
src/jarvis/engineering_substrate/
    contracts.py
    canonical.py
    provenance.py
    artifacts.py
    sandbox.py
    dependency/
        broker.py
        policy.py
        uv_adapter.py
        pylock.py
    secrets/
        broker.py
        store.py
        cli.py
    manifests/
        models.py
        registry.py
        schema.py
    discovery/
        broker.py
        models.py
        mdns.py
    hardware/
        models.py
        acceptance.py
~~~

Exact filenames may shift for repository consistency, but these trust boundaries may not change after owner approval without another architecture revision.

## 5. Canonical contracts

All are immutable typed objects with deterministic canonical JSON and SHA-256 digests. Reuse the repository's RFC-8785/canonical-hash patterns rather than adding another serialization convention.

### DependencyRequirement

Contains requirement ID/schema version, ecosystem, normalized identity, version constraint, purpose, change/artifact lineage, platform constraints, registered source IDs and source-build policy.

A raw model URL is not an approved source.

### DependencyResolution

Contains resolver ID/version/binary digest, exact resolved packages, artifact candidates, dependency graph digest, environment constraints, canonical lock format/digest and lineage.

Python v1 uses PEP 751 pylock.toml/1.0 as canonical interchange evidence. uv.lock may exist as adapter working state but is not the sole architectural truth.

### DependencyArtifact / ArtifactProvenance

Artifact records bind name/version/distribution kind/size/SHA-256/source/platform tags to provenance.

Provenance records source identity, resolver version/digest, attestation status/references, publisher identity when known, optional SLSA/in-toto evidence, optional SBOM reference/version and verification result.

Missing optional attestation is explicit NOT_AVAILABLE; an invalid/mismatched attestation is REJECTED.

### SecretDescriptor / SecretLease

SecretDescriptor contains nonsecret metadata only: opaque ID, service/kind, allowed consumers/scopes, lifecycle status, timestamps and version.

SecretLease binds a secret to exact consumer, optional change/work lineage, scope, materialization mode, expiry, use budget and policy digest. A lease itself never contains plaintext.

### CapabilityManifest

A versioned manifest binds capability identity/purpose to registered adapter/executor IDs, operations, dependency resolutions, secret requirements/scopes, Authority attributes, sandbox profiles, discovery requirements, platform/resources, health probes, verification contracts, optional hardware acceptance contracts, provenance and disable/rollback contract.

Manifest digest is immutable evidence.

### DiscoveryScope / DiscoveryObservation

DiscoveryScope contains only registered adapter/protocol, allowed local interface/domain, service/device types, bounded target hints, timeout and max results. Raw port ranges are not part of v1.

Observation binds stable service/device identity, endpoints, bounded metadata, scope digest, adapter version, freshness and evidence digest.

### SandboxProfile

Versioned profile includes trusted entrypoint, network/filesystem mode, mounts, capabilities, no-new-privileges, CPU/RAM/PID/time limits, environment allowlist, allowed secret scopes and output rules.

### HardwareAcceptanceRequest / Evidence

Request is digest-bound to current change, manifest revision, exact device/service identity, tested operation, expected physical observation, required automated evidence and expiry.

Evidence records PASS/FAIL/INCONCLUSIVE, exact request digest, trusted owner observation reference where required, telemetry/verifier references, timestamp and evidence digest.

## 6. DependencyBroker

Responsibilities:

- validate DependencyRequirement;
- enforce source policy;
- select a registered resolver adapter;
- generate reproducible lock evidence;
- acquire artifacts to immutable staging;
- verify hashes/provenance;
- create isolated candidate environments;
- return bounded EngineeringChange evidence.

It never approves the change.

### Python v1

~~~text
typed requirement
      |
source/policy validation
      |
 pinned uv adapter
      |
PEP-751 lock resolution
      |
wheel acquisition to staging
      |
SHA-256 + provenance verification
      |
content-addressed ArtifactStore
      |
dependency.verify.v1 (network off)
      |
isolated candidate environment
~~~

### uv trust

uv is itself registered by exact version, executable SHA-256, source release and attestation/signature status. It is pinned; no automatic latest upgrade.

At research freeze, 0.12.18 is current and contains the Windows wheel path-traversal security fix. Implementation may pin that version after verifying the exact owner-machine artifact; later upgrades are governed changes.

### Source policy v1

Allowed: public PyPI simple index over HTTPS.

Private indexes require a registered source plus scoped SecretLease. Phase-5 v1 resolves a dependency from one explicitly selected source policy; it does not combine public and private indexes with an extra-index search. Current pip documentation warns that extra-index behavior can create dependency-confusion risk because candidate locations are searched together.

Denied by default:

- HTTP downgrade;
- trusted-host/TLS verification bypass;
- public/private extra-index mixing for one requirement;
- arbitrary model-provided index;
- mutable VCS dependency;
- local path outside the isolated worktree/artifact cache;
- source build.

### Candidate environments

Dependency verification builds a disposable environment from canonical lock + staged artifacts. Protected-main .venv, acceptance environment and system Python are never targets.

## 7. Content-addressed ArtifactStore

Root:

%LOCALAPPDATA%\JARVIS\engineering\artifacts\sha256\<digest>

Admission:

1. download to broker-owned temporary path;
2. stream SHA-256;
3. compare expected/index/lock hashes;
4. atomic create at digest path;
5. record immutable metadata/provenance;
6. re-verify digest before security-sensitive reuse.

A staged artifact is not automatically a trusted dependency.

Garbage collection must retain objects referenced by active or accepted EngineeringChanges/provenance.

## 8. SecretBroker

### SecretStore

Dedicated local store:

%LOCALAPPDATA%\JARVIS\secrets\secrets.sqlite

Production requirements:

- versioned schema;
- each secret stored as a DPAPI-sealed envelope containing the plaintext value plus the security-sensitive descriptor identity/scope/version;
- nonsecret metadata may be projected into index columns, but projection is checked against the sealed envelope before materialization so local metadata edits cannot broaden scope;
- plaintext never persisted;
- machine-wide DPAPI mode forbidden;
- fail closed if production DPAPI unavailable.

Tests use an explicit fake/in-memory protector; never a silent plaintext production fallback.

### Enrollment

First trusted enrollment surface: jarvis-secret CLI.

Operations: enroll, rotate/replace, revoke, list metadata, inspect metadata.

Plaintext input uses no-echo local console input and never argv. Voice/model may ask the owner to enroll a secret but never receives its value.

### Lease policy

Leases are short-lived, non-transferable and are not automatically reusable across a JARVIS process restart. Durable audit metadata may record that a lease existed, but a resumed WorkItem must obtain a fresh policy-checked lease.

Lease requires:

1. active SecretDescriptor;
2. registered consumer;
3. allowed descriptor scope;
4. current manifest/change permits requirement;
5. materialization mode supported;
6. underlying operation passes canonical Authority;
7. expiry/use budget valid.

### Materialization

Preferred v1 mode is a child-process environment map passed directly to trusted subprocess APIs.

Rules:

- no shell string;
- no global os.environ mutation;
- no persistence;
- minimal inherited env allowlist;
- redact secret names/values from diagnostics;
- plaintext lifetime bounded to the trusted invocation.

File materialization is disabled in v1 unless a later adapter proves it necessary and gets a reviewed restrictive temp-file policy.

## 9. CapabilityManifestRegistry

Registry validates and digests candidate manifests. It does not dynamically import code.

Activation checks:

- schema/version registered;
- executor/adapter trusted;
- operation registered;
- dependency evidence acceptable;
- secret requirements reference scopes only;
- SandboxProfiles registered;
- discovery adapters registered;
- Authority attributes do not lower deterministic floors;
- verification and disable/rollback contracts present;
- hardware contract present where physical effect is not fully automatable.

Export JSON Schema Draft 2020-12 for interoperability; typed JARVIS validation remains canonical.

## 10. DiscoveryBroker

Discovery extends the existing CapabilityDiscoverySource/CapabilityResolver foundation.

Initial generic adapter: mdns_dns_sd.v1.

It may browse only explicit service types under local-link/domain scope with bounded timeout/results. It performs no control action.

ONVIF WS-Discovery is an optional registered device-specific adapter when needed for camera work. It is not a generic UDP scanner.

A model may narrow an approved DiscoveryScope but cannot broaden it.

## 11. SandboxRegistry

Profiles are version-controlled trusted definitions and deterministic command builders.

### test.offline.v1

Formalizes the accepted current runner:

- network none;
- read-only root/source;
- all capabilities dropped;
- no-new-privileges;
- bounded CPU/RAM/PIDs/time;
- isolated writable temp/output;
- no secrets.

### dependency.acquire.v1

- network only for registered source use;
- no protected-main mount;
- worktree read-only if required;
- staging writable;
- no Docker socket/home-profile mount;
- no generic secret access;
- private-index lease only when declared;
- source builds disabled.

### dependency.verify.v1

- network none;
- staged artifacts read-only;
- candidate env writable;
- exact PEP-751 lock;
- hashes required;
- wheels only;
- no secrets;
- deterministic verification/tests.

Only trusted JARVIS code can invoke Docker. If Docker is unavailable, sandbox-required work truthfully blocks; it never falls back to host execution.

## 12. ProvenancePolicy

Evidence states are deterministic, for example:

- HASH_ONLY;
- INDEX_HASH_VERIFIED;
- PUBLISH_ATTESTED;
- SLSA_ATTESTED;
- LOCALLY_BUILT_VERIFIED;
- UNVERIFIED;
- REJECTED.

Initial production baseline:

- SHA-256 mandatory;
- HTTPS registered source mandatory;
- Python transitive install bound to lock;
- wheel-only default;
- available PyPI PEP-740 attestations captured/verified;
- optional missing attestation explicit;
- invalid/mismatched attestation rejects artifact.

NIST SSDF third-party component/provenance guidance informs this policy; Phase 5 does not claim formal NIST compliance.

## 13. EngineeringChange integration

No parallel lifecycle is introduced.

~~~text
research
  |
architecture
  |
owner architecture gate
  |
dependency plan/resolution evidence
  |
candidate capability manifest
  |
development WorkItem
  |
verification evidence
  |
hardware evidence if required
  |
existing acceptance gate
  |
existing promotion-intent gate
~~~

A revised dependency plan, manifest, sandbox profile or secret scope after an approved architecture must invalidate stale downstream evidence through deterministic digest binding.

## 14. Authority integration

The substrate introduces no lower-risk shortcut.

- public dependency metadata research: bounded read-only action;
- public wheel staging: isolated EngineeringChange write, never production mutation;
- private repository secret lease: inherits secret/target risk;
- secret create/rotate/revoke: direct trusted-owner operation;
- discovery: scoped read only;
- hardware control for acceptance: existing capability-specific Authority;
- production candidate acceptance/promotion: existing EngineeringChange gates.

If OPA/deterministic policy requires strong Windows Hello, a broker cannot reduce it.

## 15. HardwareAcceptanceService

Hardware acceptance fills physical-world evidence gaps without turning free-form conversation into verification.

Trusted code creates requests only for manifest-declared contracts. Request is bound to exact manifest/device/operation/expected observation/automated evidence.

First implementation uses a trusted local acceptance surface/command that displays the exact request and records PASS/FAIL/INCONCLUSIVE. Voice may notify and explain, but an unrelated conversational yes cannot resolve an ambiguous request.

Hardware PASS becomes one evidence input; existing EngineeringChange acceptance remains authoritative.

## 16. Failure semantics

Dependency:
- no acceptable resolution -> WAITING_RESOURCE/blocker;
- no wheel -> blocker, never implicit source build;
- hash/attestation mismatch -> reject/quarantine;
- unregistered source -> DENIED.

Secrets:
- missing -> owner/resource blocker with metadata only;
- revoked/expired/scope mismatch -> DENIED;
- DPAPI failure -> fail closed, no plaintext fallback.

Discovery:
- invalid/broadened scope -> DENIED;
- timeout/no result -> bounded empty observation, not fabricated global absence.

Sandbox:
- unknown profile/version -> fail closed;
- Docker unavailable -> resource blocker;
- arbitrary args -> INVALID/DENIED;
- timeout/resource cap -> failed verification evidence.

Hardware:
- FAIL blocks acceptance;
- INCONCLUSIVE/expired remains waiting, never PASS.

## 17. Concurrency and observability

Extend existing ResourceLeaseManager with fixed resources such as dependency_resolver, artifact_store, secret_store, local_discovery, docker and hardware_acceptance:<device-id>. Independent EngineeringChanges remain concurrent.

Operational evidence records IDs/digests/status only:

- dependency resolution/acquisition/verification;
- artifact hash/attestation result;
- secret enrollment/rotation/revocation/lease issue or deny;
- discovery scope lifecycle;
- sandbox lifecycle/limits;
- hardware request/result.

No secret-bearing argv/environment/value is logged.

## 18. Required verification

Implementation acceptance must prove:

Dependency:
- deterministic resolution/lock digests;
- wheel-only rejection;
- hash mismatch fail closed;
- arbitrary index/TLS bypass rejected;
- protected-main environment unchanged;
- offline candidate recreation.

Secrets:
- DPAPI sealed at rest on owner Windows;
- plaintext absent from WorkStore, EngineeringChange artifacts, logs, model payloads and Git;
- no-echo enrollment;
- lease scope/consumer/expiry/use-budget/revocation;
- scoped child receives the secret without global env mutation.

Manifest:
- version/digest;
- unknown version/executor fail closed;
- cannot lower Authority;
- JSON Schema export validates.

Discovery:
- bounded mDNS/DNS-SD;
- cannot widen scope;
- stale evidence expires;
- discovery cannot execute/control.

Sandbox:
- profile command generation fixed;
- offline network proof;
- read-only/source protection;
- no Docker socket/arbitrary args;
- resource/time limits;
- no unsandboxed fallback.

Hardware:
- exact request/evidence digest binding;
- stale/wrong device/manifest rejected;
- FAIL/INCONCLUSIVE cannot satisfy acceptance;
- PASS cannot override failed automated verification.

Governance:
- generic unrelated yes cannot approve EngineeringChange;
- Windows Hello/strong approval unchanged;
- promotion still does not auto-merge/deploy;
- protected main untouched by acceptance run.

## 19. Owner-machine acceptance target

Preferred harmless live scenario:

1. bounded EngineeringChange in isolated worktree;
2. resolve/stage one harmless Python dependency;
3. verify PEP-751, SHA-256 and provenance;
4. enroll a non-production test secret through no-echo SecretBroker;
5. prove one scoped child consumes it with no plaintext persistence;
6. perform bounded local-service discovery if a safe target is available;
7. validate a candidate CapabilityManifest;
8. verify under dependency.verify.v1/test.offline.v1;
9. collect hardware evidence only if physical hardware is involved;
10. restart while active/waiting and prove same lineage;
11. run Authority/security regression;
12. stop before production promotion unless separately approved.

Unavailable hardware is recorded as an external limitation and replaced by deterministic adapter tests, never by widening discovery/security.

## 20. Frozen architecture decisions

1. Brokers, not a new control plane.
2. PEP 751 is canonical Python lock evidence.
3. uv is the first trusted Python DependencyBroker adapter.
4. Wheel-only + hashes + registered HTTPS sources by default.
5. DPAPI-backed dedicated SecretStore; opaque references only.
6. Trusted no-echo secret enrollment; no voice/model plaintext.
7. CapabilityManifest is declarative and registry-bound.
8. Discovery extends the current capability discovery model and remains read-only/scoped.
9. Versioned JARVIS-owned SandboxProfiles formalize current Docker hardening.
10. SHA-256 is mandatory; attestations/SLSA are captured when available.
11. Hardware acceptance is evidence, never Authority.
12. EngineeringChange remains lifecycle/governance truth.
13. No mandatory paid/cloud control service.
14. No Phase-6 or Phase-9 capability creep.

**Implementation may begin only after explicit owner approval of this architecture.**
