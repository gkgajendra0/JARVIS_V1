# Phase 5 Secure Autonomous Engineering Substrate — Implementation Plan

Status: **OWNER-APPROVED / AUTHORIZED FOR IMPLEMENTATION**

Owner approval recorded: 2026-09-26

Date: 2026-09-26

Architecture: PHASE5_SECURE_ENGINEERING_SUBSTRATE_ARCHITECTURE.md

Research: PHASE5_SECURE_ENGINEERING_SUBSTRATE_RESEARCH.md

## 1. Execution rule

Implementation must follow the permanent engineering sequence:

research -> architecture -> owner approval -> isolated branch/PR -> CI -> owner-machine acceptance where required -> docs -> merge

The owner explicitly approved the Phase-5 architecture on 2026-09-26. Implementation is authorized under the standing rule to continue slice-by-slice until genuine owner-machine/manual input or a new architectural decision is required.

Every slice must preserve:

- canonical Authority and Windows Hello;
- EngineeringChange lifecycle/gates;
- WorkItem/DBOS durability;
- Phase-4 Model Router behavior;
- protected-main governance;
- no arbitrary shell/package-manager/Docker/network-scanner arguments from model output;
- no plaintext secret persistence/model exposure;
- no direct protected-main .venv mutation;
- no implicit source builds;
- no mandatory paid/cloud control service.

## 2. Slice strategy

Phase 5 should be implemented in small additive PRs. Each slice must be independently testable and merge only when its own acceptance surface is green.

Recommended sequence:

- 5A — canonical contracts, versions, digests and registries;
- 5B — SandboxRegistry and content-addressed ArtifactStore;
- 5C — Python DependencyBroker + trusted uv adapter;
- 5D — dependency provenance and offline candidate verification;
- 5E — SecretBroker + DPAPI SecretStore + trusted enrollment CLI;
- 5F — CapabilityManifestRegistry + JSON Schema export;
- 5G — bounded DiscoveryBroker + mDNS/DNS-SD adapter;
- 5H — HardwareAcceptance contracts/service;
- 5I — EngineeringChange integration, observability and concurrency;
- 5J — evaluation + owner-machine acceptance + final documentation.

Do not parallelize slices whose contracts depend on an unmerged previous slice. Tests/research inside a slice can run concurrently where safe.

## 3. Phase 5A — canonical substrate contracts

### Goal

Create immutable provider-neutral contracts and fail-closed registries with no host/network/secret/package side effects.

### Deliverables

- engineering_substrate package boundary;
- deterministic canonical JSON/digest helper reusing repository RFC-8785 pattern;
- schema/version registry;
- DependencyRequirement;
- DependencyResolution;
- DependencyArtifact;
- ArtifactProvenance;
- SecretDescriptor;
- SecretLease metadata contract;
- CapabilityManifest;
- DiscoveryScope / DiscoveryObservation;
- SandboxProfile;
- HardwareAcceptanceRequest / Evidence;
- enums for lifecycle/evidence states;
- unknown-version errors.

### Tests

- normalization;
- immutable contracts;
- duplicate registry fail closed;
- unknown version fail closed;
- canonical digest stability;
- secret value fields structurally impossible in model-facing contracts;
- raw shell/Docker/port-range fields absent;
- invalid broad discovery scope rejected.

### Exit

No I/O side effects are added. CI green.

## 4. Phase 5B — SandboxRegistry + ArtifactStore

### Goal

Formalize accepted Docker hardening and immutable artifact staging before any dependency acquisition exists.

### Deliverables

SandboxRegistry with fixed profiles:

- test.offline.v1;
- dependency.acquire.v1;
- dependency.verify.v1.

Trusted command builder:

- no raw model args;
- fixed security switches;
- bounded resources/time;
- explicit mounts;
- no Docker socket;
- offline profile uses network none;
- acquire profile cannot mount protected main writable;
- verify profile consumes staged artifacts offline.

ArtifactStore:

- LOCALAPPDATA content-addressed root;
- streaming SHA-256;
- temp -> atomic create;
- verify-on-read;
- metadata/provenance link;
- quarantine path/state for rejected downloads;
- safe garbage-collection reference contract.

### Tests

- digest path cannot be escaped;
- duplicate immutable artifact is idempotent;
- wrong digest rejected/quarantined;
- symlink/path traversal blocked;
- Docker command snapshots prove profile invariants;
- unavailable Docker returns resource blocker, never host fallback.

### Owner-machine gate

One smoke test of the three profile command constructions and offline network isolation may be required on Windows/Docker Desktop.

## 5. Phase 5C — Python DependencyBroker + uv adapter

### Goal

Resolve and acquire reproducible Python wheel dependencies without exposing package-manager authority to models.

### Tool bootstrap

uv is a trusted implementation dependency, not something a model auto-installs.

Initial implementation must:

- pin a reviewed uv version;
- record its executable version and SHA-256;
- verify source/release identity;
- treat missing/wrong uv as resource unavailable.

At architecture research freeze, uv 0.12.18 is the current candidate because it includes the current Windows wheel path-traversal fix. Re-confirm exact release/artifact before implementation pin.

### Deliverables

- registered dependency source policy;
- PyPI HTTPS source v1;
- no extra-index mixing;
- normalized package identity;
- uv resolver adapter using explicit argv list;
- PEP-751 pylock.toml generation;
- exact resolved package graph evidence;
- wheel-only acquisition;
- staged artifact hashes;
- no production environment sync.

### Trusted adapter rules

Allowed operations are fixed methods such as:

- resolve_python(requirement, environment);
- acquire_locked_wheels(resolution);
- inspect_lock(resolution).

The model cannot pass arbitrary uv flags.

### Tests

- stable resolution evidence fixture;
- arbitrary index denied;
- HTTP/TLS bypass denied;
- extra-index mixing denied;
- mutable VCS input denied;
- wheel-only enforced;
- sdist-only fixture blocks;
- protected-main .venv timestamp/content unchanged;
- missing uv -> resource blocker;
- wrong registered uv version/digest -> fail closed.

## 6. Phase 5D — provenance + offline candidate verification

### Goal

Separate networked acquisition from offline trust verification.

### Deliverables

- ProvenancePolicy;
- PyPI index hash capture;
- PEP-740/PyPI attestation client/parser if present;
- SLSA/in-toto reference capture;
- mandatory SHA-256 result;
- explicit NOT_AVAILABLE for optional attestations;
- REJECTED for mismatch/invalid evidence;
- dependency.verify.v1 candidate environment builder;
- offline install from staged wheels and canonical lock;
- deterministic package inventory;
- optional SBOM export metadata, exact format/version recorded.

### Tests

- hash mismatch reject;
- forged/mismatched attestation reject fixture;
- missing attestation not silently reported verified;
- no network during candidate recreation;
- candidate contains only locked dependencies;
- source artifact refused by default;
- provenance digest stable.

### Security note

Do not claim SLSA/PyPI attestation verification unless cryptographic/identity verification actually ran. Presence of an attestation URL alone is not verification.

## 7. Phase 5E — SecretBroker

### Goal

Allow later trusted adapters to use owner secrets without exposing plaintext to models, persistence or global process state.

### Deliverables

SecretStore:

- dedicated LOCALAPPDATA SQLite;
- per-secret user-scoped DPAPI sealed envelope;
- sealed envelope includes security-sensitive ID/scope/version;
- indexed projection cross-checked against sealed envelope;
- schema version;
- atomic create/rotate/revoke;
- no plaintext fallback.

Trusted CLI:

- jarvis-secret entry point;
- enroll/rotate/revoke/list/inspect;
- getpass/no-echo plaintext entry;
- no plaintext argv.

SecretBroker:

- policy-checked lease issuance;
- consumer/scope/expiry/use budget;
- non-transferable process lease;
- restart invalidates active lease;
- direct child-env materialization;
- minimal inherited environment;
- redaction helpers;
- audit metadata only.

### Tests

- owner Windows DPAPI round trip;
- different/malformed sealed blob fails;
- projection scope tamper detected;
- plaintext absent from SQLite byte scan;
- plaintext absent from WorkStore/EngineeringChange artifact/log fixtures;
- no global os.environ mutation;
- lease scope mismatch/expired/revoked/exhausted denied;
- restart simulation requires a new lease;
- command line never contains secret.

### Owner-machine gate

Required because production DPAPI behavior is Windows/user-bound.

Use a disposable non-production test value only. Do not ask the owner to paste it into chat.

## 8. Phase 5F — CapabilityManifestRegistry

### Goal

Create a declarative, digest-bound description of candidate capabilities without creating dynamic execution authority.

### Deliverables

- manifest version 1;
- registry;
- executor/adapter-reference validation;
- dependency/provenance references;
- secret scope requirements;
- SandboxProfile references;
- discovery requirements;
- Authority attribute floor validation;
- verification/hardware contract references;
- disable/rollback contract;
- deterministic digest;
- JSON Schema Draft 2020-12 export.

### Tests

- representative manifest validates;
- unknown version rejected;
- unknown executor cannot activate;
- raw executable/shell field rejected;
- secret plaintext impossible;
- manifest cannot reduce risk floor;
- dependency/sandbox digest mismatch rejected;
- schema output deterministic.

## 9. Phase 5G — bounded DiscoveryBroker

### Goal

Provide safe local-service discovery without creating network reconnaissance or control.

### Deliverables

- DiscoveryAdapter protocol;
- DiscoveryBroker;
- mDNS/DNS-SD v1 adapter;
- scope/digest validation;
- timeout/max-result bounds;
- stable identity/freshness;
- integration projection to existing DiscoverySnapshot/CapabilityDescriptor as discovery-only;
- no execution-enabled flag from discovery alone.

Optional only if genuinely useful during implementation:

- ONVIF WS-Discovery adapter.

Do not implement generic port scanning.

### Tests

- synthetic mDNS/DNS-SD fixtures;
- scope widening denied;
- unsupported service type denied;
- result limit enforced;
- freshness expires;
- discovered descriptor remains execution-disabled without a registered manifest/executor;
- no state-changing network call.

### Owner-machine gate

Try one safe local discovery if a suitable service/device exists. If not, record external unavailability and use deterministic adapter tests.

## 10. Phase 5H — HardwareAcceptance

### Goal

Capture physical-world owner/device evidence without weakening EngineeringChange acceptance.

### Deliverables

- HardwareAcceptanceRequest;
- HardwareAcceptanceEvidence;
- durable request/evidence linkage;
- trusted local resolve surface;
- PASS/FAIL/INCONCLUSIVE;
- expiry;
- exact manifest/device/operation/evidence digest binding;
- service that exposes accepted evidence to EngineeringChange verification.

### Tests

- stale request rejected;
- wrong manifest/device rejected;
- unrelated free-form yes cannot resolve ambiguous request;
- FAIL/INCONCLUSIVE do not satisfy required hardware contract;
- PASS cannot override failed software/security verification;
- duplicate resolution idempotent/CAS-safe.

### Owner-machine gate

One harmless physical observation only if a Phase-5 representative integration genuinely has a physical effect. Do not create a risky action merely to exercise the gate.

## 11. Phase 5I — lifecycle integration

### Goal

Join the brokers into the accepted WorkItem/EngineeringChange architecture without a parallel orchestrator.

### Deliverables

- EngineeringChange artifact types/evidence adapters for dependency plan/resolution, manifest and hardware evidence;
- digest binding from approved architecture to dependency/manifest/profile/secret scopes;
- stale downstream evidence invalidation;
- Work resource keys for resolver/artifact/secret/discovery/docker/device acceptance;
- owner-visible bounded blockers;
- self-awareness operational events with IDs/digests only;
- no new approval authority.

### Tests

- approved architecture cannot silently swap dependency artifact;
- manifest revision invalidates stale verification;
- secret scope revision invalidates stale lease/evidence;
- same WorkItem/Change resumes across restart;
- independent work remains concurrent;
- blocker delivery de-duplicates by stable reason;
- all existing Phase 1–4 Authority/EngineeringChange/ModelRouter regressions green.

## 12. Phase 5J — evaluation and owner acceptance

### Automated evaluation

Build a replay/fixture matrix covering:

- clean PyPI wheel dependency;
- sdist-only dependency;
- bad hash;
- missing optional attestation;
- failed attestation;
- unregistered private index;
- secret missing/revoked/scope mismatch;
- discovery empty/stale/out-of-scope;
- Docker unavailable;
- hardware PASS/FAIL/INCONCLUSIVE;
- restart at each waiting boundary.

Metrics are factual counts/status, not model-assigned trust scores.

### Owner-machine acceptance

Preferred scenario:

1. exact green PR/worktree;
2. harmless dependency through DependencyBroker;
3. PEP-751 + hash/provenance evidence;
4. disposable test secret enrolled via no-echo CLI;
5. scoped child consumes value without persistence/leak;
6. bounded discovery if safe target available;
7. manifest validation;
8. offline candidate verification;
9. optional hardware evidence;
10. restart and same-lineage proof;
11. Authority/security regression;
12. final evidence artifact;
13. docs-only reconciliation;
14. compare accepted code head to docs head;
15. merge only after all gates pass.

### Acceptance failure policy

Never create success by:

- disabling TLS;
- corrupting credentials;
- adding a broad network scan;
- using unsandboxed fallback;
- allowing source build;
- printing a secret;
- bypassing Windows Hello;
- directly mutating protected main.

External limitations are recorded truthfully.

## 13. CI requirements

Every implementation PR should run normal Code Quality plus focused Phase-5 tests.

Security-sensitive slices should add Windows CI where required:

- DPAPI SecretStore;
- path/ACL behavior;
- Windows trusted tool resolution;
- hardware adapters only when deterministic simulation is possible in CI.

Linux CI remains useful for deterministic contracts, provenance, manifests and Docker command generation but must not be treated as proof of owner-Windows DPAPI behavior.

## 14. Documentation/promotion rule

After owner-machine acceptance:

- write PHASE5_SECURE_ENGINEERING_SUBSTRATE_ACCEPTANCE_<date>.md;
- reconcile CURRENT_PLAN, CURRENT_ARCHITECTURE, PROJECT_STATE, ROADMAP and both master plans;
- run final CI;
- compare owner-accepted implementation head to docs head and require docs-only delta;
- merge under existing protected-main governance.

## 15. Stop condition

After this research/architecture/implementation-plan PR is green, **stop**.

Do not start Phase-5 implementation until the owner explicitly approves PHASE5_SECURE_ENGINEERING_SUBSTRATE_ARCHITECTURE.md.

After approval, implementation may continue slice-by-slice under the owner's existing standing authorization, stopping only for genuine owner-machine/manual acceptance or a new architecture decision.
