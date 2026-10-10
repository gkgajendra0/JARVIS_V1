# Phase 9 — Owner-Requested Capability Acquisition Architecture

## Status

**OWNER-APPROVED / FROZEN FOR IMPLEMENTATION — 2026-09-27**

The owner approved implementation after the Phase-9 research and technology-disposition review on 2026-09-27. This architecture is the binding implementation contract until new concrete evidence requires revision.

## 1. Purpose

Phase 9 is the first complete **capability-to-build-capabilities** milestone.

The target behavior is:

> Owner: "JARVIS, I want to control this TV through you. Get that capability."

JARVIS should determine whether the capability already exists, discover and compare reusable integration routes, propose an exact architecture, wait for required owner approval, adapt/generate/build in isolation, verify the candidate, perform owner-assisted real-world acceptance where software alone cannot observe the outcome, package the result through Phase 8, promote source changes through Phase 7, observe production behavior, and retain verified EngineeringKnowledge.

Phase 9 is successful when the owner can acquire one real new capability without manually researching, coding, managing Git, or debugging the candidate.

## 2. Architectural rule

Phase 9 owns **acquisition intelligence**, not another execution/control plane.

It must reuse:

- EngineeringChange + WorkItem + DBOS for durable work;
- Phase-4 model routing for research/reasoning;
- Phase-5 dependency, ArtifactStore, provenance, secrets, sandbox, discovery and CapabilityManifest controls;
- Phase-6 isolated development, verification and protected-surface controls;
- Phase-7 exact promotion/release/observation/rollback;
- Phase-8 CapabilityPackageV1, provider registry, compatibility, lifecycle registry and runtime projection.

It must not create a second:

- task/work database;
- orchestration runtime;
- approval/Authority system;
- secret store;
- sandbox;
- package registry;
- capability lifecycle database;
- promotion/deployment path;
- health truth system.

## 3. Process contract

Register one EngineeringChange process family:

`owner_capability_acquisition.v1`

Stages:

```text
RESEARCH
  acquisition
    -> exact owner goal
    -> current capability check
    -> source discovery
    -> normalized candidates
    -> evidence/trust/requirements
    -> selected acquisition plan
    -> architecture artifact

OWNER ARCHITECTURE GATE

DEVELOPMENT
  development
    -> existing isolated worktree
    -> adapt/generate/build selected route
    -> dependency/secret/sandbox/provenance controls
    -> tests + candidate evidence

VERIFICATION / ACCEPTANCE
    -> capability-specific deterministic verification
    -> owner-assisted physical/external acceptance if required
    -> Phase-8 package evidence
    -> Phase-7 promotion
```

The architecture-source role remains a normal `WorkType.RESEARCH` WorkItem. Phase 9 adds typed acquisition actions/results; it does not create a new WorkType.

## 4. New domain

Create `jarvis.capability_acquisition`.

### 4.1 OwnerCapabilityGoalV1

Immutable normalized intent evidence:

- goal_id;
- exact owner request;
- requested capability key/description;
- required semantic operations;
- optional target hints;
- source session/turn identity;
- created timestamp;
- canonical digest.

The goal is intent evidence, not execution Authority.

### 4.2 AcquisitionSourceKind

Initial source kinds:

- `existing_capability`;
- `owner_configured_local`;
- `mcp`;
- `openapi`;
- `asyncapi`;
- `sdk_library`;
- `custom_build`.

The enum is extensible only through source change and review.

### 4.3 AcquisitionTrustClass

Deterministic source/evidence classes:

- `accepted_release`;
- `owner_configured`;
- `verified_official_remote`;
- `verified_signed_external`;
- `unverified_candidate`.

A model may recommend a class, but only a registered source adapter/evidence verifier can assign it.

### 4.4 AcquisitionStrategy

- `reuse`;
- `wrap`;
- `generate_contract_client`;
- `adapt_sdk`;
- `build_custom`.

Default preference order is the same. Custom source generation is the last resort.

### 4.5 AcquisitionCandidateV1

Immutable candidate evidence:

- candidate_id;
- source kind;
- stable source identity;
- source version;
- immutable source/evidence digest when available;
- trust class;
- supported semantic operations;
- required dependency references;
- required secret scopes;
- required network/device/discovery scopes;
- license/provenance evidence references;
- adaptation strategy;
- verification requirements;
- external acceptance requirements;
- reason codes;
- canonical digest.

Candidate records may not contain arbitrary shell commands, argv, import paths, executable paths, plaintext credentials or installer flags.

### 4.6 AcquisitionCandidateEvaluationV1

Deterministic evaluation facts:

- candidate digest;
- selectable / blocked disposition;
- operation coverage;
- evidence completeness;
- trust-policy result;
- dependency-policy result;
- secret/network/device requirement compatibility;
- reason codes;
- evaluator version;
- canonical digest.

Numeric model confidence never makes a candidate selectable.

### 4.7 CapabilityAcquisitionPlanV1

The exact selected plan:

- owner goal digest;
- selected candidate ID/digest;
- strategy;
- requested operations;
- expected changed components/paths;
- dependency/provenance requirements;
- secret scopes;
- sandbox/discovery/network requirements;
- verification contracts;
- owner-assisted acceptance contracts;
- proposed capability/package identity;
- rollback/disable behavior;
- exact evidence references;
- canonical digest.

This plan is used to derive the canonical EngineeringChange architecture artifact reviewed by the owner.

## 5. CapabilitySourceAdapter

Define a JARVIS-owned replaceable protocol:

```python
class CapabilitySourceAdapter(Protocol):
    source_kind: AcquisitionSourceKind

    def discover(
        self,
        goal: OwnerCapabilityGoalV1,
        context: AcquisitionContextV1,
    ) -> tuple[AcquisitionCandidateV1, ...]: ...
```

Rules:

- adapters produce normalized evidence only;
- adapters do not mutate JARVIS;
- adapters do not install dependencies;
- adapters do not enable capabilities;
- adapters do not become package registries;
- adapter failure cannot broaden privileges or silently fall through to arbitrary shell/code execution.

Initial adapters:

1. `ExistingCapabilitySourceAdapter`;
2. `OwnerConfiguredSourceAdapter`;
3. `McpCapabilitySourceAdapter`;
4. `OpenApiCapabilitySourceAdapter`;
5. `AsyncApiCapabilitySourceAdapter`;
6. `SdkLibraryCapabilitySourceAdapter`;
7. `CustomBuildSourceAdapter`.

Implementation may land adapters incrementally. The resolver contract must exist before external adapters.

## 6. Existing capability check

Existing capability/package reuse has highest priority.

Before researching a new integration, Phase 9 checks:

- current `CapabilityRuntime` descriptors;
- Phase-8 PACKAGE_MANAGED registry inventory;
- release-owned provider inventory;
- desired/effective state and compatibility;
- operation coverage.

If an existing capability already satisfies the owner goal, acquisition resolves to `reuse` and does not create unnecessary source code.

A disabled but compatible package may require a normal Phase-8 lifecycle proposal rather than a new EngineeringChange implementation.

## 7. Candidate resolver

Introduce `CapabilityAcquisitionResolver`.

Responsibilities:

1. call registered source adapters under bounded policy;
2. canonicalize/deduplicate candidates by source identity + digest;
3. evaluate deterministic policy/evidence facts;
4. remove blocked candidates from automatic selection;
5. apply deterministic strategy preference:
   `reuse -> wrap -> generate_contract_client -> adapt_sdk -> build_custom`;
6. prefer stronger verified evidence when strategies are otherwise equivalent;
7. persist the complete candidate/evaluation set;
8. return a selected candidate only when deterministic requirements are satisfied.

The resolver may use model reasoning to interpret owner semantics and compare tradeoffs, but final selectable/blocking conditions are deterministic.

## 8. MCP boundary

MCP is adopted as a standardized acquisition/integration protocol, not as Authority.

Phase 9 may discover:

- owner-configured MCP servers;
- approved registry metadata;
- remote Streamable HTTP MCP servers;
- local exact-pinned MCP servers.

Rules:

- MCP tool/server descriptions are untrusted input;
- registry presence is discovery evidence only;
- JARVIS exposes only selected semantic operations;
- credentials remain SecretBroker-managed;
- network destinations remain allowlisted;
- local server dependencies/processes use Phase-5 controls;
- no `npx -y`, unpinned package execution, arbitrary command strings or registry-directed executable paths;
- remote MCP tools still pass JARVIS Authority before state-changing execution.

The persistent Phase-8 package contract references only trusted provider identities, never arbitrary MCP launch commands.

## 9. OpenAPI / AsyncAPI boundary

Machine-readable contracts are preferred over hand-written protocol clients.

OpenAPI/AsyncAPI source adapters may:

- parse an owner/research-discovered contract;
- enumerate operations/channels;
- normalize schemas/auth requirements;
- generate candidate evidence;
- request generated client plumbing through approved DEVELOPMENT work.

Generation tooling is a build aid only. Generated source remains candidate code and must pass normal sandbox/provenance/tests.

Phase 9 must not expose an entire large API automatically. The resulting capability package exposes the smallest semantic operation set needed for the owner goal.

## 10. Development-worker backend

Phase 9 preserves the current DEVELOPMENT worker as baseline.

Introduce a narrow future-compatible `DevelopmentWorkerBackend` boundary only if needed by implementation evidence.

ACP is the preferred protocol for interchangeable external coding-agent workers, but:

- ACP is not Authority;
- ACP permission callbacks are not JARVIS security boundaries;
- external coding agents must run inside JARVIS-owned worktree/sandbox/network/secret constraints;
- no ACP dependency is required merely to complete 9A/9B;
- a default ACP backend is selected only after a JARVIS-specific benchmark against the current worker.

OpenHands/other coding agents remain optional workers behind this boundary.

## 11. Research completion

The acquisition RESEARCH WorkItem completes only when:

1. the canonical owner goal exists;
2. existing capability/package inventory was checked;
3. at least one source path was evaluated, unless existing reuse fully satisfies the goal;
4. every candidate has typed source/trust/evidence/requirements;
5. blocked/unverified candidates remain visibly blocked;
6. one exact acquisition plan is selected, or the result truthfully records no safe route;
7. the final plan references only canonical candidate/evidence IDs;
8. architecture payload can be deterministically derived.

Free-form model text cannot complete the acquisition stage.

## 12. Architecture artifact

A Phase-9 source-completion handler derives the canonical `architecture` artifact from the selected `CapabilityAcquisitionPlanV1`.

The architecture artifact includes:

- exact goal/plan/candidate digests;
- chosen source/strategy;
- semantic operations;
- expected code/config/package changes;
- dependency/provenance/secret/network/sandbox requirements;
- verification and external acceptance requirements;
- Phase-8 package identity/manifest/provider expectations;
- rollback/disable semantics;
- protected-surface classification.

The existing GateService/strong owner verification remains the only transition to write-capable DEVELOPMENT work.

## 13. Development handoff

After owner approval, reuse the existing DEVELOPMENT WorkItem.

Its context binds:

- exact owner goal;
- selected candidate and plan digests;
- architecture artifact;
- allowed changed scope;
- dependency/provenance requirements;
- verification targets;
- expected package descriptor/manifest/provider changes.

Existing development controls remain binding: isolated worktree, bounded typed file actions, sandboxed tests, tests after latest edit, final diff, clean commit and no implicit push/merge.

## 14. Capability candidate evidence

Before Phase-9 verification can advance, persist `CapabilityAcquisitionCandidateEvidenceV1` binding:

- change/work IDs;
- plan and architecture digests;
- branch/commit/diff digest;
- changed paths;
- verified tests/targets;
- dependency/provenance evidence;
- secret scopes without secret plaintext;
- expected `CapabilityPackageV1` descriptor digest;
- expected manifest/provider identity;
- external acceptance state;
- protected-surface verdict;
- canonical digest.

Model claims are not evidence.

## 15. Phase-8 package bridge

Every newly created Phase-9 capability is `PACKAGE_MANAGED`.

Phase 9 may prepare package/manifest/provider source changes in the candidate release, but package admission and lifecycle remain Phase 8.

Registration alone never enables execution.

After the source release is promoted through Phase 7:

1. `ReleaseCapabilityPackageSource` sees the exact descriptor in the active release;
2. Phase-8 admission validates package/manifest/provider/artifact evidence;
3. lifecycle enable/version selection goes through existing Phase-8 Authority;
4. runtime projection remains generation-fenced and fail-closed.

## 16. Phase-7 promotion bridge

Any source change still uses exact Phase-7 candidate/PR/CI/promotion/release identity.

Phase 9 cannot:

- merge protected main;
- deploy directly;
- replace Phase-7 owner promotion;
- mutate the production checkout;
- bypass release observation or rollback.

## 17. Supply-chain policy

Discovery and trust are separate.

Initial priority:

1. accepted-release code/package;
2. owner-configured trusted local integration;
3. verified official remote protocol/API;
4. exact pinned external dependency through Phase 5;
5. signed external artifact when needed;
6. unverified candidate only for research/sandbox, never production execution.

OCI/ORAS and Sigstore/Cosign are conditional future transports/verifiers for external prebuilt capability artifacts.

TUF is deferred until JARVIS actually depends on a persistent remote capability repository/update channel.

No JARVIS-specific signing ecosystem is introduced.

## 18. Failure semantics

- no candidate -> truthful blocked/no-safe-route result;
- source unavailable -> WAITING_RESOURCE or bounded failure;
- missing owner credential/pairing/PIN -> WAITING_FOR_OWNER, preserving same change/work identity;
- candidate becomes stale -> invalidate/re-research; never silently substitute;
- architecture digest changes -> old approval invalid;
- dependency/provenance verification failure -> no development acceptance;
- external physical result cannot be independently observed -> owner-assisted acceptance required;
- package compatibility failure -> Phase-8 effective state stays unavailable;
- promotion/production regression -> Phase-7 rollback.

## 19. Protected surfaces

Phase-9 ordinary acquisition may not autonomously modify:

- Authority/approval policy;
- protected-main/ruleset/CI governance;
- SecretBroker policy;
- sandbox policy;
- Phase-7 promotion/rollback policy;
- Phase-8 registry/admission/lifecycle policy;
- acceptance/evaluator code capable of self-approving the same change.

Normal capability/provider source is not automatically protected merely because it is new, but the existing protected-surface classifier remains authoritative.

## 20. Real-world acceptance target

Phase 9 is not complete after synthetic fixtures alone.

Final owner-machine acceptance requires one genuine owner-requested capability with external state.

Preferred reference case remains a TV/device integration if the owner has a reachable supported route. Another real capability is acceptable if it exercises the same lifecycle.

Acceptance must prove:

- owner goal admission;
- duplicate/existing capability check;
- real source discovery/research;
- architecture proposal + exact owner gate;
- isolated implementation without manual coding/Git/debugging by the owner;
- dependency/secret handling;
- automated tests;
- real external/physical verification where applicable;
- package descriptor/manifest/provider evidence;
- Phase-7/8 integration;
- production observation;
- rollback/disable path;
- protected main unchanged except through governed promotion.

## 21. Permanent invariants

1. Owner request is intent, not unrestricted Authority.
2. Discovery metadata is never trust.
3. External descriptions/contracts are untrusted input.
4. No unpinned package execution/install path.
5. No arbitrary model-authored shell.
6. Credentials never enter capability/package metadata.
7. Acquisition cannot broaden sandbox/network/device scope.
8. Candidate selection cannot weaken Phase-5 constraints.
9. Every new Phase-9 capability is PACKAGE_MANAGED.
10. Registration alone never enables execution.
11. Phase 7 remains source-production promotion truth.
12. Phase 8 remains capability-lifecycle truth.
13. DBOS/WorkItem remains durable execution truth.
14. EngineeringChange remains governed engineering truth.
15. External frameworks remain replaceable workers/adapters, never canonical JARVIS Authority/work/memory/package/promotion truth.


## 22. Unverified candidate governance boundary

Research may discover and propose reusable source identity, version, semantic operations,
license metadata and evidence references. It may not establish canonical governance by
free-form model prose.

For `acq_record_candidate`:

- verification requirements are deterministic source-type contract IDs;
- trust remains `UNVERIFIED_CANDIDATE`;
- model-authored secret/network/device/discovery scopes are not accepted at this step;
- model-authored external/owner acceptance requirements are not accepted at this step;
- later trusted source verification/evidence and deterministic plan/Authority layers own
  those contracts and scopes.

This keeps candidate identity/digests reproducible and enforces the existing invariant
that discovery metadata is not Authority or trust.
