# Phase 9 — Owner-Requested Capability Acquisition Implementation Plan

## Status

**DONE (BOUNDED) / OWNER ACCEPTED — 2026-09-28 — FINAL END-TO-END EXTERNAL VALIDATION DEFERRED**

Original reviewed implementation head: `81d498a22bb2293d69c6b6a848b08740fae30f75`

PR #178 protected-main merge: `e73db07abad7ab0e73ee2f0030ff6e58e9f3ee76`

Target-aware live-routing hardening was subsequently completed by PR #180 and squash-merged to protected main as `15974c4089aeea014dc68f4a6fb385072278b379`. The final PR #180 CI run passed the required Linux/Windows regression and promotion-policy gates.

The 2026-09-28 owner-machine run proved target-aware Phase-9 admission, canonical EngineeringChange/WorkItem durability, provider-pressure survival and bounded Gemini -> OpenAI fallback behavior. The run could not progress through the complete external TV lifecycle because Gemini was rate-limited and the configured OpenAI fallback was quota-exhausted.

The owner explicitly accepted Phase 9 as bounded and chose not to purchase provider quota solely for this intermediate acceptance. The complete external lifecycle — research through real device effect and disable/rollback — remains mandatory final-system validation and must not be represented as already proven.

Phase 10 may now become active under this explicit owner sequencing decision.

Canonical acceptance-status record: `PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_ACCEPTANCE_2026-09-27.md`

Architecture: `PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_ARCHITECTURE.md`

Research: `PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_RESEARCH.md`

## 9A — acquisition contracts + EngineeringChange process

Deliver:

- `jarvis.capability_acquisition` package;
- `OwnerCapabilityGoalV1`;
- source/trust/strategy/disposition enums;
- `AcquisitionCandidateV1`;
- `AcquisitionCandidateEvaluationV1`;
- `CapabilityAcquisitionPlanV1`;
- canonical digest/normalization/closed validation;
- `owner_capability_acquisition.v1` ProcessContract using RESEARCH -> DEVELOPMENT;
- protected-surface registration for Phase-9 policy/control files;
- deterministic contract/process tests.

Exit gate: typed Phase-9 truth exists, but no external source or mutation is enabled.

## 9B — existing-capability inventory + source resolver

Deliver:

- `AcquisitionContextV1`;
- `CapabilitySourceAdapter` protocol;
- registered adapter inventory;
- `ExistingCapabilitySourceAdapter`;
- deterministic candidate deduplication;
- deterministic eligibility/evidence evaluation;
- strategy preference and safe selection;
- blocked/no-safe-route semantics;
- replay fixtures for reuse vs build decisions.

Exit gate: JARVIS can prove when it should reuse an existing capability instead of creating code.

## 9C — standardized source adapters

Deliver incrementally:

- owner-configured source adapter;
- MCP source normalization boundary;
- OpenAPI source normalization boundary;
- AsyncAPI source normalization boundary where justified;
- SDK/library candidate source;
- custom-build fallback source;
- external metadata redaction/bounds;
- no install/execute side effects during discovery;
- exact evidence/source identity;
- source-specific deterministic tests.

Do not add ACP/OpenHands or another coding framework merely to satisfy this slice.

Exit gate: acquisition research can compare real reusable integration routes through one normalized contract.

## 9D — durable acquisition research + architecture handoff

Deliver:

- Phase-9 admission coordinator bound to exact canonical owner turn;
- goal/candidate/evaluation/plan artifacts in existing ChangeStore;
- typed acquisition research actions/guard;
- completion result derived from canonical final plan, not prose;
- source-completion handler deriving exact architecture artifact;
- owner architecture gate reuse;
- restart/idempotency/WAITING_RESOURCE/WAITING_FOR_OWNER behavior;
- stale candidate/plan invalidation.

Exit gate: one owner request reaches the existing exact architecture approval gate without manual research.

## 9E — development + capability candidate evidence

Deliver:

- approved plan bound into DEVELOPMENT request;
- capability-specific changed-scope/verification requirements;
- current isolated development substrate reused unchanged where possible;
- exact dependency/provenance/SecretBroker/SandboxProfile handoff;
- `CapabilityAcquisitionCandidateEvidenceV1`;
- expected Phase-8 descriptor/manifest/provider binding;
- external/physical acceptance requirement tracking;
- no push/merge/deploy authority.

Optional ACP development-worker backend may be benchmarked here, behind a narrow replaceable backend interface, only after the native baseline is measured.

Exit gate: JARVIS can produce a verified owner-reviewable capability candidate without manual coding/Git/debugging.

## 9F — Phase-8 package + Phase-7 promotion integration

Deliver:

- candidate package/manifest/provider evidence verifier;
- exact Phase-7 promotion bridge reuse;
- active-release package presence verification;
- Phase-8 admission/compatibility verification;
- package-managed lifecycle proposal;
- production observation;
- compatible disable/rollback evidence;
- no automatic enable solely because a package was admitted.

Exit gate: accepted source candidate becomes a governed PACKAGE_MANAGED capability through existing Phase-7/8 truth.

## 9G — deterministic evaluation + owner-machine acceptance

Deterministic replay must cover at least:

1. existing capability fully satisfies goal -> no build;
2. compatible disabled package -> lifecycle route, no rebuild;
3. duplicate candidates deduplicate deterministically;
4. stronger verified evidence wins within same strategy;
5. wrap beats generated/custom build when requirements are satisfied;
6. blocked/unverified source cannot auto-select;
7. no candidate -> truthful no-safe-route;
8. stale candidate digest invalidates plan;
9. restart during acquisition research;
10. source/provider pressure -> WAITING_RESOURCE;
11. missing owner pairing/credential -> WAITING_FOR_OWNER;
12. architecture approval binds exact plan digest;
13. architecture revision invalidates old approval;
14. DEVELOPMENT cannot start before approval;
15. dependency/provenance failure blocks candidate;
16. plaintext secret injection rejected;
17. source metadata cannot inject command/import/executable fields;
18. protected-surface attempt fails closed;
19. package registration does not auto-enable;
20. package compatibility failure remains effectively unavailable;
21. protected main changes only through Phase 7;
22. rollback/disable restores safe state;
23. real external capability owner-machine path;
24. cold restart preserves same canonical change/work identity.

Owner-machine acceptance must use one genuine owner-requested capability and record exact implementation SHA/evidence digest.

## Permanent implementation rules

- extend Phases 3–8; do not duplicate them;
- reuse before generate;
- generate from machine-readable contracts before bespoke source;
- custom code is the last resort;
- no external framework owns JARVIS control-plane truth;
- no model confidence creates trust/Authority;
- no arbitrary shell/install commands;
- external metadata is untrusted;
- every new capability is PACKAGE_MANAGED;
- production activation remains Phase-8 Authority-bound;
- source promotion remains Phase-7 governed;
- real-world acceptance remains mandatory for final integrated-system validation; Phase 9 is owner-accepted bounded because provider quota prevented completion of the live external lifecycle.
