# Verified Target and Access Preflight — Phase 9 Integration Architecture

Status: implementation candidate; source anchor `a8b543f8ae54a936953bc713d6511ee1de32321c`. Requires CI, owner-machine and independent review before promotion. No approval, owner-store migration, network-policy change or production activation is authorized by this document.

## Defect and evidence

The owner requests a reusable ability to control **their television**. A GICC gap with `target_entity_type=television` and `target_entity_id=None` enters Phase 9. Its immutable owner capability goal contains `entity_type:television` only. The planner chooses custom-build and later Roku ECP. Roku-specific `device_scopes` and SSDP `roku:ecp` are accepted into an architecture even though the registered SSDP policy excludes that discovery target; the local discovery request was correctly rejected. The architecture is nevertheless owner-approved and enters development. This must never count as evidence of control over a Hisense U7N/VIDAA owner device.

Code anchors: `goal_intelligence/composition.py` (resource resolution depends on model-proposed entities; missing `target_entity_id` allowed in requirements); `goal_intelligence/phase9.py` (`to_v1` includes only entity type if ID missing); `capability_acquisition/target_compatibility.py` (intrinsic custom-build verdict is not protocol evidence); `engineering_change/delivery.py` (architecture gate summary omits physical device/network scopes).

## Boundary and invariants

1. JARVIS does **not** invent or presume a target, manufacturer, protocol, endpoint, permission, or verified operation. Model strings are proposals only.
2. The canonical GICC WorldRegistry and ResourceBindingV1 remain authoritative for known entities/bindings; DiscoveryBroker/Authority/CapabilityRuntime/Phase 8/WorkStore remain existing owners. No parallel device store.
3. Distinct evidence states: known entity, recent observation, reachable endpoint, authentication, operation authorization, actual effect verification. None implies the next state.
4. For a request to act on a particular physical device, derive requirements with a **concrete, independently grounded `target_entity_id`** before admitting a device-specific Phase 9 build. Only entity type is insufficient. An alias of an unverified configured device is not proof of live reachability.
5. Generic platform-level capabilities with no physical target are not subjected to a fabricated device prerequisite. A shared semantic capability may be built generically, but no target-specific transport/protocol may be claimed as compatible without evidence.
6. Discovery is bounded, explicit, read-only and registered. Rejected discovery is a failed observation, not a license to widen SSDP targets or silently substitute another device family. Do not introduce unrestricted scans or treat `ssdp:all` as safe.
7. A technology proposal is not physical compatibility. Existing capabilities, custom builds, packages and SDK integrations all require matching target evidence when claiming target-specific access.
8. At owner approval, show device identity, evidence source/freshness, protocol, operations, credential/pairing requirements, device/network scope, tests, unresolved unknowns and what will require owner-machine verification. Fingerprint the exact artifact. Do not assume acknowledgement resolves unknown prerequisites.
9. Preserve current goal, original owner request, linked gap, work history and previously recorded decisions. A change in target identity/protocol requires a **new digest-bound architecture** and separate approval. Never edit old approvals or underlying owner data to make tests pass.
10. External acceptance must observe a genuine effect on the exact owner device, then verify the installed capability survives restart, is reusable, and completes the original GICC goal.

## Intended flow

```
owner goal
 -> GICC interpretation and semantic requirements
 -> deterministic physical-target requirement check
 -> registry/entity resolution, then bounded discovery, then InformationNeed
 -> independently observed/confirmed target identity
 -> Phase 9 reuse/source research, with explicit target evidence
 -> per-target protocol/scope compatibility (unproven != compatible)
 -> architecture + transparent approval
 -> governed implementation and offline tests
 -> owner-device external acceptance and operation verification
 -> promotion, Phase 8 registration/activation, restart, original-goal continuation
```

Missing device identity blocks device-specific acquisition while allowing information gathering. Missing reachable/authenticated evidence should not be recast as verified control, but research may proceed under an explicit unresolved state to determine pairing requirements. A build requires proof of the specific target/protocol; physical execution requires fresh authorization. If device is unavailable, report `unavailable` instead of guessing. A canonical, owner-confirmed device identity can support offline architecture research but does not by itself prove control access.

## Implementation steps (ordered, no shotgun changes)

1. GICC intake: derive deterministic physical target requirement from validated semantic requirements. If unresolved, use existing world registry + bounded discovery and exact InformationNeed with owner as last resort; preserve original goal and resume. Enforce the binding in RequirementValidator and Phase9GoalBridge, not only the LLM prompt.
2. Phase 9: validate GICC target context before acquisition finalize/architecture and before any restart/resume that could submit development; require sourced vendor/platform/protocol compatibility for a target-specific plan. Custom `owner-goal:` provenance proves origin, not target compatibility. Maintain generic acquisition paths.
3. Evidence: record stable `entity_id` with verifiable provenance, observation timestamp/TTL, resolved protocol and declared per-operation support; do not promote a discovery observation to an executor. Authoritative evidence schema to be chosen after store/connector integration checks.
4. Gate review: add target evidence/scope and unresolved prerequisites to owner summary, without leaking credentials or unreviewed network addresses.
5. Recovery: block the currently approved Roku plan without mutating owner store. Request a governed architecture revision only once new target evidence exists. Revoke no prior owner decision; supersede it with a new artifact and fresh approval.
6. Tests: explicit missing/ambiguous/stale/wrong-device/wrong-protocol/SSD P-policy-rejected/no-auth/no-authority/false-success cases, plus generic nondevice acquisition; restart, duplicate reconcilers, prior approved incorrect architecture, requirement graph/digest lineage and exact goal continuity.
7. CI then real owner-machine acceptance. No merge, activation, or production claim until both gates pass.

## Decisions that require further validation

- Real TV protocol and permissions: confirm by approved local discovery/owner-device inspection. This document makes **no** claim that Roku ECP, VIDAA ports or other transports are enabled.
- Whether the GICC default-media-target entry has a verified binding: check it; a machine-config alias alone is not an execution permit.
- How to attach typed device evidence to existing change without mutating immutable goal and digest-bound approval artifacts: use append-only artifacts and latest-source provenance.
- Recovery of the already developing change must use an existing governed revision/state transition, not direct SQLite edits.

## Acceptance contract

An owner can say “acquire control of my TV” without specifying brand. JARVIS finds a uniquely grounded device or requests the smallest necessary clarification; it does not build for a guessed platform. The approved plan matches the device, its network/protocol and restrictions. Simulated tests cannot satisfy external physical acceptance. The exact target responds to an authorized action, its effect is observed, installed capability is reused after restart, and the original owner goal—not a test surrogate—is completed.
