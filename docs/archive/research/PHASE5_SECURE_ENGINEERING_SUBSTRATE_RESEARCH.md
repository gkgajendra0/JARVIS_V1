# Phase 5 Secure Autonomous Engineering Substrate — Research

Status: **RESEARCH COMPLETE / ARCHITECTURE OWNER-APPROVED 2026-09-26**

Date: 2026-09-26

## 1. Purpose

Phase 5 builds the security substrate JARVIS needs before later phases can safely investigate unknown failures, acquire new dependencies, integrate services/devices, or build owner-requested capabilities.

Phase 5 is deliberately **not** the capability-acquisition phase. It creates governed primitives that later EngineeringChanges can use without giving a model arbitrary package-install, secret, network-discovery, shell, or host-mutation authority.

The required substrate is:

- DependencyBroker;
- SecretBroker;
- versioned CapabilityManifest;
- bounded device/service discovery;
- versioned least-privilege SandboxProfiles;
- artifact/source/dependency provenance;
- hardware-in-the-loop acceptance evidence.

The design must reuse the accepted EngineeringChange, WorkItem, Authority, EngineeringKnowledge, Model Router, capability runtime, development-worktree and Docker-test foundations.

## 2. Existing JARVIS constraints and reusable foundations

Repository inspection on protected `main` after Phase 4 shows strong primitives already exist.

### 2.1 Isolated development

`jarvis.work.development` already:

- creates one deterministic Git worktree per development WorkItem;
- blocks production-tree writes;
- blocks sensitive filenames/suffixes and secret-like text from model-visible reads/writes;
- does not expose arbitrary shell, package installation, push, merge or deploy;
- runs pytest through a trusted Docker adapter with a read-only worktree mount;
- uses `--network none`, `--read-only`, `--cap-drop ALL` and `no-new-privileges`.

Phase 5 should formalize these properties into named SandboxProfiles instead of building another sandbox system.

### 2.2 Secret protection

Persistent Work payloads already use AES-GCM with a separate master key protected by Windows DPAPI on production Windows.

Microsoft documents that DPAPI normally binds protected data to the same user credentials and machine. The non-interactive DPAPI path remains appropriate; the old prompt-based DPAPI flow is deprecated and scheduled for removal.

Phase 5 should reuse the accepted DPAPI trust boundary for local secret storage rather than introduce a mandatory cloud vault.

### 2.3 Capability discovery/runtime

The capability runtime already owns:

`resolve -> validate -> authorize -> revalidate -> execute -> audit`

and has provider-neutral CapabilityDescriptor / DiscoverySnapshot / CapabilityCatalog contracts plus a `CapabilityDiscoverySource` protocol.

Phase 5 discovery should add typed, owner-scoped discovery adapters behind this boundary. It must not create an alternative executable plugin registry.

### 2.4 EngineeringChange

EngineeringChange already owns durable research/architecture/build/verification/acceptance/promotion lifecycle and digest-bound strong owner gates.

Dependency plans, manifest revisions and hardware-acceptance requests should be artifacts/evidence inside this lifecycle. A DependencyBroker or SecretBroker must not become a second approval system.

## 3. Dependency locking and acquisition research

### 3.1 PEP 751 / `pylock.toml`

Python standardized `pylock.toml` in PEP 751. The PyPA specification defines it as a tool-neutral format for reproducible Python dependency installation; lock format version 1.0 is current.

This is a strong canonical interoperability boundary for JARVIS because it avoids persisting one package manager's private lock semantics as architectural truth.

Disposition: **ADOPT as canonical Python lock interchange/evidence format.**

### 3.2 pip

Current pip provides `pip lock` and can emit `pylock.toml`, but the command is still explicitly marked experimental and its generated lock is only guaranteed for the current Python version/platform.

pip's secure-install guidance is still useful and should become policy:

- hashes for every requirement (`--require-hashes`);
- exact pins;
- binary-only distributions (`--only-binary :all:`) when source build is not explicitly approved;
- avoid arbitrary unchecked source/build execution.

Disposition: **retain as compatibility/fallback tool, not the preferred Phase-5 resolver.**

### 3.3 uv

Current uv provides:

- exact project sync;
- `--locked` and `--frozen`;
- PEP 751 `pylock.toml` export and installation;
- offline mode;
- hash verification / `--require-hashes`;
- `--only-binary` to fail rather than execute source-distribution builds;
- cross-platform `uv.lock`;
- CycloneDX export;
- current Windows release artifacts with SHA-256, signatures/attestations.

The current 0.12.18 release also fixes a Windows wheel-install path traversal advisory, which reinforces the need to pin the trusted tool version and provenance rather than invoking “latest”.

Disposition: **ADOPT uv as the first trusted Python DependencyBroker adapter, pinned and provenance-verified.** JARVIS persists PEP 751 and its own typed evidence, not `uv.lock` as the sole canonical record.

### 3.4 Index/source confusion

Current pip documentation explicitly warns that combining a private repository with public candidates through extra-index search is unsafe because all locations are considered and a higher-version public package can win, creating dependency-confusion risk.

Disposition: **Phase-5 v1 uses one explicitly selected registered source policy for a dependency resolution. Public/private extra-index mixing is denied.** Private indexes require an explicit source registration and SecretLease.

### 3.5 Source builds

Both pip and uv documentation make clear that source/build backends can execute code.

Default Phase-5 policy must therefore be:

- wheels/prebuilt artifacts only;
- source distributions/build scripts denied by default;
- a future source-build exception requires an explicit architecture/dependency exception, isolated build sandbox, stronger review, source provenance, and owner approval.

Phase 5 does not silently weaken this rule when no wheel exists.

## 4. Software supply-chain evidence

### 4.1 PyPI attestations

PyPI supports PEP 740 digital attestations using the in-toto Attestation Framework. Supported predicates include PyPI Publish and SLSA Provenance. These bind a release distribution to a digest and publishing identity when present.

Disposition: **capture and verify attestations when available; absence remains explicit evidence, not automatic rejection for all packages in the first slice.**

### 4.2 SLSA

SLSA v1.2 defines provenance as verifiable information describing where, when and how an artifact was produced.

Disposition: **use SLSA-compatible provenance references as optional high-grade evidence, while SHA-256 identity is mandatory for every staged artifact.**

### 4.3 SBOM

CycloneDX 1.7 and SPDX 3.0.1 are both mature interoperability standards. CycloneDX directly represents components, services, dependencies and provenance/pedigree; SPDX covers broader BOM, build, provenance, integrity, license and vulnerability metadata.

uv currently exports CycloneDX 1.5, not 1.7.

Disposition:

- do not make either full external schema the internal canonical object model;
- persist compact typed JARVIS dependency/provenance records;
- permit deterministic CycloneDX/SPDX export later;
- if uv export is used, record the exact CycloneDX version actually emitted.

## 5. Secret storage and materialization research

### 5.1 Windows DPAPI

Microsoft DPAPI provides same-user/same-machine protection by default and integrity-checked unprotect. JARVIS already has an accepted DPAPI abstraction.

Disposition: **ADOPT existing DPAPI KeyProtector for the first production SecretBroker.**

Do not use `CRYPTPROTECT_LOCAL_MACHINE` because it weakens user isolation.

### 5.2 Secret input

Secret plaintext must not travel through:

- voice transcripts;
- model prompts;
- WorkItem request/result payloads;
- EngineeringChange artifacts;
- logs;
- Git;
- command-line arguments.

Python's standard `getpass` supports no-echo console input, including Windows.

Disposition: first trusted enrollment surface is a local `jarvis-secret` CLI using no-echo input. A later native trusted UI may replace or supplement it without changing SecretBroker contracts.

### 5.3 Credential Locker / cloud vault

Windows Credential Locker is available, but it introduces different storage/roaming semantics. A cloud vault would add external service dependency/cost and is unnecessary for a single-owner local Phase-5 substrate.

Disposition: **DEFER**. Re-evaluate only if multi-device JARVIS requires roaming/central secret custody.

## 6. Capability manifest research

JSON Schema Draft 2020-12 remains the current JSON Schema specification.

JARVIS already has Pydantic/dataclass-style typed contracts and RFC-8785 canonical JSON + SHA-256 integrity patterns in EngineeringKnowledge.

Disposition:

- define CapabilityManifest as a versioned JARVIS-owned typed contract;
- canonicalize/digest it deterministically;
- export a JSON Schema 2020-12 representation for tooling/interoperability;
- unknown manifest versions fail closed.

A manifest is declarative evidence. It is never executable authority.

## 7. Discovery research

### 7.1 mDNS / DNS-SD

RFC 6762 defines multicast DNS on the local link. RFC 6763 defines DNS-Based Service Discovery for discovering named service instances by service type/domain.

Disposition: **ADOPT as the first generic local-service discovery adapter family.**

### 7.2 ONVIF

ONVIF device discovery is based on WS-Discovery and returns a device service address for discoverable compatible devices.

Disposition: **SUPPORTED AS A TYPED FUTURE/OPTIONAL ADAPTER**, useful for camera integration, but not required to make the Phase-5 core generic.

### 7.3 No network scanner

Phase 5 discovery must never become arbitrary subnet/port reconnaissance.

Every discovery request must be bound to a typed owner-authorized DiscoveryScope defining protocol, interface/domain, allowed service/device types, duration and maximum results.

Discovery returns evidence/inventory only. It never authorizes control.

## 8. Sandbox research

Docker's supported security controls align with JARVIS's already-accepted test runner:

- read-only container root;
- capability drop;
- `no-new-privileges`;
- network isolation;
- explicit mounts.

The Docker daemon itself is a high-privilege boundary. Models must never receive raw Docker CLI/control.

Disposition: **formalize JARVIS-owned versioned SandboxProfiles.**

Profiles are trusted code/configuration, not model-authored dictionaries of Docker switches.

Initial profiles:

1. `test.offline.v1`
   - current accepted pytest posture;
   - no network;
   - read-only root;
   - no Linux capabilities;
   - no-new-privileges;
   - bounded CPU/RAM/PIDs/time;
   - read-only source mount;
   - dedicated writable temp/output only.

2. `dependency.acquire.v1`
   - narrow network-enabled broker process;
   - no production environment mutation;
   - writes only to immutable staging/cache area;
   - no owner secrets except an explicitly scoped repository credential lease when required;
   - trusted adapter builds all command arguments;
   - TLS verification cannot be disabled;
   - source builds denied by default.

3. `dependency.verify.v1`
   - network off;
   - consumes staged artifacts/PEP-751 lock;
   - hash/provenance verification;
   - wheel-only installation into an isolated candidate environment;
   - no production `.venv` mutation.

Physical LAN/BLE discovery and hardware acceptance should use dedicated host adapters with explicit scopes rather than a generic privileged container.

Rootless Docker is useful defense-in-depth, but is not made a Phase-5 invariant until proven practical on the owner's Windows/Docker Desktop environment.

## 9. Hardware-in-the-loop acceptance research

Real device integration cannot always be proven by CI. Phase 5 needs a typed acceptance boundary, not a free-form “looks good” shortcut.

A HardwareAcceptanceRequest should bind:

- EngineeringChange;
- capability manifest revision/digest;
- exact device/service identity;
- operation/effect being tested;
- expected observable state;
- automated evidence already collected;
- owner action/observation requested.

HardwareAcceptanceEvidence should bind:

- the exact request/digest;
- canonical owner turn or trusted local acknowledgement;
- observed result;
- timestamp;
- optional sensor/device telemetry;
- verifier references.

Owner observation may satisfy a physical-world acceptance criterion, but cannot waive failed automated tests, security, Authority, dependency, provenance or promotion gates.

## 10. Recommended canonical contracts

### 10.1 DependencyRequirement

Fields should include:

- ecosystem;
- normalized package/tool identity;
- version constraint;
- purpose;
- platform/runtime constraints;
- allowed source/index;
- source-build policy;
- requesting change/artifact.

### 10.2 DependencyResolution

- exact resolved versions;
- dependency graph digest;
- PEP-751 lock artifact/digest for Python;
- artifact candidates;
- source/index identities;
- platform tags;
- license metadata when available;
- resolution tool ID/version/digest.

### 10.3 ArtifactProvenance

- SHA-256 (mandatory);
- artifact type;
- size;
- source URI/index identity;
- package/version/platform identity;
- fetched/built timestamps;
- attestation type/status/reference;
- SLSA/in-toto evidence when available;
- SBOM reference/version when exported.

### 10.4 SecretDescriptor

Nonsecret metadata only:

- opaque secret ID;
- kind/provider/service;
- permitted consumers/scopes;
- lifecycle state;
- creation/update metadata;
- rotation/revocation metadata.

### 10.5 SecretLease

- lease ID;
- secret ID;
- requesting WorkItem/EngineeringChange;
- exact consumer;
- allowed materialization mode;
- expiry;
- use count;
- revocation;
- audit reference.

The model may see descriptor/lease metadata but never plaintext.

### 10.6 CapabilityManifest

- manifest schema/version;
- capability ID/version;
- purpose;
- registered adapter/executor IDs;
- operations;
- dependency evidence references;
- secret references/scopes;
- required permissions/Authority attributes;
- network/discovery requirements;
- resource requirements;
- supported platform/device constraints;
- health probes;
- automated verification contracts;
- hardware acceptance contracts;
- enable/disable/rollback;
- source/build provenance;
- lifecycle state.

### 10.7 DiscoveryScope / DiscoveryObservation

Scope:
- registered protocol adapter;
- allowed interface/domain/subnet boundary;
- service/device types;
- optional owner-provided target hint;
- timeout;
- max results.

Observation:
- adapter;
- stable device/service identity;
- addresses/endpoints;
- advertised capabilities;
- source/scope digest;
- timestamp/freshness.

### 10.8 SandboxProfile

- profile ID/version/digest;
- allowed trusted entrypoint;
- network mode;
- mount rules;
- filesystem mode;
- capability/security options;
- CPU/RAM/PID/time budgets;
- environment allowlist;
- secret lease allowance;
- output paths;
- provenance requirements.

## 11. Storage and lifecycle

### Engineering evidence

Dependency requirements/resolutions, capability manifests, provenance summaries, discovery observations and hardware acceptance should remain linked to EngineeringChange artifacts and WorkItems.

Where query-heavy state needs dedicated tables, those tables should still retain exact `change_id`, `work_id`, artifact digest and version provenance.

### Secret values

Secret plaintext/sealed blobs must not enter the WorkStore or EngineeringChange artifact JSON.

Use a dedicated local SecretStore with:

- user-scoped DPAPI-sealed values;
- nonsecret metadata;
- opaque IDs;
- versioned schema;
- deny-by-default ACL/scope checks;
- verify-on-read;
- audit without values.

### Artifact cache

Use content-addressed immutable staging:

`%LOCALAPPDATA%\JARVIS\engineering\artifacts\sha256\<digest>`

Properties:

- create-only/atomic write;
- SHA-256 verify before admission and every security-sensitive use;
- no model-selected absolute path;
- staged artifact != trusted dependency until policy/evidence gates pass.

## 12. Risk model and owner gates

Phase 5 must distinguish ordinary research/evidence from actions that increase local execution capability.

Default gate guidance:

- read-only dependency research: no new strong gate;
- resolution/download to isolated staging from approved index: bounded EngineeringChange action;
- adding a dependency to candidate source/manifest: architecture-bound change evidence;
- source-build exception: strong owner architecture approval;
- creating/replacing/revoking secret: direct trusted owner operation, never model-created plaintext;
- leasing a secret to an already-approved scoped executor: policy + audit; strong approval according to the underlying operation risk;
- discovery: only within owner-approved scope; no control;
- hardware state-changing acceptance operation: normal CapabilityRuntime/Authority rules still apply;
- promotion remains existing EngineeringChange promotion governance.

## 13. Technology dispositions

| Technology / approach | Disposition | Reason |
| --- | --- | --- |
| PEP 751 `pylock.toml` | ADOPT | standard tool-neutral reproducible Python lock evidence |
| uv | ADOPT as first Python broker adapter | mature lock/sync/export/offline/hash/wheel controls; fast; signed/attested releases |
| pip `pip lock` | COMPATIBILITY / DEFER AS PRIMARY | current lock command still experimental/platform-specific |
| pip secure install flags | ADOPT AS POLICY PATTERN | hashes + exact pins + wheel-only are strong baseline |
| PyPI PEP 740 attestations | ADOPT WHEN AVAILABLE | distribution-to-identity/digest evidence |
| SLSA v1.2 provenance | ADOPT AS OPTIONAL HIGH-GRADE EVIDENCE | standard verifiable artifact provenance |
| CycloneDX / SPDX | EXPORT / INTEROP | useful BOM formats, too broad to be canonical internal authority |
| Windows user-scoped DPAPI | ADOPT | already accepted, local, no new service, same user/machine binding |
| Windows Credential Locker | DEFER | different/roaming semantics unnecessary for current single-owner substrate |
| Cloud secret vault | DEFER | added cost/service dependency not required |
| JSON Schema 2020-12 | ADOPT FOR MANIFEST EXPORT/VALIDATION | current standard |
| mDNS/DNS-SD | ADOPT first generic discovery | bounded local service discovery standard |
| ONVIF WS-Discovery | OPTIONAL REGISTERED ADAPTER | useful device-specific discovery |
| arbitrary port/subnet scan | REJECT | violates bounded discovery principle |
| versioned Docker SandboxProfiles | ADOPT | formalizes accepted least-privilege runner |
| model-authored raw Docker/shell/package-manager args | REJECT | bypasses trusted adapter boundary |
| source builds by default | REJECT | can execute build code |
| mandatory external package-routing/security proxy | REJECT | unnecessary control plane/cost; JARVIS remains owner |

## 14. Final research conclusion

The finest practical Phase-5 design is not a new autonomous-agent platform. It is a set of narrow, deterministic security brokers around the already accepted JARVIS engineering lifecycle.

The central pattern is:

`model proposes typed intent -> deterministic broker validates -> canonical Authority/EngineeringChange gates -> isolated trusted adapter -> verify provenance/postconditions -> persist bounded evidence`

This gives later phases enough power to acquire dependencies, secrets and physical integrations while keeping the dangerous primitives out of model control.

## 15. Primary references

- Python Packaging User Guide, `pylock.toml` specification:
  https://packaging.python.org/en/latest/specifications/pylock-toml/
- PEP 751:
  https://peps.python.org/pep-0751/
- pip `pip lock`:
  https://pip.pypa.io/en/stable/cli/pip_lock/
- pip Secure Installs:
  https://pip.pypa.io/en/latest/topics/secure-installs/
- pip index/extra-index dependency-confusion warning:
  https://pip.pypa.io/en/latest/cli/pip_install/
- uv locking/syncing:
  https://docs.astral.sh/uv/concepts/projects/sync/
- uv CLI/export:
  https://docs.astral.sh/uv/reference/cli/
- PyPI Digital Attestations:
  https://docs.pypi.org/attestations/
- SLSA v1.2 Provenance:
  https://slsa.dev/spec/v1.2/provenance
- NIST SP 800-218 SSDF 1.1:
  https://csrc.nist.gov/pubs/sp/800/218/final
- Microsoft DPAPI `CryptProtectData`:
  https://learn.microsoft.com/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
- Python `getpass`:
  https://docs.python.org/3/library/getpass.html
- JSON Schema Draft 2020-12:
  https://json-schema.org/draft/2020-12/
- RFC 6762 / RFC 6763:
  https://www.rfc-editor.org/rfc/rfc6762
  https://www.rfc-editor.org/rfc/rfc6763
- ONVIF Core Specification:
  https://www.onvif.org/specs/
- CycloneDX 1.7:
  https://cyclonedx.org/specification/overview/
- SPDX 3.0.1:
  https://spdx.dev/specifications/
