# ADR-017 — Accept Post-Step-7 Hands/Pocket Integration Without Renumbering the Roadmap

- **Status:** Accepted
- **Date:** 2026-09-14
- **Scope:** Post-Step-7 production integration and roadmap semantics

## Context

After Step 7 established the generic capability/authority runtime, real owner use exposed two immediate needs before formal Step 8 work:

1. JARVIS needed useful governed computer “hands” rather than safe reads only.
2. Pocket 3 tracking/perception and overall voice/runtime behavior needed production hardening so JARVIS could remain present reliably while those hands were used.

This work overlapped capability families assigned to later roadmap Steps 9, 10 and 12. Treating every accepted primitive as completion of those future product slices would make the roadmap misleading, while pretending the capabilities do not exist would make the current architecture equally misleading.

## Decision

Accept the work as a **post-Step-7 integration interlude** that does not renumber or prematurely complete later roadmap steps.

Accepted production foundations include:

### Governed JARVIS Hands

- one voice-facing `use_computer` handoff;
- canonical USER-generation leases/duplicate suppression/supersession;
- native Windows operations;
- Playwright browser execution;
- Microsoft `winapp` structured desktop automation;
- bounded file/document/device/Git executors;
- generic multilingual grounding;
- bounded low-latency fast path;
- target-window-scoped visual Computer Use as last resort;
- canonical AuthorityService, one-time permits, verification and audit throughout.

### Pocket 3 native OWNER tracking

- BLE/Wi-Fi/DUML native transport;
- OWNER target command + native tracking evidence;
- adaptive perception cadence;
- OWNER leave/re-enter reacquisition;
- clear-target/recenter on confirmed loss;
- bounded session recovery and stale-evidence invalidation;
- startup readiness gating on trusted native lock when configured;
- protocol-readiness gating before BLE pairing;
- bounded startup retry batches and reconnect cooldown measured from attempt completion;
- shutdown-aware BLE waits and fresh-frame restart after slow connection.

### Selective performance/stability recovery

- bounded MiniFAS CPU threading;
- low-CPU streaming wake proposal + exact verifier;
- optional vision preview and runtime profiler;
- final-empty USER-generation cleanup;
- near-silent assistant-audio replay;
- immediate standby exit;
- Hands schema/stagnation fixes;
- Pocket ACK/Wi-Fi/recovery sequencing fixes;
- Pocket BLE startup-readiness/retry-lifecycle fix from PR #40.

## Roadmap consequence

Steps 9, 10 and 12 remain **PLANNED WITH PARTIAL ACCEPTED FOUNDATIONS**.

They are not marked DONE because their full product requirements, integrations, edge cases and acceptance boundaries have not yet been executed as formal slices.

Step 8 remains the next formal slice.

## Why

- Current documentation must describe what actually runs.
- Roadmap status must represent full product-slice completion rather than count primitives.
- Mature foundations should be reused later rather than reimplemented simply because their formal step number arrives later.
- Pulling forward a bounded executor does not pre-authorize every future operation in its semantic domain.

## Safety boundary

The interlude does not expand JARVIS beyond the bounded authority contracts already accepted for these capabilities. Later slices remain subject to research-first design, canonical authority, automated validation and owner-machine acceptance.

### 2026-09-18 power/session safety amendment

Power/session execution is additionally fail-closed on operation-specific canonical USER intent:

- the planner's exact latest-USER evidence must name both the proposed operation and the local computer/Windows target;
- the bound operation/evidence are included in the proposal fingerprint and Windows Hello material summary;
- the native power executor refuses unbound or substituted intent;
- Authority audit records the bounded power intent for incident reconstruction.

Windows Hello remains a strong owner verifier, not a semantic-intent detector. Standby/sleep language directed at JARVIS must never be reinterpreted as Windows sleep/restart/shutdown.

See `docs/research/POWER_SESSION_INTENT_BINDING_2026-09-18.md`.

## Superseded/rejected experiment handling

Historical optimization/integration branches are evidence rather than merge queues. Proven work was selectively recovered on current main. In particular:

- PR #31/#32 are superseded by selective accepted recovery;
- workstation auto-lock based on OWNER absence was rejected and is not production behavior;
- PR #37's generation fix is represented through the consolidated PR #38 baseline.

See `docs/research/POST_STEP_7_INTEGRATION_ACCEPTANCE.md` and `docs/research/POCKET3_BLE_STARTUP_ACCEPTANCE_2026-09-14.md` for the detailed disposition and PR #40 acceptance records.
