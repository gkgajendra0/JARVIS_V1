# Phase 9H — Autonomous External Capability Completion

## Status

**IMPLEMENTED ON DRAFT PR #221 / VALIDATION IN PROGRESS — 2026-09-29**

Phase 9H closes the generic infrastructure gaps identified before spending paid
provider quota on the first real autonomous external-capability acquisition test.

This phase is deliberately **device-agnostic**. It must not encode the eventual
acceptance target, its IP address, ports, vendor protocol, application names, or a
preselected SDK/package. The final real test remains responsible for proving that
JARVIS can discover and research those facts itself from a high-level owner request.

## 1. Why Phase 9H exists

The Phase-9 architecture already provided durable acquisition research, exact
architecture approval, isolated development, candidate verification, governed
promotion, Phase-8 package admission/lifecycle and durable owner handoffs.

Preflight analysis found three generic integration gaps between those pieces:

1. the Phase-9 reasoning loop could not invoke the existing governed local-discovery
   substrate;
2. Phase-5 could resolve and verify dependencies, but Phase-9 DEVELOPMENT and the
   promoted production runtime did not have an end-to-end bridge for new runtime
   dependencies;
3. the system had durable owner-input and hardware-evidence primitives, but no generic
   post-activation mission that could invoke a newly acquired capability, pause for a
   pairing/confirmation interaction, resume the same mission and bind the observed
   physical/external result.

Phase 9H fills only those gaps. It does not replace the ownership boundaries of
Phases 5, 7, 8 or 9.

## 2. Reuse decisions

Phase 9H reuses the existing JARVIS control planes instead of introducing parallel
frameworks.

- **DBOS + WorkItem** remain the durable workflow and owner-input/resume substrate.
- **DiscoveryBroker** remains the local-discovery policy boundary.
- **DependencyBroker + pinned uv + ArtifactStore + pylock.toml** remain the only
  Python dependency acquisition path.
- **EngineeringSubstrateChangeService** remains the dependency/manifest evidence
  binding authority.
- **Phase-7 promotion/deployment** remains the only protected-main release path.
- **Phase-8 capability lifecycle** remains the only package enable/disable authority.
- **CapabilityRuntime** remains the operation execution boundary.
- **HardwareAcceptanceService** remains the durable physical/external evidence store.

No second workflow engine, package manager, registry, deployment path or authority
system is introduced.

## 3. 9H.1 — Bounded local discovery

### Added

- SSDP/UPnP M-SEARCH adapter under the Phase-5 DiscoveryBroker;
- Phase-9 RESEARCH action: `acq_discover_local`;
- default discovery composition now supports registered mDNS/DNS-SD and SSDP scopes;
- acquisition completion guard treats local-discovery evidence as plan-invalidating
  evidence, so a plan cannot finalize from stale discovery state.

### Discovery invariants

The model can select only registered adapters and explicit service/search types.

The adapter does not:

- issue `ssdp:all`;
- enumerate arbitrary DNS-SD service types;
- scan subnets;
- scan port ranges;
- fetch/execute discovered services;
- convert discovery into execution authority.

Only local/private/link-local responders are accepted as SSDP observations.

Discovery evidence remains execution-disabled until normal acquisition,
manifest/package and lifecycle controls succeed.

## 4. 9H.2 — Governed dependency acquisition and runtime materialization

### Verified reusable-SDK bridge

Web research remains untrusted metadata. A model-authored SDK candidate is never made
selectable merely because research found a package name or project page.

For Python SDK candidates, Phase-9 RESEARCH now provides
`acq_verify_pypi_sdk`. It accepts only a previously recorded unverified
`sdk_library` candidate with an exact version, then:

1. resolves that exact distribution through the registered
   `pypi.public.v1` source;
2. permits wheel-only artifacts and no source build;
3. seals the canonical `pylock.toml` plus wheel SHA-256 identities in
   ArtifactStore;
4. queries PyPI's official Integrity API and verifies available PEP-740
   attestations through the existing Phase-5 provenance service;
5. assigns `VERIFIED_SIGNED_EXTERNAL` only when the resolved artifacts have
   verified attestations, otherwise `VERIFIED_OFFICIAL_REMOTE` when the exact
   official PyPI artifact/hash path is verified but attestations are unavailable;
6. emits a trusted SDK candidate without importing or executing the package;
7. carries the research-proposed secret/network/device/discovery/external-acceptance
   requirements forward for owner architecture review;
8. binds the candidate dependency reference to the exact verified lock digest.

The deterministic resolver is rerun after this evidence. A verified `ADAPT_SDK`
candidate therefore outranks the last-resort `BUILD_CUSTOM` route when it covers
the owner goal.

Fresh research, local discovery, candidate recording or SDK verification now
invalidates the previous source resolution. The stage must
`re-resolve -> re-finalize` before it can complete.

### DEVELOPMENT bridge

Phase-9 DEVELOPMENT can now use typed JARVIS actions to:

1. request one dependency already declared by the owner-approved acquisition
   architecture;
2. require an exact package version;
3. resolve through the existing registered Phase-5 dependency source policy;
4. acquire wheel-only artifacts;
5. admit the canonical lock and wheels into the content-addressed ArtifactStore;
6. bind exact dependency resolution evidence to the EngineeringChange;
7. bind the capability manifest from the approved architecture and current evidence;
8. require current Phase-5 substrate verification before DEVELOPMENT completion.

The model never receives raw package-manager flags or unrestricted shell/install
authority.

### Reviewed uv runtime

The production dependency path uses the already-reviewed pinned uv release. The
owner machine must persist two non-secret machine settings after Phase-5 acceptance:

- `JARVIS_UV_EXECUTABLE_PATH`
- `JARVIS_UV_EXECUTABLE_SHA256`

Every use re-verifies the configured executable against the reviewed version,
release commit, release artifact policy and executable SHA-256.

### Release-local runtime overlay

A promoted Phase-9 release that declares new Python dependencies receives a
release-specific dependency overlay built before the runtime switch.

The materializer:

- reads only the exact dependency resolutions bound to the current manifest;
- verifies canonical lock artifacts and wheel hashes from ArtifactStore;
- performs an offline/hash-bound target installation through the reviewed uv adapter;
- stores the overlay outside protected main and outside the detached Git release;
- records a deterministic overlay tree digest;
- verifies the overlay again before use;
- rejects symlinks;
- rejects executable `.pth` startup logic;
- rejects attempts to shadow `jarvis` or Python standard-library modules;
- refuses conflicting versions of distributions already present in the JARVIS
  runtime.

The overlay is appended after normal interpreter/site-package paths. Protected main,
the shared JARVIS virtual environment and the detached release worktree remain
unchanged.

## 5. 9H.3 — Durable real external acceptance

A new provider-neutral `WorkType.EXTERNAL_ACCEPTANCE` is used after the owner
explicitly activates an acquired Phase-9 package.

This is intentionally a separate durable WorkItem linked to the same
EngineeringChange/activation rather than a new EngineeringChange process stage.
The canonical Phase-9 process contract therefore remains RESEARCH + DEVELOPMENT.

### Lifecycle

```text
explicit owner activation
    -> exact activation/binding inspection
    -> prepare hardware/external acceptance request
    -> explicit owner approval for first real effect
    -> invoke activated CapabilityRuntime operation
       -> optional pairing/confirmation request
       -> WAITING_FOR_OWNER
       -> resume the same WorkItem
       -> retry with owner input
    -> accept independent device/system readback when available
       OR ask owner to confirm the physical effect
    -> HardwareAcceptanceService evidence
    -> durable Phase-9 external-acceptance artifact
```

### Generic interaction contract

An acquired capability may return a bounded `owner_input_request` when execution
requires owner participation.

Supported kinds are:

- `pin`;
- `confirmation`.

A request may supply a bounded parameter name to inject on resume.

PIN values use the protected WorkStore sensitive-input channel. The normal durable
`owner_input` WorkStep records only that a redacted value was supplied; it does not
persist the PIN in model-visible WorkStep evidence. The value is atomically consumed
when the capability resumes.

### Real-effect evidence

An acquired capability may provide independent acceptance evidence through a bounded
`acceptance_observation` object using:

- `device_state_readback`; or
- `external_system_readback`.

If independent readback is unavailable, the WorkItem asks the owner to confirm
whether the expected physical effect occurred.

Hardware PASS cannot waive failed software, dependency, provenance, sandbox,
promotion or lifecycle checks.

## 6. 9H.4 — Integrated acceptance requirements

Phase 9H is not considered accepted merely because the code exists.

The deterministic/CI baseline must prove:

1. formatting and lint pass;
2. the full Linux pytest suite passes;
3. Windows platform regression lanes pass;
4. existing Phase-7, Phase-8 and Phase-9 replay/acceptance regressions remain green;
5. SSDP discovery remains bounded and rejects broad enumeration;
6. new local-discovery evidence invalidates stale Phase-9 finalization;
7. a sensitive pairing value is never stored in the normal WorkStep response;
8. a sensitive pairing value is one-time consumed;
9. a research-discovered SDK remains blocked until trusted source verification;
10. a verified exact-version PyPI SDK can outrank the custom-build fallback;
11. a verified SDK's exact lock digest is carried into owner-reviewed architecture
    and enforced again during DEVELOPMENT;
12. fresh research/source-verification evidence requires re-resolution before
    re-finalization;
13. external acceptance cannot complete after a successful invocation without
    durable real-world evidence;
14. explicit owner decline is represented truthfully rather than converted to a
    false failure/success;
15. runtime dependency overlays fail closed after tampering;
16. runtime dependency overlays reject executable `.pth` startup logic;
17. promotion prepares required runtime dependencies before switching the active
    runtime;
18. protected main and the shared JARVIS environment remain unchanged.

## 7. Final paid real-world test

Only after the deterministic baseline is green should provider quota be purchased
for the autonomous acquisition experiment.

The owner request should remain high-level, for example:

> JARVIS, build yourself a capability to control my TV on the local network.

For a fair test, the owner should not provide JARVIS with pre-researched vendor
protocol details, target IP/port details, a preferred integration package, or
implementation code.

Valid owner interactions during the experiment are governance/physical boundaries,
not autonomy failures:

- architecture approval;
- acceptance/promotion decisions required by existing Authority;
- explicit package activation;
- a pairing PIN or device-side confirmation when the external device itself requires
  it;
- physical-effect confirmation when no trusted readback exists.

The owner should **not** need to research the integration, write code, install the
candidate dependency manually, perform Git operations, or debug the implementation.

## 8. Non-goals

Phase 9H does not:

- implement a TV capability;
- implement any vendor-specific external-device protocol;
- weaken Phase-5 discovery or dependency policy;
- permit arbitrary shell/package installation;
- auto-enable newly admitted capabilities;
- replace Phase-7 promotion;
- replace Phase-8 lifecycle Authority;
- claim the deferred real external lifecycle is already proven.

The final physical/external run remains separate acceptance evidence.

## 9. Current implementation location

Implementation branch:

`feat/phase9h-autonomous-external-completion`

Draft review:

`PR #221 — Phase 9H: complete autonomous external capability acquisition`

The PR must remain unmerged until CI, regression review and owner approval are
complete.


## 10. External research basis

Phase 9H deliberately reuses patterns and primitives that are already mature outside
JARVIS instead of recreating them.

### Durable owner pause/resume

DBOS documents durable workflows that recover from the last completed step after
interruption, plus persisted workflow messaging through `send` / `recv`. This
matches the existing JARVIS WorkItem design for pairing/confirmation pauses, so a
second orchestration engine was rejected.

References:

- https://docs.dbos.dev/python/tutorials/workflow-tutorial
- https://docs.dbos.dev/python/tutorials/workflow-communication

### Local discovery

Home Assistant's developer architecture uses mDNS/Zeroconf and SSDP as first-class
local-network discovery mechanisms. JARVIS already had python-zeroconf-backed mDNS,
so Phase 9H adds the missing SSDP policy adapter rather than a general subnet scanner.

The production/stable `async-upnp-client` project was also reviewed. It provides
mature SSDP/UPnP discovery and was originally written for Home Assistant. It was not
added as a JARVIS-core dependency in this phase because doing so would create a
bootstrap dependency on the dependency-acquisition mechanism that 9H itself is
completing. The bounded SSDP M-SEARCH transport is therefore implemented behind the
existing DiscoveryBroker using the standard protocol and standard-library sockets.

References:

- https://developers.home-assistant.io/docs/network_discovery/
- https://pypi.org/project/async-upnp-client/

### Python dependency resolution/materialization

The existing Phase-5 pinned `uv` adapter remains the package-management boundary.
Current uv supports offline operation, hash-required installs, wheel-only policy and
installation into an explicit target directory. These primitives map directly to a
release-local dependency overlay without mutating protected main or the shared JARVIS
environment.

Reference:

- https://docs.astral.sh/uv/reference/cli/

### Package provenance

PyPI's Integrity API exposes PyPI's PEP-740 provenance objects for individual release
files. Phase 9H reuses the existing Phase-5 provenance service to consume that
evidence when verifying a research-discovered SDK candidate rather than trusting a
model-authored package name or project page.

References:

- https://docs.pypi.org/api/integrity/
- https://docs.pypi.org/attestations/

### Rejected alternatives

The research did not justify introducing Temporal, LangGraph or another workflow
engine because DBOS already owns durable execution and owner message resume.

A broad ARP/subnet scanner was also rejected for the first implementation because
mDNS + SSDP cover the intended discovery class while preserving the Phase-5
non-reconnaissance boundary. If a future capability genuinely requires another
discovery protocol, it should be added as another reviewed DiscoveryBroker adapter
with an explicit scope rather than granting generic scan authority.
